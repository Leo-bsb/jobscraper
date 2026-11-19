"""Testes do pipeline com coletor injetado (sem rede, sem pandas/jobspy)."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

try:
    import openpyxl  # noqa: F401  (pipeline importa export_xlsx)
except ImportError:  # pragma: no cover - depende do ambiente
    raise unittest.SkipTest("openpyxl não está instalado")

import config
import database
import export_xlsx
import pipeline


class _StubFrame:
    """Imita o mínimo do DataFrame do pandas usado pelo pipeline."""

    def __init__(self, rows):
        self._rows = list(rows)
        self.empty = not self._rows

    def __len__(self):
        return len(self._rows)

    def astype(self, _dtype):
        return self

    def notna(self):
        return self

    def where(self, _cond, _other):
        return self

    def to_dict(self, orient="records"):
        if orient != "records":
            raise AssertionError("orient inesperado: %r" % (orient,))
        return [dict(row) for row in self._rows]


def _record(job_id="id1"):
    return {"id": job_id, "chave_dup": "c-" + job_id, "titulo": "Analista de Dados"}


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jobscraper-pipeline-")
        self._old_db = config.DB_PATH
        config.DB_PATH = os.path.join(self.tmp, "vagas.db")
        self.filters = {"dias": 7}

    def tearDown(self):
        config.DB_PATH = self._old_db
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, df, records=None, discarded=None, save_result=None,
             send_email=False, scrape=None, email_side_effect=None):
        records = records or []
        discarded = discarded or []
        save_result = records if save_result is None else save_result
        scrape = scrape or (lambda _filters: df)

        patches = [
            mock.patch.object(export_xlsx, "import_statuses", return_value=0),
            mock.patch.object(export_xlsx, "export_weekly_report",
                              return_value="planilha.xlsx"),
            mock.patch.object(database, "save_jobs", return_value=save_result),
            mock.patch.object(pipeline.filtering, "filter_jobs",
                              return_value=(records, discarded, {})),
        ]
        if email_side_effect is not None:
            patches.append(mock.patch("notifier.send_daily_digest",
                                      side_effect=email_side_effect))
        else:
            patches.append(mock.patch("notifier.send_daily_digest",
                                      return_value=True))

        started = [p.start() for p in patches]
        try:
            resultado = pipeline.run_search(self.filters, send_email=send_email,
                                            scrape=scrape)
        finally:
            for p in patches:
                p.stop()
        return resultado, started

    def test_retorna_chaves_antigas_e_erros(self):
        registros = [_record("1")]
        resultado, (imp, exportar, salvar, filtrar, email) = self._run(
            _StubFrame([{"title": "vaga"}]), records=registros)

        self.assertEqual(resultado["coletadas"], 1)
        self.assertEqual(resultado["aprovadas"], 1)
        self.assertEqual(resultado["novas"], 1)
        self.assertEqual(resultado["planilha"], "planilha.xlsx")
        self.assertEqual(resultado["erros"], [])
        filtrar.assert_called_once()
        salvar.assert_called_once_with(registros)
        self.assertEqual(exportar.call_args.kwargs["days"], 7)
        email.assert_not_called()  # send_email=False

    def test_coletor_recebe_os_filtros(self):
        recebidos = []

        def coletor(filters):
            recebidos.append(filters)
            return _StubFrame([])

        _, patches = self._run(None, scrape=coletor)
        self.assertEqual(recebidos, [self.filters])
        # Sem vagas: planilha é gerada mesmo assim.
        exportar = patches[1]
        exportar.assert_called_once()
        self.assertEqual(exportar.call_args.kwargs["discarded"], [])

    def test_dataframe_vazio_gera_planilha_sem_salvar(self):
        resultado, (_, exportar, salvar, _, _) = self._run(_StubFrame([]))
        self.assertEqual(resultado["coletadas"], 0)
        self.assertEqual(resultado["aprovadas"], 0)
        self.assertEqual(resultado["novas"], 0)
        self.assertEqual(resultado["planilha"], "planilha.xlsx")
        self.assertEqual(resultado["erros"], [])
        salvar.assert_not_called()
        exportar.assert_called_once()

    def test_falha_no_email_nao_impede_a_planilha(self):
        registros = [_record()]
        resultado, (_, exportar, _, _, email) = self._run(
            _StubFrame([{"title": "vaga"}]),
            records=registros,
            send_email=True,
            email_side_effect=RuntimeError("SMTP fora do ar"),
        )
        self.assertEqual(resultado["novas"], 1)
        self.assertEqual(resultado["planilha"], "planilha.xlsx")
        self.assertTrue(any("e-mail" in msg for msg in resultado["erros"]))
        exportar.assert_called_once()
        email.assert_called_once()

    def test_falha_na_coleta_e_recuperavel(self):
        def coletor(_filters):
            raise RuntimeError("site bloqueado")

        resultado, (_, exportar, salvar, _, _) = self._run(None, scrape=coletor)
        self.assertEqual(resultado["coletadas"], 0)
        self.assertEqual(resultado["novas"], 0)
        self.assertEqual(resultado["planilha"], "planilha.xlsx")
        self.assertTrue(resultado["erros"])
        salvar.assert_not_called()
        exportar.assert_called_once()

    def test_sem_vagas_novas_nao_tenta_email(self):
        resultado, (_, _, _, _, email) = self._run(
            _StubFrame([{"title": "vaga"}]),
            records=[_record()],
            save_result=[],
            send_email=True,
        )
        self.assertEqual(resultado["novas"], 0)
        email.assert_not_called()

    def test_dias_invalido_nao_impede_a_planilha(self):
        # "dias": null (ou "sete") fazia int() estourar antes de exportar.
        for valor in (None, "sete", 0, -3):
            with self.subTest(dias=valor):
                self.filters = {"dias": valor}
                resultado, (_, exportar, _, _, _) = self._run(_StubFrame([]))
                self.assertEqual(resultado["planilha"], "planilha.xlsx")
                self.assertEqual(resultado["erros"], [])
                self.assertEqual(exportar.call_args.kwargs["days"], 7)

    def test_erros_sempre_presente_mesmo_com_coleta_ruim(self):
        resultado, _ = self._run(None, scrape=lambda _f: (_ for _ in ()).throw(
            ValueError("formato inesperado")))
        self.assertIn("erros", resultado)
        self.assertIsInstance(resultado["erros"], list)
        self.assertTrue(resultado["erros"])


if __name__ == "__main__":
    unittest.main()
