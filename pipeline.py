"""Pipeline completo, usado tanto pela interface (app.py) quanto pela CLI (main.py)."""

import logging

import config
import database
import export_xlsx
import filtering
from scraper import scrape_all

logger = logging.getLogger("buscavagas.pipeline")


def run_search(filters: dict = None, send_email: bool = False) -> dict:
    filters = filters or config.load_filters()
    database.init_db()

    # 1) Antes de tudo, lê o que você marcou na planilha (Candidatei/Recusei)
    export_xlsx.import_statuses()

    # 2) Coleta
    df = scrape_all(filters)

    # 3) Filtro + 4) Banco
    records, novas, discarded = [], [], []
    if df.empty:
        logger.warning("Nenhuma vaga coletada (os sites podem ter recusado). "
                       "Vou gerar a planilha só com o que já estava salvo.")
    else:
        raw_jobs = df.astype(object).where(df.notna(), "").to_dict(orient="records")
        records, discarded, _ = filtering.filter_jobs(raw_jobs, filters)
        novas = database.save_jobs(records)

    # 5) Planilha (a aba de auditoria mostra só as descartadas DESTA execução)
    path = export_xlsx.export_weekly_report(days=int(filters["dias"]), discarded=discarded)

    if send_email and novas:
        from notifier import send_daily_digest
        send_daily_digest(novas)

    result = {"coletadas": len(df), "aprovadas": len(records),
              "novas": len(novas), "planilha": path}
    logger.info("Concluído: %d coletadas, %d aprovadas, %d novas.",
                result["coletadas"], result["aprovadas"], result["novas"])
    return result
