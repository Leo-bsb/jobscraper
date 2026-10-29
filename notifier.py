"""E-mail opcional (`python main.py --email`) com as vagas NOVAS da execução."""

import html
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config

logger = logging.getLogger("buscavagas.notifier")


def _build_html(jobs: list) -> str:
    esc = lambda v: html.escape(str(v or ""))
    rows = "".join(
        f"<tr>"
        f"<td style='padding:6px;border-bottom:1px solid #eee'>{esc(j['titulo'])}</td>"
        f"<td style='padding:6px;border-bottom:1px solid #eee'>{esc(j['empresa'])}</td>"
        f"<td style='padding:6px;border-bottom:1px solid #eee'>{esc(j['localizacao'])}</td>"
        f"<td style='padding:6px;border-bottom:1px solid #eee'>{esc(j['modelo_trabalho'])}</td>"
        f"<td style='padding:6px;border-bottom:1px solid #eee'>"
        f"<a href='{esc(j['link'])}'>Abrir</a></td></tr>"
        for j in jobs
    )
    return (
        "<html><body style='font-family:Arial,sans-serif'>"
        f"<h2>{len(jobs)} vaga(s) nova(s)</h2>"
        "<table style='border-collapse:collapse;width:100%'>"
        "<tr style='background:#f5f5f5'><th align=left>Cargo</th><th align=left>Empresa</th>"
        "<th align=left>Local</th><th align=left>Modelo</th><th align=left>Link</th></tr>"
        f"{rows}</table></body></html>"
    )


def send_daily_digest(jobs: list) -> bool:
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        logger.warning("E-mail não configurado (JOBSCRAPER_SMTP_USER / _PASSWORD). Pulando.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Vagas] {len(jobs)} nova(s)"
    msg["From"] = config.EMAIL_FROM
    msg["To"] = config.EMAIL_TO
    msg.attach(MIMEText(_build_html(jobs), "html", "utf-8"))

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(config.EMAIL_FROM, [config.EMAIL_TO], msg.as_string())
        logger.info("E-mail enviado (%d vagas).", len(jobs))
        return True
    except Exception as exc:
        logger.exception("Falha ao enviar e-mail: %s", exc)
        return False
