"""
Configuração central.

Os FILTROS (o que buscar, cidades, palavras exigidas/proibidas...) ficam no
arquivo `filtros.json`, que pode ser editado à mão OU pela interface (app.py).
Os arquivos gerados (banco, planilha, log) ficam na mesma pasta do programa/.exe,
então cada pessoa pode ter a sua própria pasta com filtros e vagas separados.

PERFIS PRONTOS: a pasta `perfis/` (ao lado do programa) traz modelos de
filtro já preenchidos para áreas comuns (dados, enfermagem...). A interface
lê essa pasta para montar o menu "Perfil pronto".
"""

import copy
import json
import logging
import os
import sys
from datetime import datetime

logger = logging.getLogger("buscavagas.config")


def _base_dir() -> str:
    # Empacotado com PyInstaller: usa a pasta onde está o .exe (não a pasta temporária)
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _base_dir()
DB_PATH = os.path.join(BASE_DIR, "vagas.db")
FILTERS_PATH = os.path.join(BASE_DIR, "filtros.json")
XLSX_PATH = os.path.join(BASE_DIR, "vagas_da_semana.xlsx")
LOG_PATH = os.path.join(BASE_DIR, "buscavagas.log")
PRESETS_DIR = os.path.join(BASE_DIR, "perfis")
DISCARDED_PATH = os.path.join(BASE_DIR, "descartadas_ultima_busca.json")

# Mostrada no título das janelas e no log — ajuda a saber qual versão está rodando
VERSION = "2026.10"

# ----------------------------------------------------------------------
# Situações possíveis de uma vaga (dropdown da planilha)
# ----------------------------------------------------------------------
STATUS_PENDENTE = "Pendente"
STATUS_CANDIDATEI = "Candidatei"
STATUS_RECUSEI = "Recusei"
STATUS_OPTIONS = [STATUS_PENDENTE, STATUS_CANDIDATEI, STATUS_RECUSEI]

# Coluna "Auto-preencher" da planilha (candidatura assistida)
AUTOFILL_SIM = "Sim"
AUTOFILL_NAO = "Não"
AUTOFILL_OPTIONS = [AUTOFILL_NAO, AUTOFILL_SIM]

# ----------------------------------------------------------------------
# Comportamento do scraper (anti-bloqueio)
# ----------------------------------------------------------------------
COUNTRY = "brazil"              # país usado por Indeed/Glassdoor no JobSpy
DELAY_MIN = 4                   # pausa aleatória entre buscas (segundos)
DELAY_MAX = 12
RETRY_MAX = 3                   # tentativas por busca quando o site recusa/erra
RETRY_WAIT_MIN = 15             # espera base entre tentativas (multiplicada pela tentativa)
RETRY_WAIT_MAX = 40
SITE_GIVE_UP_AFTER = 2         # buscas seguidas recusadas antes de pular o site na execução
LINKEDIN_MAX_RESULTS = 25       # LinkedIn bloqueia rápido, principalmente ao baixar descrições
DISTANCE_MILES_DEFAULT = 50     # raio padrão do JobSpy ao redor da cidade de busca (~80 km,
                                 # cobre regiões metropolitanas inteiras, ex.: Contagem/Betim/BH)

# Como cada site entende "Brasil inteiro" (usado na busca por vagas home office)
NATIONAL_LOCATION_DEFAULT = "Brasil"
NATIONAL_LOCATION_BY_SITE = {"linkedin": "Brazil"}

# ----------------------------------------------------------------------
# Filtros padrão (usados se filtros.json não existir)
#
# REGRA DE BUSCA DE PALAVRAS: ignora maiúsculas e acentos e casa o COMEÇO
# da palavra. Ex: "desenvolv" pega desenvolver, desenvolvedor, desenvolvimento.
#
# TERMOS "FORTES" vs. "FRACOS" (por que essa divisão existe):
#   Palavras como "desenvolv" e "analis" aparecem em QUALQUER vaga de
#   desenvolvedor ou analista, não só as de dados — e também aparecem sozinhas
#   em rodapés padrão de LGPD ("tratamento de dados pessoais") de vagas que não
#   têm nada a ver (recepcionista, vendedor, etc.). Por isso elas contam para
#   o "minimo_de_termos", mas sozinhas NÃO aprovam a vaga: é preciso pelo
#   menos um termo "forte" (python, sql, power bi, etl...) junto.
#
# "cidades": lista de nomes de cidade/região aceitos na vaga (o primeiro da
#   lista também é usado como centro da busca nos sites — o raio de busca
#   ("alcance_km") já cobre cidades vizinhas automaticamente).
# ----------------------------------------------------------------------
FILTERS_VERSION = 4

# Termos antigos de home office que não pegavam "remota"/"remotas" (o filtro
# casa o COMEÇO da palavra, então "remoto" não acha "remota").
_LEGACY_HOME_OFFICE = {"remoto", "remota", "remotas", "remote"}

# Termos que, até a versão 2, ficavam em "termos_proibidos" (título + descrição)
# mas na prática descrevem o CARGO — então passaram a valer só para o título.
_LEGACY_TITLE_TERMS = {
    "estagi", "senior", "logistic", "almoxarifado", "assistente administrativo",
    "auxiliar administrativo", "auxiliar financeiro", "contas a pagar",
    "telemarketing", "televendas", "recepcao", "promotor de vendas",
    "consultor de vendas", "vendedor", "representante comercial",
    "operador de caixa", "motorista", "montador", "bobinador",
    "backoffice", "back office", "auxiliar de treinamento", "trainee",
}

DEFAULT_FILTERS = {
    "versao_filtros": FILTERS_VERSION,
    "termos_busca": ["dados"],
    # Uma linha por cidade aceita. "Cidade, UF" casa só a cidade; uma linha sem
    # vírgula (ex.: "DF") casa como está — útil para aceitar uma região inteira.
    "cidades": ["Brasília, DF", "DF", "Distrito Federal", "Federal District"],
    "alcance_km": 80,
    "aceitar_home_office_todo_brasil": True,
    "termos_home_office": [
        "home office", "homeoffice", "home-office", "remot",
        "trabalho a distancia",
    ],
    "termos_fortes": [
        "python", "sql", "power bi", "poder bi", "dashboard", "etl", "elt",
        "machine learning", "estatistic", "data engineer", "data scientist",
        "data analyst", "cientista de dados", "engenheiro de dados",
        "analista de dados", "business intelligence", "databricks", "spark",
        "airflow", "pandas", "tableau", "looker", "snowflake", "big data",
        "pipeline de dados", "banco de dados", "data warehouse", "data lake",
        "nosql", "mineracao de dados", "ciencia de dados",
    ],
    "termos_fracos": ["desenvolv", "analis", "automac"],
    "exigir_termo_forte": True,
    "minimo_de_termos": 2,
    # Procurados SÓ NO TÍTULO (senioridade e tipo de cargo).
    "termos_proibidos_titulo": sorted(_LEGACY_TITLE_TERMS | {"sr", "jovem aprendiz"}),
    # Procurados no título E na descrição (use para algo que nunca serve).
    "termos_proibidos": ["digitador", "digitacao de dados"],
    "dias": 7,
    "sites": ["indeed", "linkedin", "glassdoor"],
    "resultados_por_busca": 40,
}


def _migrate_old_schema(saved: dict) -> dict:
    """
    Compatibilidade com filtros.json de versões antigas, que tinham uma
    única "cidade" (texto) + "locais_extras", em vez da lista "cidades".
    """
    if "cidades" not in saved and "cidade" in saved:
        cidades = [saved["cidade"]] + list(saved.get("locais_extras", []))
        saved = dict(saved)
        saved["cidades"] = [c for c in cidades if c]
        saved.pop("cidade", None)
        saved.pop("locais_extras", None)
    if "termos_fortes" not in saved and "termos_obrigatorios_qualquer" in saved:
        # Schema bem antigo (v1): só existia uma lista única de termos.
        saved = dict(saved)
        saved["termos_fortes"] = saved.pop("termos_obrigatorios_qualquer")
        saved.setdefault("termos_fracos", [])
        saved.setdefault("exigir_termo_forte", False)
    try:
        # Um "versao_filtros": null (ou "abc") no JSON derrubava o programa
        # na abertura, porque int(None) levanta TypeError.
        versao = int(saved.get("versao_filtros") or 0)
    except (TypeError, ValueError):
        versao = 0
    saved = dict(saved)
    if versao < 3:
        # v3: termos de cargo/senioridade passam a valer só no título.
        if "termos_proibidos" in saved:
            antigos = list(saved["termos_proibidos"])
            saved["termos_proibidos_titulo"] = list(dict.fromkeys(
                list(saved.get("termos_proibidos_titulo", []))
                + [t for t in antigos if t in _LEGACY_TITLE_TERMS]))
            saved["termos_proibidos"] = [t for t in antigos if t not in _LEGACY_TITLE_TERMS]
        # v3: "Cidade, UF" deixou de aceitar o estado inteiro. O DF é uma única
        # região metropolitana, então mantemos o comportamento antigo para ele.
        cidades = list(saved.get("cidades", []))
        if any(str(c).strip().upper().endswith(", DF") for c in cidades) and "DF" not in cidades:
            cidades.append("DF")
        saved["cidades"] = cidades
    if versao < 4:
        # v4: home office por radical ("remot" acha remoto, remota, remotas).
        termos = saved.get("termos_home_office")
        if isinstance(termos, list):
            saved["termos_home_office"] = list(dict.fromkeys(
                "remot" if str(t).strip().lower() in _LEGACY_HOME_OFFICE else t
                for t in termos))
    saved["versao_filtros"] = FILTERS_VERSION
    return saved


def _backup_broken_file() -> None:
    """Move um filtros.json ilegível para .bak, em vez de perdê-lo no próximo save."""
    try:
        destino = FILTERS_PATH + ".bak"
        if os.path.exists(destino):
            destino = f"{FILTERS_PATH}.{datetime.now():%Y%m%d_%H%M%S}.bak"
        os.replace(FILTERS_PATH, destino)
        logger.warning("O filtros.json antigo foi guardado em %s.", destino)
    except OSError as exc:
        logger.warning("Não consegui guardar uma cópia do filtros.json antigo (%s).", exc)


def load_filters() -> dict:
    """Lê filtros.json (criando-o com os padrões se não existir)."""
    filters = copy.deepcopy(DEFAULT_FILTERS)
    if not os.path.exists(FILTERS_PATH):
        save_filters(filters)
        return filters

    try:
        with open(FILTERS_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if not isinstance(saved, dict):
            raise ValueError("o conteúdo não é um objeto JSON")
    except (OSError, ValueError) as exc:
        logger.warning("Não consegui ler filtros.json (%s). Usando padrões.", exc)
        _backup_broken_file()
        return filters

    try:
        filters.update(_migrate_old_schema(saved))
    except Exception as exc:  # formato inesperado: não impede o programa de abrir
        logger.exception("filtros.json tem um formato inesperado (%s). Usando padrões.", exc)
        _backup_broken_file()
    return filters


def save_filters(filters: dict) -> None:
    with open(FILTERS_PATH, "w", encoding="utf-8") as f:
        json.dump(filters, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------
# Perfis prontos (pasta perfis/, ao lado do programa)
# ----------------------------------------------------------------------
def list_presets() -> dict:
    """{nome_para_mostrar: caminho_do_arquivo} dos perfis disponíveis em perfis/."""
    presets = {}
    if not os.path.isdir(PRESETS_DIR):
        return presets
    for name in sorted(os.listdir(PRESETS_DIR)):
        if not name.lower().endswith(".json"):
            continue
        path = os.path.join(PRESETS_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            label = data.get("_nome_exibicao", os.path.splitext(name)[0])
            presets[label] = path
        except (OSError, ValueError):
            continue
    return presets


def load_preset(path: str) -> dict:
    """Carrega um perfil pronto, já mesclado sobre os padrões."""
    filters = copy.deepcopy(DEFAULT_FILTERS)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.pop("_nome_exibicao", None)
    filters.update(_migrate_old_schema(data))
    return filters


# ----------------------------------------------------------------------
# Perfil do candidato (candidatura assistida)
# ----------------------------------------------------------------------
PROFILE_PATH = os.path.join(BASE_DIR, "perfil.json")
# Pasta onde o navegador guarda o login do Indeed entre execuções
BROWSER_PROFILE_DIR = os.path.join(BASE_DIR, "navegador_indeed")

DEFAULT_PROFILE = {
    "nome_completo": "",
    "email": "",
    "telefone": "",
    "curriculo_pdf": "",
    # Chave da API do Gemini (Google AI Studio), para a carta de apresentação
    # personalizada. Fica salva aqui para não precisar digitar de novo.
    "google_api_key": "",
}


def load_profile() -> dict:
    profile = copy.deepcopy(DEFAULT_PROFILE)
    if os.path.exists(PROFILE_PATH):
        try:
            with open(PROFILE_PATH, "r", encoding="utf-8") as f:
                profile.update(json.load(f))
        except (OSError, ValueError) as exc:
            logger.warning("Não consegui ler perfil.json (%s).", exc)
    else:
        save_profile(profile)
    return profile


def save_profile(profile: dict) -> None:
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------
# E-mail (opcional, só usado com `python main.py --email`)
# ----------------------------------------------------------------------
SMTP_HOST = os.environ.get("JOBSCRAPER_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("JOBSCRAPER_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("JOBSCRAPER_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("JOBSCRAPER_SMTP_PASSWORD", "")
EMAIL_FROM = os.environ.get("JOBSCRAPER_EMAIL_FROM", SMTP_USER)
EMAIL_TO = os.environ.get("JOBSCRAPER_EMAIL_TO", SMTP_USER)
