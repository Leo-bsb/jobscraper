# Busca de Vagas

Dois programas:
- **BuscaVagas** — coleta vagas (Indeed, LinkedIn, Glassdoor), filtra por regras
  simples e gera uma planilha Excel onde você marca Candidatei/Recusei.
- **CandidatarVagas** — ajuda a preencher o Easy Apply do Indeed para as vagas
  marcadas na planilha, sem nunca enviar por você.

A busca e o filtro não usam LLM nem servidor — rodam localmente. Só os
recursos opcionais de carta/currículo adaptado chamam a API do Gemini (e
apenas quando você clica no botão).

## Múltiplas cidades / região metropolitana
O campo `cidades` é a lista de cidades **aceitas** — só entram vagas cujo local
bate com uma delas. Regras de cada linha:
- `"Contagem, MG"` casa só **Contagem** (a sigla do estado não entra; antes ela
  entrava e aceitava qualquer cidade de Minas Gerais);
- uma linha sem vírgula vale inteira: `"DF"` aceita qualquer cidade do DF.

A primeira cidade também é o centro da busca nos sites, com raio `alcance_km`.
O raio só define **o que os sites devolvem**; quem decide o que entra é a
lista. Por isso o perfil da Grande BH lista os municípios vizinhos (Ibirité,
Sarzedo, Ribeirão das Neves, Santa Luzia, Sabará, Nova Lima...).

## Perfis prontos (pasta `perfis/`)
Em vez de montar os filtros do zero, a interface oferece um menu "Perfil
pronto" com modelos já calibrados (ex.: *Dados/TI — Brasília*, *Enfermagem —
Contagem/Betim/Grande BH*). Escolher um preenche tudo automaticamente; dá para editar
depois. Para criar um novo perfil, copie um `.json` de `perfis/` e ajuste
`termos_busca`, `cidades` e `termos_fortes`.

## Como o filtro decide
Uma vaga só entra se:
1. o **título** não tiver nenhum de `termos_proibidos_titulo` (padrão: `estagi`,
   `senior`, `sr`, `logistic`, `almoxarifado`, `vendedor`...) e o título/descrição
   não tiver nenhum de `termos_proibidos`. Senioridade e tipo de cargo ficam só
   no título porque, na descrição, "estágio concluído", "reporta ao gerente
   sênior" ou "área de logística" aparecem em vagas boas;
2. tiver pelo menos **1 termo forte** (`python`, `sql`, `power bi`, `etl`,
   `enfermag`, `coren`...) **e** pelo menos `minimo_de_termos` termos no total
   (fortes + fracos somados, padrão 2);
3. o local bater com alguma das **cidades aceitas**, **ou** o próprio texto da
   vaga mencionar home office/remoto (se `aceitar_home_office_todo_brasil`) —
   desde que a vaga **não** seja híbrida e o texto não negue o remoto ("não é
   remoto", "sem home office", "100% presencial").

O home office é reconhecido por **radical**: `remot` pega remoto/remota/remotas,
e `hibrid` pega híbrido/híbrida (antes só a forma masculina era detectada). O
campo de local também conta — vaga com local "Home Office" e descrição que não
repete a palavra é aceita normalmente.

Termos de até 3 letras (`sr`, `sql`, `upa`) só contam como palavra inteira —
senão `sr` casaria com "SRE" e `upa` com "upar". `filtros.json` de versões
anteriores é migrado sozinho na primeira abertura (os termos de cargo vão para
a lista "só no título"; quem tinha "Cidade, DF" ganha a linha "DF"; e
`remoto`/`remote` em `termos_home_office` viram `remot`).

**Por que "termo forte" existe:** palavras como `desenvolv` e `analis`
aparecem em qualquer vaga de desenvolvedor/analista, e até em rodapés padrão
de LGPD de vagas sem nada a ver ("seus dados serão tratados conforme a
LGPD..."). Sozinhas, elas não aprovam a vaga — só contam para o total, junto
com pelo menos um termo forte que confirme que é realmente a vaga certa.

**Por que não confiamos na flag "remoto" do site:** o Indeed/LinkedIn às vezes
marca vagas híbridas (presenciais parte da semana, em outra cidade) como
remotas. Por isso só aceitamos como home office quando a própria vaga diz
isso no texto.

Palavras ignoram acentos/maiúsculas e casam o *começo* da palavra
(`desenvolv` pega desenvolver/desenvolvedor). A mesma vaga em sites diferentes
(mesma empresa + título + cidade) aparece uma vez só — e para vagas remotas,
a cidade é ignorada nessa comparação, já que a mesma vaga remota costuma ser
postada sob várias cidades diferentes.

## Aba "Descartadas (última busca)"
Toda busca gera uma aba extra mostrando o que foi rejeitado **nesta execução**
e por quê (não acumula entre buscas). Serve para calibrar os filtros.

## Planilha `vagas_da_semana.xlsx`
- Aba **Vagas**: pendentes dos últimos N dias, ordenadas por nº de termos encontrados.
- Coluna **Situação**: Pendente / Candidatei / Recusei (verde / cinza).
- Coluna **Auto-preencher**: Sim/Não — usada pelo CandidatarVagas (ver abaixo).
- Aba **Já tratadas**: histórico.
- Marque e **salve** (Ctrl+S). O programa lê suas marcações ao buscar, ao abrir o
  CandidatarVagas e ao clicar em "Abrir planilha" — não precisa buscar de novo.
- Se o arquivo estiver aberto no Excel quando o programa for regerá-lo, ele salva
  uma cópia com outro nome e avisa; feche o Excel e clique em "Abrir planilha".
- Quem manda quando planilha e programa discordam: a planilha guarda, em colunas
  ocultas, o valor de cada vaga no momento em que foi gerada. Só o que você
  **mudou à mão** é aplicado — então o "Candidatei" marcado pelo CandidatarVagas
  nunca é desfeito por uma planilha antiga.

## Candidatura assistida (CandidatarVagas)
Abre, uma de cada vez, as vagas marcadas com **Auto-preencher = Sim**. No
Indeed com Candidatura Simplificada, preenche nome/e-mail/telefone/currículo
e **para antes de enviar** — você revisa e decide. Em qualquer outro site, só
abre a aba para preenchimento manual.

Pela interface gráfica (`candidatar_app.py` / `CandidatarVagas.exe`): preencha
seus dados uma vez, clique em "Iniciar candidaturas" e use os botões
"✅ Já candidatei" / "⏭️ Pular" / "🛑 Parar tudo" conforme avança pelas vagas.

Pela linha de comando (`applier.py`), para quem prefere terminal:
```bash
pip install playwright && playwright install chromium
cp perfil_exemplo.json perfil.json   # preencha nome, e-mail, telefone, currículo
python applier.py
```
A sessão do navegador (login do Indeed) fica salva em `navegador_indeed/`, então
você loga uma vez só. Ele nunca clica em enviar nem responde perguntas de
triagem — isso é sempre manual. A lógica do navegador é compartilhada entre
os dois modos em `apply_core.py`.

## Carta de apresentação e currículo adaptado (opcional)
Dentro do `CandidatarVagas` (GUI ou `python candidatar_app.py`), enquanto
revisa uma vaga, dois botões usam a API do **Gemini** (Google AI Studio) a
partir do seu currículo em PDF e da descrição daquela vaga específica:

- **"✍️ Gerar carta personalizada"**: carta de apresentação (rascunho, para
  você revisar — nunca é enviada automaticamente) + sugestões de como
  destacar pontos do currículo para aquela vaga.
- **"📄 Gerar currículo adaptado"**: um `.docx` com o currículo inteiro
  reorganizado para aquela vaga — mesmas empresas, cargos e datas do
  original, só a ordem dos pontos/habilidades e o resumo profissional mudam
  para destacar o que é relevante.

```bash
pip install -U google-genai pypdf python-docx
```
Chave de API gratuita em https://aistudio.google.com/apikey — cole uma vez no
campo "Chave Gemini" da interface e clique em "Salvar meus dados"; ela fica
guardada em `perfil.json` e não precisa ser digitada de novo. O modelo usado
é configurável em `resume_adapter.py` (`MODEL = "gemini-3.5-flash"`).

**Trava contra invenção:** as instruções enviadas ao modelo (`SYSTEM_PROMPT` /
`SYSTEM_PROMPT_CURRICULO` em `resume_adapter.py`) proíbem citar experiência,
cargo, certificação ou habilidade que não esteja no currículo original — só
reorganiza e destaca o que já é verdade. Para o currículo adaptado, que é
estruturado (não texto livre), há uma segunda camada de proteção:
`_checar_fabricacao()` compara cada nome de empresa/instituição que o modelo
devolveu contra o texto original do currículo; qualquer um que não bater
aparece destacado em vermelho no topo do `.docx` e também numa janela de
alerta na interface, para você revisar antes de usar. Essa checagem é
heurística (compara palavras-chave, não é prova formal) — sempre releia o
resultado antes de enviar para uma empresa.

Os arquivos gerados ficam em `cartas/` e `curriculos_adaptados/`, com nome
baseado em empresa + título da vaga. Gerar de novo para a mesma vaga
**sobrescreve** o arquivo anterior (não cria versões numeradas) — se quiser
guardar mais de uma versão, renomeie antes de gerar outra.

**Privacidade:** para gerar a carta ou o currículo, o texto do currículo e a
descrição da vaga são enviados à API do Gemini. Veja a política de uso de
dados em https://ai.google.dev/gemini-api/terms se isso for uma preocupação.

## Usar (Python 3.12)
```bash
pip install -r requirements.txt
python app.py               # interface de busca (a mesma do BuscaVagas.exe)
python candidatar_app.py    # interface de candidatura assistida
python main.py              # linha de comando: busca + planilha
python main.py --only-export
python main.py --days 30    # janela de busca (1 a 90 dias)
python main.py --email      # e-mail com as vagas novas (variáveis JOBSCRAPER_SMTP_*)
```
Filtros ficam em `filtros.json`, perfil do candidato em `perfil.json` (ambos
editáveis à mão ou pela interface).

### Opções de linha de comando
```bash
python main.py --check              # valida filtros, perfil, perfis prontos e pasta base
python main.py --dry-run            # mostra o plano de consultas (sites x termos x locais)
python main.py --days 30            # sobrescreve a janela de dias (1 a 90)
python main.py --only-export        # não busca; só regera a planilha
python main.py --email              # busca e envia e-mail com as vagas novas
python main.py --log-level DEBUG    # DEBUG, INFO (padrão), WARNING ou ERROR
python main.py --version            # mostra a versão
```

- **`--check`**: não busca nada. Confere o `filtros.json` (inclusive
  `sites`, `termos_busca`, `dias`, `alcance_km`), os arquivos de
  `perfis/`, se a pasta do programa aceita gravação e, se `perfil.json`
  existir, se os dados básicos da candidatura assistida estão coerentes.
  Imprime um relatório em português e termina com código **2** se houver
  problema, **0** se estiver tudo certo. Bom para rodar antes da primeira
  busca ou depois de editar os filtros à mão.
- **`--dry-run`**: monta o mesmo plano de consultas que a busca faria
  (`sites` × `termos_busca` × local, mais as buscas nacionais de home
  office), com a contagem e o raio — **sem acessar a rede**. Útil para
  estimar quanto tempo a busca vai levar.
- **`--log-level`**: controla o detalhamento do `buscavagas.log` e do
  console. Se o arquivo de log não puder ser gravado (pasta somente
  leitura), o programa avisa e continua só com as mensagens na tela.
- **`--version`**: imprime a versão de `config.VERSION` e sai.
- **`--days N`**: usa N dias como janela (o mesmo limite do `filtros.json`:
  1 a 90). Fora da faixa, o comando termina com código 2 e não busca.
- **`--only-export`**: não acessa os sites; só relê o banco e regera a
  planilha. **`--email`**: ao terminar uma busca, envia o resumo por e-mail
  (precisa das variáveis `JOBSCRAPER_SMTP_*`).

## Testes
Sem rede, sem Excel, sem navegador — usa só `unittest` da biblioteca padrão:
```bash
python -m unittest discover -s tests -t .
```

## Qualidade/CI
- Os testes rodam **sem rede**, sem abrir janelas e sem Playwright/pandas:
  só `unittest` + `openpyxl`.
- `.github/workflows/tests.yml` roda a suíte em todo `push`/`pull_request`
  (Ubuntu, Python 3.12), instalando apenas `openpyxl`.
- `.github/workflows/build_exe.yml` e o `build_exe.bat` rodam os testes
  **antes** do PyInstaller, para não publicar um `.exe` quebrado.
- Antes de abrir um chamado/issue, rode `python main.py --check` — ele
  costuma apontar o problema (filtro vazio, site inválido, pasta sem
  permissão de escrita).

## Privacidade e segurança
- **`perfil.json`** guarda nome, e-mail, telefone, o caminho do currículo e a
  chave do Gemini. Ele está no `.gitignore` e **não deve ser commitado nem
  compartilhado** — é dado pessoal. Em Linux/macOS ele é gravado com permissão
  `600` (só o dono lê); no Windows valem as permissões da pasta. A chave do
  Gemini nunca aparece em mensagens de erro/log (é mascarada, inclusive no
  `buscavagas.log`), e e-mails também são mascarados nos logs das interfaces.
- **`vagas_da_semana.xlsx`** e `vagas.db` contêm as vagas coletadas
  (empresa, título, link, descrição) e o que você marcou. Também estão no
  `.gitignore`; trate como dado pessoal do seu histórico de candidaturas.
- **A candidatura assistida nunca envia sozinha**: ela só abre a vaga,
  preenche campos de contato vazios e (se o arquivo existir e for
  PDF/DOC/DOCX) anexa o currículo. O botão de enviar é sempre seu. Essa
  regra está explícita em `apply_core.py` (`NEVER_SUBMIT`).
- Links de vaga só são abertos se forem `http`/`https`; `javascript:`,
  `file:` e afins são recusados.
- Para gerar carta/currículo adaptado, o texto do currículo e a descrição da
  vaga são enviados à API do Gemini. O texto da vaga é tratado como **dado
  não confiável** (delimitado por tags, com instrução para o modelo ignorar
  comandos vindos dali); ocorrências das próprias tags delimitadoras no
  conteúdo (ex.: uma descrição contendo `</descricao_vaga>`) são removidas
  antes do envio, e o texto é truncado em ~20.000 caracteres.

## Gerar os .exe
Precisa ser feito no Windows (o PyInstaller não gera .exe a partir de Linux/Mac):
- **Local:** dê dois cliques em `build_exe.bat` (Python 3.12 instalado) →
  `dist\BuscaVagas.exe` e `dist\CandidatarVagas.exe`.
- **Sem instalar nada:** suba o projeto para um repositório no GitHub → aba
  *Actions* → *Gerar BuscaVagas.exe + CandidatarVagas.exe* → *Run workflow* →
  baixe o artefato (já vem com `COMO_USAR.txt` e a pasta `perfis/`).

Entregue a pasta inteira (os dois `.exe` + `perfis/` + `COMO_USAR.txt`). Cada
pasta tem seu próprio banco/filtros/perfil, então duas pessoas usando o
programa em pastas separadas não interferem uma na outra. O Windows pode
mostrar o aviso "protegeu o computador" (exe novo sem assinatura): *Mais
informações → Executar assim mesmo*.

## Se os sites recusarem muito
- O programa já espera tempos aleatórios e tenta de novo (até 3x) com espera crescente.
- Desmarque o site que mais recusa (LinkedIn/Glassdoor costumam ser os piores).
- Ajuste `DELAY_*` / `RETRY_*` em `config.py`, ou reduza `resultados_por_busca`.

## Documentação da revisão
- [`docs/REVISAO_E_MELHORIAS.md`](docs/REVISAO_E_MELHORIAS.md): o que foi
  auditado, problemas encontrados e correções (versão 2026.11).
- [`docs/LIMITACOES_E_PENDENCIAS.md`](docs/LIMITACOES_E_PENDENCIAS.md): o que
  não foi possível validar nesta máquina, riscos residuais e decisões pendentes.
