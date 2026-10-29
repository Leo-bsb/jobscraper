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


def _write_sheet(ws, jobs: list) -> None:
    for col, (_, title, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.fill = HEADER_FILL
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(col)].width = width

    for row, job in enumerate(jobs, start=2):
        for col, (field, _, _) in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=row, column=col, value=job.get(field, ""))
            cell.alignment = Alignment(vertical="top")
            if field == "link" and job.get(field):
                cell.hyperlink = job[field]
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


def _save(wb: Workbook, path: str) -> str:
    try:
        wb.save(path)
        return path
    except PermissionError:
        alt = path.replace(".xlsx", f"_{datetime.now():%H%M%S}.xlsx")
        wb.save(alt)
        logger.warning(
            "A planilha estava ABERTA no Excel, então salvei em outro arquivo: %s. "
            "Feche o Excel e busque de novo para que suas marcações sejam lidas.", alt)
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
        cell = ws.cell(row=1, column=col, value=title)
        cell.fill = HEADER_FILL
        cell.font = Font(color="FFFFFF", bold=True)
        ws.column_dimensions[get_column_letter(col)].width = width
    for row, job in enumerate(discarded, start=2):
        for col, (field, _, _) in enumerate(AUDIT_COLUMNS, start=1):
            cell = ws.cell(row=row, column=col, value=job.get(field, ""))
            if field == "link" and job.get(field):
                cell.hyperlink = job[field]
                cell.font = Font(color="0563C1", underline="single")
    ws.freeze_panes = "A2"
    if discarded:
        last_col = get_column_letter(len(AUDIT_COLUMNS))
        ws.auto_filter.ref = f"A1:{last_col}{len(discarded) + 1}"


def _load_discarded() -> list:
    try:
        with open(config.DISCARDED_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


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


def import_statuses(path: str = None) -> int:
    """
    Lê as colunas Situação e Auto-preencher da planilha (todas as abas) e
    atualiza o banco. Retorna quantas vagas mudaram (soma das duas colunas).
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
            if not header or HEADER_TITLE_ID not in header:
                continue
            def idx(title):
                return header.index(title) if title in header else None

            i_id = idx(HEADER_TITLE_ID)
            columns = [  # (coluna atual, coluna "ao gerar", conversor, destino)
                (idx(HEADER_TITLE_STATUS), idx(HEADER_TITLE_STATUS_SNAP), _to_status, status_changes),
                (idx(HEADER_TITLE_AUTOFILL), idx(HEADER_TITLE_AUTOFILL_SNAP), _to_autofill, autofill_changes),
            ]
            for row in rows:
                if len(row) <= i_id or not row[i_id]:
                    continue
                job_id = str(row[i_id])
                for i_cur, i_snap, convert, changes in columns:
                    if i_cur is None or len(row) <= i_cur:
                        continue
                    value = convert(row[i_cur])
                    if not value:
                        continue
                    if i_snap is not None and len(row) > i_snap and convert(row[i_snap]) == value:
                        continue  # você não mexeu nesta célula: o banco continua valendo
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
