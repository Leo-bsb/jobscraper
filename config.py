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

from __future__ import annotations

import copy
import json
import logging
import os
import re
import sys
import tempfile
from datetime import datetime

logger = logging.getLogger("buscavagas.config")


def _int_env(name: str, default: int, minimo: int = None, maximo: int = None) -> int:
    """
    Lê uma variável de ambiente inteira sem derrubar o programa no import.

    Um valor inválido (ex.: JOBSCRAPER_SMTP_PORT=abc) ou fora da faixa faz o
    padrão ser usado, com um aviso no log.
    """
    bruto = os.environ.get(name)
    if bruto is None or str(bruto).strip() == "":
        return default
    try:
        valor = int(str(bruto).strip())
    except (TypeError, ValueError):
        logger.warning("Valor inválido para %s (%r); usando %d.", name, bruto, default)
        return default
    if (minimo is not None and valor < minimo) or (maximo is not None and valor > maximo):
        logger.warning("Valor fora da faixa para %s (%r); usando %d.", name, bruto, default)
        return default
    return valor


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
VERSION = "2026.11"

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
        "pipeline de dados", "banco de dados", "data warehouse", "data lake", "bi",
        "nosql", "mineracao de dados", "ciencia de dados",
    ],
    "termos_fracos": ["desenvolv", "analis", "automac"],
    "exigir_termo_forte": True,
    # Opcional: exige que o termo forte apareça no TÍTULO (reduz falsos
    # positivos de vagas que só citam "dados" na descrição, ex.: LGPD).
    "exigir_termo_forte_no_titulo": False,
    "minimo_de_termos": 2,
    # Procurados SÓ NO TÍTULO (senioridade e tipo de cargo).
    # "pl" = pleno (abreviação comum nos títulos brasileiros). Entra como
    # proibido no título porque o perfil padrão busca vagas de entrada.
    "termos_proibidos_titulo": sorted(_LEGACY_TITLE_TERMS | {"sr", "pl", "jovem aprendiz"}),
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
    saved = dict(saved)
    # Um "cidades" escrito como texto é um arquivo editado à mão no formato
    # atual (o schema antigo usava "cidade" + "locais_extras"), não um arquivo
    # legado: não devemos ampliar a lista com "DF" nesse caso.
    cidades_como_texto = isinstance(saved.get("cidades"), str)
    if "cidades" not in saved and "cidade" in saved:
        cidades = _normalizar_lista(saved.get("cidade"), separar_virgula=False)
        cidades += _normalizar_lista(saved.get("locais_extras"), separar_virgula=False)
        saved["cidades"] = [c for c in cidades if c]
        saved.pop("cidade", None)
        saved.pop("locais_extras", None)
    if "termos_fortes" not in saved and "termos_obrigatorios_qualquer" in saved:
        # Schema bem antigo (v1): só existia uma lista única de termos.
        saved["termos_fortes"] = _normalizar_lista(
            saved.pop("termos_obrigatorios_qualquer"), separar_virgula=True)
        saved.setdefault("termos_fracos", [])
        saved.setdefault("exigir_termo_forte", False)
    # Antes de migrar: garante que os campos de lista sejam listas de verdade.
    # Um "cidades": "Brasília, DF" (ou "locais_extras": "Contagem") era
    # explodido em caracteres por list()/iteração, quebrando o filtro de local.
    if "cidades" in saved:
        saved["cidades"] = _normalizar_lista(saved["cidades"], separar_virgula=False)
    for campo in ("termos_proibidos", "termos_proibidos_titulo", "termos_home_office"):
        if campo in saved:
            saved[campo] = _normalizar_lista(saved[campo], separar_virgula=True)
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
        if (not cidades_como_texto
                and any(str(c).strip().upper().endswith(", DF") for c in cidades)
                and "DF" not in cidades):
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
        return coerce_filters(filters)

    try:
        # utf-8-sig: o Bloco de Notas do Windows grava BOM por padrão; sem
        # isso o arquivo era tratado como corrompido e voltava aos padrões.
        with open(FILTERS_PATH, "r", encoding="utf-8-sig") as f:
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
    return coerce_filters(filters)


def _write_json_atomic(path: str, data) -> None:
    """
    Grava um JSON de forma atômica: escreve num arquivo temporário na MESMA
    pasta e só então o substitui com os.replace().

    Assim uma queda de energia ou disco cheio não deixa o filtros.json/
    perfil.json pela metade (o que impediria o programa de abrir). Em caso de
    falha, o temporário é removido e um OSError com mensagem clara é levantado.
    """
    pasta = os.path.dirname(os.path.abspath(path))
    try:
        descritor, temporario = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=pasta)
    except OSError as exc:
        raise OSError("Não consegui criar o arquivo temporário em %s: %s"
                      % (pasta, exc)) from exc
    try:
        with os.fdopen(descritor, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, path)
    except BaseException as exc:
        try:
            os.unlink(temporario)
        except OSError:
            pass
        if isinstance(exc, OSError):
            raise OSError("Não consegui gravar %s: %s" % (os.path.basename(path), exc)) from exc
        raise


def save_filters(filters: dict) -> None:
    _write_json_atomic(FILTERS_PATH, filters)


# ----------------------------------------------------------------------
# Validação e normalização dos filtros
# ----------------------------------------------------------------------
_LISTAS_DE_TERMOS = (
    "termos_busca", "termos_home_office", "termos_fortes", "termos_fracos",
    "termos_proibidos", "termos_proibidos_titulo",
)
_CAMPOS_INTEIROS = ("versao_filtros", "dias", "resultados_por_busca", "minimo_de_termos")
_CAMPOS_BOOLEANOS = ("exigir_termo_forte", "exigir_termo_forte_no_titulo",
                     "aceitar_home_office_todo_brasil")
SITES_VALIDOS = ("indeed", "linkedin", "glassdoor", "google")


def _eh_inteiro(valor) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _eh_numero(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def dias_do_filtro(filters, padrao: int = 7) -> int:
    """
    Devolve o "dias" do filtro já validado (1..90), sem nunca lançar exceção.

    Um filtros.json editado à mão pode trazer "dias": null, "sete" ou 0. Sem
    esta proteção, regerar a planilha fora de uma busca (ex.: --only-export ou
    o applier) quebrava com TypeError/ValueError.
    """
    try:
        bruto = (filters or {}).get("dias", padrao)
    except AttributeError:  # filtros não é um dict
        bruto = None
    try:
        valor = int(bruto)
    except (TypeError, ValueError):
        logger.warning("Valor inválido em 'dias' (%r); usando %d.", bruto, padrao)
        valor = padrao
    return max(1, min(90, valor))


def validate_filters(filters: dict) -> list[str]:
    """
    Confere os filtros e devolve uma lista de mensagens legíveis (pt-BR) sobre
    o que está errado. Nunca levanta exceção — quem chama decide o que fazer.
    """
    if not isinstance(filters, dict):
        return ["filtros: os filtros não são um objeto válido"]

    problemas = []

    def validar_lista(campo: str, permitir_vazia: bool = False) -> None:
        if campo not in filters:
            problemas.append("%s: campo ausente" % campo)
            return
        valor = filters[campo]
        if not isinstance(valor, (list, tuple)):
            problemas.append("%s: deve ser uma lista de textos" % campo)
            return
        if not valor and not permitir_vazia:
            problemas.append("%s: lista vazia — informe pelo menos um item" % campo)
            return
        for indice, item in enumerate(valor, start=1):
            if not isinstance(item, str) or not item.strip():
                problemas.append("%s: o item %d não é um texto válido" % (campo, indice))

    validar_lista("termos_busca")
    validar_lista("cidades")
    for campo in ("termos_home_office", "termos_fortes", "termos_fracos",
                  "termos_proibidos", "termos_proibidos_titulo"):
        validar_lista(campo, permitir_vazia=True)

    if "sites" not in filters:
        problemas.append("sites: campo ausente")
    else:
        sites = filters["sites"]
        if not isinstance(sites, (list, tuple)):
            problemas.append("sites: deve ser uma lista de textos")
        elif not sites:
            problemas.append("sites: lista vazia — escolha pelo menos um site")
        else:
            for item in sites:
                if not isinstance(item, str) or not item.strip():
                    problemas.append("sites: contém um item vazio ou que não é texto")
                elif item.strip().lower() not in SITES_VALIDOS:
                    problemas.append(
                        "sites: site desconhecido '%s' (aceitos: %s)"
                        % (item, ", ".join(SITES_VALIDOS)))

    for campo, minimo, maximo in (
            ("dias", 1, 90),
            ("resultados_por_busca", 1, 1000),
            ("minimo_de_termos", 0, 20)):
        if campo not in filters:
            problemas.append("%s: campo ausente" % campo)
            continue
        valor = filters[campo]
        if not _eh_inteiro(valor) or not (minimo <= valor <= maximo):
            problemas.append("%s: deve ser um número inteiro entre %d e %d"
                             % (campo, minimo, maximo))

    if "alcance_km" not in filters:
        problemas.append("alcance_km: campo ausente")
    else:
        valor = filters["alcance_km"]
        if not _eh_numero(valor) or not (0 <= valor <= 500):
            problemas.append("alcance_km: deve ser um número entre 0 e 500")

    for campo in _CAMPOS_BOOLEANOS:
        if campo not in filters:
            problemas.append("%s: campo ausente" % campo)
        elif not isinstance(filters[campo], bool):
            problemas.append("%s: deve ser verdadeiro ou falso" % campo)

    if "versao_filtros" not in filters:
        problemas.append("versao_filtros: campo ausente")
    elif not _eh_inteiro(filters["versao_filtros"]):
        problemas.append("versao_filtros: deve ser um número inteiro")

    return problemas


def _para_inteiro(valor):
    """Converte '7', 7.0 -> 7; devolve o original se não der para converter."""
    if isinstance(valor, bool) or isinstance(valor, int):
        return valor
    if isinstance(valor, float):
        return int(valor) if valor.is_integer() else valor
    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return valor
        try:
            return int(texto)
        except ValueError:
            try:
                numero = float(texto)
            except ValueError:
                return valor
            return int(numero) if numero.is_integer() else valor
    return valor


def _para_numero(valor):
    """Converte '80', '80,5' -> número; devolve o original se não der."""
    if isinstance(valor, bool) or isinstance(valor, (int, float)):
        return valor
    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return valor
        try:
            return int(texto)
        except ValueError:
            pass
        try:
            return float(texto)
        except ValueError:
            pass
        try:
            return float(texto.replace(".", "").replace(",", "."))
        except ValueError:
            return valor
    return valor


def _para_booleano(valor):
    """Converte 'sim'/'não'/'true'/1 -> bool; devolve o original se não der."""
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)) and valor in (0, 1):
        return bool(valor)
    if isinstance(valor, str):
        texto = valor.strip().lower()
        if texto in ("true", "1", "sim", "s", "yes", "y", "on", "verdadeiro"):
            return True
        if texto in ("false", "0", "nao", "não", "n", "no", "off", "falso"):
            return False
    return valor


def _normalizar_lista(valor, separar_virgula: bool) -> list:
    """
    Garante uma lista: string vira lista (separando por vírgula quando faz
    sentido, ex.: termos), None vira [] e itens None são descartados.
    """
    if valor is None:
        return []
    if isinstance(valor, str):
        partes = re.split(r"[,;\n]", valor) if separar_virgula else valor.splitlines()
        if not partes:
            partes = [valor]
    elif isinstance(valor, (list, tuple, set)):
        partes = list(valor)
    else:
        partes = [valor]

    resultado = []
    for item in partes:
        if item is None:
            continue
        if isinstance(item, str):
            item = item.strip()
            if not item:
                continue
        resultado.append(item)
    return resultado


def coerce_filters(filters: dict) -> dict:
    """
    Corrige tipos óbvios (string -> lista, "7" -> 7, "sim" -> True) sem
    descartar dados e sem salvar nada. Não substitui a validação: valores
    realmente inválidos são mantidos para que validate_filters os aponte.
    """
    if not isinstance(filters, dict):
        return copy.deepcopy(DEFAULT_FILTERS)

    resultado = dict(filters)
    for campo in _LISTAS_DE_TERMOS:
        if campo in resultado:
            resultado[campo] = _normalizar_lista(resultado[campo], separar_virgula=True)
    for campo in ("cidades", "sites"):
        if campo in resultado:
            resultado[campo] = _normalizar_lista(resultado[campo], separar_virgula=(campo == "sites"))
    for campo in _CAMPOS_INTEIROS:
        if campo in resultado:
            resultado[campo] = _para_inteiro(resultado[campo])
    if "alcance_km" in resultado:
        resultado["alcance_km"] = _para_numero(resultado["alcance_km"])
    for campo in _CAMPOS_BOOLEANOS:
        if campo in resultado:
            resultado[campo] = _para_booleano(resultado[campo])
    return resultado


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
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            label = data.get("_nome_exibicao", os.path.splitext(name)[0])
            presets[label] = path
        except (OSError, ValueError):
            continue
    return presets


def load_preset(path: str) -> dict:
    """Carrega um perfil pronto, já mesclado sobre os padrões."""
    filters = copy.deepcopy(DEFAULT_FILTERS)
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    data.pop("_nome_exibicao", None)
    filters.update(_migrate_old_schema(data))
    return coerce_filters(filters)


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
            with open(PROFILE_PATH, "r", encoding="utf-8-sig") as f:
                profile.update(json.load(f))
        except (OSError, ValueError) as exc:
            logger.warning("Não consegui ler perfil.json (%s).", exc)
    else:
        save_profile(profile)
    return profile


def save_profile(profile: dict) -> None:
    _write_json_atomic(PROFILE_PATH, profile)
    # O perfil.json guarda e-mail, telefone e a chave do Gemini: em POSIX
    # restringimos a leitura/escrita ao dono. Em Windows/POSIX sem suporte,
    # apenas ignoramos a falha.
    if os.name == "posix":
        try:
            os.chmod(PROFILE_PATH, 0o600)
        except OSError as exc:
            logger.warning("Não consegui restringir as permissões do perfil.json (%s).", exc)


# ----------------------------------------------------------------------
# E-mail (opcional, só usado com `python main.py --email`)
# ----------------------------------------------------------------------
SMTP_HOST = os.environ.get("JOBSCRAPER_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _int_env("JOBSCRAPER_SMTP_PORT", 587, minimo=1, maximo=65535)
SMTP_USER = os.environ.get("JOBSCRAPER_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("JOBSCRAPER_SMTP_PASSWORD", "")
EMAIL_FROM = os.environ.get("JOBSCRAPER_EMAIL_FROM", SMTP_USER)
EMAIL_TO = os.environ.get("JOBSCRAPER_EMAIL_TO", SMTP_USER)
