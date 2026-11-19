"""E-mail opcional (`python main.py --email`) com as vagas NOVAS da execução."""

import html
import logging
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlparse

import config

logger = logging.getLogger("buscavagas.notifier")

# Usado quando config.SMTP_TIMEOUT não existe. Sem timeout, um servidor SMTP
# travado deixaria o programa parado para sempre.
DEFAULT_SMTP_TIMEOUT = 30


def _esc(value) -> str:
    """Escapa texto para HTML (inclusive aspas, para uso seguro em href)."""
    return html.escape(str(value or ""), quote=True)


def _safe_href(value) -> str:
    """Só devolve o link se for http/https; senão, string vazia."""
    texto = str(value or "").strip()
    if not texto:
        return ""
    try:
        parsed = urlparse(texto)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return ""
    return _esc(texto)


def _build_html(jobs: list) -> str:
    linhas = []
    for job in jobs:
        titulo = _esc(job.get("titulo"))
        empresa = _esc(job.get("empresa"))
        local = _esc(job.get("localizacao"))
        modelo = _esc(job.get("modelo_trabalho"))
        href = _safe_href(job.get("link"))
        link = f"<a href=\"{href}\">Abrir</a>" if href else _esc(job.get("link"))
        linhas.append(
            "<tr>"
            f"<td style=\"padding:6px;border-bottom:1px solid #eee\">{titulo}</td>"
            f"<td style=\"padding:6px;border-bottom:1px solid #eee\">{empresa}</td>"
            f"<td style=\"padding:6px;border-bottom:1px solid #eee\">{local}</td>"
            f"<td style=\"padding:6px;border-bottom:1px solid #eee\">{modelo}</td>"
            f"<td style=\"padding:6px;border-bottom:1px solid #eee\">{link}</td>"
            "</tr>"
        )
    return (
        "<html><body style=\"font-family:Arial,sans-serif\">"
        f"<h2>{len(jobs)} vaga(s) nova(s)</h2>"
        "<table style=\"border-collapse:collapse;width:100%\">"
        "<tr style=\"background:#f5f5f5\"><th align=\"left\">Cargo</th>"
        "<th align=\"left\">Empresa</th><th align=\"left\">Local</th>"
        "<th align=\"left\">Modelo</th><th align=\"left\">Link</th></tr>"
        f"{''.join(linhas)}</table></body></html>"
    )


def _build_text(jobs: list) -> str:
    """Alternativa em texto puro (clientes que bloqueiam HTML)."""
    linhas = [f"{len(jobs)} vaga(s) nova(s)", ""]
    for job in jobs:
        linhas.append(
            "- %s | %s | %s | %s" % (
                job.get("titulo") or "", job.get("empresa") or "",
                job.get("localizacao") or "", job.get("modelo_trabalho") or "",
            )
        )
        link = str(job.get("link") or "").strip()
        if link:
            linhas.append(f"  {link}")
    return "\n".join(linhas)


def _recipients() -> list:
    """Aceita vários destinatários separados por vírgula ou ponto e vírgula."""
    raw = str(getattr(config, "EMAIL_TO", "") or "")
    vistos = []
    # Espaços/quebras de linha também separam: evita cabeçalho malformado se
    # alguém colar uma lista com uma linha por endereço.
    for parte in re.split(r"[,;\s]+", raw):
        endereco = parte.strip()
        if endereco and endereco not in vistos:
            vistos.append(endereco)
    return vistos


def send_daily_digest(jobs: list, timeout=None) -> bool:
    """
    Envia o resumo das vagas novas. Retorna True só se o envio funcionou.

    `timeout` (segundos) evita que um SMTP travado pare o programa; quando não
    informado, usa config.SMTP_TIMEOUT (se existir) ou 30 s.
    """
    if not jobs:
        logger.info("Nenhuma vaga nova: e-mail não enviado.")
        return False

    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        logger.warning("E-mail não configurado (JOBSCRAPER_SMTP_USER / _PASSWORD). Pulando.")
        return False

    destinatarios = _recipients()
    if not destinatarios:
        logger.warning("E-mail não configurado (JOBSCRAPER_EMAIL_TO vazio). Pulando.")
        return False

    if timeout is None:
        timeout = getattr(config, "SMTP_TIMEOUT", DEFAULT_SMTP_TIMEOUT)
    if timeout is None:  # SMTP_TIMEOUT definido como None não pode travar o envio
        timeout = DEFAULT_SMTP_TIMEOUT

    remetente = config.EMAIL_FROM or config.SMTP_USER
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Vagas] {len(jobs)} nova(s)"
    msg["From"] = remetente
    msg["To"] = ", ".join(destinatarios)
    # Texto primeiro, HTML depois: clientes escolhem a última alternativa
    # que conseguem exibir.
    msg.attach(MIMEText(_build_text(jobs), "plain", "utf-8"))
    msg.attach(MIMEText(_build_html(jobs), "html", "utf-8"))

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=timeout) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(remetente, destinatarios, msg.as_string())
        logger.info("E-mail enviado (%d vaga(s), %d destinatário(s)).",
                    len(jobs), len(destinatarios))
        return True
    except Exception as exc:
        # Nunca inclui usuário/senha/destinatários na mensagem de log.
        logger.exception("Falha ao enviar e-mail: %s", exc)
        return False
