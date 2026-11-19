"""Testes dos helpers puros de apply_core.py (sem Playwright/navegador)."""

import unittest

import apply_core


class SafeJobUrlTest(unittest.TestCase):
    def test_aceita_http_e_https(self):
        self.assertTrue(apply_core.is_safe_job_url("https://br.indeed.com/viewjob?jk=abc"))
        self.assertTrue(apply_core.is_safe_job_url("http://exemplo.com/vaga/1"))
        self.assertTrue(apply_core.is_safe_job_url("  https://www.linkedin.com/jobs/view/1  "))

    def test_bloqueia_esquemas_perigosos(self):
        for url in ("javascript:alert(1)", "file:///C:/Windows/win.ini",
                    "data:text/html,<h1>x</h1>", "ftp://exemplo.com/vaga"):
            with self.subTest(url=url):
                self.assertFalse(apply_core.is_safe_job_url(url))

    def test_bloqueia_vazio_e_sem_host(self):
        for url in ("", "   ", None, "https://", "//exemplo.com/vaga"):
            with self.subTest(url=url):
                self.assertFalse(apply_core.is_safe_job_url(url))


class ProfileValueTest(unittest.TestCase):
    def setUp(self):
        self.profile = {"nome_completo": "  João da Silva  ", "email": "a@b.com",
                        "telefone": " 11 99999-0000 "}

    def test_primeiro_nome(self):
        self.assertEqual(apply_core._profile_value(self.profile, "primeiro_nome"), "João")

    def test_sobrenome(self):
        self.assertEqual(apply_core._profile_value(self.profile, "sobrenome"), "da Silva")

    def test_nome_completo_e_contato(self):
        self.assertEqual(apply_core._profile_value(self.profile, "nome_completo"), "João da Silva")
        self.assertEqual(apply_core._profile_value(self.profile, "email"), "a@b.com")
        self.assertEqual(apply_core._profile_value(self.profile, "telefone"), "11 99999-0000")

    def test_nome_vazio(self):
        vazio = {}
        self.assertEqual(apply_core._profile_value(vazio, "primeiro_nome"), "")
        self.assertEqual(apply_core._profile_value(vazio, "sobrenome"), "")


class UploadResumeTest(unittest.TestCase):
    def test_arquivo_inexistente_nao_toca_na_pagina(self):
        # page=None: se a validação de arquivo falhar antes, não dá AttributeError.
        self.assertFalse(apply_core.try_upload_resume(None, "nao_existe.pdf"))
        self.assertFalse(apply_core.try_upload_resume(None, ""))


class SafetyInvariantTest(unittest.TestCase):
    def test_nunca_envia(self):
        self.assertTrue(apply_core.NEVER_SUBMIT)


if __name__ == "__main__":
    unittest.main()
