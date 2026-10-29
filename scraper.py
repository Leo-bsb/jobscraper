"""
Coleta via JobSpy, feita de forma "educada" para reduzir recusas (HTTP 429/403):

- cada site é consultado separadamente (a falha de um não derruba os outros);
- a ordem das buscas é embaralhada, então um mesmo site não recebe várias
  requisições seguidas;
- pausa ALEATÓRIA entre buscas;
- se o site recusar ou devolver vazio, tenta de novo com espera aleatória
  crescente (backoff com jitter).
"""

import logging
import random
import time

import pandas as pd

import config

logger = logging.getLogger("buscavagas.scraper")


def _national_location(site: str) -> str:
    return config.NATIONAL_LOCATION_BY_SITE.get(site, config.NATIONAL_LOCATION_DEFAULT)


def _busca_principal(filters: dict) -> str:
    """Primeira cidade da lista = centro da busca (o raio cobre as vizinhas)."""
    cidades = filters.get("cidades") or ["Brasil"]
    return str(cidades[0])


def build_queries(filters: dict) -> list:
    """Lista de (site, termo, local, raio_ou_None) a consultar, já embaralhada."""
    queries = []
    local_principal = _busca_principal(filters)
    km = filters.get("alcance_km")
    miles = round(km / 1.60934) if km else config.DISTANCE_MILES_DEFAULT
    for term in filters["termos_busca"]:
        for site in filters["sites"]:
            queries.append((site, term, local_principal, miles))
            if filters.get("aceitar_home_office_todo_brasil"):
                # Busca nacional (sem restringir raio) para pegar home office em qualquer lugar
                queries.append((site, term, _national_location(site), None))
    random.shuffle(queries)
    return queries


class SiteBlocked(Exception):
    """O site recusou todas as tentativas desta busca."""


def _fetch(site: str, term: str, location: str, distance_miles, filters: dict):
    """
    Retorna o DataFrame da busca (pode vir vazio — isso é uma resposta
    válida, "não há vagas"), ou levanta SiteBlocked se o site recusou/errou em
    todas as tentativas. Só repetimos quando houve ERRO: repetir uma busca que
    só voltou vazia gastava minutos de espera sem trazer nada.
    """
    from jobspy import scrape_jobs  # import tardio: deixa a interface abrir mais rápido

    results = int(filters.get("resultados_por_busca", 40))
    if site == "linkedin":
        results = min(results, config.LINKEDIN_MAX_RESULTS)

    kwargs = {}
    if distance_miles is not None:
        kwargs["distance"] = int(distance_miles)

    for attempt in range(1, config.RETRY_MAX + 1):
        try:
            df = scrape_jobs(
                site_name=[site],
                search_term=term,
                location=location,
                results_wanted=results,
                hours_old=int(filters["dias"]) * 24,
                country_indeed=config.COUNTRY,
                # Sem isto o LinkedIn não traz a descrição e o filtro por termos falharia
                linkedin_fetch_description=(site == "linkedin"),
                verbose=1,
                **kwargs,
            )
            if df is None or df.empty:
                logger.info("[%s] '%s' em '%s': nenhuma vaga.", site, term, location)
                return pd.DataFrame()
            return df
        except Exception as exc:  # o site recusou, mudou o layout, timeout etc.
            logger.warning("[%s] '%s' em '%s': erro '%s' (tentativa %d/%d)",
                           site, term, location, exc, attempt, config.RETRY_MAX)

        if attempt < config.RETRY_MAX:
            wait = random.uniform(config.RETRY_WAIT_MIN, config.RETRY_WAIT_MAX) * attempt
            logger.info("Aguardando %.0f s antes de tentar de novo...", wait)
            time.sleep(wait)

    raise SiteBlocked(f"{site} recusou {config.RETRY_MAX} tentativas")


def scrape_all(filters: dict) -> pd.DataFrame:
    queries = build_queries(filters)
    logger.info("Vou fazer %d busca(s). Isso pode levar alguns minutos...", len(queries))

    frames = []
    falhas_seguidas = {}   # site -> buscas seguidas em que o site recusou tudo
    desistidos = set()
    for i, (site, term, location, distance_miles) in enumerate(queries, start=1):
        if site in desistidos:
            continue
        logger.info("(%d/%d) %s: '%s' em %s", i, len(queries), site, term, location)
        try:
            df = _fetch(site, term, location, distance_miles, filters)
            falhas_seguidas[site] = 0
            if not df.empty:
                logger.info("   -> %d vaga(s) recebida(s)", len(df))
                frames.append(df)
        except SiteBlocked:
            falhas_seguidas[site] = falhas_seguidas.get(site, 0) + 1
            if falhas_seguidas[site] >= config.SITE_GIVE_UP_AFTER:
                desistidos.add(site)
                logger.warning("%s está recusando as buscas; vou pular esse site no resto desta "
                               "execução (tente de novo mais tarde ou desmarque-o).", site)
        if i < len(queries):
            time.sleep(random.uniform(config.DELAY_MIN, config.DELAY_MAX))

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    if "job_url" in combined.columns:
        combined = combined.drop_duplicates(subset=["job_url"])
    logger.info("Total bruto (sem repetições de link): %d vaga(s)", len(combined))
    return combined
