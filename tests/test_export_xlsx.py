"""Testes da planilha (openpyxl). Pulados se a biblioteca não estiver instalada."""

import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from unittest import mock

try:
    import openpyxl
    from openpyxl import Workbook, load_workbook
except ImportError:  # pragma: no cover - depende do ambiente
    raise unittest.SkipTest("openpyxl não está instalado")

import config
import database
import export_xlsx


def _record(job_id="id1", chave="c-1", **kwargs):
    base = {
        "id": job_id,
        "chave_dup": chave,
        "titulo": "Analista de Dados",
        "empresa": "ACME",
        "localizacao": "Brasília, DF",
        "modelo_trabalho": "Presencial",
        "faixa_salarial": "",
        "termos_encontrados": "python, sql",
        "pontos": 2,
        "link": "https://exemplo/vaga/1",
        "descricao": "Python e SQL",
        "site_origem": "indeed",
        "data_publicacao": datetime.now().strftime("%Y-%m-%d"),
        "data_coleta": datetime.now().isoformat(timespec="seconds"),
        "situacao": config.STATUS_PENDENTE,
        "auto_preencher": config.AUTOFILL_NAO,
    }
    base.update(kwargs)
    return base


def _col(ws, title):
    """Índice (1-based) da coluna pelo título do cabeçalho."""
    for cell in ws[1]:
        if cell.value == title:
            return cell.column
    raise AssertionError("coluna não encontrada: %s" % title)


def _row_by_id(ws, job_id):
    col_id = _col(ws, export_xlsx.HEADER_TITLE_ID)
    for row in ws.iter_rows(min_row=2):
        if row[col_id - 1].value == job_id:
            return row[0].row
    raise AssertionError("vaga não encontrada na planilha: %s" % job_id)


class ExportXlsxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jobscraper-xlsx-")
        self._old_paths = (config.DB_PATH, config.XLSX_PATH, config.DISCARDED_PATH)
        config.DB_PATH = os.path.join(self.tmp, "vagas.db")
        config.XLSX_PATH = os.path.join(self.tmp, "vagas_da_semana.xlsx")
        config.DISCARDED_PATH = os.path.join(self.tmp, "descartadas.json")
        database.init_db()

    def tearDown(self):
        config.DB_PATH, config.XLSX_PATH, config.DISCARDED_PATH = self._old_paths
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gera_abas_e_cabecalhos(self):
        database.save_jobs([_record()])
        path = export_xlsx.export_weekly_report(days=30, discarded=[])
        self.assertTrue(os.path.exists(path))

        wb = load_workbook(path)
        self.assertEqual(wb.sheetnames[:2], ["Vagas", "Já tratadas"])
        cabecalho = [c.value for c in wb["Vagas"][1]]
        self.assertEqual(cabecalho, [titulo for _, titulo, _ in export_xlsx.COLUMNS])

    def test_gera_arquivo_mesmo_sem_vagas(self):
        path = export_xlsx.export_weekly_report(days=7, discarded=[])
        wb = load_workbook(path)
        self.assertEqual(wb.sheetnames, ["Vagas", "Já tratadas"])
        # Só a linha de cabeçalho em cada aba.
        self.assertEqual(wb["Vagas"].max_row, 1)
        self.assertEqual(wb["Já tratadas"].max_row, 1)

    def test_formula_em_dado_raspado_vira_texto(self):
        database.save_jobs([_record(
            titulo="=1+1",
            empresa="+ACME",
            localizacao="@local",
            modelo_trabalho="-x",
            termos_encontrados="\tpython",
        )])
        path = export_xlsx.export_weekly_report(days=30, discarded=[])
        ws = load_workbook(path)["Vagas"]
        row = _row_by_id(ws, "id1")
        esperados = {
            "Cargo": "=1+1",
            "Empresa": "+ACME",
            "Local": "@local",
            "Modelo": "-x",
            "Termos encontrados": "\tpython",
        }
        for titulo, valor in esperados.items():
            cell = ws.cell(row=row, column=_col(ws, titulo))
            # Conteúdo original preservado (sem apóstrofo visível) e força de
            # texto (quotePrefix), nunca fórmula.
            self.assertEqual(cell.value, valor, titulo)
            self.assertNotEqual(cell.data_type, "f", titulo)
            self.assertTrue(cell.quotePrefix, titulo)

    def test_formula_nao_e_gravada_como_formula_no_xml(self):
        import zipfile
        database.save_jobs([_record(
            job_id="inj", chave="c-inj", titulo="=1+1", empresa="+cmd",
            localizacao="-2+3", termos_encontrados="@SUM(A1)")])
        path = export_xlsx.export_weekly_report(days=30, discarded=[])
        with zipfile.ZipFile(path) as z:
            xml = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertNotIn("<f>", xml)
        self.assertNotIn("<f ", xml)
        self.assertIn("=1+1", xml)  # conteúdo íntegro, como texto

    def test_apostrofo_nao_aparece_na_planilha(self):
        # A abordagem antiga gravava "'=1+1" e o apóstrofo aparecia na célula.
        database.save_jobs([_record(titulo="=1+1")])
        path = export_xlsx.export_weekly_report(days=30, discarded=[])
        ws = load_workbook(path)["Vagas"]
        cell = ws.cell(row=_row_by_id(ws, "id1"), column=_col(ws, "Cargo"))
        self.assertEqual(cell.value, "=1+1")
        self.assertFalse(cell.value.startswith("'"))

    def test_texto_gigante_e_cortado_no_limite_do_excel(self):
        database.save_jobs([_record(titulo="A" * 40000)])
        path = export_xlsx.export_weekly_report(days=30, discarded=[])
        ws = load_workbook(path)["Vagas"]
        row = _row_by_id(ws, "id1")
        cell = ws.cell(row=row, column=_col(ws, "Cargo"))
        self.assertEqual(len(cell.value), export_xlsx.MAX_CELL_CHARS)

    def test_link_gigante_e_cortado_no_limite_do_excel(self):
        link = "https://exemplo.com/" + "a" * 40000
        database.save_jobs([_record(link=link)])
        path = export_xlsx.export_weekly_report(days=30, discarded=[])
        ws = load_workbook(path)["Vagas"]
        cell = ws.cell(row=_row_by_id(ws, "id1"), column=_col(ws, "Link"))
        self.assertEqual(len(cell.value), export_xlsx.MAX_CELL_CHARS)
        self.assertLessEqual(len(cell.hyperlink.target), export_xlsx.MAX_CELL_CHARS)

    def test_link_invalido_nao_gera_hyperlink(self):
        database.save_jobs([
            _record(job_id="ruim", chave="c-ruim", link="javascript:alert(1)"),
            _record(job_id="bom", chave="c-bom", link="https://exemplo/vaga/2"),
        ])
        path = export_xlsx.export_weekly_report(days=30, discarded=[])
        ws = load_workbook(path)["Vagas"]
        col_link = _col(ws, "Link")

        ruim = ws.cell(row=_row_by_id(ws, "ruim"), column=col_link)
        self.assertIsNone(ruim.hyperlink)
        self.assertEqual(ruim.value, "javascript:alert(1)")

        bom = ws.cell(row=_row_by_id(ws, "bom"), column=col_link)
        self.assertEqual(bom.hyperlink.target, "https://exemplo/vaga/2")

    def test_somente_http_ou_https_vira_hyperlink(self):
        links = [
            "file:///C:/Windows/System32/calc.exe",
            "=HYPERLINK(\"http://malicioso\",\"clique\")",
            "ftp://exemplo/x",
            "https://ok.exemplo/vaga",
        ]
        database.save_jobs([
            _record(job_id="l%d" % i, chave="cl%d" % i, link=link)
            for i, link in enumerate(links)
        ])
        path = export_xlsx.export_weekly_report(days=30, discarded=[])
        ws = load_workbook(path)["Vagas"]
        col = _col(ws, "Link")
        for i, link in enumerate(links):
            cell = ws.cell(row=_row_by_id(ws, "l%d" % i), column=col)
            self.assertEqual(cell.value, link)  # conteúdo íntegro
            self.assertNotEqual(cell.data_type, "f")
            if link.startswith("https://"):
                self.assertIsNotNone(cell.hyperlink)
                self.assertEqual(cell.hyperlink.target, link)
            else:
                self.assertIsNone(cell.hyperlink)

    def test_import_statuses_com_id_numerico(self):
        database.save_jobs([_record(job_id="123", chave="c-123")])
        wb = Workbook()
        ws = wb.active
        ws.append(["ID", "Situação", "Situação (ao gerar)"])
        ws.append([123, "Candidatei", "Pendente"])  # ID como número
        path = os.path.join(self.tmp, "numerico.xlsx")
        wb.save(path)
        self.assertEqual(export_xlsx.import_statuses(path), 1)
        self.assertEqual([v["id"] for v in database.get_treated()], ["123"])

    def test_conversao_de_status_tolera_maiusculas_e_acentos(self):
        self.assertEqual(export_xlsx._to_status("Candidatei"), config.STATUS_CANDIDATEI)
        self.assertEqual(export_xlsx._to_status("candidato"), config.STATUS_CANDIDATEI)
        self.assertEqual(export_xlsx._to_status("CANDIDATADO"), config.STATUS_CANDIDATEI)
        self.assertEqual(export_xlsx._to_status("recusada"), config.STATUS_RECUSEI)
        self.assertEqual(export_xlsx._to_status("Pendente "), config.STATUS_PENDENTE)
        self.assertIsNone(export_xlsx._to_status("talvez"))
        self.assertEqual(export_xlsx._to_autofill("não"), config.AUTOFILL_NAO)
        self.assertEqual(export_xlsx._to_autofill("NAO"), config.AUTOFILL_NAO)
        self.assertEqual(export_xlsx._to_autofill("Sim"), config.AUTOFILL_SIM)
        self.assertIsNone(export_xlsx._to_autofill("talvez"))

    def test_leitura_tolerante_a_descartadas_corrompidas(self):
        with io.open(config.DISCARDED_PATH, "w", encoding="utf-8") as f:
            f.write("{ isto não é json")
        database.save_jobs([_record()])
        path = export_xlsx.export_weekly_report(days=30)  # discarded=None -> lê o arquivo
        wb = load_workbook(path)
        self.assertEqual(wb.sheetnames, ["Vagas", "Já tratadas"])

    def test_descartadas_que_nao_sao_lista_sao_ignoradas(self):
        with io.open(config.DISCARDED_PATH, "w", encoding="utf-8") as f:
            json.dump({"nao": "e lista"}, f)
        path = export_xlsx.export_weekly_report(days=7)
        self.assertEqual(load_workbook(path).sheetnames, ["Vagas", "Já tratadas"])

    def test_import_statuses_so_aplica_o_que_mudou(self):
        database.save_jobs([_record()])
        path = export_xlsx.export_weekly_report(days=30, discarded=[])
        wb = load_workbook(path)
        ws = wb["Vagas"]
        row = _row_by_id(ws, "id1")
        col_status = _col(ws, export_xlsx.HEADER_TITLE_STATUS)
        col_snap = _col(ws, export_xlsx.HEADER_TITLE_STATUS_SNAP)

        # Planilha "gerada" quando o banco já estava Candidatei: atual == snapshot.
        ws.cell(row=row, column=col_status).value = config.STATUS_CANDIDATEI
        ws.cell(row=row, column=col_snap).value = config.STATUS_CANDIDATEI
        wb.save(path)
        self.assertEqual(export_xlsx.import_statuses(path), 0)
        self.assertEqual(len(database.get_pending(days=30)), 1)

        # Agora o usuário mudou só a coluna visível.
        wb = load_workbook(path)
        ws = wb["Vagas"]
        row = _row_by_id(ws, "id1")
        ws.cell(row=row, column=col_status).value = config.STATUS_RECUSEI
        wb.save(path)
        self.assertEqual(export_xlsx.import_statuses(path), 1)
        self.assertEqual([v["id"] for v in database.get_treated()], ["id1"])

        # Células irreconhecíveis dos dois lados não mudam nada.
        wb = load_workbook(path)
        ws = wb["Vagas"]
        row = _row_by_id(ws, "id1")
        ws.cell(row=row, column=col_status).value = "???"
        ws.cell(row=row, column=col_snap).value = "???"
        wb.save(path)
        self.assertEqual(export_xlsx.import_statuses(path), 0)

    def test_round_trip_de_status_e_autofill(self):
        database.save_jobs([_record()])
        path = export_xlsx.export_weekly_report(days=30, discarded=[])
        wb = load_workbook(path)
        ws = wb["Vagas"]
        row = _row_by_id(ws, "id1")
        ws.cell(row=row, column=_col(ws, export_xlsx.HEADER_TITLE_STATUS)).value = \
            config.STATUS_CANDIDATEI
        ws.cell(row=row, column=_col(ws, export_xlsx.HEADER_TITLE_AUTOFILL)).value = \
            config.AUTOFILL_SIM
        wb.save(path)

        self.assertEqual(export_xlsx.import_statuses(path), 2)
        with database.get_connection() as conn:
            salva = conn.execute("SELECT * FROM vagas WHERE id = 'id1'").fetchone()
        self.assertEqual(salva["situacao"], config.STATUS_CANDIDATEI)
        self.assertEqual(salva["auto_preencher"], config.AUTOFILL_SIM)
        # Importar de novo o mesmo arquivo não muda nada (snapshot continua igual).
        self.assertEqual(export_xlsx.import_statuses(path), 0)

    def test_import_tolera_cabecalho_vazio_linha_curta_e_aba_estranha(self):
        database.save_jobs([
            _record(job_id="id1", chave="c-1"),
            _record(job_id="id2", chave="c-2"),
        ])
        wb = Workbook()
        ws = wb.active
        ws.title = "Vagas"
        ws.append([None, "ID", "Situação", "Situação (ao gerar)",
                   "Auto-preencher", "Auto-preencher (ao gerar)"])
        ws.append([None, "id1", "Candidatei", "Pendente", "Sim", "Não"])
        ws.append(["linha curta", "id2", "Recusei"])  # sem colunas de snapshot
        outra = wb.create_sheet("Sem cabeçalho")
        outra.append(["foo", "bar"])
        outra.append([1, 2])
        path = os.path.join(self.tmp, "manual.xlsx")
        wb.save(path)

        self.assertEqual(export_xlsx.import_statuses(path), 3)
        with database.get_connection() as conn:
            ids = {row["id"]: row["situacao"] for row in conn.execute(
                "SELECT id, situacao FROM vagas")}
        self.assertEqual(ids["id1"], config.STATUS_CANDIDATEI)
        self.assertEqual(ids["id2"], config.STATUS_RECUSEI)

    def test_cabecalho_duplicado_usa_a_primeira_ocorrencia(self):
        database.save_jobs([_record()])
        wb = Workbook()
        ws = wb.active
        ws.append(["ID", "Situação", "Situação (ao gerar)",
                   "Situação", "Situação (ao gerar)"])
        ws.append(["id1", "Candidatei", "Pendente", "Recusei", "Pendente"])
        path = os.path.join(self.tmp, "duplicado.xlsx")
        wb.save(path)

        self.assertEqual(export_xlsx.import_statuses(path), 1)
        self.assertEqual([v["id"] for v in database.get_treated()], ["id1"])

    def test_limite_de_300_descartadas(self):
        descartadas = [
            {"motivo": "teste", "titulo": "=malicioso", "empresa": "ACME",
             "localizacao": "DF", "link": "https://exemplo/%d" % i}
            for i in range(350)
        ]
        path = export_xlsx.export_weekly_report(days=7, discarded=descartadas)
        wb = load_workbook(path)
        self.assertIn("Descartadas (última busca)", wb.sheetnames)
        ws = wb["Descartadas (última busca)"]
        self.assertEqual(ws.max_row, 301)  # cabeçalho + 300
        self.assertEqual(ws.cell(row=2, column=_col(ws, "Cargo")).value, "=malicioso")

    def test_save_cai_para_nome_alternativo_em_erro_de_os(self):
        wb = Workbook()
        wb.active["A1"] = "x"
        caminho = os.path.join(self.tmp, "ocupado.xlsx")
        for erro in (PermissionError("aberta no Excel"), OSError("disco cheio")):
            with self.subTest(erro=type(erro).__name__):
                with mock.patch.object(
                        Workbook, "save", side_effect=[erro, None]):
                    salvo = export_xlsx._save(wb, caminho)
                self.assertNotEqual(salvo, caminho)
                self.assertTrue(salvo.endswith(".xlsx"))
                self.assertFalse(os.path.exists(salvo))

    def test_save_propaga_erro_claro_se_alternativo_tambem_falhar(self):
        wb = Workbook()
        caminho = os.path.join(self.tmp, "ocupado.xlsx")
        with mock.patch.object(Workbook, "save", side_effect=OSError("sem permissão")):
            with self.assertRaises(OSError) as ctx:
                export_xlsx._save(wb, caminho)
        self.assertIn("Feche o arquivo", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
