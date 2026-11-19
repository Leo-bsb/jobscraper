"""
Linha de comando (para você, que é de T.I.). Quem não é usa app.py / BuscaVagas.exe.

    python main.py                # busca + filtro + banco + planilha
    python main.py --only-export  # só relê as marcações e regera a planilha
    python main.py --email        # também envia e-mail com as vagas novas
    python main.py --days 14      # muda a janela de dias
    python main.py --check        # só valida filtros/perfil/pastas (não busca)
    python main.py --dry-run      # mostra o plano de consultas (não busca)
    python main.py --log-level DEBUG
    python main.py --version

Os testes chamam `main.main([...])` e recebem o código de saída (int); por isso
os imports pesados (pipeline/scraper) são tardios: assim `--check`/`--dry-run`
funcionam mesmo sem pandas/jobspy instalados.
"""

import argparse
import json
import logging
import os
import re
import sys
import tempfile

import config

logger = logging.getLogger("buscavagas.main")

SITES_VALIDOS = tuple(getattr(config, "SITES_VALIDOS", ("indeed", "linkedin", "glassdoor")))
# config.validate_filters usa esta mesma faixa; manter igual evita que o
# --check aprove um valor que a busca recusaria (ou vice-versa).
DIAS_MIN, DIAS_MAX = 1, 90
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ----------------------------------------------------------------------
# Argumentos
# ----------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Busca de vagas (Indeed, LinkedIn, Glassdoor) + planilha Excel.",
    )
    parser.add_argument("--only-export", action="store_true",
                        help="não busca; só regera a planilha")
    parser.add_argument("--email", action="store_true",
                        help="envia e-mail com as vagas novas")
    parser.add_argument("--days", type=int,
                        help="sobrescreve 'dias' do filtros.json (1 a 90)")
    parser.add_argument("--check", action="store_true",
                        help="valida filtros, perfil, perfis prontos e pasta base (não busca)")
    parser.add_argument("--dry-run", action="store_true",
                        help="mostra quais consultas seriam feitas, sem acessar a rede")
    parser.add_argument("--log-level", default="INFO", type=str.upper, choices=LOG_LEVELS,
                        metavar="LEVEL", help="DEBUG, INFO, WARNING ou ERROR (padrão: INFO)")
    parser.add_argument("--version", action="store_true",
                        help="mostra a versão do programa e sai")
    return parser


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
def _setup_logging(level_name: str = "INFO") -> None:
    """
    Configura o log. Se não for possível gravar o arquivo (pasta somente
    leitura, OneDrive travado...), o programa continua só com o console —
    em vez de morrer no primeiro logging.basicConfig.
    """
    level = getattr(logging, str(level_name or "INFO").upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    # Chamadas repetidas (testes/uso programático) não acumulam handlers.
    for handler in list(root.handlers):
        if getattr(handler, "_buscavagas_cli", False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handlers = []
    try:
        file_handler = logging.FileHandler(config.LOG_PATH, encoding="utf-8")
        file_handler.setFormatter(fmt)
        file_handler._buscavagas_cli = True
        handlers.append(file_handler)
    except OSError as exc:
        print(f"Aviso: não consegui gravar o log em {config.LOG_PATH} ({exc}). "
              "Seguindo só com as mensagens na tela.")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console._buscavagas_cli = True
    handlers.append(console)

    for handler in handlers:
        root.addHandler(handler)


# ----------------------------------------------------------------------
# Validação de filtros
# ----------------------------------------------------------------------
def _validate_filters_fallback(filters: dict) -> list:
    """
    Verificação local, usada sempre (inclusive junto com
    config.validate_filters, quando ele existir). Não acessa rede nem disco.
    """
    problemas = []
    filters = filters or {}

    termos = [str(t).strip() for t in (filters.get("termos_busca") or []) if str(t).strip()]
    if not termos:
        problemas.append('"termos_busca": preencha pelo menos uma palavra para buscar.')

    cidades = [str(c).strip() for c in (filters.get("cidades") or []) if str(c).strip()]
    if not cidades:
        problemas.append('"cidades": preencha pelo menos uma cidade aceita (ex.: "Brasília, DF").')

    sites = [str(s).strip().lower() for s in (filters.get("sites") or []) if str(s).strip()]
    if not sites:
        problemas.append('"sites": marque pelo menos um site (indeed, linkedin, glassdoor).')
    else:
        desconhecidos = [s for s in sites if s not in SITES_VALIDOS]
        if desconhecidos:
            problemas.append(f'"sites": site(s) desconhecido(s): {", ".join(desconhecidos)} '
                             f'(válidos: {", ".join(SITES_VALIDOS)}).')

    dias = filters.get("dias")
    try:
        dias_int = int(dias)
    except (TypeError, ValueError):
        dias_int = None
    if dias_int is None or not DIAS_MIN <= dias_int <= DIAS_MAX:
        problemas.append(f'"dias": deve ser um número entre {DIAS_MIN} e {DIAS_MAX}.')

    minimo = filters.get("minimo_de_termos", 1)
    try:
        minimo_int = int(minimo)
    except (TypeError, ValueError):
        minimo_int = None
    if minimo_int is None or minimo_int < 1:
        problemas.append('"minimo_de_termos": deve ser pelo menos 1.')

    if filters.get("exigir_termo_forte"):
        fortes = [str(t).strip() for t in (filters.get("termos_fortes") or []) if str(t).strip()]
        if not fortes:
            problemas.append('"termos_fortes": com "exigir_termo_forte" ligado, informe pelo '
                             'menos uma palavra forte.')

    alcance = filters.get("alcance_km")
    if alcance is not None:
        try:
            alcance_ok = int(alcance) > 0
        except (TypeError, ValueError):
            alcance_ok = False
        if not alcance_ok:
            problemas.append('"alcance_km": deve ser um número maior que zero.')

    return problemas


def _validate_filters(filters: dict) -> list:
    """
    Usa config.validate_filters quando disponível e soma a verificação local.
    Assim o --check continua funcionando mesmo se a função ainda não existir
    ou se ela levantar uma exceção.
    """
    problemas = []
    fn = getattr(config, "validate_filters", None)
    if callable(fn):
        try:
            resultado = fn(filters)
            if isinstance(resultado, str):
                problemas.append(resultado)
            elif resultado:
                problemas.extend(str(item) for item in resultado)
        except Exception as exc:  # não deixa a validação derrubar a CLI
            logger.warning("config.validate_filters falhou (%s); usando a verificação local.", exc)

    for problema in _validate_filters_fallback(filters):
        if problema not in problemas:
            problemas.append(problema)
    return problemas


# ----------------------------------------------------------------------
# --check
# ----------------------------------------------------------------------
def _check_base_dir() -> list:
    """Confere se a pasta base (onde ficam banco/planilha/log) aceita escrita."""
    base = getattr(config, "BASE_DIR", "") or os.getcwd()
    try:
        fd, temp_path = tempfile.mkstemp(prefix=".buscavagas-teste-", dir=base)
        os.close(fd)
        os.remove(temp_path)
    except OSError as exc:
        return [f'A pasta base "{base}" não é gravável ({exc}).']
    return []


def _check_profile():
    """Valida perfil.json sem exigir nada quando o arquivo não existe."""
    problemas, avisos = [], []
    caminho = getattr(config, "PROFILE_PATH", "")
    if not caminho or not os.path.exists(caminho):
        avisos.append('Perfil do candidato (perfil.json) não existe — ok se você não usa a '
                      'candidatura assistida.')
        return problemas, avisos

    try:
        with open(caminho, "r", encoding="utf-8-sig") as f:
            perfil = json.load(f)
        if not isinstance(perfil, dict):
            raise ValueError("o conteúdo não é um objeto JSON")
    except (OSError, ValueError) as exc:
        return [f'perfil.json não pôde ser lido ({exc}).'], avisos

    nome = str(perfil.get("nome_completo") or "").strip()
    email = str(perfil.get("email") or "").strip()
    telefone = str(perfil.get("telefone") or "").strip()

    # Só cobramos nome/e-mail quando o perfil já tem algum dado pessoal:
    # quem só salvou a chave do Gemini não precisa disso para buscar vagas.
    if nome or email or telefone:
        if not nome:
            problemas.append('perfil.json: falta "nome_completo" (necessário para a '
                             'candidatura assistida).')
        if not email:
            problemas.append('perfil.json: falta "email" (necessário para a candidatura '
                             'assistida).')
        elif not _EMAIL_RE.match(email):
            problemas.append('perfil.json: "email" não parece um e-mail válido.')
        if telefone and len(re.sub(r"\D", "", telefone)) < 8:
            problemas.append('perfil.json: "telefone" parece incompleto (use DDD + número).')
    else:
        avisos.append("perfil.json existe, mas está vazio — ok se você não usa a candidatura "
                      "assistida.")

    curriculo = str(perfil.get("curriculo_pdf") or "").strip()
    if curriculo and not os.path.isfile(curriculo):
        avisos.append(f'perfil.json: "curriculo_pdf" aponta para um arquivo que não existe '
                      f'({curriculo}).')

    return problemas, avisos


def _check_presets():
    """Valida cada .json da pasta perfis/ (opcional: pasta ausente não é erro)."""
    problemas, avisos = [], []
    pasta = getattr(config, "PRESETS_DIR", "") or ""
    if not pasta or not os.path.isdir(pasta):
        avisos.append("Pasta perfis/ não encontrada — sem perfis prontos (opcional).")
        return problemas, avisos

    encontrados = 0
    try:
        nomes = sorted(os.listdir(pasta))
    except OSError as exc:
        return [f'Não consegui listar a pasta perfis/ ({exc}).'], avisos

    for nome_arquivo in nomes:
        if not nome_arquivo.lower().endswith(".json"):
            continue
        encontrados += 1
        caminho = os.path.join(pasta, nome_arquivo)
        try:
            filtros = config.load_preset(caminho)
        except (OSError, ValueError) as exc:
            problemas.append(f'Perfil pronto "{nome_arquivo}" inválido: {exc}')
            continue
        for problema in _validate_filters(filtros):
            problemas.append(f'Perfil pronto "{nome_arquivo}": {problema}')

    if not encontrados:
        avisos.append("Nenhum perfil pronto (.json) em perfis/ (opcional).")
    return problemas, avisos


def _run_check() -> int:
    print("== Verificação do BuscaVagas ==")
    problemas, avisos = [], []

    try:
        filters = config.load_filters()
    except Exception as exc:  # JSON/permissões: reporta em vez de estourar
        filters = None
        problemas.append(f"filtros.json: não consegui carregar ({exc}).")

    if filters is not None:
        encontrados = _validate_filters(filters)
        if encontrados:
            problemas.extend(f"filtros.json: {p}" for p in encontrados)
        else:
            print("[OK] Filtros (filtros.json): nenhum problema encontrado.")

    base_problemas = _check_base_dir()
    problemas.extend(base_problemas)
    if not base_problemas:
        print(f"[OK] Pasta base gravável: {getattr(config, 'BASE_DIR', '')}")

    preset_problemas, preset_avisos = _check_presets()
    problemas.extend(preset_problemas)
    avisos.extend(preset_avisos)
    if not preset_problemas and not preset_avisos:
        print("[OK] Perfis prontos (perfis/): todos válidos.")

    perfil_problemas, perfil_avisos = _check_profile()
    problemas.extend(perfil_problemas)
    avisos.extend(perfil_avisos)
    if not perfil_problemas and not perfil_avisos:
        print("[OK] Perfil do candidato (perfil.json): ok.")

    for aviso in avisos:
        print(f"[aviso] {aviso}")

    if problemas:
        print("\nProblemas encontrados:")
        for problema in problemas:
            print(f"  - {problema}")
        print("\nCorrija os itens acima e rode `python main.py --check` de novo.")
        return 2

    print("\nTudo certo! Nenhum problema encontrado.")
    return 0


# ----------------------------------------------------------------------
# --dry-run
# ----------------------------------------------------------------------
def _local_plan(filters: dict) -> list:
    """
    Monta o plano (site, termo, local, raio_em_milhas_ou_None) localmente.
    Mesma regra de scraper.build_queries, mas sem embaralhar e sem importar pandas.
    """
    termos = [str(t).strip() for t in (filters.get("termos_busca") or []) if str(t).strip()]
    sites = [str(s).strip().lower() for s in (filters.get("sites") or []) if str(s).strip()]
    cidades = [str(c).strip() for c in (filters.get("cidades") or []) if str(c).strip()]
    local_principal = cidades[0] if cidades else "Brasil"

    try:
        km = int(filters.get("alcance_km"))
    except (TypeError, ValueError):
        km = None
    miles = round(km / 1.60934) if km else config.DISTANCE_MILES_DEFAULT

    nacional_por_site = getattr(config, "NATIONAL_LOCATION_BY_SITE", {}) or {}
    nacional_padrao = getattr(config, "NATIONAL_LOCATION_DEFAULT", "Brasil")

    plano = []
    for termo in termos:
        for site in sites:
            plano.append((site, termo, local_principal, miles))
            if filters.get("aceitar_home_office_todo_brasil"):
                plano.append((site, termo, nacional_por_site.get(site, nacional_padrao), None))
    return plano


def _plan_from_scraper(filters: dict):
    """
    Usa scraper.plan_queries se existir. Import tardio e tolerante: sem pandas
    (ou se a função ainda não foi criada) simplesmente devolve None.
    """
    try:
        import scraper  # noqa: F401  (import tardio de propósito)
    except Exception:
        return None

    fn = getattr(scraper, "plan_queries", None)
    if not callable(fn):
        return None
    try:
        plano = fn(filters)
    except Exception as exc:
        logger.warning("Não consegui usar scraper.plan_queries (%s); montando o plano local.", exc)
        return None

    normalizado = []
    for item in plano or []:
        if isinstance(item, dict):
            normalizado.append((
                item.get("site", ""), item.get("termo", item.get("term", "")),
                item.get("local", item.get("location", "")),
                item.get("raio_milhas", item.get("distance", item.get("raio"))),
            ))
        elif isinstance(item, (tuple, list)) and len(item) >= 3:
            normalizado.append(tuple(item[:4]) + (None,) * (4 - len(item[:4])))
    return normalizado or None


def _build_plan(filters: dict) -> list:
    plano = _plan_from_scraper(filters)
    if plano:
        return plano
    return _local_plan(filters)


def _print_plan(filters: dict) -> None:
    print("== Plano de consultas (--dry-run: nada será buscado) ==")
    cidades = [str(c).strip() for c in (filters.get("cidades") or []) if str(c).strip()]
    local_principal = cidades[0] if cidades else "Brasil"
    try:
        km = int(filters.get("alcance_km"))
    except (TypeError, ValueError):
        km = None

    print(f"Local principal: {local_principal}")
    if km:
        print(f"Raio: {km} km (~{round(km / 1.60934)} milhas)")
    else:
        print(f"Raio: padrão (~{getattr(config, 'DISTANCE_MILES_DEFAULT', 50)} milhas)")
    print(f"Home office no Brasil inteiro: "
          f"{'sim' if filters.get('aceitar_home_office_todo_brasil') else 'não'}")
    print("")

    plano = _build_plan(filters)
    for i, (site, termo, local, raio) in enumerate(plano, start=1):
        detalhe = f"raio ~{raio} mi" if raio else "sem raio, busca nacional"
        print(f'  {i:>2}. {site}: "{termo}" em {local} ({detalhe})')

    print("")
    print(f"Consultas: {len(plano)}")
    if not plano:
        print("Nenhuma consulta — confira 'termos_busca' e 'sites' (use --check).")


# ----------------------------------------------------------------------
# Execução normal
# ----------------------------------------------------------------------
def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --days fora da faixa: mensagem do próprio argparse (sem stack trace).
    if args.days is not None and not DIAS_MIN <= args.days <= DIAS_MAX:
        parser.error(f"--days deve ser um número entre {DIAS_MIN} e {DIAS_MAX}.")

    if args.version:
        print(f"BuscaVagas {config.VERSION}")
        return 0

    _setup_logging(args.log_level)

    if args.check:
        return _run_check()

    try:
        filters = config.load_filters()
    except Exception as exc:
        logger.exception("Não consegui carregar os filtros")
        print(f"Não consegui carregar os filtros ({exc}). Rode `python main.py --check`.")
        return 1

    if args.days is not None:
        filters["dias"] = args.days

    if args.dry_run:
        _print_plan(filters)
        return 0

    try:
        if args.only_export:
            import database
            import export_xlsx

            database.init_db()
            print("Planilha:", export_xlsx.sync_spreadsheet(days=config.dias_do_filtro(filters)))
        else:
            import pipeline

            result = pipeline.run_search(filters, send_email=args.email)
            print("Planilha:", result["planilha"])
    except KeyboardInterrupt:
        print("\nInterrompido por você. Nada foi enviado; a planilha atual continua válida.")
        return 130
    except Exception as exc:  # não mostra traceback cru para quem só quer as vagas
        logger.exception("Erro durante a execução")
        print(f"Erro: {exc}\nDetalhes no log: {config.LOG_PATH}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
