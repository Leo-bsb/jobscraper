"""
Lógica compartilhada da candidatura assistida (Indeed Easy Apply).
Usada tanto por applier.py (linha de comando) quanto por candidatar_app.py
(interface gráfica), para não duplicar a parte que mexe no navegador.

PRINCÍPIOS (não mude sem reler isto):
  - Nunca clica em enviar a candidatura.
  - Nunca responde perguntas de triagem específicas da vaga.
  - Só preenche campo que estiver vazio (não sobrescreve o que o site já
    preencheu sozinho, ex.: currículo salvo na conta do Indeed).
  - Fora do Indeed Easy Apply, só abre a aba — não tenta adivinhar formulários
    fora do padrão.
"""

import logging
import os
import re
import sys

import config

logger = logging.getLogger("buscavagas.apply_core")

# No .exe, guardamos o navegador numa pasta fixa ao lado do programa. Assim a
# instalação (install_browser) e o uso (new_browser_context) olham sempre para
# o mesmo lugar, sem depender de onde o Playwright empacotado procuraria.
if getattr(sys, "frozen", False):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                          os.path.join(config.BASE_DIR, "navegador_programa"))

# Botão que abre a candidatura no Indeed. Procuramos BOTÃO/LINK pelo nome
# acessível (não qualquer texto): "Candidatura simplificada" também aparece
# como selo informativo no anúncio, e clicar no selo não faz nada.
EASY_APPLY_NAME = re.compile(
    r"candidat(ar|e|ura)[- ]?se|candidatura simplificada|easy apply|apply now|candidatar agora",
    re.IGNORECASE,
)

# (rótulo do campo, como regex ancorada) -> como obter o valor a partir do perfil.
# Ancorar evita o erro clássico de "nome" casar com "Sobrenome".
_LABEL_END = r"\s*\*?\s*(\(.*\))?\s*$"
FIELD_MAP = [
    (re.compile(r"^\s*(nome completo|full name|your name)" + _LABEL_END, re.I), "nome_completo"),
    (re.compile(r"^\s*(nome|primeiro nome|first name)" + _LABEL_END, re.I), "primeiro_nome"),
    (re.compile(r"^\s*(sobrenome|[uú]ltimo nome|last name)" + _LABEL_END, re.I), "sobrenome"),
    (re.compile(r"^\s*(e-?mail|endere[cç]o de e-?mail|email address)" + _LABEL_END, re.I), "email"),
    (re.compile(r"^\s*(telefone|celular|phone|phone number|n[uú]mero de telefone)" + _LABEL_END, re.I),
     "telefone"),
]


def _profile_value(profile: dict, key: str) -> str:
    nome = (profile.get("nome_completo") or "").split()
    if key == "primeiro_nome":
        return nome[0] if nome else ""
    if key == "sobrenome":
        return " ".join(nome[1:]) if len(nome) > 1 else ""
    return (profile.get(key) or "").strip()


def browser_is_ready() -> bool:
    """True se o navegador do Playwright já está baixado e pronto para uso."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


def install_browser(on_progress=None) -> bool:
    """
    Baixa o navegador do Playwright (Chromium), ~150 MB, só na primeira vez.

    Não usa "sys.executable -m playwright install" porque, dentro do .exe
    empacotado, sys.executable é o PRÓPRIO .exe (não um Python de verdade) —
    isso faria o comando falhar silenciosamente. Em vez disso, chamamos o
    instalador do Playwright diretamente, por dentro do processo atual.
    """
    if on_progress:
        on_progress("Baixando o navegador (só acontece uma vez, ~1-2 minutos)...")
    try:
        from playwright.__main__ import main as playwright_cli
    except ImportError:
        logger.error("O pacote 'playwright' não está instalado.")
        return False

    old_argv = sys.argv
    sys.argv = ["playwright", "install", "chromium"]
    try:
        playwright_cli()
    except SystemExit as exc:
        if exc.code not in (0, None):
            logger.error("Instalação do navegador terminou com código %s.", exc.code)
            return False
    except Exception as exc:
        logger.error("Falha ao instalar o navegador: %s", exc)
        return False
    finally:
        sys.argv = old_argv

    return browser_is_ready()


def fill_known_fields(page, profile: dict) -> int:
    """Preenche campos de contato reconhecidos pelo rótulo. Retorna quantos preencheu."""
    filled = 0
    for label_regex, profile_key in FIELD_MAP:
        value = _profile_value(profile, profile_key)
        if not value:
            continue
        try:
            field = page.get_by_label(label_regex)
            if field.count() == 0:
                continue
            current = (field.first.input_value() or "").strip()
            if not current:
                field.first.fill(value)
                filled += 1
        except Exception:
            continue
    return filled


def try_upload_resume(page, resume_path: str) -> bool:
    if not resume_path:
        return False
    try:
        file_input = page.locator("input[type='file']").first
        if file_input.count() > 0:
            file_input.set_input_files(resume_path)
            return True
    except Exception:
        pass
    return False


def click_easy_apply(page):
    """
    Clica no botão de candidatura. Retorna a página onde o formulário abriu
    (o Indeed às vezes abre o formulário numa ABA NOVA), ou None se não achou.
    """
    context = page.context
    for role in ("button", "link"):
        try:
            btn = page.get_by_role(role, name=EASY_APPLY_NAME)
            if btn.count() == 0:
                continue
            antes = set(context.pages)
            btn.first.click()
            page.wait_for_timeout(2500)
            novas = [p for p in context.pages if p not in antes]
            alvo = novas[-1] if novas else page
            try:
                alvo.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            return alvo
        except Exception:
            continue
    return None


def open_and_fill(context, job: dict, profile: dict) -> dict:
    """
    Abre a vaga numa aba nova e, se possível, preenche automaticamente.
    Retorna {"page": <aba>, "pages": [abas abertas], "preencheu": bool, "campos": int,
    "curriculo": bool, "erro": str|None}. As abas ficam abertas; quem chamou
    fecha depois com close_pages(resultado).
    """
    page = context.new_page()
    resultado = {"page": page, "pages": [page], "preencheu": False, "campos": 0,
                 "curriculo": False, "erro": None}
    try:
        page.goto(job["link"], timeout=30000)
        page.wait_for_timeout(2500)
        if job.get("site_origem") == "indeed":
            form = click_easy_apply(page)
            if form is not None:
                if form is not page:
                    resultado["pages"].append(form)
                    resultado["page"] = form
                resultado["campos"] = fill_known_fields(form, profile)
                resultado["curriculo"] = try_upload_resume(form, profile.get("curriculo_pdf", ""))
                resultado["preencheu"] = True
    except Exception as exc:
        resultado["erro"] = str(exc)
    return resultado


def close_pages(resultado: dict) -> None:
    for p in resultado.get("pages", [resultado.get("page")]):
        try:
            p.close()
        except Exception:
            pass


def new_browser_context(p):
    """Sessão persistente: você loga no Indeed uma vez, fica salvo para a próxima execução."""
    return p.chromium.launch_persistent_context(
        config.BROWSER_PROFILE_DIR, headless=False, args=["--start-maximized"],
        no_viewport=True,
    )
