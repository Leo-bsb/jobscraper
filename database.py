"""Persistência em SQLite (um arquivo, sem instalação)."""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

import config

logger = logging.getLogger("buscavagas.database")

SCHEMA = """
CREATE TABLE IF NOT EXISTS vagas (
    id TEXT PRIMARY KEY,
    chave_dup TEXT UNIQUE,
    titulo TEXT,
    empresa TEXT,
    localizacao TEXT,
    modelo_trabalho TEXT,
    faixa_salarial TEXT,
    termos_encontrados TEXT,
    pontos INTEGER,
    link TEXT,
    descricao TEXT,
    site_origem TEXT,
    data_publicacao TEXT,
    data_coleta TEXT,
    situacao TEXT DEFAULT 'Pendente',
    auto_preencher TEXT DEFAULT 'Não'
);
"""

_INSERT = """
INSERT OR IGNORE INTO vagas (
    id, chave_dup, titulo, empresa, localizacao, modelo_trabalho, faixa_salarial,
    termos_encontrados, pontos, link, descricao, site_origem, data_publicacao,
    data_coleta, situacao, auto_preencher
) VALUES (
    :id, :chave_dup, :titulo, :empresa, :localizacao, :modelo_trabalho, :faixa_salarial,
    :termos_encontrados, :pontos, :link, :descricao, :site_origem, :data_publicacao,
    :data_coleta, :situacao, :auto_preencher
)
"""


@contextmanager
def get_connection():
    # timeout/busy_timeout + WAL: BuscaVagas e CandidatarVagas podem ficar
    # abertos ao mesmo tempo e os dois escrevem neste MESMO arquivo.
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.execute(SCHEMA)
        # Migração: bancos criados antes da coluna existir
        try:
            conn.execute("ALTER TABLE vagas ADD COLUMN auto_preencher TEXT DEFAULT 'Não'")
        except sqlite3.OperationalError:
            pass  # coluna já existe


_REFRESH = """
UPDATE vagas SET
    link = CASE WHEN ? <> '' THEN ? ELSE link END,
    descricao = CASE WHEN length(?) > length(COALESCE(descricao, '')) THEN ? ELSE descricao END
WHERE id = ?
"""


def save_jobs(records: list) -> list:
    """
    Salva vagas novas. Ignora as que já existem (mesmo link OU mesma
    empresa+título+cidade vinda de outro site). Retorna só as NOVAS.

    Para as que já existiam, atualiza o link e a descrição: a mesma vaga é
    republicada com URL nova, e sem isso o link antigo (às vezes morto) ficava
    para sempre na planilha. Situação e "Auto-preencher" NUNCA são tocados.
    """
    novas = []
    with get_connection() as conn:
        for record in records:
            existente = conn.execute(
                "SELECT id FROM vagas WHERE chave_dup = ?", (record["chave_dup"],)
            ).fetchone()
            if existente is None:
                cur = conn.execute(_INSERT, record)
                if cur.rowcount == 1:
                    novas.append(record)
                continue
            link = str(record.get("link") or "")
            descricao = str(record.get("descricao") or "")
            conn.execute(_REFRESH, (link, link, descricao, descricao, existente["id"]))
    logger.info("Banco: %d nova(s), %d já conhecida(s).", len(novas), len(records) - len(novas))
    return novas


def get_pending(days: int) -> list:
    """
    Vagas ainda 'Pendente' publicadas nos últimos `days` dias.

    Usa `data_publicacao` quando ela existe e está no formato AAAA-MM-DD
    (é o que a interface promete: "vagas publicadas nos últimos N dias");
    senão cai para a data em que a vaga foi coletada. Antes filtrávamos só por
    `data_coleta`, então vaga publicada há um mês e coletada hoje aparecia.
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM vagas
               WHERE situacao = ?
                 AND (CASE WHEN data_publicacao GLOB
                             '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'
                           THEN substr(data_publicacao, 1, 10)
                           ELSE substr(data_coleta, 1, 10) END) >= ?
               ORDER BY pontos DESC, data_coleta DESC""",
            (config.STATUS_PENDENTE, cutoff),
        ).fetchall()
    return [dict(r) for r in rows]


def get_treated() -> list:
    """Vagas já marcadas como Candidatei/Recusei (histórico)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM vagas WHERE situacao IN (?, ?) ORDER BY data_coleta DESC",
            (config.STATUS_CANDIDATEI, config.STATUS_RECUSEI),
        ).fetchall()
    return [dict(r) for r in rows]


def apply_statuses(changes: dict) -> int:
    """changes = {id_da_vaga: nova_situacao}. Retorna quantas realmente mudaram."""
    updated = 0
    with get_connection() as conn:
        for job_id, status in changes.items():
            if status not in config.STATUS_OPTIONS:
                # Sem esta trava, uma planilha com texto estranho gravava um
                # status que não existe e a vaga sumia das duas abas.
                logger.warning("Status inválido para a vaga %s: %r. Ignorando.", job_id, status)
                continue
            cur = conn.execute(
                "UPDATE vagas SET situacao = ? WHERE id = ? AND situacao != ?",
                (status, job_id, status),
            )
            updated += cur.rowcount
    return updated


def apply_autofill_flags(changes: dict) -> int:
    """changes = {id_da_vaga: 'Sim'|'Não'}. Retorna quantas realmente mudaram."""
    updated = 0
    with get_connection() as conn:
        for job_id, flag in changes.items():
            if flag not in config.AUTOFILL_OPTIONS:
                logger.warning("Auto-preencher inválido para a vaga %s: %r. Ignorando.", job_id, flag)
                continue
            cur = conn.execute(
                "UPDATE vagas SET auto_preencher = ? WHERE id = ? AND auto_preencher != ?",
                (flag, job_id, flag),
            )
            updated += cur.rowcount
    return updated


def get_marked_for_apply() -> list:
    """Vagas pendentes marcadas com Auto-preencher = Sim, usadas pelo applier.py."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM vagas WHERE situacao = ? AND auto_preencher = ? "
            "ORDER BY pontos DESC, data_coleta DESC",
            (config.STATUS_PENDENTE, config.AUTOFILL_SIM),
        ).fetchall()
    return [dict(r) for r in rows]
