"""
Interface gráfica principal: escolher um perfil pronto (ou editar os
filtros), clicar em "Buscar vagas" e abrir a planilha. Vira o BuscaVagas.exe
(ver build_exe.bat).
"""

import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

# Com --windowed não existe console: evita erro se algo tentar imprimir
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import config
import database
import export_xlsx
import pipeline
from utils import open_file, parse_list, parse_lines

SITE_LABELS = {"indeed": "Indeed", "linkedin": "LinkedIn", "glassdoor": "Glassdoor"}
PERSONALIZADO = "— Meus filtros (já salvos) —"


class QueueLogHandler(logging.Handler):
    """Encaminha as mensagens de log do programa para a caixa de texto da janela."""

    def __init__(self, q: queue.Queue):
        super().__init__(level=logging.INFO)
        self.q = q
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record):
        if record.name.startswith("buscavagas") or record.levelno >= logging.WARNING:
            self.q.put(("log", self.format(record)))


def _companion_app_path():
    """Caminho do app de candidatura assistida, se existir ao lado deste programa."""
    exe = os.path.join(config.BASE_DIR, "CandidatarVagas.exe")
    if os.path.exists(exe):
        return [exe]
    script = os.path.join(config.BASE_DIR, "candidatar_app.py")
    if os.path.exists(script):
        return [sys.executable, script]
    return None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Busca de Vagas  (v{config.VERSION})")
        self.geometry("760x780")
        self.minsize(700, 680)

        self.presets = config.list_presets()
        self.filters = config.load_filters()
        self.q = queue.Queue()
        self._setup_logging()
        self._build()
        self._fill_form()
        self._poll_id = self.after(150, self._poll)

    # ---------------------------------------------------------------- logging
    def _setup_logging(self):
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        file_handler = logging.FileHandler(config.LOG_PATH, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(file_handler)
        root.addHandler(QueueLogHandler(self.q))

    # ------------------------------------------------------------------- tela
    def _build(self):
        pad = {"padx": 10, "pady": 4}
        main = ttk.Frame(self, padding=10)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        ttk.Label(
            main, wraplength=720, justify="left",
            text=("1) Se quiser, escolha um perfil pronto abaixo.  2) Confira a cidade e as "
                  "palavras de busca.  3) Clique em \"Buscar vagas\" e aguarde alguns minutos.  "
                  "4) Abra a planilha: marque \"Situação\" (Candidatei/Recusei) e, se quiser ajuda "
                  "para preencher o formulário da vaga, marque \"Sim\" em \"Auto-preencher\"."),
        ).grid(row=0, column=0, sticky="w", **pad)

        # --------------------------------------------------- perfil pronto
        preset_row = ttk.Frame(main)
        preset_row.grid(row=1, column=0, sticky="ew", **pad)
        ttk.Label(preset_row, text="Perfil pronto:").pack(side="left")
        self.var_preset = tk.StringVar(value=PERSONALIZADO)
        values = [PERSONALIZADO] + list(self.presets.keys())
        combo = ttk.Combobox(preset_row, textvariable=self.var_preset, values=values,
                              state="readonly", width=40)
        combo.pack(side="left", padx=8)
        combo.bind("<<ComboboxSelected>>", self._on_preset_selected)

        # --------------------------------------------------------- o básico
        box = ttk.LabelFrame(main, text=" O que buscar ", padding=8)
        box.grid(row=2, column=0, sticky="ew", **pad)
        box.columnconfigure(0, weight=1)

        self.var_busca = tk.StringVar()
        self.var_home = tk.BooleanVar()
        self.var_dias = tk.StringVar()
        self.var_alcance = tk.StringVar()
        self.var_minimo = tk.StringVar()
        self.var_exige_forte = tk.BooleanVar()

        ttk.Label(box, text="Palavras para buscar nos sites (separe por vírgula). "
                            "Ex.: enfermeiro, enfermeira").grid(row=0, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.var_busca).grid(row=1, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(box, wraplength=700, justify="left",
                  text="Cidades aceitas — uma por linha, no formato \"Cidade, UF\". Só entram vagas "
                       "dessas cidades (a primeira também é o centro da busca nos sites). Uma linha só "
                       "com a sigla (ex.: DF) aceita a região inteira.").grid(row=2, column=0, sticky="w")
        self.txt_cidades = tk.Text(box, height=4, wrap="word")
        self.txt_cidades.grid(row=3, column=0, sticky="ew", pady=(0, 6))

        row = ttk.Frame(box)
        row.grid(row=4, column=0, sticky="w", pady=2)
        ttk.Label(row, text="Alcance da busca:").pack(side="left")
        ttk.Spinbox(row, from_=10, to=200, increment=10, width=5, textvariable=self.var_alcance).pack(
            side="left", padx=6)
        ttk.Label(row, text="km   |   Vagas publicadas nos últimos").pack(side="left")
        ttk.Spinbox(row, from_=1, to=30, width=4, textvariable=self.var_dias).pack(side="left", padx=6)
        ttk.Label(row, text="dias").pack(side="left")

        ttk.Checkbutton(
            box, variable=self.var_home,
            text="Aceitar também vagas de QUALQUER cidade do Brasil se forem home office / remoto",
        ).grid(row=5, column=0, sticky="w", pady=4)

        row = ttk.Frame(box)
        row.grid(row=6, column=0, sticky="w", pady=2)
        ttk.Label(row, text="Sites:").pack(side="left")
        self.var_sites = {}
        for key, label in SITE_LABELS.items():
            self.var_sites[key] = tk.BooleanVar()
            ttk.Checkbutton(row, text=label, variable=self.var_sites[key]).pack(side="left", padx=8)

        # ------------------------------------------------------- avançado
        self.var_show_advanced = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            main, variable=self.var_show_advanced, text="Mostrar opções avançadas (palavras que "
            "confirmam/descartam uma vaga)", command=self._toggle_advanced,
        ).grid(row=3, column=0, sticky="w", padx=10)

        self.box2 = ttk.LabelFrame(main, text=" Filtros da descrição (avançado) ", padding=8)
        self.box2.columnconfigure(0, weight=1)

        ttk.Label(self.box2, text="Palavras FORTES — qualquer uma já indica que é a vaga certa "
                                   "(ex.: python, enfermagem, coren):").grid(row=0, column=0, sticky="w")
        self.txt_fortes = tk.Text(self.box2, height=3, wrap="word")
        self.txt_fortes.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        ttk.Label(self.box2, text="Palavras FRACAS — ajudam, mas sozinhas não bastam "
                                   "(ex.: desenvolver, analisar, atender):").grid(row=2, column=0, sticky="w")
        self.txt_fracos = tk.Text(self.box2, height=2, wrap="word")
        self.txt_fracos.grid(row=3, column=0, sticky="ew", pady=(0, 6))

        row = ttk.Frame(self.box2)
        row.grid(row=4, column=0, sticky="w", pady=2)
        ttk.Label(row, text="Quantidade mínima de palavras (fortes + fracas) na vaga:").pack(side="left")
        ttk.Spinbox(row, from_=1, to=10, width=4, textvariable=self.var_minimo).pack(side="left", padx=6)
        ttk.Checkbutton(
            self.box2, variable=self.var_exige_forte,
            text="Exigir pelo menos uma palavra FORTE (recomendado — sem isso, vagas genéricas passam)",
        ).grid(row=5, column=0, sticky="w", pady=2)

        ttk.Label(self.box2, text="NÃO mostrar vagas cujo TÍTULO tenha qualquer uma destas palavras "
                                   "(ex.: estagi, senior, sr):").grid(row=6, column=0, sticky="w", pady=(6, 0))
        self.txt_proibidos_titulo = tk.Text(self.box2, height=3, wrap="word")
        self.txt_proibidos_titulo.grid(row=7, column=0, sticky="ew", pady=(0, 4))

        ttk.Label(self.box2, text="NÃO mostrar vagas que tenham qualquer uma destas palavras no título "
                                   "OU na descrição (use pouco):").grid(row=9, column=0, sticky="w", pady=(6, 0))
        self.txt_proibidos = tk.Text(self.box2, height=2, wrap="word")
        self.txt_proibidos.grid(row=10, column=0, sticky="ew", pady=(0, 4))

        ttk.Label(
            self.box2, foreground="#666666", wraplength=700, justify="left",
            text=("Dica: escreva só o começo da palavra para pegar as variações. Ex.: \"enfermag\" acha "
                  "enfermagem. Siglas de até 3 letras (sr, upa, sql) só contam como palavra inteira. "
                  "Depois de uma busca, confira a aba \"Descartadas\" da planilha para ver o que foi "
                  "removido e por quê."),
        ).grid(row=11, column=0, sticky="w")

        # ---------------------------------------------------------- botões
        buttons = ttk.Frame(main)
        buttons.grid(row=5, column=0, sticky="ew", **pad)
        self.btn_run = ttk.Button(buttons, text="🔍  Buscar vagas", command=self._on_run)
        self.btn_run.pack(side="left", padx=(0, 8), ipadx=10, ipady=4)
        ttk.Button(buttons, text="Salvar filtros", command=self._on_save).pack(side="left", padx=4)
        ttk.Button(buttons, text="Abrir planilha", command=self._on_open).pack(side="left", padx=4)
        ttk.Button(buttons, text="📨  Candidatar nas vagas marcadas",
                   command=self._on_open_companion).pack(side="left", padx=4)

        self.log = scrolledtext.ScrolledText(main, height=9, state="disabled", wrap="word")
        self.log.grid(row=6, column=0, sticky="nsew", **pad)
        main.rowconfigure(6, weight=1)

    def _toggle_advanced(self):
        if self.var_show_advanced.get():
            self.box2.grid(row=4, column=0, sticky="ew", padx=10, pady=4)
        else:
            self.box2.grid_remove()

    # ------------------------------------------------------- filtros <-> tela
    def _fill_form(self):
        f = self.filters
        self.var_busca.set(", ".join(f["termos_busca"]))
        self.txt_cidades.delete("1.0", "end")
        self.txt_cidades.insert("1.0", "\n".join(f.get("cidades", [])))
        self.var_alcance.set(str(f.get("alcance_km", 80)))
        self.var_home.set(bool(f.get("aceitar_home_office_todo_brasil")))
        self.var_dias.set(str(f["dias"]))
        for key, var in self.var_sites.items():
            var.set(key in f["sites"])
        self.txt_fortes.delete("1.0", "end")
        self.txt_fortes.insert("1.0", ", ".join(f.get("termos_fortes", [])))
        self.txt_fracos.delete("1.0", "end")
        self.txt_fracos.insert("1.0", ", ".join(f.get("termos_fracos", [])))
        self.var_minimo.set(str(f.get("minimo_de_termos", 2)))
        self.var_exige_forte.set(bool(f.get("exigir_termo_forte", True)))
        self.txt_proibidos_titulo.delete("1.0", "end")
        self.txt_proibidos_titulo.insert("1.0", ", ".join(f.get("termos_proibidos_titulo", [])))
        self.txt_proibidos.delete("1.0", "end")
        self.txt_proibidos.insert("1.0", ", ".join(f.get("termos_proibidos", [])))

    def _on_preset_selected(self, _event=None):
        nome = self.var_preset.get()
        if nome == PERSONALIZADO:
            return
        try:
            self.filters = config.load_preset(self.presets[nome])
        except (OSError, ValueError) as exc:
            messagebox.showerror("Erro ao carregar perfil", str(exc))
            return
        self._fill_form()

    def _collect(self) -> dict:
        f = dict(self.filters)  # preserva chaves avançadas que não aparecem na tela
        f["termos_busca"] = parse_list(self.var_busca.get())
        if not f["termos_busca"]:
            raise ValueError('Preencha o campo "Palavras para buscar".')
        f["cidades"] = parse_lines(self.txt_cidades.get("1.0", "end"))
        if not f["cidades"]:
            raise ValueError('Preencha pelo menos uma cidade em "Cidades aceitas".')
        try:
            f["alcance_km"] = max(5, min(300, int(self.var_alcance.get())))
        except ValueError:
            raise ValueError("O alcance precisa ser um número (ex.: 80).")
        f["aceitar_home_office_todo_brasil"] = bool(self.var_home.get())
        try:
            f["dias"] = max(1, min(30, int(self.var_dias.get())))
        except ValueError:
            raise ValueError("O número de dias precisa ser um número (ex.: 7).")
        f["sites"] = [k for k, v in self.var_sites.items() if v.get()]
        if not f["sites"]:
            raise ValueError("Marque pelo menos um site.")
        f["termos_fortes"] = parse_list(self.txt_fortes.get("1.0", "end"))
        f["termos_fracos"] = parse_list(self.txt_fracos.get("1.0", "end"))
        if not f["termos_fortes"] and not f["termos_fracos"]:
            raise ValueError('Preencha pelo menos uma palavra em "Palavras FORTES" ou "Palavras FRACAS" '
                              '(nas opções avançadas).')
        try:
            f["minimo_de_termos"] = max(1, min(10, int(self.var_minimo.get())))
        except ValueError:
            raise ValueError("A quantidade mínima de palavras precisa ser um número (ex.: 2).")
        f["exigir_termo_forte"] = bool(self.var_exige_forte.get())
        f["termos_proibidos_titulo"] = parse_list(self.txt_proibidos_titulo.get("1.0", "end"))
        f["termos_proibidos"] = parse_list(self.txt_proibidos.get("1.0", "end"))
        f["versao_filtros"] = config.FILTERS_VERSION
        return f

    # ------------------------------------------------------------------ ações
    def _on_save(self):
        try:
            self.filters = self._collect()
        except ValueError as exc:
            messagebox.showwarning("Atenção", str(exc))
            return
        config.save_filters(self.filters)
        self._append("Filtros salvos.")

    def _on_open(self):
        if not os.path.exists(config.XLSX_PATH):
            messagebox.showinfo("Planilha", 'Ainda não existe planilha. Clique em "Buscar vagas" primeiro.')
            return
        # Regera com o estado atual (inclui o que o CandidatarVagas marcou),
        # depois de ler o que já estava marcado na planilha.
        try:
            database.init_db()
            path = export_xlsx.sync_spreadsheet(days=int(self.filters.get("dias", 7)))
        except Exception as exc:
            logging.getLogger("buscavagas").warning("Não consegui atualizar a planilha: %s", exc)
            path = config.XLSX_PATH
        open_file(path)

    def _on_open_companion(self):
        cmd = _companion_app_path()
        if not cmd:
            messagebox.showinfo(
                "Candidatura assistida",
                "Não encontrei o programa CandidatarVagas.exe nesta pasta.\n\n"
                "Ele é um programa separado (porque precisa baixar um navegador na primeira vez). "
                "Copie-o para esta mesma pasta, ou veja o COMO_USAR.txt para gerá-lo.")
            return
        try:
            subprocess.Popen(cmd, cwd=config.BASE_DIR)
        except OSError as exc:
            messagebox.showerror("Não consegui abrir", str(exc))

    def _on_run(self):
        try:
            self.filters = self._collect()
        except ValueError as exc:
            messagebox.showwarning("Atenção", str(exc))
            return
        config.save_filters(self.filters)
        self.btn_run.config(state="disabled", text="Buscando... aguarde")
        threading.Thread(target=self._worker, args=(self.filters,), daemon=True).start()

    def _worker(self, filters):
        try:
            self.q.put(("done", pipeline.run_search(filters)))
        except Exception as exc:  # qualquer erro vira mensagem amigável na tela
            logging.getLogger("buscavagas").exception("Erro durante a busca")
            self.q.put(("error", str(exc)))

    # ---------------------------------------------------------- fila -> tela
    def _append(self, text: str):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append(payload)
                elif kind == "done":
                    self._finish(payload)
                elif kind == "error":
                    self.btn_run.config(state="normal", text="🔍  Buscar vagas")
                    messagebox.showerror(
                        "Ocorreu um erro",
                        f"{payload}\n\nDetalhes no arquivo buscavagas.log (na pasta do programa).")
        except queue.Empty:
            pass
        self._poll_id = self.after(150, self._poll)

    def destroy(self):
        try:
            self.after_cancel(self._poll_id)
        except Exception:
            pass
        super().destroy()

    def _finish(self, result: dict):
        self.btn_run.config(state="normal", text="🔍  Buscar vagas")
        msg = (f"Busca concluída!\n\nVagas novas: {result['novas']}\n"
               f"(aprovadas pelo filtro: {result['aprovadas']} de {result['coletadas']} coletadas)\n\n"
               "Abrir a planilha agora?")
        if messagebox.askyesno("Pronto!", msg):
            open_file(result["planilha"])


if __name__ == "__main__":
    App().mainloop()
