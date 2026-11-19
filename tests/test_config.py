"""Testes de migração/robustez do filtros.json."""

import copy
import importlib
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from unittest import mock

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
            self.assertEqual(filtros["versao_filtros"], config.FILTERS_VERSION, caminho)
            self.assertEqual(config.validate_filters(filtros), [], caminho)

    def test_cidades_como_texto_nao_vira_caracteres(self):
        # list("Brasília, DF") explodia o texto em letras e o filtro de local
        # passava a aceitar qualquer vaga (cada letra virava uma "cidade").
        for versao in (0, 2, 4):
            with self.subTest(versao=versao):
                self._write({"versao_filtros": versao, "cidades": "Brasília, DF"})
                filtros = config.load_filters()
                # Texto vira UM item; nunca uma letra por elemento.
                self.assertEqual(filtros["cidades"], ["Brasília, DF"])

    def test_migracao_com_campos_de_lista_como_texto_ou_none(self):
        self._write({
            "versao_filtros": 2,
            "cidade": "Belo Horizonte, MG",
            "locais_extras": "Contagem",
            "termos_proibidos": "digitador",
            "termos_home_office": "remoto",
        })
        filtros = config.load_filters()
        self.assertEqual(filtros["cidades"], ["Belo Horizonte, MG", "Contagem"])
        self.assertEqual(filtros["termos_proibidos"], ["digitador"])
        self.assertEqual(filtros["termos_home_office"], ["remot"])

        self._write({"versao_filtros": 2, "termos_proibidos": None})
        filtros = config.load_filters()
        self.assertEqual(filtros["termos_proibidos"], [])
        self.assertEqual(filtros["versao_filtros"], config.FILTERS_VERSION)

    def test_load_filters_corrige_tipos(self):
        # A correção é aplicada só em memória (não regrava o arquivo).
        self._write({
            "versao_filtros": 4,
            "termos_busca": "python, sql",
            "sites": "indeed",
            "dias": "7",
            "alcance_km": "80,5",
            "minimo_de_termos": "2",
            "termos_fortes": None,
            "exigir_termo_forte": "sim",
        })
        with io.open(config.FILTERS_PATH, encoding="utf-8") as f:
            antes = f.read()
        filtros = config.load_filters()
        self.assertEqual(filtros["termos_busca"], ["python", "sql"])
        self.assertEqual(filtros["sites"], ["indeed"])
        self.assertEqual(filtros["dias"], 7)
        self.assertEqual(filtros["alcance_km"], 80.5)
        self.assertEqual(filtros["minimo_de_termos"], 2)
        self.assertEqual(filtros["termos_fortes"], [])
        self.assertIs(filtros["exigir_termo_forte"], True)
        with io.open(config.FILTERS_PATH, encoding="utf-8") as f:
            self.assertEqual(f.read(), antes)  # nada foi salvo automaticamente


class ValidateFiltersTest(unittest.TestCase):
    def test_filtros_padrao_sao_validos(self):
        self.assertEqual(config.validate_filters(copy.deepcopy(config.DEFAULT_FILTERS)), [])

    def test_lista_de_problemas_legivel(self):
        filtros = copy.deepcopy(config.DEFAULT_FILTERS)
        filtros["sites"] = []
        filtros["termos_busca"] = []
        filtros["cidades"] = [None]
        filtros["dias"] = 0
        filtros["resultados_por_busca"] = 2000
        filtros["alcance_km"] = 999
        filtros["minimo_de_termos"] = 99
        filtros["exigir_termo_forte"] = "sim"
        problemas = config.validate_filters(filtros)
        texto = "\n".join(problemas)
        self.assertIn("sites: lista vazia — escolha pelo menos um site", texto)
        self.assertIn("termos_busca: lista vazia", texto)
        self.assertIn("cidades: o item 1 não é um texto válido", texto)
        self.assertIn("dias:", texto)
        self.assertIn("resultados_por_busca:", texto)
        self.assertIn("alcance_km:", texto)
        self.assertIn("minimo_de_termos:", texto)
        self.assertIn("exigir_termo_forte:", texto)

    def test_site_desconhecido(self):
        filtros = copy.deepcopy(config.DEFAULT_FILTERS)
        filtros["sites"] = ["indeed", "sine"]
        texto = "\n".join(config.validate_filters(filtros))
        self.assertIn("sites: site desconhecido 'sine'", texto)

    def test_resultados_none_e_flag_apontados(self):
        filtros = copy.deepcopy(config.DEFAULT_FILTERS)
        filtros["resultados_por_busca"] = None
        filtros["dias"] = None
        texto = "\n".join(config.validate_filters(filtros))
        self.assertIn("resultados_por_busca:", texto)
        self.assertIn("dias:", texto)

    def test_entrada_que_nao_e_dict(self):
        self.assertTrue(config.validate_filters(None))


class CoerceFiltersTest(unittest.TestCase):
    def test_corrige_tipos_sem_mutar_original(self):
        original = {
            "termos_busca": "dados",
            "cidades": "Brasília, DF",
            "sites": "indeed, linkedin",
            "dias": "7",
            "alcance_km": "80,5",
            "minimo_de_termos": "2",
            "versao_filtros": "4",
            "resultados_por_busca": "40",
            "termos_fracos": None,
            "aceitar_home_office_todo_brasil": "não",
        }
        copia = copy.deepcopy(original)
        filtros = config.coerce_filters(original)
        self.assertEqual(original, copia)  # não altera o dicionário recebido
        self.assertEqual(filtros["termos_busca"], ["dados"])
        self.assertEqual(filtros["cidades"], ["Brasília, DF"])
        self.assertEqual(filtros["sites"], ["indeed", "linkedin"])
        self.assertEqual(filtros["dias"], 7)
        self.assertEqual(filtros["alcance_km"], 80.5)
        self.assertEqual(filtros["minimo_de_termos"], 2)
        self.assertEqual(filtros["versao_filtros"], 4)
        self.assertEqual(filtros["resultados_por_busca"], 40)
        self.assertEqual(filtros["termos_fracos"], [])
        self.assertIs(filtros["aceitar_home_office_todo_brasil"], False)

    def test_nao_descarta_valores_invalidos(self):
        filtros = config.coerce_filters({"dias": "sete"})
        self.assertEqual(filtros["dias"], "sete")  # quem aponta o erro é validate_filters

    def test_load_preset_tambem_corrige(self):
        tmp = tempfile.mkdtemp(prefix="jobscraper-preset-")
        try:
            caminho = os.path.join(tmp, "perfil.json")
            with io.open(caminho, "w", encoding="utf-8") as f:
                json.dump({"_nome_exibicao": "Teste", "versao_filtros": 4,
                           "termos_busca": "python, sql", "sites": "indeed"}, f)
            filtros = config.load_preset(caminho)
            self.assertEqual(filtros["termos_busca"], ["python", "sql"])
            self.assertEqual(filtros["sites"], ["indeed"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class EscritaAtomicaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jobscraper-atomic-")
        self._old_filters = config.FILTERS_PATH
        self._old_profile = config.PROFILE_PATH
        config.FILTERS_PATH = os.path.join(self.tmp, "filtros.json")
        config.PROFILE_PATH = os.path.join(self.tmp, "perfil.json")

    def tearDown(self):
        config.FILTERS_PATH = self._old_filters
        config.PROFILE_PATH = self._old_profile
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_salva_sem_deixar_temporario(self):
        config.save_filters({"a": 1})
        self.assertEqual(os.listdir(self.tmp), ["filtros.json"])
        with io.open(config.FILTERS_PATH, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"a": 1})

    def test_falha_propaga_erro_claro_e_limpa_temporario(self):
        with mock.patch.object(config.os, "replace", side_effect=OSError("disco cheio")):
            with self.assertRaises(OSError) as ctx:
                config.save_filters({"a": 1})
        self.assertIn("Não consegui gravar", str(ctx.exception))
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".tmp-")], [])
        self.assertFalse(os.path.exists(config.FILTERS_PATH))

    def test_falha_no_meio_preserva_conteudo_antigo(self):
        config.save_filters({"original": "íntegro ✅"})
        with io.open(config.FILTERS_PATH, encoding="utf-8") as f:
            antes = f.read()
        with mock.patch.object(config.json, "dump", side_effect=OSError("sem espaço")):
            with self.assertRaises(OSError) as ctx:
                config.save_filters({"novo": True})
        self.assertIn("Não consegui gravar", str(ctx.exception))
        with io.open(config.FILTERS_PATH, encoding="utf-8") as f:
            self.assertEqual(f.read(), antes)
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".tmp-")], [])

    def test_diretorio_inexistente_da_erro_claro(self):
        destino = os.path.join(self.tmp, "nao_existe", "filtros.json")
        with self.assertRaises(OSError) as ctx:
            config._write_json_atomic(destino, {"a": 1})
        self.assertIn("Não consegui criar o arquivo temporário", str(ctx.exception))

    def test_ida_e_volta_preserva_acentos_e_emoji(self):
        dados = {
            "versao_filtros": config.FILTERS_VERSION,
            "termos_busca": ["análise de dados 🚀", "saúde", "ação"],
            "cidades": ["Brasília, DF", "São Paulo, SP"],
            "observacao": "não remova ✅",
        }
        config.save_filters(dados)
        lido = config.load_filters()
        self.assertEqual(lido["termos_busca"], dados["termos_busca"])
        self.assertEqual(lido["cidades"], dados["cidades"])
        with io.open(config.FILTERS_PATH, encoding="utf-8") as f:
            bruto = f.read()
        self.assertIn("🚀", bruto)  # ensure_ascii=False: emoji legível no arquivo
        self.assertIn("análise", bruto)


class ProfilePermissionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jobscraper-profile-")
        self._old_profile = config.PROFILE_PATH
        config.PROFILE_PATH = os.path.join(self.tmp, "perfil.json")

    def tearDown(self):
        config.PROFILE_PATH = self._old_profile
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipIf(os.name != "posix", "permissões POSIX não se aplicam ao Windows")
    def test_perfil_fica_restrito_ao_dono(self):
        config.save_profile({"email": "eu@exemplo.com"})
        modo = stat.S_IMODE(os.stat(config.PROFILE_PATH).st_mode)
        self.assertEqual(modo, 0o600)


class BomTest(unittest.TestCase):
    """JSON salvo pelo Bloco de Notas (UTF-8 com BOM) não é arquivo corrompido."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jobscraper-bom-")
        self._old_path = config.FILTERS_PATH
        config.FILTERS_PATH = os.path.join(self.tmp, "filtros.json")

    def tearDown(self):
        config.FILTERS_PATH = self._old_path
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_filtros_com_bom_carregam_normalmente(self):
        dados = json.dumps({"versao_filtros": 4, "termos_busca": ["dados"]},
                           ensure_ascii=False).encode("utf-8")
        with open(config.FILTERS_PATH, "wb") as f:
            f.write(b"\xef\xbb\xbf" + dados)

        filters = config.load_filters()

        self.assertEqual(filters["termos_busca"], ["dados"])
        # Foi lido de verdade: não houve backup de "arquivo corrompido".
        self.assertFalse(os.path.exists(config.FILTERS_PATH + ".bak"))


class SmtpPortTest(unittest.TestCase):
    def _com_env(self, valor):
        try:
            with mock.patch.dict(os.environ, {"JOBSCRAPER_SMTP_PORT": valor}):
                modulo = importlib.reload(config)
                return modulo.SMTP_PORT
        finally:
            importlib.reload(config)

    def test_porta_valida(self):
        self.assertEqual(self._com_env("2525"), 2525)

    def test_porta_invalida_usa_padrao(self):
        self.assertEqual(self._com_env("abc"), 587)

    def test_porta_fora_da_faixa_usa_padrao(self):
        self.assertEqual(self._com_env("99999"), 587)


class DiasDoFiltroTest(unittest.TestCase):
    """config.dias_do_filtro(): nunca quebra ao regerar a planilha fora da busca."""

    def test_valor_normal(self):
        self.assertEqual(config.dias_do_filtro({"dias": 14}), 14)

    def test_string_numerica(self):
        self.assertEqual(config.dias_do_filtro({"dias": "7"}), 7)

    def test_ausente_usa_padrao(self):
        self.assertEqual(config.dias_do_filtro({}), 7)

    def test_nulo_ou_texto_usa_padrao(self):
        self.assertEqual(config.dias_do_filtro({"dias": None}), 7)
        self.assertEqual(config.dias_do_filtro({"dias": "sete"}), 7)

    def test_filtros_invalidos_nao_estouram(self):
        self.assertEqual(config.dias_do_filtro(None), 7)
        self.assertEqual(config.dias_do_filtro(["dias"]), 7)

    def test_valores_fora_da_faixa_sao_limitados(self):
        self.assertEqual(config.dias_do_filtro({"dias": 0}), 1)
        self.assertEqual(config.dias_do_filtro({"dias": 999}), 90)
        self.assertEqual(config.dias_do_filtro({"dias": -5}), 1)


if __name__ == "__main__":
    unittest.main()
