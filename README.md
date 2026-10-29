# Busca de Vagas

Dois programas:
- **BuscaVagas** — coleta vagas (Indeed, LinkedIn, Glassdoor), filtra por regras
  simples e gera uma planilha Excel onde você marca Candidatei/Recusei.
- **CandidatarVagas** — ajuda a preencher o Easy Apply do Indeed para as vagas
  marcadas na planilha, sem nunca enviar por você.

Sem LLM, sem servidor — tudo roda localmente.

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

Termos de até 3 letras (`sr`, `sql`, `upa`) só contam como palavra inteira —
senão `sr` casaria com "SRE" e `upa` com "upar". `filtros.json` de versões
anteriores é migrado sozinho na primeira abertura (os termos de cargo vão para
a lista "só no título"; quem tinha "Cidade, DF" ganha a linha "DF").

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
python main.py --email      # e-mail com as vagas novas (variáveis JOBSCRAPER_SMTP_*)
```
Filtros ficam em `filtros.json`, perfil do candidato em `perfil.json` (ambos
editáveis à mão ou pela interface).

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
