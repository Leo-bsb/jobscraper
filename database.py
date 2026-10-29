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
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
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


def save_jobs(records: list) -> list:
    """
    Salva vagas novas. Ignora as que já existem (mesmo link OU mesma
    empresa+título+cidade vinda de outro site). Retorna só as NOVAS.
    """
    novas = []
    with get_connection() as conn:
        for record in records:
            cur = conn.execute(_INSERT, record)
            if cur.rowcount == 1:
                novas.append(record)
    logger.info("Banco: %d nova(s), %d já conhecida(s).", len(novas), len(records) - len(novas))
    return novas


def get_pending(days: int) -> list:
    """Vagas ainda 'Pendente' coletadas nos últimos `days` dias."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM vagas
               WHERE situacao = ? AND data_coleta >= ?
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
