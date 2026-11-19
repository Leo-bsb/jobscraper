"""
Coleta via JobSpy, feita de forma "educada" para reduzir recusas (HTTP 429/403):

- cada site é consultado separadamente (a falha de um não derruba os outros);
- a ordem das buscas é embaralhada, então um mesmo site não recebe várias
  requisições seguidas;
- pausa ALEATÓRIA entre buscas;
- se o site recusar ou devolver vazio, tenta de novo com espera aleatória
  crescente (backoff com jitter).
"""

from __future__ import annotations

import logging
import random
import time

import config
from utils import normalize_text

logger = logging.getLogger("buscavagas.scraper")


def _national_location(site: str) -> str:
    return config.NATIONAL_LOCATION_BY_SITE.get(site, config.NATIONAL_LOCATION_DEFAULT)


def _lista_textos(valor, separar_virgula: bool = False) -> list:
    """
    Garante uma lista de textos não vazios a partir de um filtro que pode vir
    como None, string, lista, tupla etc. Nunca levanta exceção.
    """
    if valor is None:
        return []
    if isinstance(valor, str):
        partes = valor.replace(";", ",").split(",") if separar_virgula else valor.splitlines()
        if not partes:
            partes = [valor]
    elif isinstance(valor, (list, tuple, set)):
        partes = list(valor)
    else:
        partes = [valor]

    resultado = []
    for item in partes:
        if item is None:
            continue
        texto = str(item).strip()
        if texto:
            resultado.append(texto)
    return resultado


def _busca_principal(filters: dict) -> str:
    """Primeira cidade da lista = centro da busca (o raio cobre as vizinhas)."""
    cidades = _lista_textos((filters or {}).get("cidades"))
    return cidades[0] if cidades else "Brasil"


def _raio_milhas(filters: dict):
    """Converte o alcance em km para milhas (o JobSpy usa milhas)."""
    km = (filters or {}).get("alcance_km")
    try:
        # "80,5" (vírgula decimal) também é aceito, como em coerce_filters.
        km = float(str(km).strip().replace(",", ".")) if isinstance(km, str) else float(km)
    except (TypeError, ValueError):
        km = 0
    return round(km / 1.60934) if km > 0 else config.DISTANCE_MILES_DEFAULT


def plan_queries(filters: dict) -> list[dict]:
    """
    Planeja as consultas sem tocar na rede. Um dict por consulta:
        {"site", "termo", "local", "raio_milhas", "nacional"}
    Útil para um futuro `--dry-run`. Filtros incompletos/estranhos resultam em
    uma lista vazia, nunca em exceção.
    """
    if not isinstance(filters, dict):
        filters = {}

    termos = _lista_textos(filters.get("termos_busca"), separar_virgula=True)
    sites = [s.lower() for s in _lista_textos(filters.get("sites"), separar_virgula=True)]
    if not termos or not sites:
        return []

    local_principal = _busca_principal(filters)
    miles = _raio_milhas(filters)
    nacional = bool(filters.get("aceitar_home_office_todo_brasil"))

    planos = []
    for termo in termos:
        for site in sites:
            planos.append({
                "site": site, "termo": termo, "local": local_principal,
                "raio_milhas": miles, "nacional": False,
            })
            if nacional:
                # Busca nacional (sem restringir raio) para pegar home office
                # em qualquer lugar do país.
                planos.append({
                    "site": site, "termo": termo, "local": _national_location(site),
                    "raio_milhas": None, "nacional": True,
                })
    return planos


def build_queries(filters: dict) -> list:
    """
    Lista de (site, termo, local, raio_ou_None) a consultar, já embaralhada.
    Mantém o formato antigo; o planejamento fica em plan_queries().
    """
    planos = plan_queries(filters)
    random.shuffle(planos)
    return [(p["site"], p["termo"], p["local"], p["raio_milhas"]) for p in planos]


class SiteBlocked(Exception):
    """O site recusou todas as tentativas desta busca."""


def _resultados_por_busca(filters: dict, site: str) -> int:
    """
    Quantos resultados pedir ao site, tolerando "resultados_por_busca": null,
    texto ou fora da faixa (antes um None levantava TypeError e derrubava a
    coleta inteira antes da primeira tentativa).
    """
    try:
        results = int((filters or {}).get("resultados_por_busca") or 40)
    except (AttributeError, TypeError, ValueError):
        results = 40
    results = max(1, min(results, 1000))
    if site == "linkedin":
        results = min(results, config.LINKEDIN_MAX_RESULTS)
    return results


def _horas_desde(filters: dict) -> int:
    """'dias' -> horas para o JobSpy, com padrão de 7 dias se inválido."""
    try:
        return int((filters or {}).get("dias") or 7) * 24
    except (AttributeError, TypeError, ValueError):
        return 7 * 24


def _fetch(site: str, term: str, location: str, distance_miles, filters: dict):
    """
    Retorna o DataFrame da busca (pode vir vazio — isso é uma resposta
    válida, "não há vagas"), ou levanta SiteBlocked se o site recusou/errou em
    todas as tentativas. Só repetimos quando houve ERRO: repetir uma busca que
    só voltou vazia gastava minutos de espera sem trazer nada.
    """
    from jobspy import scrape_jobs  # import tardio: deixa a interface abrir mais rápido
    import pandas as pd           # tardio também: dá para testar o planejamento sem pandas

    results = _resultados_por_busca(filters, site)
    hours_old = _horas_desde(filters)

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
                hours_old=hours_old,
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


class _QuadroVazio:
    """
    Substituto mínimo de um DataFrame vazio. Só é usado se o pandas não
    estiver instalado (ex.: rodando os testes sem as dependências de coleta),
    para que a interface ainda consiga abrir e dizer "nenhuma vaga".
    """
    empty = True
    columns = []

    def __len__(self):
        return 0

    def drop_duplicates(self, *args, **kwargs):
        return self

    def __bool__(self):
        return False


def _quadro_vazio():
    try:
        import pandas as pd
        return pd.DataFrame()
    except ImportError:
        return _QuadroVazio()


def _dedupe_dataframe(df):
    """
    Remove repetições de um DataFrame de vagas:
      1. por link (job_url), quando a coluna existe;
      2. por (título, empresa, local) normalizados, mantendo a PRIMEIRA
         ocorrência — pega a mesma vaga publicada com links diferentes.

    Não exige pandas no import: usa apenas os métodos do próprio DataFrame,
    então pode ser testada com um stub simples.
    """
    if df is None or getattr(df, "empty", False):
        return df

    colunas = list(getattr(df, "columns", []))
    if "job_url" in colunas:
        df = df.drop_duplicates(subset=["job_url"])

    if all(coluna in colunas for coluna in ("title", "company", "location")):
        vistos = set()
        manter = []
        for titulo, empresa, local in zip(df["title"], df["company"], df["location"]):
            chave = (normalize_text(titulo), normalize_text(empresa), normalize_text(local))
            if not any(chave):
                # Sem nenhum dado útil: não arrisca juntar vagas diferentes.
                manter.append(True)
                continue
            if chave in vistos:
                manter.append(False)
            else:
                vistos.add(chave)
                manter.append(True)
        if not all(manter):
            df = df[manter]
    return df


def scrape_all(filters: dict, sleep=None, fetch=None):
    """
    Coleta todas as consultas planejadas.

    `sleep` e `fetch` existem para testes: por padrão usam time.sleep e
    _fetch (JobSpy). Assim dá para simular bloqueio/backoff sem rede.
    """
    if sleep is None:
        sleep = time.sleep
    if fetch is None:
        fetch = _fetch

    inicio = time.monotonic()
    queries = build_queries(filters)
    logger.info("Vou fazer %d busca(s). Isso pode levar alguns minutos...", len(queries))

    frames = []
    falhas_seguidas = {}   # site -> buscas seguidas em que o site recusou tudo
    desistidos = set()
    try:
        for i, (site, term, location, distance_miles) in enumerate(queries, start=1):
            if site in desistidos:
                continue
            logger.info("(%d/%d) %s: '%s' em %s", i, len(queries), site, term, location)
            try:
                df = fetch(site, term, location, distance_miles, filters)
                falhas_seguidas[site] = 0
                # fetch falso/instável pode devolver None: trata como "sem vagas".
                if df is not None and not getattr(df, "empty", True):
                    logger.info("   -> %d vaga(s) recebida(s)", len(df))
                    frames.append(df)
            except SiteBlocked:
                falhas_seguidas[site] = falhas_seguidas.get(site, 0) + 1
                if falhas_seguidas[site] >= config.SITE_GIVE_UP_AFTER:
                    desistidos.add(site)
                    logger.warning("%s está recusando as buscas; vou pular esse site no resto desta "
                                   "execução (tente de novo mais tarde ou desmarque-o).", site)
            # Pausa só ENTRE consultas que ainda vão rodar (não depois da
            # última e nem quando o que resta é só site já desistido).
            if any(prox[0] not in desistidos for prox in queries[i:]):
                sleep(random.uniform(config.DELAY_MIN, config.DELAY_MAX))
    except KeyboardInterrupt:
        logger.warning("Coleta interrompida pelo usuário (Ctrl+C).")
        raise

    duracao = time.monotonic() - inicio
    if not frames:
        logger.info("Coleta concluída em %.1f s (nenhuma vaga recebida).", duracao)
        return _quadro_vazio()

    import pandas as pd  # tardio: importar o módulo não exige pandas

    combined = pd.concat(frames, ignore_index=True)
    combined = _dedupe_dataframe(combined)
    logger.info("Total bruto (sem repetições): %d vaga(s)", len(combined))
    logger.info("Coleta concluída em %.1f s.", duracao)
    return combined
