"""Persistência em SQLite (um arquivo, sem instalação)."""

import logging
import re
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

# Índices das consultas reais do programa (get_pending/get_treated/
# get_marked_for_apply e a própria importação da planilha). Criados sempre com
# IF NOT EXISTS porque init_db roda a cada execução.
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_vagas_situacao ON vagas(situacao)",
    "CREATE INDEX IF NOT EXISTS idx_vagas_data_coleta ON vagas(data_coleta)",
    "CREATE INDEX IF NOT EXISTS idx_vagas_situacao_auto "
    "ON vagas(situacao, auto_preencher)",
    "CREATE INDEX IF NOT EXISTS idx_vagas_pontos ON vagas(pontos)",
)

# Tamanho do lote do SELECT ... IN (...). 500 fica bem abaixo do limite de
# variáveis do SQLite (999 em versões antigas) e evita uma consulta gigante.
_BATCH_SIZE = 500

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

# Campos que o INSERT exige. Se um registro raspado vier sem algum deles,
# avisamos e pulamos só ele (antes o sqlite levantava ProgrammingError e
# derrubava o lote inteiro).
_INSERT_FIELDS = tuple(re.findall(r":(\w+)", _INSERT))


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
        # Só depois da migração: um banco antigo não tem a coluna ainda.
        for statement in _INDEXES:
            conn.execute(statement)


_REFRESH = """
UPDATE vagas SET
    link = CASE WHEN ? <> '' THEN ? ELSE link END,
    descricao = CASE WHEN length(?) > length(COALESCE(descricao, '')) THEN ? ELSE descricao END
WHERE id = ?
"""


def _normaliza_chave(record):
    """
    Devolve a chave_dup como texto, ou None se o registro não tem uma chave
    utilizável. KeyError aqui é dado ruim (não bug de SQL): avisamos e pulamos
    só aquele registro, sem derrubar o lote.
    """
    try:
        chave = record["chave_dup"]
    except (KeyError, TypeError):
        return None
    if chave is None:
        return None
    chave = str(chave).strip()
    return chave or None


def _normaliza_id(record):
    """
    Devolve o id como texto, ou None se o registro não tem um id utilizável.

    Um id None passava pelo INSERT e virava uma linha com id NULL no SQLite
    (TEXT PRIMARY KEY aceita NULL). Essa vaga nunca mais podia ser atualizada
    por id e aparecia como pendente para sempre.
    """
    try:
        bruto = record["id"]
    except (KeyError, TypeError):
        return None
    if bruto is None:
        return None
    try:
        return _normaliza_job_id(bruto)
    except Exception:  # formato exótico vindo de um coletor alternativo
        return None


def _refresh_job(conn, job_id, record) -> None:
    """Atualiza link/descrição de uma vaga já existente, sem tocar em situação."""
    link = str(record.get("link") or "")
    descricao = str(record.get("descricao") or "")
    conn.execute(_REFRESH, (link, link, descricao, descricao, job_id))


def save_jobs(records: list) -> list:
    """
    Salva vagas novas. Ignora as que já existem (mesmo link OU mesma
    empresa+título+cidade vinda de outro site). Retorna só as NOVAS.

    Para as que já existiam, atualiza o link e a descrição: a mesma vaga é
    republicada com URL nova, e sem isso o link antigo (às vezes morto) ficava
    para sempre na planilha. Situação e "Auto-preencher" NUNCA são tocados.

    Antes era feito um SELECT por vaga (N+1): com centenas de resultados isso
    abria centenas de consultas. Agora consultamos as chaves em lotes de
    _BATCH_SIZE e decidimos em memória.
    """
    records = list(records or [])
    novas = []
    if not records:
        logger.info("Banco: nenhum registro para salvar.")
        return novas

    # Deduplicação DENTRO do lote: a primeira ocorrência vence, a segunda é
    # tratada como repetida (não vira "nova" e nem atualiza a primeira).
    vistos = set()
    validos = []
    for record in records:
        chave = _normaliza_chave(record)
        if chave is None:
            logger.warning("Registro sem 'chave_dup' válido ignorado ao salvar no banco.")
            continue
        if _normaliza_id(record) is None:
            logger.warning("Registro sem 'id' válido ignorado ao salvar no banco "
                           "(chave %s).", chave)
            continue
        if chave in vistos:
            continue
        vistos.add(chave)
        validos.append((chave, record))

    with get_connection() as conn:
        for inicio in range(0, len(validos), _BATCH_SIZE):
            lote = validos[inicio:inicio + _BATCH_SIZE]
            chaves = [chave for chave, _ in lote]
            placeholders = ",".join("?" for _ in chaves)
            rows = conn.execute(
                "SELECT chave_dup, id FROM vagas WHERE chave_dup IN (%s)" % placeholders,
                chaves,
            ).fetchall()
            existentes = {row["chave_dup"]: row["id"] for row in rows}

            for chave, record in lote:
                if chave in existentes:
                    _refresh_job(conn, existentes[chave], record)
                    continue
                faltando = [campo for campo in _INSERT_FIELDS if campo not in record]
                if faltando:
                    logger.warning("Registro incompleto ignorado (campo(s) ausente(s): %s).",
                                   ", ".join(faltando))
                    continue
                try:
                    cur = conn.execute(_INSERT, record)
                except sqlite3.IntegrityError as exc:
                    # Uma vaga problemática (ex.: id repetido de um registro
                    # antigo) não pode derrubar o lote inteiro.
                    logger.warning("Vaga ignorada por conflito de integridade "
                                   "(chave %s): %s", chave, exc)
                    continue
                except KeyError as exc:
                    # Defesa extra: campo obrigatório ausente no registro.
                    logger.warning("Registro incompleto ignorado (campo %s ausente).", exc)
                    continue
                if cur.rowcount == 1:
                    novas.append(record)
                    # Evita reinserir a mesma chave caso ela reapareça num lote
                    # seguinte (defesa extra; o dedupe acima já cobre o caso).
                    existentes[chave] = record.get("id")

    logger.info("Banco: %d nova(s), %d já conhecida(s).",
                len(novas), len(records) - len(novas))
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


def _normaliza_job_id(job_id):
    """
    IDs vêm da planilha (texto ou número) ou da interface. Aceita str/int/float
    e devolve o texto usado no banco; None para valores que devem ser ignorados.
    """
    if job_id is None or isinstance(job_id, bool):
        return None
    if isinstance(job_id, float) and job_id.is_integer():
        job_id = int(job_id)
    if not isinstance(job_id, (str, int)):
        return None
    texto = str(job_id).strip()
    return texto or None


def apply_statuses(changes: dict) -> int:
    """changes = {id_da_vaga: nova_situacao}. Retorna quantas realmente mudaram."""
    updated = 0
    with get_connection() as conn:
        for job_id, status in (changes or {}).items():
            job_id = _normaliza_job_id(job_id)
            if job_id is None:
                continue
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
        for job_id, flag in (changes or {}).items():
            job_id = _normaliza_job_id(job_id)
            if job_id is None:
                continue
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
