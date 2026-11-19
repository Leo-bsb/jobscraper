# Limitações da validação, riscos residuais e pendências

Documento complementar a [`REVISAO_E_MELHORIAS.md`](REVISAO_E_MELHORIAS.md).
Registra o que **não** foi possível validar nesta máquina/ambiente, o que ficou
como risco residual e o que depende de uma decisão do mantenedor.

## 1. O que não foi validado (e por quê)

| Item | Por que não foi validado | Como validar depois |
|---|---|---|
| Coleta real em Indeed/LinkedIn/Glassdoor | Exige rede e provoca bloqueio/rate-limit; os testes não podem depender de sites de terceiros | `python main.py` numa máquina com `python-jobspy` instalado, com poucas consultas |
| Navegador (Playwright/Chromium) | Exigiria baixar ~150 MB, abrir janela e ter sessão logada no Indeed | `pip install playwright ; playwright install chromium`, depois `python applier.py` com uma vaga marcada |
| Gemini (carta/currículo) | Exige chave de API e envia dados pessoais a terceiros | `python candidatar_app.py` com uma chave própria, revisando o resultado |
| Build dos `.exe` (PyInstaller) | Só roda em Windows com o ambiente completo; o workflow faz isso no CI | Actions → *Gerar BuscaVagas.exe + CandidatarVagas.exe* → Run workflow |
| Aparência real no Microsoft Excel | Não há Excel instalado; validamos via `openpyxl` e XML (`data_type`, `quotePrefix`) | Abrir `vagas_da_semana.xlsx` e conferir que `=1+1` aparece como texto |
| Permissões `chmod 600` | Windows não tem POSIX; o teste é pulado (`skipIf`) | Rodar a suíte em Linux/macOS |
| Concorrência em carga real | Testado com 4 threads e ~80 inserções (WAL), não com uso simultâneo prolongado | Abrir BuscaVagas e CandidatarVagas juntos por alguns minutos |
| Interface Tkinter (renderização) | Ambiente sem display automatizável | Abrir `python app.py` e `python candidatar_app.py` manualmente |
| SMTP real | Exige credenciais | `JOBSCRAPER_SMTP_*=... python main.py --email` |

## 2. Ambiente usado na revisão

- Python 3.8.2 do sistema (com `openpyxl 3.1.5` e `pandas 2.0.3` via `--user`).
- Python 3.13.0 em venv temporário **fora do repositório**, com `jobspy 1.4.1`,
  `pandas 3.1.1`, `openpyxl`, `playwright`, `google-genai`, `python-docx`,
  `pypdf` e `coverage`.
- O venv ficou em `%TEMP%\opencode\venv-jobscraper` e **não** faz parte do
  projeto; pode ser apagado sem afetar o repositório.
- Observação: o venv acabou com `pandas 3.1.1`, mas `requirements.txt` fixa
  `pandas<3`. A suíte não depende da versão do pandas (usa stubs e não importa
  pandas); ainda assim, para reproduzir exatamente o que o usuário instala,
  use `pip install "pandas>=2.0,<3"`.

## 3. Riscos residuais

1. **`filtros.json` corrompido**: o programa faz backup (`.bak`) e volta aos
   padrões, mas `--check` pode terminar com "OK" depois desse aviso. Decisão
   possível: tratar como erro no `--check` (código 2) em vez de aviso.
2. **`--check` duplica mensagens** quando cai no validador local de fallback
   (robustez proposital). É cosmético.
3. **Cartas/currículos sobrescrevem** o arquivo da mesma vaga (comportamento
   documentado). Versionamento automático é decisão de produto.
4. **Excel real não testado**: `quotePrefix` é o mecanismo correto do formato
   OOXML e foi verificado no arquivo salvo, mas a exibição final depende do
   Excel/LibreOffice.
5. **Console do Windows**: mensagens acentuadas podem aparecer como `?` em
   consoles com página de código legada (`cp850`). Não é regressão — o programa
   já imprimia acentos — e não afeta a interface gráfica.
6. **`perfil*.json` ignorado**: o `.gitignore` cobre qualquer perfil pessoal e
   reabre apenas `perfil_exemplo.json`. Se você criar um modelo novo chamado
   `perfil_*.json`, ele será ignorado de propósito.
7. **Dependências opcionais** (Playwright, Gemini, docx) não são instaladas por
   `requirements.txt`; quem usa os recursos precisa instalar os extras
   indicados no README.
8. **Token/credenciais**: nenhum token ou chave foi gravado no repositório. O
   `git remote` foi deixado sem credencial embutida.

## 4. Decisões pendentes (mantenedor)

- [ ] `--check` deve falhar (exit 2) quando `filtros.json` existe mas está
      ilegível, em vez de apenas avisar?
- [ ] Limite de `dias` deve continuar em 1–90 (hoje alinhado entre CLI,
      validação e UI) ou subir para 365?
- [ ] Cartas/currículos devem ganhar sufixo de versão em vez de sobrescrever?
- [ ] Fixar a versão do `python-jobspy` usada no `.exe` (hoje `>=1.1.80,<2`)
      para builds reproduzíveis?
- [ ] Adicionar um `Makefile`/`justfile` com `test`, `check`, `lint`?

## 5. Próximos passos sugeridos

1. Rodar uma busca real curta (`resultados_por_busca` baixo, um site) e conferir
   a planilha e a aba de descartadas.
2. Rodar o workflow *Testes* no GitHub Actions e o de geração dos `.exe`.
3. Se for usar a candidatura assistida, testar o fluxo com uma vaga de teste e
   confirmar que ele nunca envia sozinho.
4. Avaliar a inclusão de `ruff`/`flake8` no CI (não foi adicionado para não
   impor novas dependências sem decisão).
