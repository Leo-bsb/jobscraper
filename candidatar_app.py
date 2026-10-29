"""
Interface gráfica da candidatura assistida. Vira o CandidatarVagas.exe
(ver build_exe.bat) — um programa separado do BuscaVagas.exe porque precisa
baixar um navegador (~150 MB) na primeira vez.

Como funciona por baixo: a automação do navegador (Playwright) roda na
MESMA thread da janela (é uma exigência do Playwright). Para a janela não
"travar" enquanto espera você revisar uma vaga, em vez de usar threads nós
mesmos "bombeamos" a fila de eventos do Tkinter (self.update()) dentro de um
laço de espera — por isso os botões continuam clicáveis mesmo durante a
automação. Veja _wait_for_click().
"""

import logging
import os
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import apply_core
import config
import database
import export_xlsx
from utils import open_file

PT_SAFETY_NOTE = (
    "Este programa abre, uma de cada vez, as vagas marcadas com \"Sim\" na coluna "
    "Auto-preencher da planilha. Quando possível, preenche nome, e-mail, telefone e "
    "currículo — mas NUNCA clica em enviar: você revisa e decide na hora."
)

CARTA_INFO = (
    "Opcional: gera uma carta de apresentação personalizada para a vaga atual, usando "
    "seu currículo em PDF. Pede uma chave gratuita do Google AI Studio na primeira vez "
    "(fica salva — não pede de novo). O texto do currículo e da vaga é enviado ao Google "
    "para gerar a carta."
)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Candidatar nas Vagas  (v{config.VERSION})")
        self.geometry("720x620")
        self.minsize(660, 560)

        database.init_db()
        self.profile = config.load_profile()
        self._advance_choice = None
        self._abort = False
        self._running = False
        self._current_job = None
        self._resume_cache_path = None
        self._resume_cache_text = None

        self._build()
        self._refresh_count()

    # ------------------------------------------------------------------- tela
    def _build(self):
        pad = {"padx": 12, "pady": 6}
        main = ttk.Frame(self, padding=10)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        ttk.Label(main, text=PT_SAFETY_NOTE, wraplength=660, justify="left",
                  foreground="#444444").grid(row=0, column=0, sticky="w", **pad)

        box = ttk.LabelFrame(main, text=" Seus dados (usados para preencher as candidaturas) ",
                              padding=10)
        box.grid(row=1, column=0, sticky="ew", **pad)
        box.columnconfigure(1, weight=1)

        self.var_nome = tk.StringVar(value=self.profile.get("nome_completo", ""))
        self.var_email = tk.StringVar(value=self.profile.get("email", ""))
        self.var_tel = tk.StringVar(value=self.profile.get("telefone", ""))
        self.var_cv = tk.StringVar(value=self.profile.get("curriculo_pdf", ""))
        self.var_api_key = tk.StringVar(value=self.profile.get("google_api_key", ""))

        self._row(box, 0, "Nome completo:", self.var_nome)
        self._row(box, 1, "E-mail:", self.var_email)
        self._row(box, 2, "Telefone (com DDD):", self.var_tel)

        ttk.Label(box, text="Currículo (PDF):").grid(row=3, column=0, sticky="w", pady=2)
        cv_row = ttk.Frame(box)
        cv_row.grid(row=3, column=1, sticky="ew", padx=(8, 0))
        cv_row.columnconfigure(0, weight=1)
        ttk.Entry(cv_row, textvariable=self.var_cv).grid(row=0, column=0, sticky="ew")
        ttk.Button(cv_row, text="Procurar...", command=self._choose_resume).grid(row=0, column=1, padx=(6, 0))

        ttk.Label(box, text="Chave Gemini (opcional, p/ carta):").grid(row=4, column=0, sticky="w", pady=2)
        key_row = ttk.Frame(box)
        key_row.grid(row=4, column=1, sticky="ew", padx=(8, 0))
        key_row.columnconfigure(0, weight=1)
        ttk.Entry(key_row, textvariable=self.var_api_key, show="•").grid(row=0, column=0, sticky="ew")
        ttk.Button(key_row, text="Obter chave grátis",
                   command=lambda: self._open_url("https://aistudio.google.com/apikey")
                   ).grid(row=0, column=1, padx=(6, 0))

        ttk.Button(box, text="💾  Salvar meus dados", command=self._on_save_profile
                   ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

        status_row = ttk.Frame(main)
        status_row.grid(row=2, column=0, sticky="ew", **pad)
        self.lbl_status = ttk.Label(status_row, text="", foreground="#444444")
        self.lbl_status.pack(side="left")

        action_row = ttk.Frame(main)
        action_row.grid(row=3, column=0, sticky="ew", **pad)
        self.btn_start = ttk.Button(action_row, text="🚀  Iniciar candidaturas", command=self._on_start)
        self.btn_start.pack(side="left", ipadx=8, ipady=3)
        self.btn_refresh = ttk.Button(action_row, text="Atualizar lista", command=self._refresh_count)
        self.btn_refresh.pack(side="left", padx=8)

        # Painel que só aparece DURANTE a revisão de uma vaga
        self.flow = ttk.LabelFrame(main, text=" Vaga atual ", padding=10)
        self.lbl_job = ttk.Label(self.flow, text="", wraplength=620, justify="left", font=("", 10, "bold"))
        self.lbl_job.pack(anchor="w")
        self.lbl_job_info = ttk.Label(self.flow, text="", wraplength=620, justify="left")
        self.lbl_job_info.pack(anchor="w", pady=(2, 8))
        flow_buttons = ttk.Frame(self.flow)
        flow_buttons.pack(anchor="w")
        self.btn_marcar = ttk.Button(flow_buttons, text="✅  Já enviei / candidatei — próxima vaga",
                                      command=lambda: self._choose("marcar"))
        self.btn_marcar.pack(side="left", padx=(0, 8))
        self.btn_pular = ttk.Button(flow_buttons, text="⏭️  Pular esta vaga",
                                     command=lambda: self._choose("pular"))
        self.btn_pular.pack(side="left", padx=8)
        self.btn_parar = ttk.Button(flow_buttons, text="🛑  Parar tudo",
                                     command=self._on_abort)
        self.btn_parar.pack(side="left", padx=8)
        self.btn_carta = ttk.Button(flow_buttons, text="✍️  Gerar carta personalizada",
                                     command=self._on_generate_letter)
        self.btn_carta.pack(side="left", padx=8)
        self.btn_curriculo = ttk.Button(flow_buttons, text="📄  Gerar currículo adaptado",
                                         command=self._on_generate_resume)
        self.btn_curriculo.pack(side="left", padx=8)

        self.log = scrolledtext.ScrolledText(main, height=12, state="disabled", wrap="word")
        self.log.grid(row=5, column=0, sticky="nsew", **pad)
        main.rowconfigure(5, weight=1)

    @staticmethod
    def _row(parent, row, label, var):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)

    # ------------------------------------------------------------------ dados
    def _choose_resume(self):
        path = filedialog.askopenfilename(title="Escolha seu currículo",
                                           filetypes=[("PDF", "*.pdf"), ("Todos os arquivos", "*.*")])
        if path:
            self.var_cv.set(path)

    def _collect_profile(self) -> dict:
        return {
            "nome_completo": self.var_nome.get().strip(),
            "email": self.var_email.get().strip(),
            "telefone": self.var_tel.get().strip(),
            "curriculo_pdf": self.var_cv.get().strip(),
            "google_api_key": self.var_api_key.get().strip(),
        }

    @staticmethod
    def _open_url(url: str):
        import webbrowser
        webbrowser.open(url)

    def _on_save_profile(self):
        self.profile = self._collect_profile()
        config.save_profile(self.profile)
        messagebox.showinfo("Pronto", "Seus dados foram salvos.")

    def _read_marks_from_spreadsheet(self):
        """Traz para o banco o que foi marcado na planilha (ex.: Auto-preencher = Sim)."""
        try:
            export_xlsx.import_statuses()
        except Exception as exc:  # planilha corrompida/aberta: segue com o que o banco já tem
            logging.getLogger("buscavagas.candidatar").warning("Não li a planilha: %s", exc)

    def _refresh_count(self):
        self._read_marks_from_spreadsheet()
        try:
            n = len(database.get_marked_for_apply())
        except Exception:
            n = 0
        if n == 0:
            self.lbl_status.config(
                text='Nenhuma vaga marcada. Na planilha, marque "Sim" na coluna '
                     'Auto-preencher, salve e feche o Excel — depois clique em "Atualizar lista".')
        else:
            self.lbl_status.config(text=f"{n} vaga(s) marcada(s), prontas para revisar.")

    # ---------------------------------------------------------------- log/UI
    def _log(self, text: str):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")
        self.update()

    def _choose(self, opcao: str):
        self._advance_choice = opcao

    def _on_abort(self):
        self._abort = True
        self._advance_choice = "pular"  # libera o laço de espera atual, se houver

    def _get_resume_text(self, pdf_path: str):
        """Extrai o texto do currículo, reaproveitando se o caminho não mudou."""
        import resume_adapter
        if self._resume_cache_path != pdf_path:
            self._resume_cache_text = resume_adapter.extract_resume_text(pdf_path)
            self._resume_cache_path = pdf_path
        return self._resume_cache_text

    def _on_generate_letter(self):
        job = self._current_job
        if not job:
            return
        api_key = self.var_api_key.get().strip()
        cv_path = self.var_cv.get().strip()
        if not api_key:
            messagebox.showwarning(
                "Falta a chave",
                'Preencha "Chave Gemini" (botão "Obter chave grátis" ao lado) e clique em '
                '"Salvar meus dados".')
            return
        if not cv_path or not os.path.exists(cv_path):
            messagebox.showwarning("Falta o currículo", "Escolha o arquivo do seu currículo em PDF.")
            return

        self.profile = self._collect_profile()
        config.save_profile(self.profile)

        self.btn_carta.config(state="disabled", text="Gerando carta...")
        self.update()
        try:
            import resume_adapter
            self._log(f"\nGerando carta personalizada para {job['titulo']} ({job['empresa']})...")
            self.update()
            texto_cv = self._get_resume_text(cv_path)
            resultado = resume_adapter.generate(api_key, texto_cv, job)
            path = resume_adapter.save_as_docx(job, resultado["carta"], resultado["sugestoes_curriculo"])
            self._log(f"Carta salva em: {path}")
            open_file(path)
        except ImportError:
            messagebox.showerror(
                "Faltam bibliotecas",
                "Esse recurso precisa de pacotes extras. Peça para instalar:\n"
                "pip install -U google-genai pypdf python-docx")
        except Exception as exc:
            self._log(f"Não consegui gerar a carta: {exc}")
            messagebox.showerror("Não consegui gerar a carta", str(exc))
        finally:
            self.btn_carta.config(state="normal", text="✍️  Gerar carta personalizada")

    def _on_generate_resume(self):
        job = self._current_job
        if not job:
            return
        api_key = self.var_api_key.get().strip()
        cv_path = self.var_cv.get().strip()
        if not api_key:
            messagebox.showwarning(
                "Falta a chave",
                'Preencha "Chave Gemini" (botão "Obter chave grátis" ao lado) e clique em '
                '"Salvar meus dados".')
            return
        if not cv_path or not os.path.exists(cv_path):
            messagebox.showwarning("Falta o currículo", "Escolha o arquivo do seu currículo em PDF.")
            return

        self.profile = self._collect_profile()
        config.save_profile(self.profile)

        self.btn_curriculo.config(state="disabled", text="Gerando currículo...")
        self.update()
        try:
            import resume_adapter
            self._log(f"\nGerando currículo adaptado para {job['titulo']} ({job['empresa']})...")
            self.update()
            texto_cv = self._get_resume_text(cv_path)
            path, avisos = resume_adapter.generate_adapted_resume_and_save(api_key, texto_cv, job)
            self._log(f"Currículo adaptado salvo em: {path}")
            if avisos:
                self._log("⚠ ATENÇÃO — confira antes de usar:")
                for a in avisos:
                    self._log(f"   • {a}")
                messagebox.showwarning(
                    "Confira antes de usar",
                    "O currículo foi gerado, mas uma ou mais informações não foram encontradas "
                    "no seu currículo original (destacadas em vermelho no topo do arquivo). "
                    "Isso pode indicar um erro do modelo — revise com atenção antes de enviar.\n\n"
                    + "\n".join(f"• {a}" for a in avisos))
            open_file(path)
        except ImportError:
            messagebox.showerror(
                "Faltam bibliotecas",
                "Esse recurso precisa de pacotes extras. Peça para instalar:\n"
                "pip install -U google-genai pypdf python-docx")
        except Exception as exc:
            self._log(f"Não consegui gerar o currículo: {exc}")
            messagebox.showerror("Não consegui gerar o currículo", str(exc))
        finally:
            self.btn_curriculo.config(state="normal", text="📄  Gerar currículo adaptado")

    def _wait_for_click(self):
        """
        Mantém a janela respondendo (botões clicáveis) enquanto espera você
        decidir o que fazer com a vaga atual — sem precisar de uma thread
        separada (o Playwright precisa continuar na mesma thread da janela).

        A escolha NÃO é zerada aqui (e sim no início de cada vaga): um clique
        feito enquanto a página ainda carregava precisa continuar valendo.
        """
        while self._advance_choice is None and not self._abort:
            self.update()
            time.sleep(0.05)
        return self._advance_choice or "pular"

    # ------------------------------------------------------------------ fluxo
    def _on_start(self):
        self.profile = self._collect_profile()
        if not self.profile["nome_completo"] or not self.profile["email"]:
            messagebox.showwarning("Faltam dados", "Preencha pelo menos nome completo e e-mail.")
            return
        config.save_profile(self.profile)

        self._read_marks_from_spreadsheet()
        jobs = database.get_marked_for_apply()
        if not jobs:
            messagebox.showinfo(
                "Nada para fazer",
                'Nenhuma vaga está marcada com "Sim" na coluna Auto-preencher da planilha.')
            return

        self._abort = False
        self._running = True
        self.btn_start.config(state="disabled")
        self.btn_marcar.config(state="disabled")
        self.btn_pular.config(state="disabled")
        self.flow.grid(row=4, column=0, sticky="ew", padx=12, pady=6)
        try:
            self._run_flow(jobs)
        finally:
            self.flow.grid_remove()
            self.btn_start.config(state="normal")
            self._running = False
            self._update_spreadsheet()
            self._refresh_count()

    def _update_spreadsheet(self):
        """Regera a planilha para ela já mostrar o que você marcou aqui."""
        try:
            path = export_xlsx.sync_spreadsheet(days=int(config.load_filters().get("dias", 7)))
            self._log(f"Planilha atualizada: {path}")
        except Exception as exc:
            self._log(f"Não consegui atualizar a planilha agora ({exc}). "
                      "Ela será atualizada na próxima busca — suas marcações estão salvas.")

    def _run_flow(self, jobs):
        if not apply_core.browser_is_ready():
            self._log("Preparando o navegador pela primeira vez (pode levar 1-2 minutos)...")
            self.update()
            if not apply_core.install_browser(on_progress=self._log):
                messagebox.showerror(
                    "Não consegui preparar o navegador",
                    "Tente novamente com internet disponível, ou peça ajuda para instalar "
                    "manualmente (pip install playwright && playwright install chromium).")
                return

        from playwright.sync_api import sync_playwright

        self._log(f"{len(jobs)} vaga(s) para revisar.")
        with sync_playwright() as p:
            context = apply_core.new_browser_context(p)
            try:
                for i, job in enumerate(jobs, start=1):
                    if self._abort:
                        self._log("Parado por você.")
                        break

                    self._current_job = job
                    self._advance_choice = None
                    self.lbl_job.config(text=f"Vaga {i} de {len(jobs)}: {job['titulo']}")
                    self.lbl_job_info.config(text=f"Empresa: {job['empresa']}  |  {job['localizacao']}")
                    self.btn_marcar.config(state="normal")
                    self.btn_pular.config(state="normal")
                    self.btn_carta.config(state="normal")
                    self.btn_curriculo.config(state="normal")
                    self._log(f"\n--- Vaga {i}/{len(jobs)}: {job['titulo']} ({job['empresa']}) ---")

                    r = apply_core.open_and_fill(context, job, self.profile)
                    if r["erro"]:
                        self._log(f"Não consegui abrir automaticamente ({r['erro']}). "
                                  "A aba ficou aberta para você preencher na mão.")
                    elif r["preencheu"]:
                        extra = " e anexei o currículo" if r["curriculo"] else ""
                        self._log(f"Preenchi {r['campos']} campo(s) de contato{extra}. "
                                  "Revise as perguntas da vaga e envie você mesmo no navegador.")
                    else:
                        self._log("Não é Candidatura Simplificada do Indeed — preencha manualmente "
                                  "na aba que abri.")

                    self._log("Quando terminar (enviar ou não), escolha uma opção abaixo.")
                    escolha = self._wait_for_click()

                    if escolha == "marcar":
                        database.apply_statuses({job["id"]: config.STATUS_CANDIDATEI})
                        self._log("Marcada como Candidatei.")
                    else:
                        self._log("Deixei como estava; marque na planilha se mudar de ideia.")

                    apply_core.close_pages(r)
                    self.btn_marcar.config(state="disabled")
                    self.btn_pular.config(state="disabled")
                    self.btn_carta.config(state="disabled")
                    self.btn_curriculo.config(state="disabled")
                    self._current_job = None
            finally:
                context.close()

        self._log("\nConcluído!")


if __name__ == "__main__":
    App().mainloop()
