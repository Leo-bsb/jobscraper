"""
Candidatura assistida (Indeed Easy Apply) — versão linha de comando.

Para quem prefere uma janela normal, use candidatar_app.py (ou o
CandidatarVagas.exe, se você já gerou o instalável) — ele faz a mesma coisa
com botões em vez de digitar no terminal.

O QUE ISTO FAZ / NÃO FAZ: ver apply_core.py (lógica compartilhada).

USO
    1. Preencha perfil.json (nome_completo, email, telefone, curriculo_pdf).
    2. Na planilha, marque "Sim" na coluna Auto-preencher das vagas
       desejadas, salve e FECHE o Excel.
    3. python applier.py
"""

import logging

import apply_core
import config
import database
import export_xlsx

logger = logging.getLogger("buscavagas.applier")


def run():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    database.init_db()

    profile = config.load_profile()
    if not profile.get("nome_completo") or not profile.get("email"):
        print(f"Preencha primeiro {config.PROFILE_PATH}\n"
              "(nome_completo, email, telefone, curriculo_pdf) e rode de novo.")
        return

    export_xlsx.import_statuses()  # traz as marcações "Sim" da planilha
    jobs = database.get_marked_for_apply()
    if not jobs:
        print('Nenhuma vaga marcada com "Auto-preencher = Sim" na planilha.\n'
              "Abra vagas_da_semana.xlsx, marque a coluna, salve e FECHE o Excel antes de rodar.")
        return

    if not apply_core.browser_is_ready():
        if not apply_core.install_browser(on_progress=print):
            print("Não consegui preparar o navegador. Rode manualmente: "
                  "pip install playwright  &&  playwright install chromium")
            return

    from playwright.sync_api import sync_playwright

    print(f"\n{len(jobs)} vaga(s) para revisar. Vou abrir uma de cada vez.")
    print("Em cada vaga: confira o preenchimento, responda as perguntas específicas e "
          "clique em ENVIAR você mesmo.\n")

    with sync_playwright() as p:
        context = apply_core.new_browser_context(p)
        try:
            for i, job in enumerate(jobs, start=1):
                print(f"--- Vaga {i}/{len(jobs)}: {job['titulo']} ({job['empresa']}) ---")
                r = apply_core.open_and_fill(context, job, profile)

                if r["erro"]:
                    print(f"   Não consegui abrir/preencher automaticamente ({r['erro']}).")
                    print("   A aba ficou aberta para você continuar na mão.")
                elif r["preencheu"]:
                    print(f"   Preenchi {r['campos']} campo(s) de contato"
                          + (" e anexei o currículo." if r["curriculo"] else "."))
                    print("   Revise as perguntas da vaga e envie você mesmo.")
                else:
                    print("   Não é Easy Apply do Indeed (ou não encontrei o botão): "
                          "preencha manualmente nesta aba.")

                input("   Pressione ENTER aqui depois de decidir (enviar ou pular)... ")
                resposta = input('   Marcar esta vaga como "Candidatei"? (s/n): ').strip().lower()
                if resposta.startswith("s"):
                    database.apply_statuses({job["id"]: config.STATUS_CANDIDATEI})
                    print("   Marcada como Candidatei.\n")
                else:
                    print("   Deixei como está; marque na planilha se mudar de ideia.\n")

                apply_core.close_pages(r)
        finally:
            context.close()

    path = export_xlsx.sync_spreadsheet(days=int(config.load_filters().get("dias", 7)))
    print(f"Concluído. Planilha atualizada: {path}")


if __name__ == "__main__":
    run()
