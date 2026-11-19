"""
Testes de integração entre código e documentação/empacotamento.

Não acessam rede, não precisam de Tk e não instalam nada. Quando o PyYAML não
está disponível, os testes de sintaxe dos workflows são pulados (o CI tem um
passo próprio para eles; ver README).
"""

import importlib.util
import json
import os
import re
import unittest

import main

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ler(nome: str) -> str:
    with open(os.path.join(_ROOT, nome), "r", encoding="utf-8") as f:
        return f.read()


def _flags_do_cli():
    parser = main._build_parser()
    flags = set()
    for action in parser._actions:
        for opcao in action.option_strings:
            # --help é automático do argparse, não é opção do programa.
            if opcao.startswith("--") and opcao != "--help":
                flags.add(opcao)
    return flags


class FlagsDocumentadasTest(unittest.TestCase):
    def test_todas_as_flags_do_main_aparecem_na_documentacao(self):
        flags = _flags_do_cli()
        self.assertIn("--check", flags)
        self.assertIn("--dry-run", flags)
        self.assertIn("--days", flags)
        readme = _ler("README.md")
        como_usar = _ler("COMO_USAR.txt")
        for flag in sorted(flags):
            with self.subTest(flag=flag, arquivo="README.md"):
                self.assertTrue(flag in readme, "{} não aparece no README.md".format(flag))
            with self.subTest(flag=flag, arquivo="COMO_USAR.txt"):
                self.assertTrue(flag in como_usar,
                                "{} não aparece no COMO_USAR.txt".format(flag))

    def test_limite_de_dias_documentado_bate_com_o_codigo(self):
        readme = _ler("README.md")
        self.assertIn("1 a 90", readme)
        self.assertIn(str(main.DIAS_MAX), readme)
        self.assertEqual(main.DIAS_MAX, 90)


class GitignoreTest(unittest.TestCase):
    def setUp(self):
        self.linhas = [l.strip() for l in _ler(".gitignore").splitlines() if l.strip()]

    def test_cobre_arquivos_com_dados_pessoais_e_gerados(self):
        obrigatorios = (
            "perfil.json", "filtros.json", "vagas.db", "vagas_da_semana*.xlsx",
            "buscavagas.log", "cartas/", "curriculos_adaptados/",
            "navegador_indeed/", "navegador_programa/",
            "descartadas_ultima_busca.json", ".tmp-*", ".coverage",
        )
        for padrao in obrigatorios:
            with self.subTest(padrao=padrao):
                self.assertIn(padrao, self.linhas)

    def test_perfil_exemplo_nao_e_ignorado(self):
        self.assertIn("perfil*.json", self.linhas)
        self.assertIn("!perfil_exemplo.json", self.linhas)
        # A negação precisa vir DEPOIS da regra que ignoraria o exemplo.
        self.assertLess(self.linhas.index("perfil*.json"),
                        self.linhas.index("!perfil_exemplo.json"))

    def test_bak_e_logs_genericos(self):
        self.assertTrue(any(l.startswith("filtros.json") and "*" in l for l in self.linhas))
        self.assertIn("*.log", self.linhas)


class PerfilExemploTest(unittest.TestCase):
    def test_nao_contem_dados_reais(self):
        texto = _ler("perfil_exemplo.json")
        dados = json.loads(texto)
        self.assertEqual(dados.get("nome_completo", ""), "")
        self.assertEqual(dados.get("email", ""), "")
        self.assertEqual(dados.get("telefone", ""), "")
        self.assertEqual(dados.get("google_api_key", ""), "")
        self.assertFalse(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", texto),
                         "e-mail real no perfil de exemplo")
        self.assertFalse(re.search(r"AIza[0-9A-Za-z_\-]{10,}", texto),
                         "chave real no perfil de exemplo")


class RequisitosTest(unittest.TestCase):
    def test_limites_superiores_do_requirements(self):
        linhas = [l.strip() for l in _ler("requirements.txt").splitlines()
                  if l.strip() and not l.strip().startswith("#")]
        esperados = {"python-jobspy": "<2", "pandas": "<3", "openpyxl": "<4"}
        for pacote, limite in esperados.items():
            with self.subTest(pacote=pacote):
                linha = next((l for l in linhas if l.lower().startswith(pacote.lower())), None)
                self.assertIsNotNone(linha, "{} ausente do requirements.txt".format(pacote))
                self.assertIn(limite, linha.replace(" ", ""))

    def test_requirements_build_tem_o_que_o_pyinstaller_coleta(self):
        linhas = [l.strip() for l in _ler("requirements-build.txt").splitlines()
                  if l.strip() and not l.strip().startswith("#")]
        texto = "\n".join(linhas)
        for pacote in ("pyinstaller", "playwright", "google-genai", "pypdf",
                       "python-docx", "-r requirements.txt"):
            with self.subTest(pacote=pacote):
                self.assertIn(pacote, texto.lower())


@unittest.skipUnless(importlib.util.find_spec("yaml"), "PyYAML indisponível")
class WorkflowsTest(unittest.TestCase):
    def _carregar(self, nome):
        import yaml
        with open(os.path.join(_ROOT, ".github", "workflows", nome), "r",
                  encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _passos(self, workflow):
        return workflow.get("jobs", {}).get("testes", workflow.get("jobs", {}).get("build", {})).get("steps", [])

    @staticmethod
    def _gatilhos(workflow):
        # PyYAML (YAML 1.1) lê a chave "on" como booleano True.
        return workflow.get("on", workflow.get(True)) or {}

    def test_tests_yml_roda_em_push_e_pr(self):
        wf = self._carregar("tests.yml")
        gatilhos = self._gatilhos(wf)
        self.assertIn("push", gatilhos)
        self.assertIn("pull_request", gatilhos)
        texto = json.dumps(wf)
        self.assertIn("3.12", texto)
        self.assertIn("openpyxl", texto)
        self.assertIn("unittest discover", texto)

    def test_build_roda_testes_antes_do_pyinstaller(self):
        wf = self._carregar("build_exe.yml")
        self.assertEqual(wf.get("jobs", {}).get("build", {}).get("runs-on"),
                         "windows-latest")
        passos = self._passos(wf)
        comandos = [" ".join(str(s.get("run", "")) for s in passos)]
        texto = "\n".join(comandos).lower()
        self.assertIn("unittest discover", texto)
        self.assertIn("pyinstaller", texto)
        self.assertLess(texto.index("unittest discover"), texto.index("pyinstaller"))
        # As duas coletas do primeiro .exe e as do segundo precisam existir.
        for coleta in ("--collect-all jobspy", "--collect-all tls_client",
                       "--collect-all curl_cffi", "--collect-all playwright",
                       "--collect-all google.genai", "--collect-all pypdf",
                       "--collect-all docx"):
            self.assertIn(coleta, texto)


class BuildConsistencyTest(unittest.TestCase):
    COLETAS = (
        "--collect-all jobspy", "--collect-all tls_client",
        "--collect-all curl_cffi", "--collect-all playwright",
        "--collect-all google.genai", "--collect-all pypdf", "--collect-all docx",
    )

    def test_bat_e_workflow_coletam_os_mesmos_modulos(self):
        bat = _ler("build_exe.bat")
        workflow = _ler(os.path.join(".github", "workflows", "build_exe.yml"))
        for coleta in self.COLETAS:
            with self.subTest(coleta=coleta, arquivo="build_exe.bat"):
                self.assertIn(coleta, bat)
            with self.subTest(coleta=coleta, arquivo="build_exe.yml"):
                self.assertIn(coleta, workflow)


class DocsSemPromessaFalsaTest(unittest.TestCase):
    def test_readme_nao_promete_envio_automatico(self):
        readme = _ler("README.md")
        self.assertIn("nunca envia", readme.lower())
        self.assertIn("NEVER_SUBMIT", readme)

    def test_readme_ressalva_o_uso_opcional_de_llm(self):
        readme = _ler("README.md")
        self.assertNotIn("Sem LLM, sem servidor — tudo roda localmente.", readme)
        self.assertIn("não usam LLM", readme)
        self.assertIn("Gemini", readme)


if __name__ == "__main__":
    unittest.main()
