"""
Teste de ponta a ponta SEM rede: coleta simulada -> filtro -> banco -> planilha
-> leitura das marcações da planilha -> nova planilha. Só usa openpyxl e SQLite.
"""

import copy
import os
import shutil
import tempfile
import unittest

try:
    import openpyxl  # noqa: F401
except ImportError:  # pragma: no cover - depende do ambiente
    raise unittest.SkipTest("openpyxl não está instalado")

import config
import database
import export_xlsx
import pipeline


class QuadroFalso:
    """Imita o DataFrame que o pipeline recebe do coletor (sem pandas)."""

    def __init__(self, linhas):
        self._linhas = [dict(linha) for linha in linhas]
        self.empty = not self._linhas

    def __len__(self):
        return len(self._linhas)

    def astype(self, _dtype):
        return self

    def notna(self):
        return self

    def where(self, _cond, _other):
        return self

    def to_dict(self, orient="records"):
        if orient != "records":
            raise AssertionError("orient inesperado: %r" % (orient,))
        return [dict(linha) for linha in self._linhas]


def _vaga(titulo, local, descricao, url, empresa="ACME"):
    return {
        "title": titulo, "company": empresa, "location": local,
        "description": descricao, "job_url": url, "site": "indeed",
        "date_posted": "2026-11-18", "min_amount": None, "max_amount": None,
    }


class IntegracaoOfflineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jobscraper-e2e-")
        self._paths = (config.DB_PATH, config.XLSX_PATH, config.DISCARDED_PATH)
        config.DB_PATH = os.path.join(self.tmp, "vagas.db")
        config.XLSX_PATH = os.path.join(self.tmp, "vagas_da_semana.xlsx")
        config.DISCARDED_PATH = os.path.join(self.tmp, "descartadas.json")
        self.filters = copy.deepcopy(config.DEFAULT_FILTERS)
        self.filters["dias"] = 7

    def tearDown(self):
        config.DB_PATH, config.XLSX_PATH, config.DISCARDED_PATH = self._paths
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _coleta(self):
        return QuadroFalso([
            _vaga("Analista de Dados", "Brasília, DF", "Python e SQL.", "https://x/1"),
            # Fora da cidade e presencial: descartada (aba de auditoria).
            _vaga("Analista de Dados Pleno", "São Paulo, SP",
                  "Python e SQL. Presencial.", "https://x/2"),
            # Remota: aprovada mesmo fora da cidade.
            _vaga("Engenheiro de Dados", "São Paulo, SP",
                  "Vaga remota. Python e SQL.", "https://x/3"),
            # Sem termos: descartada.
            _vaga("Recepcionista", "Brasília, DF", "Recepção.", "https://x/4"),
        ])

    def test_fluxo_completo(self):
        resultado = pipeline.run_search(self.filters, scrape=lambda _f: self._coleta())

        self.assertEqual(resultado["erros"], [])
        self.assertEqual(resultado["coletadas"], 4)
        self.assertEqual(resultado["aprovadas"], 2)
        self.assertEqual(resultado["novas"], 2)
        self.assertTrue(os.path.exists(resultado["planilha"]))

        with database.get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM vagas").fetchone()[0]
        self.assertEqual(total, 2)

        wb = openpyxl.load_workbook(resultado["planilha"])
        self.assertIn("Descartadas (última busca)", wb.sheetnames)
        self.assertEqual(wb["Vagas"].max_row, 3)       # cabeçalho + 2 aprovadas
        self.assertEqual(wb["Já tratadas"].max_row, 1)  # só o cabeçalho

    def test_marcacao_na_planilha_sobrevive_a_nova_busca(self):
        primeira = pipeline.run_search(self.filters, scrape=lambda _f: self._coleta())
        wb = openpyxl.load_workbook(primeira["planilha"])
        ws = wb["Vagas"]
        colunas = {c.value: c.column for c in ws[1]}
        # Marca a primeira vaga como "Candidatei" (só a coluna visível).
        ws.cell(row=2, column=colunas["Situação"]).value = config.STATUS_CANDIDATEI
        wb.save(primeira["planilha"])

        # Nova busca sem vagas: deve ler a marcação e regerar a planilha.
        segunda = pipeline.run_search(
            self.filters, scrape=lambda _f: QuadroFalso([]))

        self.assertEqual(len(database.get_treated()), 1)
        self.assertEqual(len(database.get_pending(days=30)), 1)
        wb2 = openpyxl.load_workbook(segunda["planilha"])
        self.assertEqual(wb2["Vagas"].max_row, 2)        # cabeçalho + 1 pendente
        self.assertEqual(wb2["Já tratadas"].max_row, 2)  # cabeçalho + Candidatei

    def test_falha_de_coleta_ainda_gera_planilha(self):
        def coletor(_filters):
            raise RuntimeError("site fora do ar")

        resultado = pipeline.run_search(self.filters, scrape=coletor)
        self.assertTrue(resultado["erros"])
        self.assertTrue(os.path.exists(resultado["planilha"]))
        self.assertEqual(resultado["novas"], 0)
        self.assertEqual(resultado["coletadas"], 0)


if __name__ == "__main__":
    unittest.main()
