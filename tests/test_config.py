"""Testes de migração/robustez do filtros.json."""

import io
import json
import os
import shutil
import tempfile
import unittest

import config


class LoadFiltersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jobscraper-cfg-")
        self._old_path = config.FILTERS_PATH
        config.FILTERS_PATH = os.path.join(self.tmp, "filtros.json")

    def tearDown(self):
        config.FILTERS_PATH = self._old_path
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, data):
        with io.open(config.FILTERS_PATH, "w", encoding="utf-8") as f:
            if isinstance(data, str):
                f.write(data)
            else:
                json.dump(data, f)

    def test_cria_arquivo_quando_nao_existe(self):
        filters = config.load_filters()
        self.assertTrue(os.path.exists(config.FILTERS_PATH))
        self.assertEqual(filters["versao_filtros"], config.FILTERS_VERSION)

    def test_versao_nula_nao_derruba_o_programa(self):
        # int(None) levantava TypeError e o .exe não abria.
        self._write({"versao_filtros": None, "termos_busca": ["dados"]})
        filters = config.load_filters()
        self.assertEqual(filters["termos_busca"], ["dados"])
        self.assertEqual(filters["versao_filtros"], config.FILTERS_VERSION)

    def test_json_corrompido_gera_backup(self):
        self._write("{ isto nao e json")
        filters = config.load_filters()
        self.assertEqual(filters["versao_filtros"], config.FILTERS_VERSION)
        self.assertTrue(os.path.exists(config.FILTERS_PATH + ".bak"))
        # o arquivo antigo foi preservado, não sobrescrito
        with io.open(config.FILTERS_PATH + ".bak", encoding="utf-8") as f:
            self.assertIn("isto nao e json", f.read())

    def test_json_que_nao_e_objeto(self):
        self._write("[1, 2, 3]")
        self.assertEqual(config.load_filters()["versao_filtros"], config.FILTERS_VERSION)

    def test_migracao_v3_para_v4_troca_remoto_por_radical(self):
        self._write({
            "versao_filtros": 3,
            "cidades": ["Brasília, DF"],
            "termos_home_office": ["home office", "remoto", "remote"],
        })
        filters = config.load_filters()
        self.assertIn("remot", filters["termos_home_office"])
        self.assertNotIn("remoto", filters["termos_home_office"])
        self.assertNotIn("remote", filters["termos_home_office"])

    def test_migracao_v2_para_v4_preserva_cidades(self):
        self._write({
            "versao_filtros": 2,
            "cidade": "Brasília, DF",
            "locais_extras": ["Taguatinga, DF"],
            "termos_proibidos": ["estagi", "digitador"],
        })
        filters = config.load_filters()
        self.assertEqual(filters["cidades"], ["Brasília, DF", "Taguatinga, DF", "DF"])
        self.assertIn("estagi", filters["termos_proibidos_titulo"])
        self.assertNotIn("estagi", filters["termos_proibidos"])
        self.assertIn("digitador", filters["termos_proibidos"])

    def test_perfis_prontos_migram_sem_erro(self):
        for caminho in config.list_presets().values():
            filtros = config.load_preset(caminho)
            self.assertIn("remot", filtros["termos_home_office"], caminho)


if __name__ == "__main__":
    unittest.main()
