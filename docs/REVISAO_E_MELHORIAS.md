# Revisão e melhorias — BuscaVagas 2026.11

Este documento registra o que foi analisado, o que foi corrigido e como validar
as mudanças. Ele acompanha o commit que elevou a versão para **2026.11**.

## 1. Contexto e método

- **Ponto de partida:** commit `481cfcc` ("Corrige detecção de remoto/híbrido,
  salário, link morto e concorrência"), com 45 testes `unittest` passando.
- **Equipe:** um orquestrador/avaliador, três programadores em frentes
  disjuntas (coleta/configuração; persistência/planilha; interface/IA/pacote) e
  dois analistas de qualidade (núcleo de dados; segurança e integração).
- **Método:** leitura do código, auditoria adversarial com testes de regressão,
  validação em duas versões de Python e teste de ponta a ponta **sem rede**
  (coleta simulada → filtro → SQLite → Excel → leitura das marcações).
- **Ambientes usados:** Python 3.8.2 (sistema) e Python 3.13.0 (venv com
  `jobspy`, `pandas`, `openpyxl`, `playwright`, `google-genai`, `python-docx`,
  `pypdf` e `coverage`). Nenhum teste acessa sites reais, envia e-mail ou chama
  a API do Gemini.

## 2. Problemas reais encontrados na linha de base

| Sev. | Onde | Problema | Correção |
|---|---|---|---|
| Alto | `export_xlsx.py` | Título/empresa/local começando com `=`, `+`, `-`, `@` podiam ser gravados como **fórmula** (injeção de planilha) | Células gravadas como texto (`data_type="s"` + `quotePrefix`), conteúdo original preservado |
| Alto | `resume_adapter.py` | Descrição da vaga (texto de terceiros) podia fechar as tags do prompt e injetar instruções | Tags delimitadoras neutralizadas + instrução explícita de que o bloco é DADO |
| Alto | `config.py` | `SMTP_PORT = int(env)` no import derrubava o programa com variável inválida | `_int_env()` com validação, faixa e fallback |
| Alto | `pipeline.py` | `dias` nulo/texto quebrava **antes** de gerar a planilha, escondendo o que já estava salvo | `config.dias_do_filtro()` + fallback 7, sempre gera a planilha |
| Alto | `config.py` | JSON com BOM (Bloco de Notas) era tratado como corrompido e substituído pelos padrões | Leitura com `utf-8-sig` (filtros, perfil, presets, descartadas) |
| Médio | `database.py` | `save_jobs` fazia um `SELECT` por vaga (N+1) e um registro ruim derrubava o lote | `SELECT ... IN` em lotes de 500, dedupe em memória e erro isolado por registro |
| Médio | `database.py` | `id` nulo/vazio era gravado com PK NULL (linhas "zumbi") | Registro inválido é pulado com aviso |
| Médio | `notifier.py` | SMTP sem `timeout` podia travar o programa; vários destinatários viravam um só | `timeout` (30 s), múltiplos destinatários, texto puro, HTML escapado |
| Médio | `apply_core.py` | `page.goto` aceitava `javascript:`, `file:` e URL com controle/quebra de linha | `is_safe_job_url()` aceita apenas `http`/`https` com host e porta válidos |
| Médio | `scraper.py` | `resultados_por_busca` inválido abortava a coleta; filtros string viravam caracteres | Validação/clamp, `plan_queries()`, tolerância a tipos |
| Médio | `config.py` | `filtros.json`/`perfil.json` podiam ficar pela metade numa queda | Escrita atômica (temporário + `os.replace` + `fsync`) e `chmod 600` no perfil (POSIX) |
| Baixo | `utils.py` | `1.234.567` era lido como `None`; `open_file` propagava `OSError` | Parser pt-BR corrigido; `open_file` devolve `bool` |
| Baixo | `filtering.py` | `evaluate(None)` e `filter_jobs(None)` estouravam exceção | Entrada inválida vira descarte com motivo |
| Baixo | `.gitignore` | `.tmp-*.json` (pode conter `perfil.json`) e artefatos de cobertura não eram ignorados | Padrões adicionados |

## 3. Mudanças por área

### 3.1 Coleta e configuração
- `config.py`: validação (`validate_filters`), coerção de tipos
  (`coerce_filters`), escrita atômica, `dias_do_filtro`, permissões do perfil,
  leitura tolerante a BOM e `SMTP_PORT` seguro.
- `scraper.py`: imports tardios (permite `--dry-run`/testes sem pandas),
  `plan_queries()` para o novo `--dry-run`, injeção de `sleep`/`fetch`,
  deduplicação por URL **e** por (título, empresa, local) normalizados, pausa
  apenas entre consultas e log de tempo total.
- `utils.py`/`filtering.py`: números pt-BR, termos tolerantes a `None`, vaga
  inválida tratada como descarte, salário vindo de string.

### 3.2 Dados, banco e planilha
- `database.py`: índices (`situacao`, `data_coleta`, `situacao+auto_preencher`,
  `pontos`), inserção em lote, isolamento de registros inválidos, IDs
  normalizados.
- `export_xlsx.py`: proteção contra injeção de fórmula, hyperlink só
  `http`/`https`, corte no limite de 32.767 caracteres, leitura de marcações
  tolerante a cabeçalho duplicado/ID numérico e fallback de nome quando a
  planilha está aberta no Excel.
- `notifier.py`: timeout, múltiplos destinatários, `text/plain`, escape seguro.
- `pipeline.py`: planilha sempre gerada, falhas recuperáveis em `erros`,
  coletor injetável (testes offline) e log de duração.

### 3.3 Interface, candidatura e IA
- `main.py`: `--check`, `--dry-run`, `--log-level`, `--version`; `--days`
  alinhado ao filtro (1–90); logging com fallback; imports tardios.
- `app.py`: validação antes de buscar, UI sempre reabilitada em erro, redação de
  e-mail/chave no log.
- `apply_core.py`: `NEVER_SUBMIT`, validação de URL, upload apenas de
  PDF/DOC/DOCX existente e timeouts por campo.
- `applier.py`/`candidatar_app.py`: abas fechadas em `finally`, `Ctrl+C` e
  interrupção tratados sem perder marcações, painel e botões reabilitados.
- `resume_adapter.py`: conteúdo não confiável delimitado e neutralizado,
  truncamento em ~20.000 caracteres, chave mascarada em erros, nomes de arquivo
  seguros (inclusive reservados do Windows) e checagem de fabricação por
  palavra normalizada.

### 3.4 Empacotamento, CI e documentação
- `requirements.txt` com limites superiores (`<2`, `<3`, `<4`).
- `.github/workflows/tests.yml`: testes em todo push/PR (Ubuntu, Python 3.12,
  apenas `openpyxl` — sem rede).
- `build_exe.bat` e `build_exe.yml`: testes antes do PyInstaller e coleta de
  `curl_cffi` (usado pelo `python-jobspy` 1.4+).
- `README.md` e `COMO_USAR.txt`: novas flags, seção de privacidade/segurança e
  de qualidade/CI.

## 4. Segurança e privacidade (resumo)

- **Planilha:** injeção de fórmula neutralizada; links só `http`/`https`.
- **Prompt do Gemini:** injeção por fechamento de tag bloqueada; texto
  truncado; chave nunca aparece em log/erro.
- **Navegador:** não envia candidatura, não responde triagem, só abre
  `http`/`https` e só anexa arquivo existente com extensão permitida.
- **Segredos/PII:** `perfil.json` fora do Git, `chmod 600` em POSIX,
  e-mail/chave mascarados nos logs das interfaces.
- **Sem `shell=True`**, sem `eval`/`exec`; o único `Popen` usa lista fixa.

## 5. Qualidade: testes e cobertura

| Métrica | Antes | Depois |
|---|---|---|
| Testes `unittest` | 45 | **256** |
| Python 3.8 | OK | **OK** (8 skips por SO/dependências opcionais) |
| Python 3.13 + deps completas | não executado | **OK** (3 skips POSIX) |
| Cobertura do núcleo (config, scraper, filtering, utils, database, export_xlsx, notifier, pipeline) | 83% | **88%** |

Os skips são esperados: permissões POSIX no Windows e bibliotecas opcionais
(`python-docx`, `pypdf`, `PyYAML`) ausentes no Python do sistema.

## 6. Como validar

```bash
python -m unittest discover -s tests -t .
python -m compileall -q .
python main.py --check
python main.py --dry-run
python main.py --version
python main.py --only-export      # regera a planilha a partir do banco
```

Com as dependências completas (Python 3.12/3.13):

```bash
pip install -r requirements.txt
pip install openpyxl
python -m unittest discover -s tests -t .
```

## 7. Compatibilidade

- Código compatível com **Python 3.8+** (o projeto continua recomendando 3.12).
- Schema do banco e colunas da planilha foram preservados; bancos antigos são
  migrados por `database.init_db()` sem perda de marcações.
- `filtros.json` de versões antigas continua migrando automaticamente.
