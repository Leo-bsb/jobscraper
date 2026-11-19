"""Funções utilitárias (sem dependências externas)."""

import hashlib
import os
import re
import subprocess
import sys
import unicodedata


def open_file(path: str) -> bool:
    """
    Abre um arquivo no programa padrão do sistema (Explorer/Finder/etc.).
    Retorna True se o comando foi disparado com sucesso e False em falha
    (arquivo inexistente, programa ausente etc.), sem propagar exceção.
    """
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
            return True
        if sys.platform == "darwin":
            return subprocess.call(["open", path]) == 0
        return subprocess.call(["xdg-open", path]) == 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def normalize_text(text) -> str:
    """Minúsculas, sem acento, espaços/quebras de linha colapsados."""
    if text is None:
        return ""
    text = unicodedata.normalize("NFKD", str(text).lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def parse_list(raw: str) -> list:
    """'a, b; c\\nd' -> ['a', 'b', 'c', 'd'] (usado pela interface)."""
    if not raw:
        return []
    return [p.strip() for p in re.split(r"[,;\n]", raw) if p.strip()]


def parse_lines(raw: str) -> list:
    """
    Igual a parse_list, mas só separa por QUEBRA DE LINHA — usado para a lista
    de cidades, onde a vírgula faz parte do item ('Contagem, MG') e não pode
    virar separador.
    """
    if not raw:
        return []
    return [p.strip() for p in raw.split("\n") if p.strip()]


def find_terms(text_norm: str, terms: list, whole_word: bool = False) -> list:
    """
    Retorna os termos (como o usuário escreveu) que aparecem em `text_norm`
    (que já deve estar normalizado).

    Por padrão casa o COMEÇO da palavra: 'desenvolv' acha 'desenvolvedor'.
    Com whole_word=True exige a palavra inteira (usado para sigla de estado, ex: 'DF').
    Termos de até 3 letras (siglas como 'sr', 'sql', 'etl', 'upa') sempre
    exigem a palavra inteira — senão 'sr' casaria com 'SRE' e 'upa' com 'upar'.
    """
    if text_norm is None:
        return []
    if not isinstance(text_norm, str):
        text_norm = str(text_norm)
    if terms is None:
        return []
    if isinstance(terms, str):
        terms = [terms]
    elif not isinstance(terms, (list, tuple, set)):
        try:
            terms = list(terms)
        except TypeError:
            terms = [terms]

    found = []
    for term in terms:
        if not isinstance(term, str):
            continue
        t = normalize_text(term)
        if not t:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(t)
        if whole_word or len(t) <= 3:
            pattern += r"(?![a-z0-9])"
        if re.search(pattern, text_norm):
            found.append(term.strip())
    return found


def make_job_hash(empresa: str, titulo: str, local: str, url: str = "") -> str:
    """ID único da vaga: prioriza a URL; senão usa empresa|título|local."""
    if url:
        base = str(url).strip()
    else:
        base = f"{empresa or ''}|{titulo or ''}|{local or ''}"
    return hashlib.md5(normalize_text(base).encode("utf-8")).hexdigest()


def make_dup_key(empresa: str, titulo: str, local: str) -> str:
    """
    Chave para detectar a MESMA vaga publicada em sites diferentes:
    empresa + título + cidade (só o trecho antes da vírgula do local).
    """
    cidade = normalize_text(str(local or "").split(",")[0])
    base = f"{normalize_text(empresa)}|{normalize_text(titulo)}|{cidade}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()


# Frases (já normalizadas) que NEGAM o trabalho remoto. Sem isto, "não é
# remoto" ou "sem home office" seriam lidos como vaga remota.
NOT_REMOTE_PHRASES = (
    "nao e remot", "nao sera remot", "nao e home office", "nao e homeoffice",
    "sem home office", "sem homeoffice", "sem possibilidade de home office",
    "nao ha home office", "nao oferece home office", "nao possui home office",
    "nao trabalhamos remot", "nao aceita remot", "100% presencial",
    "exclusivamente presencial", "not remote", "no remote",
)

NOT_HYBRID_PHRASES = (
    "nao e hibrid", "nao sera hibrid", "sem hibrid", "nao e um modelo hibrid",
    "not hybrid", "no hybrid",
)

# Radicais, não palavras inteiras: em português a vaga costuma ser "remota" /
# "híbrida", e procurar a string "remoto" não casa com "remota".
REMOTE_RE = re.compile(r"\bremot[ao]s?\b")
HYBRID_RE = re.compile(r"\bhibrid[ao]s?\b")


def says_not_remote(text_norm: str) -> bool:
    return any(p in text_norm for p in NOT_REMOTE_PHRASES)


def says_not_hybrid(text_norm: str) -> bool:
    return any(p in text_norm for p in NOT_HYBRID_PHRASES)


def detect_work_model(text_norm: str) -> str:
    if (HYBRID_RE.search(text_norm) or "hybrid" in text_norm) and not says_not_hybrid(text_norm):
        return "Híbrido"
    if says_not_remote(text_norm):
        return "Presencial"
    if REMOTE_RE.search(text_norm) or any(
            k in text_norm for k in ("home office", "homeoffice", "home-office",
                                     "trabalho a distancia")):
        return "Remoto"
    if any(k in text_norm for k in ("presencial", "on-site", "onsite")):
        return "Presencial"
    return "Não informado"


# Só "R$" — antes aceitávamos também "RS" (sigla de estado) e "Porto Alegre,
# RS 90010-000" virava "R$ 90010 - R$ 000".
_SALARY_RE = re.compile(
    r"r\$\s*(\d[\d.,]*)(?:\s*(?:a|até|ate|-|–)\s*(?:r\$\s*)?(\d[\d.,]*))?",
    re.IGNORECASE,
)


def parse_br_number(text: str):
    """
    Lê um número no formato brasileiro (ou americano simples):

        '5.000,50'   -> 5000.5
        '1.234.567'  -> 1234567.0
        '12.345'     -> 12345.0
        '1,5'        -> 1.5
        '1.234,56'   -> 1234.56
        'R$' / ''    -> None

    Também aceita valores numéricos já prontos (ex.: 5000.0).
    """
    s = str(text if text is not None else "").strip()
    s = re.sub(r"r\$\s*", "", s, flags=re.IGNORECASE).strip().rstrip(".,")
    if not s:
        return None
    if "," in s:
        # Formato pt-BR: ponto é separador de milhar, vírgula é decimal.
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        # '1.234.567' (vários pontos de milhar, sem centavos)
        partes = s.split(".")
        if partes[0].isdigit() and all(len(p) == 3 and p.isdigit() for p in partes[1:]):
            s = "".join(partes)
    elif s.count(".") == 1 and len(s.split(".")[1]) == 3 and len(s) > 4:
        # '12.345' é milhar; '1.5' continua decimal.
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


# Nome antigo mantido para não quebrar chamadas existentes.
_parse_br_number = parse_br_number


def format_brl(value) -> str:
    """5000.0 -> 'R$ 5.000' ; 5000.5 -> 'R$ 5.000,50'."""
    if value is None:
        return ""
    if abs(value - round(value)) < 0.005:
        return "R$ " + f"{int(round(value)):,}".replace(",", ".")
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def extract_salary(text: str) -> str:
    """Tenta achar uma faixa salarial em reais no texto. Retorna '' se não achar."""
    match = _SALARY_RE.search(text or "")
    if not match:
        return ""
    low = _parse_br_number(match.group(1))
    high = _parse_br_number(match.group(2) or "")
    if low is None or low <= 0:
        return ""
    if high is not None and high < low:
        low, high = high, low
    if high:
        return f"{format_brl(low)} - {format_brl(high)}"
    return format_brl(low)
