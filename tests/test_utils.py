"""Testes das funções puras (sem rede, sem Excel)."""

import os
import shutil
import tempfile
import unittest

from utils import (
    _parse_br_number, detect_work_model, extract_salary, find_terms, format_brl,
    make_dup_key, make_job_hash, normalize_text, open_file, parse_br_number,
    says_not_remote,
)


class DetectWorkModelTest(unittest.TestCase):
    def test_remoto_feminino(self):
        # Antes "remota" não era reconhecida: só a string "remoto" casava.
        self.assertEqual(detect_work_model(normalize_text("Vaga remota para analista")), "Remoto")

    def test_remoto_plural(self):
        self.assertEqual(detect_work_model(normalize_text("Vagas remotas")), "Remoto")

    def test_hibrido_feminino(self):
        self.assertEqual(detect_work_model(normalize_text("Vaga híbrida em São Paulo")), "Híbrido")

    def test_hibrido_negado_nao_vence_remoto(self):
        texto = normalize_text("Vaga 100% remota. Não é híbrida.")
        self.assertEqual(detect_work_model(texto), "Remoto")

    def test_home_office_continua_sendo_remoto(self):
        self.assertEqual(detect_work_model(normalize_text("Vaga em home office")), "Remoto")
        self.assertEqual(detect_work_model(normalize_text("Trabalho a distância")), "Remoto")

    def test_presencial(self):
        self.assertEqual(detect_work_model(normalize_text("100% presencial")), "Presencial")

    def test_sem_informacao(self):
        self.assertEqual(detect_work_model(normalize_text("Vaga de analista")), "Não informado")

    def test_nao_e_remoto_vira_presencial(self):
        texto = normalize_text("Esta vaga não é remota")
        self.assertTrue(says_not_remote(texto))
        self.assertEqual(detect_work_model(texto), "Presencial")


class ExtractSalaryTest(unittest.TestCase):
    def test_faixa(self):
        self.assertEqual(extract_salary("Salário: R$ 5.000 a R$ 7.000"), "R$ 5.000 - R$ 7.000")

    def test_faixa_com_r_apenas_no_primeiro_valor(self):
        self.assertEqual(extract_salary("R$ 3.000 a 4.000"), "R$ 3.000 - R$ 4.000")

    def test_valor_unico(self):
        self.assertEqual(extract_salary("R$ 3.500,00"), "R$ 3.500")

    def test_sigla_de_estado_nao_e_salario(self):
        # "RS" (Rio Grande do Sul) era lido como "R$".
        self.assertEqual(extract_salary("Local: Porto Alegre, RS 90010-000"), "")

    def test_faixa_invertida_e_corrigida(self):
        self.assertEqual(extract_salary("R$ 7.000 a R$ 5.000"), "R$ 5.000 - R$ 7.000")


class FormatBrlTest(unittest.TestCase):
    def test_inteiro(self):
        self.assertEqual(format_brl(5000), "R$ 5.000")

    def test_centavos(self):
        self.assertEqual(format_brl(5000.5), "R$ 5.000,50")


class FindTermsTest(unittest.TestCase):
    def test_sigla_so_palavra_inteira(self):
        self.assertEqual(find_terms(normalize_text("SRE engineer"), ["sr"]), [])
        self.assertEqual(find_terms(normalize_text("vaga sr backend"), ["sr"]), ["sr"])

    def test_prefixo(self):
        self.assertEqual(
            find_terms(normalize_text("desenvolvedor python"), ["desenvolv"]), ["desenvolv"])

    def test_remot_pega_remota(self):
        self.assertEqual(find_terms(normalize_text("vaga remota"), ["remot"]), ["remot"])


class DupKeyTest(unittest.TestCase):
    def test_mesma_vaga_sem_cidade(self):
        self.assertEqual(make_dup_key("ACME", "Dev", ""), make_dup_key("ACME", "Dev", ""))

    def test_tolera_none(self):
        self.assertIsInstance(make_dup_key(None, None, None), str)
        self.assertIsInstance(make_job_hash(None, None, None), str)
        self.assertIsInstance(make_job_hash("ACME", "Dev", "BH", None), str)

    def test_hash_usa_url_quando_existe(self):
        self.assertEqual(make_job_hash("ACME", "Dev", "BH", "http://x"),
                         make_job_hash(None, None, None, "http://x"))


class ParseBrNumberTest(unittest.TestCase):
    def test_milhar_com_varios_pontos(self):
        self.assertEqual(parse_br_number("1.234.567"), 1234567.0)

    def test_milhar_simples(self):
        self.assertEqual(parse_br_number("12.345"), 12345.0)

    def test_decimal_com_virgula(self):
        self.assertEqual(parse_br_number("1,5"), 1.5)

    def test_milhar_e_centavos(self):
        self.assertEqual(parse_br_number("1.234,56"), 1234.56)
        self.assertEqual(parse_br_number("5.000,50"), 5000.5)

    def test_vazios(self):
        self.assertIsNone(parse_br_number("R$"))
        self.assertIsNone(parse_br_number(""))
        self.assertIsNone(parse_br_number(None))

    def test_aceita_numero_pronto(self):
        self.assertEqual(parse_br_number(5000.0), 5000.0)

    def test_alias_antigo_continua_funcionando(self):
        self.assertEqual(_parse_br_number("1.234,56"), 1234.56)


class FindTermsRobustezTest(unittest.TestCase):
    def test_terms_none(self):
        self.assertEqual(find_terms(normalize_text("vaga python"), None), [])

    def test_text_none(self):
        self.assertEqual(find_terms(None, ["python"]), [])

    def test_itens_nao_string_sao_ignorados(self):
        encontrados = find_terms(normalize_text("vaga python"), [None, 123, "python"])
        self.assertEqual(encontrados, ["python"])

    def test_string_unica_vira_lista(self):
        self.assertEqual(find_terms(normalize_text("vaga python"), "python"), ["python"])


class OpenFileTest(unittest.TestCase):
    def test_caminho_inexistente_retorna_false(self):
        pasta = tempfile.mkdtemp(prefix="jobscraper-open-")
        caminho = os.path.join(pasta, "nao_existe.txt")
        try:
            self.assertFalse(open_file(caminho))
        finally:
            shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
