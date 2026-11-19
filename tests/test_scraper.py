"""Testes do planejamento/coleta do scraper (sem rede e sem pandas obrigatório)."""

import copy
import unittest
from unittest import mock

import config
import scraper


class QuadroFalso:
    """
    Stub mínimo de DataFrame, sem pandas. Implementa só o que o scraper usa:
    .empty, .columns, [coluna], [máscara de bool], .drop_duplicates(subset=...)
    e len().
    """

    def __init__(self, linhas):
        self._linhas = [dict(linha) for linha in linhas]

    @property
    def empty(self):
        return not self._linhas

    @property
    def columns(self):
        colunas = []
        for linha in self._linhas:
            for nome in linha:
                if nome not in colunas:
                    colunas.append(nome)
        return colunas

    def __len__(self):
        return len(self._linhas)

    def __getitem__(self, chave):
        if isinstance(chave, str):
            return [linha.get(chave) for linha in self._linhas]
        if isinstance(chave, list):
            if chave and all(isinstance(item, bool) for item in chave):
                return QuadroFalso(
                    [linha for linha, manter in zip(self._linhas, chave) if manter])
            if all(isinstance(item, str) for item in chave):
                return QuadroFalso(
                    [{nome: linha.get(nome) for nome in chave} for linha in self._linhas])
        raise TypeError("chave não suportada no stub: %r" % (chave,))

    def drop_duplicates(self, subset=None):
        colunas = list(subset or self.columns)
        vistos = set()
        restantes = []
        for linha in self._linhas:
            chave = tuple(linha.get(nome) for nome in colunas)
            if chave in vistos:
                continue
            vistos.add(chave)
            restantes.append(linha)
        return QuadroFalso(restantes)


def _filtros(**kwargs):
    filtros = copy.deepcopy(config.DEFAULT_FILTERS)
    filtros.update(kwargs)
    return filtros


class PlanQueriesTest(unittest.TestCase):
    def test_build_queries_com_filtros_validos(self):
        filtros = _filtros(termos_busca=["dados"], sites=["indeed", "linkedin", "glassdoor"],
                           aceitar_home_office_todo_brasil=True)
        queries = scraper.build_queries(filtros)
        # 1 termo x 3 sites x 2 (cidade + nacional)
        self.assertEqual(len(queries), 6)
        for query in queries:
            self.assertEqual(len(query), 4)
            site, termo, local, raio = query
            self.assertIn(site, ("indeed", "linkedin", "glassdoor"))
            self.assertEqual(termo, "dados")
            if local in (config.NATIONAL_LOCATION_DEFAULT, "Brazil"):
                self.assertIsNone(raio)
            else:
                self.assertEqual(raio, round(80 / 1.60934))

    def test_build_queries_dois_termos_dois_sites(self):
        filtros = _filtros(termos_busca=["dados", "bi"],
                           sites=["indeed", "linkedin"],
                           aceitar_home_office_todo_brasil=False)
        self.assertEqual(len(scraper.build_queries(filtros)), 4)

    def test_build_queries_tolera_filtros_incompletos(self):
        self.assertEqual(scraper.build_queries({}), [])
        self.assertEqual(scraper.build_queries({"termos_busca": None, "sites": None}), [])
        self.assertEqual(scraper.build_queries({"termos_busca": [], "sites": []}), [])
        self.assertEqual(scraper.build_queries({"termos_busca": "  ", "sites": "indeed"}), [])

    def test_build_queries_aceita_strings(self):
        filtros = _filtros(termos_busca="dados, bi", sites="indeed",
                           aceitar_home_office_todo_brasil=False)
        queries = scraper.build_queries(filtros)
        self.assertEqual(len(queries), 2)
        self.assertEqual({q[1] for q in queries}, {"dados", "bi"})

    def test_plan_queries_campos(self):
        filtros = _filtros(termos_busca=["dados"], sites=["linkedin"],
                           aceitar_home_office_todo_brasil=True)
        planos = scraper.plan_queries(filtros)
        self.assertEqual(len(planos), 2)
        for plano in planos:
            self.assertEqual(set(plano),
                             {"site", "termo", "local", "raio_milhas", "nacional"})
        nacional = [p for p in planos if p["nacional"]]
        local = [p for p in planos if not p["nacional"]]
        self.assertEqual(len(nacional), 1)
        self.assertEqual(nacional[0]["local"], "Brazil")  # mapa específico do LinkedIn
        self.assertIsNone(nacional[0]["raio_milhas"])
        self.assertEqual(local[0]["local"], "Brasília, DF")
        self.assertIsNotNone(local[0]["raio_milhas"])

    def test_plan_queries_nunca_levanta_com_lixo(self):
        casos = [
            None, [], "texto", 42,
            {"termos_busca": ["a", "", None], "sites": ["indeed", "", None]},
            {"termos_busca": ["a"], "sites": "indeed, linkedin"},
            {"termos_busca": ["a"], "sites": ["indeed"], "alcance_km": "xx"},
            {"termos_busca": ["a"], "sites": ["indeed"], "alcance_km": -10},
            {"termos_busca": ["a"], "sites": ["indeed"], "alcance_km": None},
            {"termos_busca": ["a"], "sites": [None, 123], "cidades": [None, 7]},
        ]
        for caso in casos:
            with self.subTest(caso=caso):
                try:
                    planos = scraper.plan_queries(caso)
                except Exception as exc:  # pragma: no cover - falha do teste
                    self.fail("plan_queries levantou %s para %r" % (exc, caso))
                self.assertIsInstance(planos, list)

    def test_raio_aceita_virgula_decimal(self):
        self.assertEqual(scraper._raio_milhas({"alcance_km": "160,0"}),
                         round(160 / 1.60934))
        self.assertEqual(scraper._raio_milhas({"alcance_km": "abc"}),
                         config.DISTANCE_MILES_DEFAULT)
        self.assertEqual(scraper._raio_milhas({}), config.DISTANCE_MILES_DEFAULT)

    def test_resultados_por_busca_tolerante(self):
        self.assertEqual(scraper._resultados_por_busca({}, "indeed"), 40)
        self.assertEqual(scraper._resultados_por_busca(
            {"resultados_por_busca": None}, "indeed"), 40)
        self.assertEqual(scraper._resultados_por_busca(
            {"resultados_por_busca": "abc"}, "indeed"), 40)
        self.assertEqual(scraper._resultados_por_busca(
            {"resultados_por_busca": 0}, "indeed"), 40)  # 0 = não informado
        self.assertEqual(scraper._resultados_por_busca(
            {"resultados_por_busca": -5}, "indeed"), 1)
        self.assertEqual(scraper._resultados_por_busca(
            {"resultados_por_busca": 99999}, "indeed"), 1000)
        self.assertEqual(scraper._resultados_por_busca(
            {"resultados_por_busca": 100}, "linkedin"), config.LINKEDIN_MAX_RESULTS)

    def test_horas_desde_tolerante(self):
        self.assertEqual(scraper._horas_desde({"dias": 7}), 168)
        self.assertEqual(scraper._horas_desde({"dias": None}), 168)
        self.assertEqual(scraper._horas_desde({"dias": "sete"}), 168)


class ScrapeAllTest(unittest.TestCase):
    def test_site_desistido_apos_falhas_seguidas(self):
        filtros = _filtros(termos_busca=["dados", "bi"], sites=["indeed"],
                           aceitar_home_office_todo_brasil=False)
        chamadas = []
        esperas = []

        def fetch(site, termo, local, raio, filtros_recebidos):
            chamadas.append((site, termo, local, raio))
            raise scraper.SiteBlocked("recusou")

        resultado = scraper.scrape_all(filtros, sleep=esperas.append, fetch=fetch)

        self.assertEqual(len(chamadas), 2)  # as duas consultas foram tentadas
        self.assertEqual(len(resultado), 0)
        # Só há pausa ENTRE as consultas: uma pausa para duas consultas.
        self.assertEqual(len(esperas), 1)
        self.assertGreaterEqual(esperas[0], config.DELAY_MIN)
        self.assertLessEqual(esperas[0], config.DELAY_MAX)

    def test_site_desistido_para_de_ser_consultado(self):
        filtros = _filtros(termos_busca=["a", "b", "c"], sites=["indeed"],
                           aceitar_home_office_todo_brasil=False)
        chamadas = []

        def fetch(*args):
            chamadas.append(args[1])
            raise scraper.SiteBlocked("recusou")

        scraper.scrape_all(filtros, sleep=lambda _s: None, fetch=fetch)
        self.assertEqual(len(chamadas), config.SITE_GIVE_UP_AFTER)

    def test_keyboard_interrupt_e_propagado(self):
        filtros = _filtros(termos_busca=["dados"], sites=["indeed"],
                           aceitar_home_office_todo_brasil=False)

        def fetch(*args):
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            scraper.scrape_all(filtros, sleep=lambda _s: None, fetch=fetch)

    def test_fetch_vazio_nao_quebra(self):
        filtros = _filtros(termos_busca=["dados"], sites=["indeed"],
                           aceitar_home_office_todo_brasil=False)

        def fetch(*args):
            return QuadroFalso([])

        resultado = scraper.scrape_all(filtros, sleep=lambda _s: None, fetch=fetch)
        self.assertEqual(len(resultado), 0)
        self.assertTrue(resultado.empty)

    def test_fetch_none_nao_quebra(self):
        filtros = _filtros(termos_busca=["dados"], sites=["indeed"],
                           aceitar_home_office_todo_brasil=False)
        resultado = scraper.scrape_all(
            filtros, sleep=lambda _s: None, fetch=lambda *a: None)
        self.assertEqual(len(resultado), 0)

    def test_um_site_desistido_nao_derruba_os_outros(self):
        filtros = _filtros(termos_busca=["a", "b", "c"],
                           sites=["indeed", "linkedin"],
                           aceitar_home_office_todo_brasil=False)
        chamadas = []

        def fetch(site, termo, local, raio, _filtros):
            chamadas.append((site, termo))
            if site == "indeed":
                raise scraper.SiteBlocked("recusou")
            return QuadroFalso([])  # vazio: sem pandas, o concat não é exercitado

        resultado = scraper.scrape_all(
            filtros, sleep=lambda _s: None, fetch=fetch)
        indeed = [c for c in chamadas if c[0] == "indeed"]
        linkedin = [c for c in chamadas if c[0] == "linkedin"]
        self.assertEqual(len(indeed), config.SITE_GIVE_UP_AFTER)
        self.assertEqual(len(linkedin), 3)  # continuou até o fim
        self.assertEqual(len(resultado), 0)

    def test_nao_dorme_quando_o_que_resta_ja_foi_desistido(self):
        filtros = _filtros(termos_busca=["a"], sites=["indeed"],
                           aceitar_home_office_todo_brasil=False)
        esperas = []
        sequencia = [
            ("linkedin", "a", "Brasília, DF", 50),
            ("indeed", "a", "Brasília, DF", 50),
            ("indeed", "b", "Brasília, DF", 50),
            ("indeed", "c", "Brasília, DF", 50),
        ]

        def fetch(site, *_args):
            if site == "indeed":
                raise scraper.SiteBlocked("recusou")
            return QuadroFalso([])

        from unittest import mock
        with mock.patch.object(scraper, "build_queries", return_value=sequencia):
            scraper.scrape_all(filtros, sleep=esperas.append, fetch=fetch)
        # Pausas: depois do LinkedIn (ainda há Indeed) e depois da 1ª falha do
        # Indeed. Depois que ele é desistido, não há mais consulta para esperar.
        self.assertEqual(len(esperas), 2)


class FetchComJobspyFalsoTest(unittest.TestCase):
    """Exercita `_fetch` (retry/backoff) sem jobspy/pandas instalados."""

    class _PandasFalso:
        class DataFrame:
            empty = True

    class _JobspyFalso:
        def __init__(self, acao):
            self.acao = acao
            self.chamadas = []

        def scrape_jobs(self, **kwargs):
            self.chamadas.append(kwargs)
            return self.acao(kwargs)

    def setUp(self):
        import sys
        import types
        self._patch = mock.patch.dict(sys.modules)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        sys.modules["jobspy"] = types.ModuleType("jobspy")
        sys.modules["pandas"] = self._PandasFalso

    def _com_jobspy(self, acao):
        import sys
        modulo = self._JobspyFalso(acao)
        sys.modules["jobspy"].scrape_jobs = modulo.scrape_jobs
        return modulo

    def test_erro_em_todas_as_tentativas_levanta_site_blocked(self):
        modulo = self._com_jobspy(lambda _kw: (_ for _ in ()).throw(RuntimeError("403")))
        with mock.patch.object(scraper.time, "sleep") as dormir:
            with self.assertRaises(scraper.SiteBlocked):
                scraper._fetch("indeed", "dados", "Brasil", 50, {})
        self.assertEqual(len(modulo.chamadas), config.RETRY_MAX)
        # Espera só ENTRE as tentativas.
        self.assertEqual(dormir.call_count, config.RETRY_MAX - 1)

    def test_quadro_vazio_e_resposta_valida_sem_retry(self):
        modulo = self._com_jobspy(lambda _kw: self._PandasFalso.DataFrame())
        with mock.patch.object(scraper.time, "sleep") as dormir:
            df = scraper._fetch("indeed", "dados", "Brasil", 50, {})
        self.assertTrue(df.empty)
        self.assertEqual(len(modulo.chamadas), 1)
        dormir.assert_not_called()

    def test_resultados_none_e_dias_invalido_nao_estouram(self):
        modulo = self._com_jobspy(lambda _kw: self._PandasFalso.DataFrame())
        with mock.patch.object(scraper.time, "sleep"):
            scraper._fetch("indeed", "dados", "Brasil", 50, {
                "resultados_por_busca": None, "dias": "sete"})
        self.assertEqual(modulo.chamadas[0]["results_wanted"], 40)
        self.assertEqual(modulo.chamadas[0]["hours_old"], 168)


class DedupeDataframeTest(unittest.TestCase):
    def test_remove_por_url_e_por_titulo_empresa_local(self):
        quadro = QuadroFalso([
            {"job_url": "http://a", "title": "Analista de Dados",
             "company": "ACME", "location": "Brasília, DF"},
            # mesmo link: sai
            {"job_url": "http://a", "title": "Outro título",
             "company": "Outra", "location": "Recife, PE"},
            # mesmo título/empresa/local (normalizados, com acento): sai
            {"job_url": "http://b", "title": "ANALISTA DE DADOS",
             "company": "acme", "location": "Brasilia, DF"},
            # vaga diferente: fica
            {"job_url": "http://c", "title": "Engenheiro de Dados",
             "company": "ACME", "location": "Brasília, DF"},
        ])
        resultado = scraper._dedupe_dataframe(quadro)
        self.assertEqual(len(resultado), 2)
        self.assertEqual(resultado["job_url"], ["http://a", "http://c"])

    def test_mantem_quando_colunas_nao_existem(self):
        quadro = QuadroFalso([
            {"job_url": "http://a", "title": "X"},
            {"job_url": "http://a", "title": "Y"},
        ])
        resultado = scraper._dedupe_dataframe(quadro)
        # job_url existe: remove o link repetido; sem company/location não há
        # a segunda regra (não pode quebrar).
        self.assertEqual(len(resultado), 1)

    def test_sem_job_url_nao_quebra(self):
        quadro = QuadroFalso([
            {"title": "X", "company": "A", "location": "L"},
            {"title": "X", "company": "A", "location": "L"},
        ])
        resultado = scraper._dedupe_dataframe(quadro)
        self.assertEqual(len(resultado), 1)

    def test_quadro_vazio(self):
        self.assertIs(scraper._dedupe_dataframe(QuadroFalso([])).empty, True)
        self.assertIsNone(scraper._dedupe_dataframe(None))


if __name__ == "__main__":
    unittest.main()
