"""
Filtro das vagas coletadas. Uma vaga só passa se:

1. NÃO contiver nenhum termo proibido (ex: estágio, sênior, almoxarifado...)
   no título/descrição;
2. contiver pelo menos `minimo_de_termos` termos (fortes + fracos somados),
   sendo que pelo menos UM precisa ser "forte" (se `exigir_termo_forte`);
3. estiver na cidade escolhida (ex: Brasília/DF)
   OU (se habilitado) tiver uma palavra de home office/remoto no próprio
   texto da vaga, em qualquer lugar do Brasil.

Por que não confiamos na flag "is_remote" do JobSpy: na prática ela vem
incorreta em vários casos (vaga claramente híbrida, numa cidade diferente da
sua, marcada como remota pelo site de origem). Preferimos exigir que a
própria vaga diga isso no texto.
"""

import logging
from collections import Counter
from datetime import datetime

import config
from utils import (
    detect_work_model, extract_salary, find_terms, format_brl, make_dup_key,
    make_job_hash, normalize_text, says_not_remote,
)

logger = logging.getLogger("buscavagas.filtering")

# Intervalo salarial que o JobSpy devolve em inglês ("yearly") -> sufixo curto.
_PERIODO = {
    "yearly": "/ano", "annual": "/ano", "monthly": "/mês", "weekly": "/semana",
    "daily": "/dia", "hourly": "/hora",
}


def _local_terms(filters: dict) -> list:
    """
    Nomes aceitos no local da vaga, um por linha da lista 'cidades':
      - "Contagem, MG" -> só "Contagem" (a sigla do estado NÃO entra; antes ela
        entrava e aceitava qualquer cidade de Minas Gerais);
      - uma linha sem vírgula vale inteira: "DF" ou "Distrito Federal" aceitam
        a região toda, de propósito.
    """
    tokens = []
    for cidade in filters.get("cidades", []):
        nome = str(cidade).split(",")[0].strip()
        if nome:
            tokens.append(nome)
    return tokens


def _salary(raw: dict, description: str) -> str:
    """
    Faixa salarial do site (min_amount/max_amount) já formatada em pt-BR;
    se o site não informar, tenta achar "R$ ..." no texto da descrição.
    """
    def _num(valor):
        if valor in ("", None):
            return None
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            return None
        return numero if numero > 0 else None

    lo, hi = _num(raw.get("min_amount")), _num(raw.get("max_amount"))
    if lo is None:
        return extract_salary(description)

    moeda = str(raw.get("currency") or "").strip().upper()
    if moeda and moeda not in ("BRL", "R$"):
        # Não é real: mostra o código da moeda em vez de fingir que é R$.
        texto = f"{moeda} {lo:,.0f}"
        if hi is not None and hi >= lo:
            texto += f" - {moeda} {hi:,.0f}"
        return texto

    periodo = _PERIODO.get(str(raw.get("interval") or "").strip().lower(), "")
    if hi is not None and hi >= lo:
        return f"{format_brl(lo)} - {format_brl(hi)}{(' ' + periodo) if periodo else ''}"
    return f"{format_brl(lo)}{(' ' + periodo) if periodo else ''}"


def evaluate(raw: dict, filters: dict):
    """Retorna (registro, None) se aprovada, ou (None, motivo) se descartada."""
    titulo = str(raw.get("title", "") or "")
    descricao = str(raw.get("description", "") or "")
    local = str(raw.get("location", "") or "")
    texto = normalize_text(f"{titulo} {descricao}")
    # O modelo de trabalho também olha o CAMPO DE LOCAL: muitas vagas chegam
    # com local "Home Office" e descrição que não repete a palavra "remoto".
    texto_modelo = normalize_text(f"{titulo} {descricao} {local}")

    # Senioridade e tipo de cargo são decididos pelo TÍTULO: na descrição,
    # "estágio concluído", "reporta ao gerente sênior" ou "área de logística"
    # aparecem em vagas perfeitamente boas.
    proibidos_titulo = find_terms(normalize_text(titulo), filters.get("termos_proibidos_titulo", []))
    if proibidos_titulo:
        return None, f"título tem termo proibido ({proibidos_titulo[0]})"
    proibidos = find_terms(texto, filters.get("termos_proibidos", []))
    if proibidos:
        return None, f"tem termo proibido ({proibidos[0]})"

    fortes = filters.get("termos_fortes", [])
    fracos = filters.get("termos_fracos", [])
    achados_fortes = find_terms(texto, fortes)
    achados_fracos = find_terms(texto, fracos)
    encontrados = achados_fortes + achados_fracos

    if (fortes or fracos) and len(encontrados) < int(filters.get("minimo_de_termos", 1)):
        return None, "menos termos do que o mínimo exigido"
    if filters.get("exigir_termo_forte", True) and fortes and not achados_fortes:
        return None, "só tem termo(s) fraco(s), sem nenhum termo forte"

    modelo_trabalho = detect_work_model(texto_modelo)
    na_cidade = bool(find_terms(normalize_text(local), _local_terms(filters), whole_word=True))
    # Só considera home office/remoto se o PRÓPRIO TEXTO da vaga disser isso
    # (não confiamos na flag is_remote do site, que vem errada com frequência).
    home_office = (bool(find_terms(texto_modelo, filters.get("termos_home_office", [])))
                   and not says_not_remote(texto_modelo))
    if not na_cidade:
        if modelo_trabalho == "Híbrido":
            # Híbrido exige ir ao escritório: fora da sua região não serve,
            # mesmo que o texto cite "remoto" ("2 dias remoto").
            return None, "híbrido fora das cidades aceitas"
        if not (filters.get("aceitar_home_office_todo_brasil") and home_office):
            return None, "fora das cidades aceitas e sem home office"

    empresa = str(raw.get("company", "") or "") or "(empresa não informada)"
    link = str(raw.get("job_url", "") or "")
    local_exibicao = local or "(local não informado)"

    # Para vagas remotas, a cidade do anúncio não importa de verdade (o mesmo
    # cargo remoto aparece postado sob várias cidades) — então a deduplicação
    # ignora a cidade nesse caso, senão a mesma vaga passaria como "nova" várias vezes.
    cidade_para_dup = "" if modelo_trabalho == "Remoto" else local

    return {
        "id": make_job_hash(empresa, titulo, local, link),
        "chave_dup": make_dup_key(empresa, titulo, cidade_para_dup),
        "titulo": titulo,
        "empresa": empresa,
        "localizacao": local_exibicao,
        "modelo_trabalho": modelo_trabalho,
        "faixa_salarial": _salary(raw, descricao),
        "termos_encontrados": ", ".join(encontrados),
        "pontos": len(encontrados),
        "link": link,
        "descricao": descricao,
        "site_origem": str(raw.get("site", "") or ""),
        "data_publicacao": str(raw.get("date_posted", "") or ""),
        "data_coleta": datetime.now().isoformat(timespec="seconds"),
        "situacao": config.STATUS_PENDENTE,
        "auto_preencher": config.AUTOFILL_NAO,
    }, None


def filter_jobs(raw_jobs: list, filters: dict):
    """
    Retorna (aprovadas, descartadas, motivos) onde:
      - aprovadas: lista de registros prontos para o banco;
      - descartadas: lista de dicts simples (titulo/empresa/link/motivo), só
        da execução atual, para a aba de auditoria da planilha;
      - motivos: Counter com a contagem por motivo de descarte.
    """
    approved, discarded, seen_keys, reasons = [], [], set(), Counter()

    for raw in raw_jobs:
        record, reason = evaluate(raw, filters)
        if record is None:
            reasons[reason] += 1
            discarded.append({
                "titulo": str(raw.get("title", "") or ""),
                "empresa": str(raw.get("company", "") or "") or "(empresa não informada)",
                "localizacao": str(raw.get("location", "") or "") or "(local não informado)",
                "link": str(raw.get("job_url", "") or ""),
                "motivo": reason,
            })
        elif record["chave_dup"] in seen_keys:
            reasons["repetida em outro site"] += 1
            discarded.append({
                "titulo": record["titulo"], "empresa": record["empresa"],
                "localizacao": record["localizacao"], "link": record["link"],
                "motivo": "repetida em outro site",
            })
        else:
            seen_keys.add(record["chave_dup"])
            approved.append(record)

    logger.info("Filtro: %d aprovada(s) de %d.", len(approved), len(raw_jobs))
    for reason, n in reasons.most_common():
        logger.info("   descartadas por '%s': %d", reason, n)
    return approved, discarded, reasons
