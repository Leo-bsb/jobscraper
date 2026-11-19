"""
Testes de segurança/privacidade (sem rede, sem navegador, sem Tk).

Cobrem: validação de URL de vaga, anexo de currículo, nomes de arquivo,
mascaramento de chaves e a invariante de nunca enviar candidatura.
"""

import importlib.util
import logging
import os
import re
import tempfile
import unittest

import apply_core
import resume_adapter

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ARQUIVOS_DO_FLUXO = (
    "main.py", "app.py", "candidatar_app.py", "applier.py", "apply_core.py",
    "resume_adapter.py", "utils.py",
)


def _fonte(nome: str) -> str:
    with open(os.path.join(_ROOT, nome), "r", encoding="utf-8") as f:
        return f.read()


class SafeJobUrlSecurityTest(unittest.TestCase):
    def test_aceita_apenas_http_https_com_host(self):
        for url in ("https://br.indeed.com/viewjob?jk=abc",
                    "http://exemplo.com/vaga/1",
                    "  https://www.linkedin.com/jobs/view/1  ",
                    "HTTPS://EXAMPLE.COM/vaga"):
            with self.subTest(url=url):
                self.assertTrue(apply_core.is_safe_job_url(url))

    def test_bloqueia_outros_esquemas(self):
        for url in ("javascript:alert(1)", "JAVASCRIPT:alert(1)",
                    "file:///C:/Windows/win.ini", "data:text/html,<h1>x</h1>",
                    "ftp://exemplo.com/vaga", "//evil.com", "mailto:a@b.com"):
            with self.subTest(url=url):
                self.assertFalse(apply_core.is_safe_job_url(url))

    def test_bloqueia_vazio_none_e_sem_host(self):
        for url in ("", "   ", None, "https://", "http:///caminho"):
            with self.subTest(url=url):
                self.assertFalse(apply_core.is_safe_job_url(url))

    def test_bloqueia_espacos_controle_e_barra_invertida(self):
        # Uma quebra de linha/controle dentro de uma URL "http" pode confundir
        # o parser/navegador; nunca deve passar pela validação.
        for url in ("http://exemplo.com/a b",
                    "http://exemplo.com/\njavascript:alert(1)",
                    "http://exemplo.com/\r\nx",
                    "http://exemplo.com/\x00x",
                    "\x01https://exemplo.com",
                    "https://exa mple.com",
                    "https://exemplo.com\\@evil.com",
                    "h\ttps://exemplo.com"):
            with self.subTest(url=repr(url)):
                self.assertFalse(apply_core.is_safe_job_url(url))

    def test_bloqueia_porta_invalida(self):
        self.assertFalse(apply_core.is_safe_job_url("http://javascript:alert(1)"))
        self.assertFalse(apply_core.is_safe_job_url("http://exemplo.com:abc/vaga"))
        self.assertTrue(apply_core.is_safe_job_url("http://exemplo.com:8080/vaga"))


class _FakeFileInput:
    def __init__(self, registro):
        self.registro = registro

    def count(self):
        return 1

    def set_input_files(self, caminho, timeout=None):
        self.registro.append(caminho)


class _FakePage:
    def __init__(self):
        self.arquivos = []
        self.seletores = []

    def locator(self, seletor):
        self.seletores.append(seletor)
        return self

    @property
    def first(self):
        return _FakeFileInput(self.arquivos)


class UploadResumeSecurityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jobscraper-upload-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _arquivo(self, nome: str) -> str:
        caminho = os.path.join(self.tmp, nome)
        with open(caminho, "wb") as f:
            f.write(b"%PDF-1.4\n%teste\n")
        return caminho

    def test_inexistente_nao_toca_na_pagina(self):
        page = _FakePage()
        self.assertFalse(apply_core.try_upload_resume(page, "nao_existe.pdf"))
        self.assertEqual(page.arquivos, [])

    def test_diretorio_nao_e_anexado(self):
        page = _FakePage()
        self.assertFalse(apply_core.try_upload_resume(page, self.tmp))
        self.assertEqual(page.arquivos, [])

    def test_extensao_nao_suportada_nao_e_anexada(self):
        page = _FakePage()
        caminho = self._arquivo("curriculo.exe")
        self.assertFalse(apply_core.try_upload_resume(page, caminho))
        self.assertEqual(page.arquivos, [])

    def test_pdf_maiusculo_e_aceito(self):
        page = _FakePage()
        caminho = self._arquivo("Curriculo.PDF")
        self.assertTrue(apply_core.try_upload_resume(page, caminho))
        self.assertEqual(page.arquivos, [caminho])

    def test_arquivo_valido_e_anexado(self):
        page = _FakePage()
        caminho = self._arquivo("curriculo.pdf")
        self.assertTrue(apply_core.try_upload_resume(page, caminho))
        self.assertEqual(page.seletores, ["input[type='file']"])
        self.assertEqual(page.arquivos, [caminho])


class SafeFilenameSecurityTest(unittest.TestCase):
    RESERVADOS = ("CON", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9")

    def test_nunca_devolve_caminho_ou_nome_reservado(self):
        entradas = (
            "../../etc/passwd", "..\\..\\Windows\\System32", "CON", "con.txt",
            "NUL.txt", "aux", "COM1.tar.gz", "LPT9.log",
            'a<b>c:d/e\\f|g?h*i', "...   ", "   ", "\x00\x01", "😀",
            "x" * 500, "nome.  ", "CON.", "com1 .txt",
        )
        for entrada in entradas:
            with self.subTest(entrada=repr(entrada)):
                nome = resume_adapter._safe_filename(entrada)
                self.assertTrue(nome)
                self.assertNotIn("/", nome)
                self.assertNotIn("\\", nome)
                self.assertFalse(nome.endswith(".") or nome.endswith(" "), repr(nome))
                self.assertNotIn(nome.split(".")[0].strip().upper(),
                                 resume_adapter._RESERVED_WINDOWS)
                self.assertLessEqual(len(nome), 80)

    def test_nome_reservado_recebe_prefixo(self):
        self.assertNotEqual(resume_adapter._safe_filename("CON").upper(), "CON")
        self.assertTrue(resume_adapter._safe_filename("NUL.txt").upper().startswith("VAGA_"))


class MaskKeyTest(unittest.TestCase):
    def test_mascara_chave_exata_e_formato_do_google(self):
        chave = "AIza" + "A" * 35
        texto = "erro com a chave {} e token {}".format(chave, "x" * 20)
        mascarado = resume_adapter._mask_key(texto, chave)
        self.assertNotIn(chave, mascarado)
        self.assertIn("***", mascarado)

    def test_chave_de_outro_formato_tambem_e_mascarada(self):
        mascarado = resume_adapter._mask_key("chave=minha-chave-secreta", "minha-chave-secreta")
        self.assertNotIn("minha-chave-secreta", mascarado)


class NuncaEnviaCandidaturaTest(unittest.TestCase):
    def test_never_submit_continua_verdadeiro(self):
        self.assertTrue(apply_core.NEVER_SUBMIT)

    def test_nenhum_arquivo_usa_shell_true(self):
        for nome in _ARQUIVOS_DO_FLUXO:
            with self.subTest(arquivo=nome):
                self.assertNotIn("shell=True", _fonte(nome))

    def test_unico_click_e_o_de_abrir_candidatura(self):
        fonte = _fonte("apply_core.py")
        self.assertEqual(fonte.count(".click("), 1, "só o Easy Apply pode ser clicado")
        # O clique precisa estar dentro de click_easy_apply.
        trecho = fonte.split("def click_easy_apply", 1)[1]
        self.assertEqual(trecho.count(".click("), 1)
        for nome in _ARQUIVOS_DO_FLUXO:
            if nome in ("apply_core.py", "utils.py"):  # utils usa subprocess.call, não click
                continue
            with self.subTest(arquivo=nome):
                self.assertNotIn(".click(", _fonte(nome))

    def test_nenhum_seletor_de_botao_enviar(self):
        for nome in _ARQUIVOS_DO_FLUXO:
            fonte = _fonte(nome).lower()
            for proibido in ("type='submit'", 'type="submit"', "enviar candidatura",
                             "submit application", "btn_enviar", "enviar_candidatura"):
                with self.subTest(arquivo=nome, proibido=proibido):
                    self.assertNotIn(proibido, fonte)


@unittest.skipUnless(importlib.util.find_spec("tkinter"), "tkinter indisponível")
class MascaramentoNasInterfacesTest(unittest.TestCase):
    """As interfaces mascaram e-mail/chave na tela E no arquivo de log."""

    def test_app_redact(self):
        import app
        texto = app._redact("contato joao@exemplo.com chave AIza" + "B" * 35)
        self.assertNotIn("joao@exemplo.com", texto)
        self.assertNotIn("AIza", texto)
        self.assertEqual(texto.count("***"), 2)

    def test_candidatar_app_mask_secrets(self):
        import candidatar_app
        texto = candidatar_app._mask_secrets("eu@exemplo.com / AIza" + "C" * 35)
        self.assertNotIn("eu@exemplo.com", texto)
        self.assertNotIn("AIza", texto)
        self.assertEqual(texto.count("***"), 2)

    def test_formatter_do_arquivo_de_log_mascara(self):
        import app
        import candidatar_app
        for formatter in (app._RedactingFormatter("%(message)s"),
                          candidatar_app._MaskingFormatter("%(message)s")):
            record = logging.LogRecord(
                "buscavagas.teste", logging.ERROR, __file__, 1,
                "falha para %s com AIza%s", ("maria@exemplo.com", "D" * 35), None)
            saida = formatter.format(record)
            self.assertNotIn("maria@exemplo.com", saida)
            self.assertNotIn("AIza", saida)
            self.assertIn("***", saida)


class PadroesDeArquivoTest(unittest.TestCase):
    def test_arquivos_temporarios_da_gravacao_atomica_tem_prefixo_seguro(self):
        # config salva via tempfile.mkstemp(prefix=".tmp-", dir=BASE_DIR) e o
        # .gitignore precisa ignorar esse padrão.
        with open(os.path.join(_ROOT, ".gitignore"), "r", encoding="utf-8") as f:
            gitignore = f.read()
        self.assertIn(".tmp-*", gitignore)

    def test_sem_segredo_real_no_repositorio(self):
        # Projeção simples: um padrão de chave do Google não pode aparecer
        # literalmente em nenhum arquivo versionado do projeto.
        padrao = re.compile(r"AIza[0-9A-Za-z_\-]{30,}")
        for raiz, pastas, arquivos in os.walk(_ROOT):
            # "tests" pode conter chaves falsas de propósito; o alvo é o código/docs.
            pastas[:] = [p for p in pastas
                         if p not in (".git", "__pycache__", "venv", "tests")]
            for arquivo in arquivos:
                if not arquivo.endswith((".py", ".json", ".md", ".txt", ".yml", ".bat", ".gitignore")):
                    continue
                caminho = os.path.join(raiz, arquivo)
                try:
                    with open(caminho, "r", encoding="utf-8", errors="ignore") as f:
                        conteudo = f.read()
                except OSError:
                    continue
                with self.subTest(arquivo=caminho):
                    self.assertIsNone(padrao.search(conteudo))


if __name__ == "__main__":
    unittest.main()
