"""
Adaptador de currículo e carta de apresentação.

A partir do seu currículo em PDF e da descrição de uma vaga específica,
gera (via API do Gemini, Google AI Studio):
  1. Uma carta de apresentação personalizada para aquela vaga.
  2. Sugestões objetivas de como destacar/reordenar pontos do currículo.
  3. Um currículo .docx REORGANIZADO para aquela vaga (mesmas experiências,
     mesmas empresas, mesmas datas — só a ênfase e a ordem mudam).

Sobre o item 3 (por que é estruturado em vez de texto livre): em vez de
pedir ao modelo "reescreva o currículo" (que é fácil demais de sair do
controle), pedimos uma lista de experiências em JSON (empresa, cargo,
período, pontos) e MONTAMOS o .docx nós mesmos a partir disso. Isso permite
comparar, depois da resposta, se cada nome de empresa/instituição que veio
na resposta realmente aparece no currículo original — ver
`_checar_fabricacao()`. Não é uma garantia perfeita, mas pega o caso mais
grave (inventar um emprego ou curso inteiro).

REQUISITOS (recurso opcional — só precisa disso se for usar este botão)
    pip install -U google-genai pypdf python-docx
    Uma chave de API gratuita em https://aistudio.google.com/apikey

CUSTO: o Google AI Studio oferece uma cota gratuita generosa para o modelo
usado aqui; uso além da cota gratuita é cobrado pelo Google. Veja os limites
atuais em https://ai.google.dev/gemini-api/docs/pricing

PRIVACIDADE: para gerar a carta, o texto do currículo e a descrição da vaga
são enviados para a API do Gemini. Veja a política de uso de dados em
https://ai.google.dev/gemini-api/terms se isso for uma preocupação para você.

A CHAVE FICA SALVA LOCALMENTE em perfil.json (ao lado do programa) depois da
primeira vez que você a digita na interface — não precisa inserir de novo.

O QUE ISTO NÃO FAZ (de propósito)
  - Nunca inventa experiência, cargo, tempo, certificação ou habilidade que
    não esteja no currículo original — só reorganiza e destaca o que já é
    verdade. Isso está travado no texto de instrução enviado ao modelo.
  - Nunca envia nada por você: só gera um arquivo .docx para você revisar.
"""

import json
import logging
import os
import re

import config

logger = logging.getLogger("buscavagas.resume_adapter")

CARTAS_DIR = os.path.join(config.BASE_DIR, "cartas")
CURRICULOS_DIR = os.path.join(config.BASE_DIR, "curriculos_adaptados")

# Nome do modelo configurável aqui caso a Google troque/aposente uma versão.
MODEL = "gemini-3.5-flash"
# Se o modelo acima deixar de existir, tentamos este apelido (sempre aponta
# para o Flash mais recente) em vez de quebrar.
FALLBACK_MODEL = "gemini-flash-latest"

# Generoso de propósito: nos modelos Gemini atuais o "raciocínio" interno
# também consome esse limite, e um limite curto cortava o JSON no meio.
MAX_OUTPUT_TOKENS = 8192

CARTA_SCHEMA = {
    "type": "object",
    "properties": {
        "carta": {"type": "string"},
        "sugestoes_curriculo": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["carta", "sugestoes_curriculo"],
}

CURRICULO_SCHEMA = {
    "type": "object",
    "properties": {
        "nome": {"type": "string"}, "email": {"type": "string"}, "telefone": {"type": "string"},
        "linkedin": {"type": "string"}, "cidade": {"type": "string"},
        "resumo_profissional": {"type": "string"},
        "experiencias": {"type": "array", "items": {"type": "object", "properties": {
            "empresa": {"type": "string"}, "cargo": {"type": "string"}, "periodo": {"type": "string"},
            "pontos": {"type": "array", "items": {"type": "string"}}},
            "required": ["empresa", "cargo", "periodo", "pontos"]}},
        "formacao": {"type": "array", "items": {"type": "object", "properties": {
            "curso": {"type": "string"}, "instituicao": {"type": "string"}, "periodo": {"type": "string"}},
            "required": ["curso", "instituicao"]}},
        "habilidades": {"type": "array", "items": {"type": "string"}},
        "certificacoes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["nome", "experiencias", "habilidades"],
}


class GeminiError(Exception):
    """Erro com mensagem já pronta para mostrar ao usuário."""


def _call_gemini(api_key: str, system_prompt: str, user_content: str, schema: dict) -> dict:
    """Chama o Gemini pedindo JSON no formato `schema` e devolve o dict."""
    from google import genai
    from google.genai import errors, types

    client = genai.Client(api_key=api_key)
    config_kwargs = dict(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_json_schema=schema,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.4,
    )
    ultimo_erro = None
    for model in (MODEL, FALLBACK_MODEL):
        for com_thinking in (True, False):
            kwargs = dict(config_kwargs)
            if com_thinking:
                # Pouco raciocínio: a tarefa é reorganizar texto, não resolver problema.
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="LOW")
            try:
                response = client.models.generate_content(
                    model=model, contents=user_content,
                    config=types.GenerateContentConfig(**kwargs),
                )
            except errors.ClientError as exc:
                code = getattr(exc, "code", None)
                msg = str(exc).lower()
                if code in (401, 403) or "api key" in msg or "api_key" in msg:
                    raise GeminiError("A chave do Gemini foi recusada. Confira se copiou a chave "
                                      "inteira do AI Studio e clique em \"Salvar meus dados\".") from exc
                if code == 429:
                    raise GeminiError("Limite de uso gratuito do Gemini atingido por agora. "
                                      "Espere alguns minutos e tente de novo.") from exc
                if code == 400 and com_thinking and "think" in msg:
                    ultimo_erro = exc
                    continue  # este modelo não aceita thinking_level: tenta sem
                if code == 404:
                    ultimo_erro = exc
                    logger.warning("Modelo %s indisponível (%s); tentando o próximo.", model, exc)
                    break  # próximo modelo
                raise GeminiError(f"O Gemini recusou o pedido: {exc}") from exc
            except errors.ServerError as exc:
                raise GeminiError("O serviço do Gemini está instável agora. Tente de novo em "
                                  "alguns minutos.") from exc

            candidato = (response.candidates or [None])[0]
            motivo = getattr(candidato, "finish_reason", None)
            if motivo is not None and getattr(motivo, "name", str(motivo)) == "MAX_TOKENS":
                raise GeminiError("A resposta do Gemini ficou longa demais e foi cortada. "
                                  "Tente de novo; se persistir, use um currículo mais curto.")
            text = (response.text or "").strip()
            text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
            if not text:
                raise GeminiError("O Gemini não devolveu texto (pode ter sido bloqueado pelo "
                                  "filtro de segurança). Tente de novo.")
            try:
                data = json.loads(text)
            except ValueError as exc:
                raise GeminiError(f"A resposta do Gemini não veio em JSON válido: {exc}") from exc
            if not isinstance(data, dict):
                raise GeminiError("A resposta do Gemini veio num formato inesperado.")
            return data
    raise GeminiError(f"Nenhum modelo do Gemini disponível agora: {ultimo_erro}")

SYSTEM_PROMPT = """Você é um assistente de carreira que ajuda a adaptar candidaturas de emprego, em português do Brasil.

REGRAS OBRIGATÓRIAS (não quebre nenhuma):
- Use APENAS fatos que já aparecem no currículo fornecido. NUNCA invente, infira ou exagere experiência, cargo, tempo, certificação, ferramenta ou habilidade que não esteja explicitamente no currículo.
- Se a vaga pedir algo que o currículo não comprova, simplesmente não mencione esse ponto — não finja que a pessoa tem.
- Tom profissional, direto, sem clichês genéricos ("apaixonado por desafios", "equipe orientada a resultados", "sinergia").
- Carta de apresentação: no máximo 300 palavras, em português do Brasil, pronta para revisão humana antes de enviar — não é para ser enviada automaticamente.
- Sugestões de currículo: no máximo 6 itens, objetivos e acionáveis (ex.: "mova a experiência com Power BI para o topo da lista de habilidades", "inclua a palavra 'ETL' já que você descreveu isso na experiência X, mesmo sem usar esse termo").

Responda SOMENTE em JSON válido, sem blocos de markdown ao redor, no formato exato:
{"carta": "texto completo da carta aqui", "sugestoes_curriculo": ["sugestão 1", "sugestão 2"]}"""


def extract_resume_text(pdf_path: str) -> str:
    """Extrai o texto de um currículo em PDF."""
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    texto = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    if not texto:
        raise ValueError(
            "Não consegui ler nenhum texto desse PDF — ele pode ser uma imagem "
            "escaneada em vez de texto selecionável."
        )
    return texto


def _user_content(resume_text: str, job: dict, rotulo_cv: str) -> str:
    return (
        f"{rotulo_cv}:\n{resume_text}\n\n"
        f"VAGA: {job.get('titulo', '')} na empresa {job.get('empresa', '')}\n"
        f"DESCRIÇÃO DA VAGA:\n{job.get('descricao', '') or '(descrição não disponível)'}\n"
    )


def generate(api_key: str, resume_text: str, job: dict) -> dict:
    """
    Chama a API do Gemini e retorna {"carta": str, "sugestoes_curriculo": [str, ...]}
    para a vaga `job` (dict com pelo menos titulo, empresa, descricao).
    """
    data = _call_gemini(api_key, SYSTEM_PROMPT,
                        _user_content(resume_text, job, "CURRÍCULO DO CANDIDATO"), CARTA_SCHEMA)
    carta = str(data.get("carta", "")).strip()
    if not carta:
        raise GeminiError("O Gemini devolveu uma carta vazia. Tente de novo.")
    return {
        "carta": carta,
        "sugestoes_curriculo": [str(x).strip() for x in data.get("sugestoes_curriculo", []) if str(x).strip()],
    }


SYSTEM_PROMPT_CURRICULO = """Você é um assistente de carreira que reorganiza currículos para uma vaga específica, em português do Brasil.

REGRAS OBRIGATÓRIAS (não quebre nenhuma, são mais importantes que ficar bem escrito):
- Copie nome, e-mail, telefone, LinkedIn e cidade EXATAMENTE como aparecem no currículo original. Se algum não existir, deixe como string vazia "".
- Liste as experiências profissionais na MESMA ORDEM CRONOLÓGICA do currículo original (não reordene por relevância). Para cada uma, "empresa", "cargo" e "periodo" devem ser EXATAMENTE os mesmos textos do currículo original — não corrija, não traduza, não reformate datas.
- Os "pontos" (bullets) de cada experiência podem ser reescritos para ficarem mais claros e podem ser REORDENADOS entre si (os mais relevantes para a vaga primeiro), mas cada ponto só pode descrever algo que já estava no currículo original — nunca adicione ferramenta, métrica, resultado numérico ou responsabilidade que não estava lá.
- A lista de "habilidades" pode ser REORDENADA para colocar as mais relevantes à vaga primeiro, mas só pode conter habilidades que já estavam no currículo original — não adicione nenhuma nova, mesmo que a vaga peça.
- "formacao" e "certificacoes": copie como estavam, pode reordenar mas não inventar nem alterar.
- "resumo_profissional": 2 a 4 frases novas que sintetizam o perfil do candidato para ESTA vaga, mas usando apenas fatos (empresas, cargos, habilidades) que já estão no currículo original. Não calcule nem afirme "X anos de experiência" a menos que o currículo original diga isso explicitamente.
- Se a vaga pedir algo que o currículo não comprova, não inclua esse ponto em lugar nenhum — não finja.

Responda SOMENTE em JSON válido, sem blocos de markdown, no formato exato:
{
  "nome": "", "email": "", "telefone": "", "linkedin": "", "cidade": "",
  "resumo_profissional": "",
  "experiencias": [{"empresa": "", "cargo": "", "periodo": "", "pontos": ["", ""]}],
  "formacao": [{"curso": "", "instituicao": "", "periodo": ""}],
  "habilidades": [""],
  "certificacoes": [""]
}"""


def generate_adapted_resume(api_key: str, resume_text: str, job: dict) -> dict:
    """
    Chama a API do Gemini e retorna o currículo reestruturado (dict no formato
    de CURRICULO_SCHEMA) para a vaga `job`.
    """
    data = _call_gemini(api_key, SYSTEM_PROMPT_CURRICULO,
                        _user_content(resume_text, job, "CURRÍCULO ORIGINAL DO CANDIDATO"),
                        CURRICULO_SCHEMA)
    if not data.get("experiencias") and not data.get("formacao"):
        raise GeminiError("O Gemini não conseguiu ler as experiências do seu currículo. Confira "
                          "se o PDF tem texto selecionável (não é uma foto/escaneado).")
    return data


def _checar_fabricacao(resume_data: dict, texto_original: str) -> list:
    """
    Checagem heurística (não é prova formal): procura no currículo ORIGINAL
    cada coisa "factual" que veio na resposta. O que não for encontrado vira
    um aviso para você revisar. Cobre:
      - empresas e instituições de ensino (por palavras do nome);
      - anos citados nos períodos (um ano que não existia no original é forte
        sinal de período inventado);
      - habilidades e certificações (inventar uma habilidade que a vaga pede é
        o erro mais provável do modelo);
      - e-mail e telefone (por dígitos, para tolerar formatação diferente).
    """
    from utils import normalize_text

    original_norm = normalize_text(texto_original)
    original_digitos = re.sub(r"\D", "", texto_original)
    anos_originais = set(re.findall(r"(?:19|20)\d{2}", texto_original))
    avisos = []

    def palavras(texto):
        return [p for p in re.findall(r"[a-z0-9+#.]+", normalize_text(texto)) if len(p) > 2]

    def checa_nome(nome, tipo):
        nome = (nome or "").strip()
        ps = palavras(nome)
        if ps and not any(p in original_norm for p in ps):
            avisos.append(f'{tipo} "{nome}" não foi encontrado no currículo original — CONFIRA antes de usar.')

    def checa_termo(termo, tipo):
        termo = (termo or "").strip()
        ps = palavras(termo) or [normalize_text(termo)]
        if termo and not all(p in original_norm for p in ps if p):
            avisos.append(f'{tipo} "{termo}" não aparece no currículo original — CONFIRA antes de usar.')

    def checa_anos(periodo, onde):
        for ano in re.findall(r"(?:19|20)\d{2}", periodo or ""):
            if ano not in anos_originais:
                avisos.append(f'O ano {ano} em "{onde}" não aparece no currículo original — CONFIRA.')

    for exp in resume_data.get("experiencias", []):
        checa_nome(exp.get("empresa", ""), "Empresa")
        checa_anos(exp.get("periodo", ""), exp.get("empresa", "") or exp.get("cargo", ""))
    for f in resume_data.get("formacao", []):
        checa_nome(f.get("instituicao", ""), "Instituição de ensino")
        checa_anos(f.get("periodo", ""), f.get("curso", "") or f.get("instituicao", ""))
    for h in resume_data.get("habilidades", []):
        checa_termo(h, "Habilidade")
    for c in resume_data.get("certificacoes", []):
        checa_termo(c, "Certificação")

    email = (resume_data.get("email") or "").strip().lower()
    if email and email not in texto_original.lower():
        avisos.append(f'E-mail "{email}" diferente do currículo original — CONFIRA.')
    tel = re.sub(r"\D", "", resume_data.get("telefone") or "")
    if len(tel) >= 8 and tel[-8:] not in original_digitos:
        avisos.append(f'Telefone "{resume_data.get("telefone")}" diferente do currículo original — CONFIRA.')

    return avisos


def _safe_filename(text: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]", "_", text).strip()
    return cleaned[:80] or "vaga"


def save_as_docx(job: dict, carta: str, sugestoes: list) -> str:
    """Salva a carta (+ sugestões de currículo) num .docx dentro de cartas/. Retorna o caminho."""
    from docx import Document

    os.makedirs(CARTAS_DIR, exist_ok=True)
    nome = _safe_filename(f"Carta - {job.get('empresa', '')} - {job.get('titulo', '')}") + ".docx"
    path = os.path.join(CARTAS_DIR, nome)

    doc = Document()
    doc.add_heading(f"Carta de apresentação — {job.get('titulo', '')}", level=1)
    doc.add_paragraph(f"Empresa: {job.get('empresa', '')}")
    doc.add_paragraph(f"Vaga: {job.get('link', '')}")
    doc.add_paragraph("")
    for paragrafo in carta.split("\n"):
        if paragrafo.strip():
            doc.add_paragraph(paragrafo.strip())

    if sugestoes:
        doc.add_heading("Sugestões para ajustar seu currículo nesta vaga", level=2)
        for s in sugestoes:
            doc.add_paragraph(s, style="List Bullet")

    doc.save(path)
    logger.info("Carta salva em %s", path)
    return path


def generate_and_save(api_key: str, resume_text: str, job: dict) -> str:
    """Atalho: gera a carta e já salva em .docx. Retorna o caminho do arquivo."""
    resultado = generate(api_key, resume_text, job)
    return save_as_docx(job, resultado["carta"], resultado["sugestoes_curriculo"])


def save_resume_as_docx(job: dict, resume_data: dict, avisos: list) -> str:
    """Monta o .docx do currículo adaptado a partir do JSON estruturado. Retorna o caminho."""
    from docx import Document
    from docx.shared import Pt

    os.makedirs(CURRICULOS_DIR, exist_ok=True)
    nome_arquivo = _safe_filename(f"Curriculo - {job.get('empresa', '')} - {job.get('titulo', '')}") + ".docx"
    path = os.path.join(CURRICULOS_DIR, nome_arquivo)

    doc = Document()

    if avisos:
        from docx.shared import RGBColor
        aviso_par = doc.add_paragraph()
        aviso_run = aviso_par.add_run(
            "⚠ REVISE ANTES DE USAR — itens abaixo não foram confirmados no currículo original:\n"
            + "\n".join(f"• {a}" for a in avisos)
        )
        aviso_run.bold = True
        aviso_run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
        doc.add_paragraph("")

    nome = resume_data.get("nome") or "(nome não informado)"
    doc.add_heading(nome, level=0)

    contato = " | ".join(filter(None, [
        resume_data.get("email", ""), resume_data.get("telefone", ""),
        resume_data.get("linkedin", ""), resume_data.get("cidade", ""),
    ]))
    if contato:
        p = doc.add_paragraph(contato)
        p.runs[0].font.size = Pt(10)

    if resume_data.get("resumo_profissional"):
        doc.add_heading("Resumo", level=1)
        doc.add_paragraph(resume_data["resumo_profissional"])

    if resume_data.get("experiencias"):
        doc.add_heading("Experiência profissional", level=1)
        for exp in resume_data["experiencias"]:
            titulo = f"{exp.get('cargo', '')} — {exp.get('empresa', '')}".strip(" —")
            p = doc.add_paragraph()
            run = p.add_run(titulo)
            run.bold = True
            if exp.get("periodo"):
                p.add_run(f"  ({exp['periodo']})").italic = True
            for ponto in exp.get("pontos", []):
                if ponto:
                    doc.add_paragraph(ponto, style="List Bullet")

    if resume_data.get("formacao"):
        doc.add_heading("Formação", level=1)
        for f in resume_data["formacao"]:
            linha = f"{f.get('curso', '')} — {f.get('instituicao', '')}".strip(" —")
            if f.get("periodo"):
                linha += f" ({f['periodo']})"
            doc.add_paragraph(linha, style="List Bullet")

    if resume_data.get("habilidades"):
        doc.add_heading("Habilidades", level=1)
        doc.add_paragraph(", ".join(resume_data["habilidades"]))

    if resume_data.get("certificacoes"):
        doc.add_heading("Certificações", level=1)
        for c in resume_data["certificacoes"]:
            doc.add_paragraph(c, style="List Bullet")

    doc.save(path)
    logger.info("Currículo adaptado salvo em %s (%d aviso(s))", path, len(avisos))
    return path


def generate_adapted_resume_and_save(api_key: str, resume_text: str, job: dict) -> tuple:
    """
    Gera o currículo adaptado, checa indícios de invenção e já salva em .docx.
    Retorna (caminho_do_arquivo, lista_de_avisos). Se houver avisos, SEMPRE
    mostre-os ao usuário além de deixá-los no topo do próprio arquivo.
    """
    resume_data = generate_adapted_resume(api_key, resume_text, job)
    avisos = _checar_fabricacao(resume_data, resume_text)
    path = save_resume_as_docx(job, resume_data, avisos)
    return path, avisos
