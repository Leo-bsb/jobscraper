"""
Planilha de vagas com coluna "Situação" (dropdown: Pendente / Candidatei / Recusei).

Fluxo:
  1. O programa gera `vagas_da_semana.xlsx` (aba "Vagas" = pendentes; aba
     "Já tratadas" = histórico de Candidatei/Recusei).
  2. Você marca a situação na planilha, salva e fecha.
  3. Na próxima busca, o programa LÊ as marcações (import_statuses) ANTES de
     gerar a planilha nova, então o que você marcou nunca volta como pendente.

Quem manda quando a planilha e o banco discordam: a planilha guarda, em
colunas ocultas, o valor que cada vaga tinha QUANDO o arquivo foi gerado.
Na leitura, só aplicamos as células que você alterou em relação a esse
valor. Assim, uma vaga marcada como "Candidatei" pelo CandidatarVagas não é
desfeita por uma planilha antiga que ainda diz "Pendente".
"""

import json
import logging
import os
from datetime import datetime
from urllib.parse import urlparse

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import config
import database
from utils import normalize_text

logger = logging.getLogger("buscavagas.xlsx")

# (campo no banco, título da coluna, largura)
COLUMNS = [
    ("situacao", "Situação", 14),
    ("auto_preencher", "Auto-preencher", 15),
    ("titulo", "Cargo", 38),
    ("empresa", "Empresa", 26),
    ("localizacao", "Local", 24),
    ("modelo_trabalho", "Modelo", 13),
    ("faixa_salarial", "Salário", 20),
    ("termos_encontrados", "Termos encontrados", 34),
    ("pontos", "Pontos", 8),
    ("site_origem", "Origem", 11),
    ("data_publicacao", "Publicada em", 13),
    ("link", "Link", 45),
    # --- colunas ocultas (sempre no fim) ---
    ("id", "ID", 10),  # é como o programa reconhece a vaga ao ler a planilha
    ("situacao", "Situação (ao gerar)", 10),        # valor no momento da exportação
    ("auto_preencher", "Auto-preencher (ao gerar)", 10),
]
HIDDEN_FROM = len(COLUMNS) - 3  # índice (0-based) da primeira coluna oculta
HEADER_TITLE_STATUS = "Situação"
HEADER_TITLE_AUTOFILL = "Auto-preencher"
HEADER_TITLE_ID = "ID"
HEADER_TITLE_STATUS_SNAP = "Situação (ao gerar)"
HEADER_TITLE_AUTOFILL_SNAP = "Auto-preencher (ao gerar)"

HEADER_FILL = PatternFill(start_color="305496", end_color="305496", fill_type="solid")
GREEN = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
GRAY = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")
BLUE = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")

# Limite de caracteres por célula no Excel. Textos maiores que isso fariam o
# openpyxl gerar um arquivo que o Excel se recusa a abrir.
MAX_CELL_CHARS = 32767
# Se o dado raspado começa com um destes, o Excel pode interpretá-lo como
# fórmula/valor especial ao abrir a planilha (injeção de fórmula).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value):
    """
    Converte um valor raspado em conteúdo seguro para a célula.

    - números e booleanos continuam como estão (não são texto);
    - textos são cortados no limite de 32767 caracteres do Excel.

    A proteção contra injeção de fórmula (textos que começam com = + - @
    TAB ou CR) NÃO é feita aqui com apóstrofo: ela é aplicada em `_write_cell`,
    que grava o texto original como string (`data_type="s"`) e marca
    `quotePrefix`, para o Excel exibir o conteúdo sem o apóstrofo visível.
    """
    if value is None:
        return ""
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return value
    return value[:MAX_CELL_CHARS]


def _write_cell(ws, row: int, column: int, value):
    """
    Grava `value` na célula sem permitir que o Excel o trate como fórmula.

    Antes o texto recebia um apóstrofo literal na frente ("'=1+1"), o que
    aparecia na planilha. Agora mantemos o conteúdo original, gravamos como
    string e usamos `quotePrefix` (o mesmo recurso que o Excel usa quando
    você digita um apóstrofo): a célula continua sendo texto e o apóstrofo
    não é exibido. O resultado é lido de volta pelo openpyxl sem alteração.
    """
    cell = ws.cell(row=row, column=column)
    dados = _safe_cell(value)
    cell.value = dados
    if isinstance(dados, str) and dados[:1] in _FORMULA_PREFIXES:
        cell.data_type = "s"     # nunca salvamos como <f> (fórmula)
        cell.quotePrefix = True  # Excel trata/exibe como texto, sem apóstrofo
    return cell


def _is_http_url(value) -> bool:
    """Só criamos hyperlink para http/https (evita javascript:, file: etc.)."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme.lower() in ("http", "https") and bool(parsed.netloc)


def _write_sheet(ws, jobs: list) -> None:
    for col, (_, title, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=_safe_cell(title))
        cell.fill = HEADER_FILL
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(col)].width = width

    for row, job in enumerate(jobs, start=2):
        for col, (field, _, _) in enumerate(COLUMNS, start=1):
            raw_value = job.get(field, "")
            cell = _write_cell(ws, row, col, raw_value)
            cell.alignment = Alignment(vertical="top")
            if field == "link" and _is_http_url(raw_value):
                cell.hyperlink = str(raw_value).strip()[:MAX_CELL_CHARS]
                cell.font = Font(color="0563C1", underline="single")

    for col in range(HIDDEN_FROM + 1, len(COLUMNS) + 1):
        ws.column_dimensions[get_column_letter(col)].hidden = True
    ws.freeze_panes = "A2"

    if not jobs:
        return

    last = len(jobs) + 1
    last_visible = get_column_letter(HIDDEN_FROM)
    ws.auto_filter.ref = f"A1:{last_visible}{last}"

    fields = [f for f, _, _ in COLUMNS]
    col_status = get_column_letter(fields.index("situacao") + 1)
    col_auto = get_column_letter(fields.index("auto_preencher") + 1)

    dv_status = DataValidation(
        type="list",
        formula1='"' + ",".join(config.STATUS_OPTIONS) + '"',
        allow_blank=False, showErrorMessage=True, errorTitle="Valor inválido",
        error="Escolha uma opção da lista: Pendente, Candidatei ou Recusei.",
    )
    ws.add_data_validation(dv_status)
    dv_status.add(f"{col_status}2:{col_status}{last}")

    dv_auto = DataValidation(
        type="list",
        formula1='"' + ",".join(config.AUTOFILL_OPTIONS) + '"',
        allow_blank=False, showErrorMessage=True, errorTitle="Valor inválido",
        error="Escolha \"Sim\" ou \"Não\".",
    )
    ws.add_data_validation(dv_auto)
    dv_auto.add(f"{col_auto}2:{col_auto}{last}")

    area = f"A2:{last_visible}{last}"
    ws.conditional_formatting.add(
        area, FormulaRule(formula=[f'${col_status}2="{config.STATUS_CANDIDATEI}"'], fill=GREEN))
    ws.conditional_formatting.add(
        area, FormulaRule(formula=[f'${col_status}2="{config.STATUS_RECUSEI}"'], fill=GRAY,
                          font=Font(color="7F7F7F")))
    ws.conditional_formatting.add(
        area, FormulaRule(formula=[f'${col_auto}2="{config.AUTOFILL_SIM}"'], fill=BLUE))


def _free_alt_path(path: str) -> str:
    """Nome alternativo com timestamp que ainda não existe (evita sobrescrever)."""
    base, ext = os.path.splitext(path)
    if not ext:
        ext = ".xlsx"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for tentativa in range(100):
        sufixo = f"_{stamp}" if tentativa == 0 else f"_{stamp}_{tentativa}"
        alt = f"{base}{sufixo}{ext}"
        if not os.path.exists(alt):
            return alt
    return f"{base}_{stamp}_{os.getpid()}{ext}"


def _save(wb: Workbook, path: str) -> str:
    try:
        wb.save(path)
        return path
    except PermissionError:
        logger.warning(
            "A planilha estava ABERTA no Excel. Vou salvar em um arquivo alternativo.")
    except OSError as exc:
        logger.warning("Não consegui salvar a planilha em %s (%s). "
                       "Vou tentar um nome alternativo.", path, exc)

    alt = _free_alt_path(path)
    try:
        wb.save(alt)
    except OSError as exc:
        logger.error("Não foi possível salvar a planilha em %s (%s). "
                     "Feche o arquivo no Excel e tente novamente.", alt, exc)
        raise OSError(
            "Não foi possível salvar a planilha em '%s' nem em '%s'. "
            "Feche o arquivo no Excel e tente novamente." % (path, alt)
        ) from exc
    logger.warning(
        "Planilha salva em outro arquivo: %s. Feche o Excel e busque de novo "
        "para que suas marcações sejam lidas.", alt)
    return alt


AUDIT_COLUMNS = [
    ("motivo", "Por que foi descartada", 32),
    ("titulo", "Cargo", 38),
    ("empresa", "Empresa", 26),
    ("localizacao", "Local", 30),
    ("link", "Link", 45),
]


def _write_audit_sheet(ws, discarded: list) -> None:
    for col, (_, title, width) in enumerate(AUDIT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=_safe_cell(title))
        cell.fill = HEADER_FILL
        cell.font = Font(color="FFFFFF", bold=True)
        ws.column_dimensions[get_column_letter(col)].width = width
    for row, job in enumerate(discarded, start=2):
        for col, (field, _, _) in enumerate(AUDIT_COLUMNS, start=1):
            raw_value = job.get(field, "")
            cell = _write_cell(ws, row, col, raw_value)
            if field == "link" and _is_http_url(raw_value):
                cell.hyperlink = str(raw_value).strip()[:MAX_CELL_CHARS]
                cell.font = Font(color="0563C1", underline="single")
    ws.freeze_panes = "A2"
    if discarded:
        last_col = get_column_letter(len(AUDIT_COLUMNS))
        ws.auto_filter.ref = f"A1:{last_col}{len(discarded) + 1}"


def _load_discarded() -> list:
    try:
        with open(config.DISCARDED_PATH, "r", encoding="utf-8-sig") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        return []
    # O arquivo é gerado pelo programa, mas pode ter sido editado à mão.
    if not isinstance(dados, list):
        return []
    return [item for item in dados if isinstance(item, dict)]


def _save_discarded(discarded: list) -> None:
    try:
        with open(config.DISCARDED_PATH, "w", encoding="utf-8") as f:
            json.dump(discarded[:300], f, ensure_ascii=False)
    except OSError as exc:
        logger.warning("Não consegui guardar as descartadas da última busca (%s).", exc)


def export_weekly_report(days: int, path: str = None, discarded: list = None) -> str:
    """
    Gera a planilha com as vagas pendentes dos últimos `days` dias + histórico.

    `discarded`, se passado (ver pipeline.run_search), é a lista de vagas
    rejeitadas pelo filtro NESTA execução, usada só para a aba de auditoria —
    ajuda a calibrar os filtros vendo o que foi descartado e por quê. Não é
    salva no banco nem acumulada entre execuções — mas fica guardada num
    arquivo à parte, para que regerar a planilha depois (ex.: ao abri-la pela
    interface) não apague essa aba. Sem `discarded`, reaproveita a última.
    """
    path = path or config.XLSX_PATH
    if discarded is None:
        discarded = _load_discarded()
    else:
        discarded = [item for item in discarded if isinstance(item, dict)]
        _save_discarded(discarded)
    pending = database.get_pending(days)
    treated = database.get_treated()

    wb = Workbook()
    _write_sheet(wb.active, pending)
    wb.active.title = "Vagas"
    _write_sheet(wb.create_sheet("Já tratadas"), treated)
    if discarded:
        # Limite de 300 linhas: suficiente para calibrar o filtro sem deixar
        # o arquivo pesado quando uma busca ampla descarta muita coisa.
        _write_audit_sheet(wb.create_sheet("Descartadas (última busca)"), discarded[:300])

    saved = _save(wb, path)
    logger.info("Planilha gerada: %s (%d pendente(s), %d já tratada(s), %d descartada(s) nesta busca)",
                saved, len(pending), len(treated), len(discarded or []))
    return saved


def _to_status(value):
    """Converte o texto da célula em uma situação válida (ou None se irreconhecível)."""
    v = normalize_text(value)
    if v.startswith("candid"):
        return config.STATUS_CANDIDATEI
    if v.startswith("recus"):
        return config.STATUS_RECUSEI
    if v.startswith("pendent"):
        return config.STATUS_PENDENTE
    return None


def _to_autofill(value):
    """Converte o texto da célula em Sim/Não (ou None se irreconhecível)."""
    v = normalize_text(value)
    if v.startswith("sim"):
        return config.AUTOFILL_SIM
    if v.startswith("nao"):
        return config.AUTOFILL_NAO
    return None


def _cell_job_id(value):
    """Normaliza o ID lido da planilha (número ou texto) para o texto do banco."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    texto = str(value).strip()
    return texto or None


def _header_indexes(header) -> dict:
    """
    {título: índice} do cabeçalho, ignorando células vazias/None. Em caso de
    título duplicado, mantém a PRIMEIRA ocorrência (é a coluna que o programa
    gravou; duplicatas costumam ser cópias feitas à mão pelo usuário).
    """
    indexes = {}
    for i, title in enumerate(header or ()):
        if title is None:
            continue
        nome = str(title).strip()
        if nome and nome not in indexes:
            indexes[nome] = i
    return indexes


def import_statuses(path: str = None) -> int:
    """
    Lê as colunas Situação e Auto-preencher da planilha (todas as abas) e
    atualiza o banco. Retorna quantas vagas mudaram (soma das duas colunas).

    Tolerante a planilhas editadas à mão: cabeçalho com células vazias,
    linhas curtas, ID numérico/texto e cabeçalhos duplicados.
    """
    path = path or config.XLSX_PATH
    if not os.path.exists(path):
        return 0
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        logger.warning("Não consegui ler a planilha (%s). Ignorando marcações.", exc)
        return 0

    status_changes, autofill_changes = {}, {}
    try:
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            header = next(rows, None)
            if not header:
                continue
            indexes = _header_indexes(header)
            if HEADER_TITLE_ID not in indexes:
                continue

            i_id = indexes[HEADER_TITLE_ID]
            columns = [  # (coluna atual, coluna "ao gerar", conversor, destino)
                (indexes.get(HEADER_TITLE_STATUS),
                 indexes.get(HEADER_TITLE_STATUS_SNAP), _to_status, status_changes),
                (indexes.get(HEADER_TITLE_AUTOFILL),
                 indexes.get(HEADER_TITLE_AUTOFILL_SNAP), _to_autofill, autofill_changes),
            ]
            for row in rows:
                if not row or len(row) <= i_id:
                    continue
                job_id = _cell_job_id(row[i_id])
                if job_id is None:
                    continue
                for i_cur, i_snap, convert, changes in columns:
                    if i_cur is None or len(row) <= i_cur:
                        continue
                    value = convert(row[i_cur])
                    if value is None:
                        # Célula vazia/irreconhecível: não temos como saber o
                        # que o usuário quis dizer; mantém o banco como está.
                        continue
                    if i_snap is not None and len(row) > i_snap:
                        snap = convert(row[i_snap])
                        if snap == value:
                            continue  # você não mexeu nesta célula
                        # Se `snap` for irreconhecível (None), a coluna oculta
                        # não serve de referência; o valor atual válido vence.
                        # Já o caso "atual irreconhecível" foi descartado acima,
                        # então nunca aplicamos lixo nos dois lados.
                    changes[job_id] = value
    finally:
        wb.close()

    updated = database.apply_statuses(status_changes)
    updated += database.apply_autofill_flags(autofill_changes)
    if updated:
        logger.info("Li suas marcações da planilha: %d vaga(s) atualizada(s).", updated)
    return updated


def sync_spreadsheet(days: int) -> str:
    """
    Lê o que você marcou na planilha e a regenera com o estado atual do banco
    (inclusive o que o CandidatarVagas marcou). Use sempre esta função para
    regerar fora de uma busca — exportar sem importar antes perderia marcações
    salvas na planilha.
    """
    import_statuses()
    return export_weekly_report(days=days)
