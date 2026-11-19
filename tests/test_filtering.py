"""Testes do filtro de vagas (avaliação de uma vaga isolada)."""

import copy
import unittest

import config
import filtering


def _job(**kwargs):
    base = {
        "title": "Analista de Dados",
        "company": "ACME",
        "location": "São Paulo, SP",
        "description": "Buscamos profissional com Python e SQL.",
        "job_url": "https://exemplo/vaga/1",
        "site": "indeed",
        "date_posted": "2026-10-20",
    }
    base.update(kwargs)
    return base


class EvaluateTest(unittest.TestCase):
    def setUp(self):
        self.filters = copy.deepcopy(config.DEFAULT_FILTERS)

    def test_remota_fora_da_cidade_passa(self):
        # "remota" (feminino) era o caso que mais escapava.
        job = _job(description="Vaga remota. Python e SQL.")
        record, motivo = filtering.evaluate(job, self.filters)
        self.assertIsNotNone(record, motivo)
        self.assertEqual(record["modelo_trabalho"], "Remoto")

    def test_home_office_so_no_campo_local_passa(self):
        job = _job(location="Home Office", description="Python e SQL.")
        record, motivo = filtering.evaluate(job, self.filters)
        self.assertIsNotNone(record, motivo)

    def test_hibrida_fora_da_cidade_cai(self):
        job = _job(description="Vaga híbrida. Python e SQL.")
        record, motivo = filtering.evaluate(job, self.filters)
        self.assertIsNone(record)
        self.assertIn("híbrido", motivo)

    def test_presencial_fora_da_cidade_cai(self):
        job = _job(description="Python e SQL. Vaga presencial.")
        record, motivo = filtering.evaluate(job, self.filters)
        self.assertIsNone(record)

    def test_nao_e_remoto_nao_passa_fora_da_cidade(self):
        job = _job(description="Python e SQL. Esta vaga não é remota.")
        record, motivo = filtering.evaluate(job, self.filters)
        self.assertIsNone(record)

    def test_cidade_aceita_passa(self):
        job = _job(location="Brasília, DF", description="Python e SQL.")
        record, motivo = filtering.evaluate(job, self.filters)
        self.assertIsNotNone(record, motivo)

    def test_sem_termo_forte_cai(self):
        # Título genérico + descrição sem nenhum termo de dados.
        job = _job(title="Assistente", location="Brasília, DF",
                   description="Rotina administrativa de escritório.")
        record, motivo = filtering.evaluate(job, self.filters)
        self.assertIsNone(record)

    def test_titulo_conta_como_termo(self):
        # "Analista de Dados" no título já é termo forte, mesmo com descrição genérica.
        job = _job(location="Brasília, DF", description="Rotina administrativa.")
        record, motivo = filtering.evaluate(job, self.filters)
        self.assertIsNotNone(record, motivo)

    def test_salario_do_site_formatado(self):
        job = _job(location="Brasília, DF",
                   min_amount=5000.0, max_amount=7000.0, currency="BRL", interval="yearly")
        record, motivo = filtering.evaluate(job, self.filters)
        self.assertIsNotNone(record, motivo)
        self.assertEqual(record["faixa_salarial"], "R$ 5.000 - R$ 7.000 /ano")

    def test_salario_ausente_usa_descricao(self):
        job = _job(location="Brasília, DF", description="Python e SQL. Salário: R$ 4.000 a R$ 6.000.")
        record, motivo = filtering.evaluate(job, self.filters)
        self.assertIsNotNone(record, motivo)
        self.assertEqual(record["faixa_salarial"], "R$ 4.000 - R$ 6.000")

    def test_duplicata_na_mesma_busca_e_descartada(self):
        job = _job(description="Vaga remota. Python e SQL.")
        aprovadas, descartadas, motivos = filtering.filter_jobs([job, dict(job)], self.filters)
        self.assertEqual(len(aprovadas), 1)
        self.assertEqual(motivos["repetida em outro site"], 1)

    def test_salario_em_string_pt_br(self):
        # Algumas versões do JobSpy devolvem os valores como texto.
        job = _job(location="Brasília, DF", min_amount="5.000,00",
                   max_amount="7.000,00", currency="BRL", interval="yearly")
        record, motivo = filtering.evaluate(job, self.filters)
        self.assertIsNotNone(record, motivo)
        self.assertEqual(record["faixa_salarial"], "R$ 5.000 - R$ 7.000 /ano")

    def test_interval_desconhecido_nao_quebra(self):
        job = _job(location="Brasília, DF", min_amount=5000,
                   max_amount=7000, interval="quinzenal")
        record, motivo = filtering.evaluate(job, self.filters)
        self.assertIsNotNone(record, motivo)
        self.assertEqual(record["faixa_salarial"], "R$ 5.000 - R$ 7.000")

    def test_interval_ausente_nao_quebra(self):
        job = _job(location="Brasília, DF", min_amount="1.234,56")
        record, motivo = filtering.evaluate(job, self.filters)
        self.assertIsNotNone(record, motivo)
        self.assertEqual(record["faixa_salarial"], "R$ 1.234,56")


class VagaInvalidaTest(unittest.TestCase):
    def setUp(self):
        self.filters = copy.deepcopy(config.DEFAULT_FILTERS)

    def test_none_nao_estoura(self):
        record, motivo = filtering.evaluate(None, self.filters)
        self.assertIsNone(record)
        self.assertTrue(motivo.startswith("vaga inválida:"))

    def test_nao_dict_nao_estoura(self):
        for raw in ("texto", [1, 2, 3], 42):
            record, motivo = filtering.evaluate(raw, self.filters)
            self.assertIsNone(record)
            self.assertTrue(motivo.startswith("vaga inválida:"))

    def test_campos_com_tipos_estranhos_nao_estouram(self):
        raw = {
            "title": ["Analista", "Dados"],
            "company": 123,
            "location": None,
            "description": {"a": 1},
            "job_url": 999,
            "min_amount": ["x"],
            "max_amount": {"y": 2},
            "interval": 7,
        }
        record, motivo = filtering.evaluate(raw, self.filters)
        self.assertIsInstance(motivo, (str, type(None)))
        if record is None:
            self.assertTrue(motivo.startswith("vaga inválida:") or motivo)

    def test_filters_invalido_nao_estoura(self):
        record, motivo = filtering.evaluate(_job(), None)
        self.assertIsNone(record)
        self.assertTrue(motivo.startswith("vaga inválida:"))

    def test_local_terms_ignora_nao_strings(self):
        filtros = copy.deepcopy(self.filters)
        filtros["cidades"] = ["Brasília, DF", None, 123, "", "  "]
        self.assertEqual(filtering._local_terms(filtros), ["Brasília"])

    def test_campos_none_e_salario_esquisito_nao_estouram(self):
        casos = [
            {"title": None, "description": None, "job_url": None},
            {"title": "Analista de Dados", "description": "Python SQL",
             "location": "Brasília, DF", "min_amount": "5.000,00",
             "interval": 123, "currency": None},
            {"title": "Analista de Dados", "description": "Python SQL",
             "location": "Brasília, DF", "min_amount": 1000,
             "max_amount": "x", "currency": "USD"},
            {"title": "Analista de Dados", "description": "Python SQL",
             "location": "Brasília, DF", "min_amount": ["x"],
             "max_amount": {"y": 2}, "currency": 5},
            {"title": "Analista de Dados", "description": "Python SQL",
             "location": "Brasília, DF", "min_amount": "R$",
             "max_amount": "R$", "currency": "BRL", "interval": "yearly"},
        ]
        for raw in casos:
            with self.subTest(raw=raw):
                record, motivo = filtering.evaluate(raw, self.filters)
                self.assertIsInstance(motivo, (str, type(None)))
                if record is not None:
                    self.assertIsInstance(record["faixa_salarial"], str)

    def test_registro_cobre_o_schema_do_banco(self):
        import re
        import database
        record, motivo = filtering.evaluate(_job(location="Brasília, DF"), self.filters)
        self.assertIsNotNone(record, motivo)
        colunas = set(re.findall(r"^\s{4}(\w+) ", database.SCHEMA, re.M))
        self.assertEqual(colunas - set(record), set())
        self.assertTrue(set(record) - colunas <= {"chave_dup"})
        self.assertEqual(record["situacao"], config.STATUS_PENDENTE)
        self.assertEqual(record["auto_preencher"], config.AUTOFILL_NAO)

    def test_filter_jobs_com_none(self):
        aprovadas, descartadas, motivos = filtering.filter_jobs(None, self.filters)
        self.assertEqual(aprovadas, [])
        self.assertEqual(descartadas, [])
        self.assertEqual(dict(motivos), {})


if __name__ == "__main__":
    unittest.main()
