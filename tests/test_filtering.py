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


if __name__ == "__main__":
    unittest.main()
