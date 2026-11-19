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

    def test_lote_vazio(self):
        self.assertEqual(database.save_jobs([]), [])

    def test_duplicatas_dentro_do_mesmo_lote(self):
        # O 3º registro repete a chave do 1º: é duplicata e não pode voltar
        # como "nova" nem sobrescrever o link do primeiro.
        registros = [
            _record(job_id="a", chave_dup="c-a", url="https://exemplo/a"),
            _record(job_id="b", chave_dup="c-b", url="https://exemplo/b"),
            _record(job_id="c", chave_dup="c-a", url="https://exemplo/c"),
        ]
        novas = database.save_jobs(registros)
        self.assertEqual([r["id"] for r in novas], ["a", "b"])
        with database.get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM vagas").fetchone()[0]
            link = conn.execute(
                "SELECT link FROM vagas WHERE chave_dup = 'c-a'").fetchone()[0]
        self.assertEqual(total, 2)
        self.assertEqual(link, "https://exemplo/a")

    def test_indices_criados_e_idempotentes(self):
        database.init_db()  # segunda chamada não pode falhar
        with database.get_connection() as conn:
            nomes = {row[1] for row in conn.execute("PRAGMA index_list(vagas)").fetchall()}
        for esperado in (
            "idx_vagas_situacao",
            "idx_vagas_data_coleta",
            "idx_vagas_situacao_auto",
            "idx_vagas_pontos",
        ):
            self.assertIn(esperado, nomes)

    def test_save_jobs_nao_altera_situacao_nem_autofill(self):
        database.save_jobs([_record(descricao="curta")])
        database.apply_statuses({"id1": config.STATUS_CANDIDATEI})
        database.apply_autofill_flags({"id1": config.AUTOFILL_SIM})

        novas = database.save_jobs([
            _record(url="https://exemplo/1-republicada",
                    descricao="descrição bem maior do que a anterior"),
        ])
        self.assertEqual(novas, [])
        with database.get_connection() as conn:
            row = conn.execute("SELECT * FROM vagas WHERE id = 'id1'").fetchone()
        self.assertEqual(row["situacao"], config.STATUS_CANDIDATEI)
        self.assertEqual(row["auto_preencher"], config.AUTOFILL_SIM)
        self.assertEqual(row["link"], "https://exemplo/1-republicada")
        self.assertIn("bem maior", row["descricao"])

    def test_cem_registros_de_uma_vez(self):
        registros = [
            _record(job_id="id-%d" % i, chave_dup="chave-%d" % i)
            for i in range(100)
        ]
        novas = database.save_jobs(registros)
        self.assertEqual(len(novas), 100)
        self.assertEqual(len(database.get_pending(days=30)), 100)
        self.assertEqual(database.save_jobs(registros), [])

    def test_registro_sem_chave_dup_e_pulado(self):
        incompleto = _record(job_id="sem-chave")
        del incompleto["chave_dup"]
        novas = database.save_jobs([incompleto, _record(job_id="ok", chave_dup="c-ok")])
        self.assertEqual([r["id"] for r in novas], ["ok"])

    def test_registro_com_campo_obrigatorio_ausente_e_pulado(self):
        incompleto = _record(job_id="incompleto", chave_dup="c-inc")
        del incompleto["titulo"]
        novas = database.save_jobs([
            incompleto, _record(job_id="ok2", chave_dup="c-ok2")])
        self.assertEqual([r["id"] for r in novas], ["ok2"])

    def test_apply_ignora_id_none_e_aceita_id_numerico(self):
        database.save_jobs([_record(job_id="123", chave_dup="c-123")])
        atualizadas = database.apply_statuses({
            None: config.STATUS_RECUSEI,
            123: config.STATUS_CANDIDATEI,
        })
        self.assertEqual(atualizadas, 1)
        self.assertEqual(database.apply_autofill_flags({None: config.AUTOFILL_SIM}), 0)
        with database.get_connection() as conn:
            row = conn.execute("SELECT * FROM vagas WHERE id = '123'").fetchone()
        self.assertEqual(row["situacao"], config.STATUS_CANDIDATEI)

        # id como texto (é o que vem da planilha) também funciona.
        database.save_jobs([_record(job_id="456", chave_dup="c-456")])
        self.assertEqual(
            database.apply_statuses({"456": config.STATUS_RECUSEI}), 1)
        with database.get_connection() as conn:
            row = conn.execute("SELECT * FROM vagas WHERE id = '456'").fetchone()
        self.assertEqual(row["situacao"], config.STATUS_RECUSEI)

    def test_registro_com_id_none_ou_vazio_e_pulado(self):
        # id NULL no SQLite (TEXT PRIMARY KEY aceita NULL) criava uma vaga
        # "zumbi": nunca atualizável por id e sempre pendente.
        sem_id = _record(job_id=None, chave_dup="c-nulo")
        id_vazio = _record(job_id="   ", chave_dup="c-vazio")
        sem_campo_id = _record(job_id="x", chave_dup="c-sem-campo")
        del sem_campo_id["id"]
        novas = database.save_jobs(
            [sem_id, id_vazio, sem_campo_id, _record(job_id="ok3", chave_dup="c-ok3")])
        self.assertEqual([r["id"] for r in novas], ["ok3"])
        with database.get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM vagas").fetchone()[0]
        self.assertEqual(total, 1)

    def test_registro_invalido_no_meio_do_lote_nao_derruba_os_demais(self):
        sem_titulo = _record(job_id="x", chave_dup="c-x")
        del sem_titulo["titulo"]
        novos = database.save_jobs([
            _record(job_id="a", chave_dup="c-a"),
            sem_titulo,
            _record(job_id="b", chave_dup="c-b"),
        ])
        self.assertEqual([r["id"] for r in novos], ["a", "b"])

    def test_mil_e_duzentos_registros_em_varios_lotes(self):
        # Mais que 2 x _BATCH_SIZE (500), com duplicatas internas e já salvas.
        registros = [
            _record(job_id="m-%d" % i, chave_dup="cm-%d" % i,
                    url="https://exemplo/m/%d" % i, descricao="d")
            for i in range(1200)
        ]
        registros.append(_record(job_id="m-repetida", chave_dup="cm-0",
                                 url="https://exemplo/repetida"))
        import time
        inicio = time.monotonic()
        novas = database.save_jobs(registros)
        duracao = time.monotonic() - inicio
        self.assertEqual(len(novas), 1200)
        self.assertLess(duracao, 10, "salvar 1200 registros demorou demais")
        self.assertEqual(database.save_jobs(registros), [])
        self.assertEqual(len(database.get_pending(days=30)), 1200)

    def test_get_pending_com_formatos_de_data(self):
        from datetime import datetime, timedelta
        hoje = datetime.now()
        registros = [
            ("iso", hoje.strftime("%Y-%m-%d")),
            ("iso-hora", hoje.strftime("%Y-%m-%dT10:00:00")),
            ("relativo", "2 days ago"),
            ("vazio", ""),
            ("nulo", None),
            ("futuro", (hoje + timedelta(days=30)).strftime("%Y-%m-%d")),
            ("antigo", (hoje - timedelta(days=30)).strftime("%Y-%m-%d")),
        ]
        database.save_jobs([
            _record(job_id=nome, chave_dup="cdata-" + nome, data_publicacao=valor)
            for nome, valor in registros
        ])
        ids = {v["id"] for v in database.get_pending(days=7)}
        self.assertEqual(ids, {"iso", "iso-hora", "relativo", "vazio", "nulo", "futuro"})

    def test_duas_conexoes_escrevendo_ao_mesmo_tempo(self):
        import threading
        erros = []

        def escrever(n):
            try:
                with database.get_connection() as conn:
                    for j in range(20):
                        conn.execute(
                            "INSERT OR IGNORE INTO vagas (id, chave_dup, titulo, situacao) "
                            "VALUES (?, ?, ?, ?)",
                            ("th-%d-%d" % (n, j), "thc-%d-%d" % (n, j), "V", config.STATUS_PENDENTE),
                        )
            except Exception as exc:  # pragma: no cover - só falha se houver lock
                erros.append(exc)

        threads = [threading.Thread(target=escrever, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(erros, [])
        with database.get_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM vagas WHERE id LIKE 'th-%'").fetchone()[0]
        self.assertEqual(total, 80)


if __name__ == "__main__":
    unittest.main()
