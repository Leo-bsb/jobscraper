"""Funções utilitárias (sem dependências externas)."""

import hashlib
import os
import re
import subprocess
import sys
import unicodedata


def open_file(path: str) -> None:
    """Abre um arquivo no programa padrão do sistema (Explorer/Finder/etc.)."""
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.call(["open", path])
    else:
        subprocess.call(["xdg-open", path])


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
    found = []
    for term in terms:
        t = normalize_text(term)
        if not t:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(t)
        if whole_word or len(t) <= 3:
            pattern += r"(?![a-z0-9])"
        if re.search(pattern, text_norm):
            found.append(str(term).strip())
    return found


def make_job_hash(empresa: str, titulo: str, local: str, url: str = "") -> str:
    """ID único da vaga: prioriza a URL; senão usa empresa|título|local."""
    base = url.strip() if url else f"{empresa}|{titulo}|{local}"
    return hashlib.md5(normalize_text(base).encode("utf-8")).hexdigest()


def make_dup_key(empresa: str, titulo: str, local: str) -> str:
    """
    Chave para detectar a MESMA vaga publicada em sites diferentes:
    empresa + título + cidade (só o trecho antes da vírgula do local).
    """
    cidade = normalize_text(str(local).split(",")[0])
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


def says_not_remote(text_norm: str) -> bool:
    return any(p in text_norm for p in NOT_REMOTE_PHRASES)


def detect_work_model(text_norm: str) -> str:
    if "hibrido" in text_norm or "hybrid" in text_norm:
        return "Híbrido"
    if says_not_remote(text_norm):
        return "Presencial"
    if any(k in text_norm for k in ("home office", "homeoffice", "home-office", "remoto", "remote")):
        return "Remoto"
    if any(k in text_norm for k in ("presencial", "on-site", "onsite")):
        return "Presencial"
    return "Não informado"


_SALARY_RE = re.compile(
    r"(?:r\$|\brs\b)\s*(\d[\d.,]*)(?:\s*(?:a|até|ate|-)\s*(?:r\$|\brs\b)?\s*(\d[\d.,]*))?",
    re.IGNORECASE,
)


def extract_salary(text: str) -> str:
    """Tenta achar uma faixa salarial em reais no texto. Retorna '' se não achar."""
    match = _SALARY_RE.search(text or "")
    if not match:
        return ""
    low = match.group(1).rstrip(".,")
    high = (match.group(2) or "").rstrip(".,")
    return f"R$ {low} - R$ {high}" if high else f"R$ {low}"
