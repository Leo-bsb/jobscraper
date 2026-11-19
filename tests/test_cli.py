"""Testes da linha de comando (main.py) — sem rede, sem Tk, sem pandas."""

import contextlib
import io
import json
import logging
import os
import shutil
import sys
import tempfile
import unittest

import config
import main

_PATHS = ("BASE_DIR", "FILTERS_PATH", "PROFILE_PATH", "DB_PATH", "XLSX_PATH", "LOG_PATH")


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jobscraper-cli-")
        self._original = {nome: getattr(config, nome) for nome in _PATHS if hasattr(config, nome)}
        config.BASE_DIR = self.tmp
        config.FILTERS_PATH = os.path.join(self.tmp, "filtros.json")
        config.PROFILE_PATH = os.path.join(self.tmp, "perfil.json")
        config.DB_PATH = os.path.join(self.tmp, "vagas.db")
        config.XLSX_PATH = os.path.join(self.tmp, "vagas_da_semana.xlsx")
        config.LOG_PATH = os.path.join(self.tmp, "buscavagas.log")

    def tearDown(self):
        for nome, valor in self._original.items():
            setattr(config, nome, valor)
        # fecha os handlers de log abertos pela CLI (senão o Windows não apaga a pasta)
        root = logging.getLogger()
        for handler in list(root.handlers):
            if getattr(handler, "_buscavagas_cli", False):
                root.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    def _write_filters(self, data):
        with io.open(config.FILTERS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def _run(self, argv):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = main.main(argv)
        return codigo, saida.getvalue()

    def _filtros_validos(self):
        filtros = json.loads(json.dumps(config.DEFAULT_FILTERS))
        filtros["termos_busca"] = ["dados"]
        filtros["cidades"] = ["Brasília, DF"]
        filtros["sites"] = ["indeed"]
        return filtros

    # ------------------------------------------------------------------
    def test_version_retorna_zero_e_imprime_versao(self):
        codigo, saida = self._run(["--version"])
        self.assertEqual(codigo, 0)
        self.assertIn(config.VERSION, saida)

    def test_check_com_filtros_validos_retorna_zero(self):
        self._write_filters(self._filtros_validos())
        codigo, saida = self._run(["--check"])
        self.assertEqual(codigo, 0, saida)
        self.assertIn("Tudo certo", saida)

    def test_check_com_filtros_vazios_retorna_dois(self):
        self._write_filters({"sites": [], "termos_busca": []})
        codigo, saida = self._run(["--check"])
        self.assertEqual(codigo, 2, saida)
        self.assertIn("sites", saida)
        self.assertIn("termos_busca", saida)

    def test_dry_run_nao_importa_rede_e_mostra_contagem(self):
        filtros = self._filtros_validos()
        filtros["sites"] = ["indeed", "linkedin"]
        filtros["aceitar_home_office_todo_brasil"] = True
        self._write_filters(filtros)

        codigo, saida = self._run(["--dry-run"])
        self.assertEqual(codigo, 0, saida)
        self.assertIn("Consultas:", saida)
        self.assertIn("indeed", saida)
        # 1 termo x 2 sites x (1 local + 1 nacional) = 4 consultas
        self.assertIn("Consultas: 4", saida)
        # Nada de jobspy/rede: o import é tardio e não deve acontecer aqui.
        self.assertNotIn("jobspy", sys.modules)

    def test_days_fora_da_faixa_gera_erro_do_argparse(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                main.main(["--days", "0"])
        self.assertEqual(ctx.exception.code, 2)

    def test_days_acima_de_90_tambem_e_recusado(self):
        with contextlib.redirect_stderr(io.StringIO()) as erro:
            with self.assertRaises(SystemExit) as ctx:
                main.main(["--days", "91"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("90", erro.getvalue())

    def test_days_no_limite_superior_funciona(self):
        self._write_filters(self._filtros_validos())
        codigo, saida = self._run(["--days", "90", "--dry-run"])
        self.assertEqual(codigo, 0, saida)
        self.assertIn("Consultas:", saida)

    def test_check_aponta_dias_fora_da_faixa(self):
        filtros = self._filtros_validos()
        filtros["dias"] = 120
        self._write_filters(filtros)
        codigo, saida = self._run(["--check"])
        self.assertEqual(codigo, 2, saida)
        self.assertIn("dias", saida)
        self.assertIn("1 e 90", saida)

    def test_only_export_gera_planilha_valida_em_pasta_temporaria(self):
        try:
            from openpyxl import load_workbook
        except ImportError:
            self.skipTest("openpyxl indisponível")
        self._write_filters(self._filtros_validos())
        codigo, saida = self._run(["--only-export"])
        self.assertEqual(codigo, 0, saida)
        self.assertTrue(os.path.isfile(config.XLSX_PATH), saida)
        wb = load_workbook(config.XLSX_PATH)
        self.assertIn("Vagas", wb.sheetnames)
        self.assertEqual(wb["Vagas"]["A1"].value, "Situação")
        wb.close()


if __name__ == "__main__":
    unittest.main()
