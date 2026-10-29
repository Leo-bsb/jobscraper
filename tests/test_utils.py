"""Testes das funções puras (sem rede, sem Excel)."""

import unittest

from utils import (
    detect_work_model, extract_salary, find_terms, format_brl, make_dup_key,
    normalize_text, says_not_remote,
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


if __name__ == "__main__":
    unittest.main()
