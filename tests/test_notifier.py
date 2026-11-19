"""Testes do envio de e-mail, sem rede (SMTP falseado)."""

import email
import os
import shutil
import tempfile
import unittest
from unittest import mock

import config
import notifier


class _FakeSMTP:
    """Registra as chamadas; nunca toca na rede."""

    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.tls = False
        self.login_done = None
        self.sent = []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.tls = True

    def login(self, user, password):
        self.login_done = (user, password)

    def sendmail(self, sender, recipients, message):
        self.sent.append((sender, recipients, message))
        return {}


def _job(**kwargs):
    base = {
        "titulo": "Analista de Dados",
        "empresa": "ACME",
        "localizacao": "Brasília, DF",
        "modelo_trabalho": "Presencial",
        "link": "https://exemplo/vaga/1",
    }
    base.update(kwargs)
    return base


class NotifierTest(unittest.TestCase):
    _CONFIG_NAMES = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
                     "EMAIL_FROM", "EMAIL_TO")

    def setUp(self):
        self._old = {nome: getattr(config, nome) for nome in self._CONFIG_NAMES}
        self._had_timeout = hasattr(config, "SMTP_TIMEOUT")
        if self._had_timeout:
            self._old_timeout = config.SMTP_TIMEOUT
        config.SMTP_HOST = "smtp.exemplo.com"
        config.SMTP_PORT = 587
        config.SMTP_USER = "remetente@exemplo.com"
        config.SMTP_PASSWORD = "senha-secreta"
        config.EMAIL_FROM = "remetente@exemplo.com"
        config.EMAIL_TO = "destino@exemplo.com"
        if self._had_timeout:
            del config.SMTP_TIMEOUT  # cada teste escolhe o seu
        _FakeSMTP.instances = []

    def tearDown(self):
        for nome, valor in self._old.items():
            setattr(config, nome, valor)
        if self._had_timeout:
            config.SMTP_TIMEOUT = self._old_timeout
        elif hasattr(config, "SMTP_TIMEOUT"):
            del config.SMTP_TIMEOUT
        _FakeSMTP.instances = []

    def _send(self, jobs, **kwargs):
        with mock.patch.object(notifier.smtplib, "SMTP", _FakeSMTP):
            return notifier.send_daily_digest(jobs, **kwargs)

    def test_timeout_informado_chega_ao_smtp(self):
        self.assertTrue(self._send([_job()], timeout=7))
        servidor = _FakeSMTP.instances[0]
        self.assertEqual(servidor.host, "smtp.exemplo.com")
        self.assertEqual(servidor.port, 587)
        self.assertEqual(servidor.timeout, 7)
        self.assertTrue(servidor.tls)
        self.assertEqual(servidor.login_done,
                         ("remetente@exemplo.com", "senha-secreta"))

    def test_timeout_padrao_vem_da_config_ou_30(self):
        self.assertTrue(self._send([_job()]))
        self.assertEqual(_FakeSMTP.instances[0].timeout, 30)

        _FakeSMTP.instances = []
        config.SMTP_TIMEOUT = 5
        self.assertTrue(self._send([_job()]))
        self.assertEqual(_FakeSMTP.instances[0].timeout, 5)

    def test_multiplos_destinatarios_separados_por_virgula_ou_ponto_e_virgula(self):
        config.EMAIL_TO = "a@exemplo.com; b@exemplo.com, c@exemplo.com; a@exemplo.com"
        self.assertTrue(self._send([_job()]))
        _, destinatarios, mensagem = _FakeSMTP.instances[0].sent[0]
        self.assertEqual(destinatarios,
                         ["a@exemplo.com", "b@exemplo.com", "c@exemplo.com"])
        msg = email.message_from_string(mensagem)
        self.assertEqual(msg["To"], "a@exemplo.com, b@exemplo.com, c@exemplo.com")

    def test_html_e_escapado_inclusive_no_href(self):
        self.assertTrue(self._send([_job(
            titulo='<script>alert("x")</script>',
            empresa="A & B",
            link='https://exemplo/vaga?q="a"&b=1',
        )]))
        _, _, bruto = _FakeSMTP.instances[0].sent[0]
        msg = email.message_from_string(bruto)
        partes = list(msg.walk())
        html_parte = next(p for p in partes if p.get_content_subtype() == "html")
        texto_html = html_parte.get_payload(decode=True).decode("utf-8")
        self.assertIn("&lt;script&gt;", texto_html)
        self.assertNotIn("<script>", texto_html)
        self.assertIn("A &amp; B", texto_html)
        self.assertIn("&quot;", texto_html)
        self.assertIn("href=", texto_html)

    def test_tem_alternativa_em_texto_puro(self):
        self.assertTrue(self._send([_job()]))
        _, _, bruto = _FakeSMTP.instances[0].sent[0]
        msg = email.message_from_string(bruto)
        texto_parte = next(p for p in msg.walk()
                           if p.get_content_subtype() == "plain")
        texto = texto_parte.get_payload(decode=True).decode("utf-8")
        self.assertIn("Analista de Dados", texto)
        self.assertIn("https://exemplo/vaga/1", texto)

    def test_link_invalido_nao_vira_hyperlinks(self):
        self.assertTrue(self._send([_job(link="javascript:alert(1)")]))
        _, _, bruto = _FakeSMTP.instances[0].sent[0]
        msg = email.message_from_string(bruto)
        html_parte = next(p for p in msg.walk()
                          if p.get_content_subtype() == "html")
        texto = html_parte.get_payload(decode=True).decode("utf-8")
        self.assertNotIn('href="javascript:', texto)

    def test_file_e_formula_nao_viram_hyperlink(self):
        for link in ("file:///C:/Windows/System32/calc.exe",
                     '=HYPERLINK("http://malicioso","clique")',
                     "ftp://exemplo/x"):
            with self.subTest(link=link):
                _FakeSMTP.instances = []
                self.assertTrue(self._send([_job(link=link)]))
                _, _, bruto = _FakeSMTP.instances[0].sent[0]
                msg = email.message_from_string(bruto)
                html_parte = next(p for p in msg.walk()
                                  if p.get_content_subtype() == "html")
                texto = html_parte.get_payload(decode=True).decode("utf-8")
                self.assertNotIn("href=", texto)

    def test_sendmail_recebe_lista_de_destinatarios(self):
        config.EMAIL_TO = "a@x.com,b@x.com"
        self.assertTrue(self._send([_job()]))
        remetente, destinatarios, _ = _FakeSMTP.instances[0].sent[0]
        self.assertIsInstance(destinatarios, list)
        self.assertEqual(destinatarios, ["a@x.com", "b@x.com"])
        self.assertEqual(remetente, "remetente@exemplo.com")

    def test_jobs_vazios_nao_envia(self):
        self.assertFalse(self._send([]))
        self.assertEqual(_FakeSMTP.instances, [])

    def test_sem_credenciais_nao_envia(self):
        config.SMTP_PASSWORD = ""
        self.assertFalse(self._send([_job()]))
        self.assertEqual(_FakeSMTP.instances, [])

    def test_sem_destinatarios_nao_envia(self):
        config.EMAIL_TO = " ; , "
        self.assertFalse(self._send([_job()]))
        self.assertEqual(_FakeSMTP.instances, [])


class AnexoTest(unittest.TestCase):
    """A planilha gerada é anexada ao e-mail (formato 'Excel para o usuário')."""

    _CONFIG_NAMES = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
                     "EMAIL_FROM", "EMAIL_TO")

    def setUp(self):
        self._old = {nome: getattr(config, nome) for nome in self._CONFIG_NAMES}
        config.SMTP_HOST = "smtp.exemplo.com"
        config.SMTP_PORT = 587
        config.SMTP_USER = "remetente@exemplo.com"
        config.SMTP_PASSWORD = "senha-secreta"
        config.EMAIL_FROM = "remetente@exemplo.com"
        config.EMAIL_TO = "destino@exemplo.com"
        self.tmp = tempfile.mkdtemp(prefix="jobscraper-anexo-")
        _FakeSMTP.instances = []

    def tearDown(self):
        for nome, valor in self._old.items():
            setattr(config, nome, valor)
        shutil.rmtree(self.tmp, ignore_errors=True)
        _FakeSMTP.instances = []

    def _arquivo(self, nome="vagas_da_semana.xlsx", conteudo=b"PK\x03\x04planilha"):
        caminho = os.path.join(self.tmp, nome)
        with open(caminho, "wb") as f:
            f.write(conteudo)
        return caminho

    def _mensagem(self):
        with mock.patch.object(notifier.smtplib, "SMTP", _FakeSMTP):
            enviado = notifier.send_daily_digest(
                [_job()], attachment_path=self._caminho)
        self.assertTrue(enviado)
        return email.message_from_string(_FakeSMTP.instances[0].sent[0][2])

    def test_anexa_planilha(self):
        self._caminho = self._arquivo()
        msg = self._mensagem()
        self.assertEqual(msg.get_content_type(), "multipart/mixed")
        anexos = [p for p in msg.walk() if p.get_filename()]
        self.assertEqual(len(anexos), 1)
        anexo = anexos[0]
        self.assertEqual(anexo.get_filename(), "vagas_da_semana.xlsx")
        self.assertEqual(anexo.get_payload(decode=True), b"PK\x03\x04planilha")
        self.assertEqual(anexo.get_content_type(), notifier.XLSX_CONTENT_TYPE)

    def test_anexo_nao_esconde_o_resumo(self):
        self._caminho = self._arquivo()
        msg = self._mensagem()
        self.assertTrue(any(p.get_content_subtype() == "plain" for p in msg.walk()))
        self.assertTrue(any(p.get_content_subtype() == "html" for p in msg.walk()))

    def test_arquivo_inexistente_envia_so_o_resumo(self):
        self._caminho = os.path.join(self.tmp, "nao_existe.xlsx")
        msg = self._mensagem()
        self.assertEqual(msg.get_content_type(), "multipart/alternative")
        self.assertEqual([p for p in msg.walk() if p.get_filename()], [])

    def test_arquivo_grande_demais_e_ignorado(self):
        self._caminho = self._arquivo(conteudo=b"x" * 20)
        with mock.patch.object(notifier, "MAX_ATTACHMENT_BYTES", 10):
            msg = self._mensagem()
        self.assertEqual([p for p in msg.walk() if p.get_filename()], [])


if __name__ == "__main__":
    unittest.main()
