"""Testes do banco (SQLite temporário, sem tocar no vagas.db do usuário)."""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta

import config
import database


def _record(job_id="id1", url="https://exemplo/1", **kwargs):
    base = {
        "id": job_id,
        "chave_dup": "chave-1",
        "titulo": "Analista de Dados",
        "empresa": "ACME",
        "localizacao": "Brasília, DF",
        "modelo_trabalho": "Presencial",
        "faixa_salarial": "",
        "termos_encontrados": "python, sql",
        "pontos": 2,
        "link": url,
        "descricao": "Python e SQL",
        "site_origem": "indeed",
        "data_publicacao": datetime.now().strftime("%Y-%m-%d"),
        "data_coleta": datetime.now().isoformat(timespec="seconds"),
        "situacao": config.STATUS_PENDENTE,
        "auto_preencher": config.AUTOFILL_NAO,
    }
    base.update(kwargs)
    return base


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jobscraper-test-")
        self._old_path = config.DB_PATH
        config.DB_PATH = os.path.join(self.tmp, "vagas.db")
        database.init_db()

    def tearDown(self):
        config.DB_PATH = self._old_path
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_vaga_nova_entra(self):
        self.assertEqual(len(database.save_jobs([_record()])), 1)

    def test_repetida_nao_conta_como_nova(self):
        database.save_jobs([_record()])
        self.assertEqual(len(database.save_jobs([_record(job_id="id2", url="https://outro/2")])), 0)

    def test_link_atualizado_quando_a_vaga_e_republicada(self):
        database.save_jobs([_record()])
        database.save_jobs([_record(job_id="id2", url="https://exemplo/1-novo")])
        pendentes = database.get_pending(days=30)
        self.assertEqual(len(pendentes), 1)
        self.assertEqual(pendentes[0]["link"], "https://exemplo/1-novo")

    def test_status_nao_e_sobrescrito_por_nova_coleta(self):
        database.save_jobs([_record()])
        database.apply_statuses({"id1": config.STATUS_CANDIDATEI})
        database.save_jobs([_record(url="https://exemplo/1-novo")])
        self.assertEqual(database.get_pending(days=30), [])
        self.assertEqual(len(database.get_treated()), 1)

    def test_status_invalido_e_ignorado(self):
        database.save_jobs([_record()])
        self.assertEqual(database.apply_statuses({"id1": "Qualquer coisa"}), 0)
        self.assertEqual(len(database.get_pending(days=30)), 1)

    def test_autofill_invalido_e_ignorado(self):
        database.save_jobs([_record()])
        self.assertEqual(database.apply_autofill_flags({"id1": "talvez"}), 0)
        self.assertEqual(database.get_marked_for_apply(), [])

    def test_pendentes_usam_data_de_publicacao(self):
        antiga = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
        database.save_jobs([_record(job_id="velha", chave_dup="c-velha", data_publicacao=antiga)])
        database.save_jobs([_record(job_id="nova", chave_dup="c-nova")])
        ids = [v["id"] for v in database.get_pending(days=7)]
        self.assertEqual(ids, ["nova"])

    def test_publicacao_invalida_cai_para_data_de_coleta(self):
        database.save_jobs([
            _record(job_id="sem-data", chave_dup="c-sem", data_publicacao=""),
            _record(job_id="relativa", chave_dup="c-rel", data_publicacao="2 days ago"),
        ])
        self.assertEqual(len(database.get_pending(days=7)), 2)

    def test_relatorio_sem_duplicar(self):
        database.save_jobs([_record()])
        a = database.get_pending(days=30)
        b = database.get_pending(days=30)
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)


if __name__ == "__main__":
    unittest.main()
