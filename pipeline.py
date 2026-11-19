"""Pipeline completo, usado tanto pela interface (app.py) quanto pela CLI (main.py)."""

import logging
import time

import config
import database
import export_xlsx
import filtering

logger = logging.getLogger("buscavagas.pipeline")


def _default_scrape(filters: dict):
    """
    Coletor padrão. Import tardio de propósito: `scraper` depende de pandas e
    jobspy, e assim o pipeline (e os testes com `scrape` injetado) funcionam
    sem essas bibliotecas instaladas.
    """
    from scraper import scrape_all

    return scrape_all(filters)


def _dias_do_relatorio(filters) -> int:
    """
    Lê "dias" dos filtros sem derrubar a execução.

    Um filtros.json editado à mão com "dias": null (ou "sete") fazia int()
    levantar antes da planilha ser gerada, então nem o que já estava salvo
    aparecia. Aqui caímos para o padrão em vez de perder a planilha.
    """
    padrao = config.DEFAULT_FILTERS.get("dias", 7)
    try:
        dias = int((filters or {}).get("dias", padrao))
    except (AttributeError, TypeError, ValueError):
        logger.warning("Valor inválido em 'dias' (%r); usando %d.",
                       (filters or {}).get("dias") if isinstance(filters, dict) else filters,
                       padrao)
        return padrao
    if dias < 1:
        logger.warning("Valor inválido em 'dias' (%r); usando %d.", dias, padrao)
        return padrao
    return dias


def run_search(filters: dict = None, send_email: bool = False, scrape=None) -> dict:
    """
    Executa uma busca completa: importa marcações, coleta, filtra, salva e
    gera a planilha. `scrape` permite injetar um coletor nos testes (default:
    scraper.scrape_all); as chamadas antigas continuam funcionando.

    Falhas recuperáveis (coleta, leitura da planilha, gravação no banco ou
    e-mail) não impedem a geração da planilha e viram mensagens em `erros`.
    """
    inicio = time.monotonic()
    filters = filters or config.load_filters()
    erros = []

    database.init_db()

    # 1) Antes de tudo, lê o que você marcou na planilha (Candidatei/Recusei)
    try:
        export_xlsx.import_statuses()
    except Exception as exc:
        logger.exception("Falha ao ler as marcações da planilha: %s", exc)
        erros.append("Não foi possível ler as marcações da planilha.")

    # 2) Coleta
    coletor = scrape or _default_scrape
    df = None
    try:
        df = coletor(filters)
    except Exception as exc:
        logger.exception("Falha na coleta de vagas: %s", exc)
        erros.append("Falha na coleta de vagas; usando o que já estava salvo.")

    try:
        coletadas = len(df) if df is not None else 0
    except TypeError:
        coletadas = 0

    # 3) Filtro + 4) Banco
    records, novas, discarded = [], [], []
    if df is None or getattr(df, "empty", True):
        logger.warning("Nenhuma vaga coletada (os sites podem ter recusado). "
                       "Vou gerar a planilha só com o que já estava salvo.")
    else:
        try:
            raw_jobs = df.astype(object).where(df.notna(), "").to_dict(orient="records")
        except Exception as exc:
            logger.exception("Falha ao preparar os dados coletados: %s", exc)
            erros.append("Falha ao preparar os dados coletados.")
        else:
            try:
                records, discarded, _ = filtering.filter_jobs(raw_jobs, filters)
            except Exception as exc:
                logger.exception("Falha ao filtrar as vagas: %s", exc)
                erros.append("Falha ao filtrar as vagas.")
            else:
                try:
                    novas = database.save_jobs(records)
                except Exception as exc:
                    logger.exception("Falha ao salvar as vagas no banco: %s", exc)
                    erros.append("Falha ao salvar as vagas no banco.")

    # 5) Planilha (a aba de auditoria mostra só as descartadas DESTA execução).
    # Gerada SEMPRE, antes de qualquer tentativa de e-mail.
    dias = _dias_do_relatorio(filters)
    path = export_xlsx.export_weekly_report(days=dias, discarded=discarded)

    # 6) E-mail: falha aqui não pode afetar a planilha já gerada.
    if send_email and novas:
        try:
            from notifier import send_daily_digest

            # A planilha é o produto para boa parte dos usuários: vai anexada.
            if not send_daily_digest(novas, attachment_path=path):
                logger.warning("O e-mail não foi enviado; a planilha já foi gerada.")
        except Exception as exc:
            logger.exception("Falha ao enviar o e-mail: %s", exc)
            erros.append("Falha ao enviar o e-mail; a planilha foi gerada normalmente.")

    result = {"coletadas": coletadas, "aprovadas": len(records),
              "novas": len(novas), "planilha": path, "erros": erros}
    logger.info("Concluído em %.1f s: %d coletadas, %d aprovadas, %d novas.",
                time.monotonic() - inicio,
                result["coletadas"], result["aprovadas"], result["novas"])
    if erros:
        logger.warning("Busca terminou com %d falha(s) recuperável(is).", len(erros))
    return result
