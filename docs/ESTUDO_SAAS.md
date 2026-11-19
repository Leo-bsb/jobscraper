# BuscaVagas como SaaS — estudo de viabilidade

Documento de avaliação de produto e negócio, escrito a partir do teste real
descrito em [`ANALISE_VAGAS_REAIS.md`](ANALISE_VAGAS_REAIS.md). Números de
mercado, custos e conversão são **estimativas** para dimensionar a conversa —
não são projeções auditadas.

## 1. Veredito executivo

**Viável — mas não como "agregador de vagas".** O valor defensável não está em
raspar Indeed/LinkedIn (caro, bloqueável e juridicamente frágil), e sim em:

1. **precisão de curadoria** (o teste mostrou 36% → 88% com o filtro certo);
2. **fluxo de candidatura** (planilha/kanban, acompanhamento, carta e currículo
   adaptados, candidatura assistida sem envio automático);
3. **confiança e privacidade** (nunca envia sozinho, dados do candidato sob
   controle, opção local-first).

O caminho com melhor relação risco/retorno é **B2C vertical (enfermagem e
dados) + B2B para coachs/outplacement**, começando com fontes de dados
licenciadas/APIs públicas. Um SaaS de scraping massivo de LinkedIn/Indeed tem
risco jurídico e operacional que compromete a tese.

## 2. O que já existe (e o que falta para SaaS)

| Já existe no projeto | Falta para SaaS |
|---|---|
| Motor de coleta multi-site (jobspy) com retry, dedupe e ritmo | Coleta legal/licenciada, multi-tenant, filas e proxies |
| Motor de filtros por termo/cidade/senioridade/home office | Interface web, onboarding e perfis salvos na nuvem |
| SQLite + planilha Excel com marcações | Postgres, API, sincronização e histórico por usuário |
| Candidatura assistida (Playwright, nunca envia) | Sessão por usuário, fila, observabilidade e suporte |
| Carta/currículo via Gemini com travas anti-invenção | Créditos, custos por usuário e revisão humana no fluxo |
| Testes (259), CI e documentação | Billing, LGPD (DPO, retenção, exclusão), SLA e suporte |

O produto atual é **desktop, local-first, single-user**. A distância até um SaaS
não é o scraper: é produto web, confiança e operação.

## 3. Público e “jobs to be done”

| Segmento | Dor | Disposição a pagar |
|---|---|---|
| Candidato de entrada (dados, enfermagem) | “Perco horas achando vaga certa e ainda assim aparece lixo” | Média (R$ 20–50/mês, sensível a preço) |
| Candidato em transição/relocação | “Quero remote/multi-cidade e acompanhar tudo num lugar” | Média-alta |
| Profissional sênior | “Poucas vagas, mas quero ser avisado na hora e adaptar currículo” | Alta (R$ 50–100/mês) |
| Coach de carreira / outplacement | “Gerencio 10–50 clientes em planilhas” | Alta (R$ 100–300/mês por carteira) |
| Escola/bootcamp/universidade | “Quero empregabilidade mensurável para alunos” | Alta (contrato anual) |
| Recrutador/consultoria | “Quero mapear oferta e salários por região” | Média (dados agregados) |

O candidato tem **churn estrutural**: assim que consegue emprego, cancela. Isso
favorece (a) planos anuais baratos, (b) pausa de assinatura e (c) B2B com
coaches, que mantêm assinatura o ano inteiro.

## 4. Concorrência

| Player | Força | Fraqueza que abre espaço |
|---|---|---|
| LinkedIn / Indeed | volume, marca, alertas | filtros rasos, ruído, pouca explicação, foco global |
| Catho / Vagas.com / Gupy | base BR e empresas | experiência de candidato genérica, sem curadoria |
| Glassdoor | salários e reputação | pouco foco em fluxo de candidatura |
| Jobscan / Teal / Huntr / Simplify | ATS, tailoring, tracking | pouco Brasil, preço em dólar, sem enfermagem/regiões |
| Planilhas e grupos de WhatsApp | custo zero e confiança | trabalho manual, sem dedupe, sem alerta |

Nenhum combina, no Brasil: **filtro por região metropolitana + precisão
explicável + acompanhamento + currículo em português + privacidade**. É uma
cunha real, mas estreita: precisa de verticalização.

## 5. Diferenciais defensáveis

1. **Precisão com explicabilidade**: mostrar *por que* a vaga entrou (termos,
   cidade, modelo) e permitir “não é para mim” → feedback vira ranking. O teste
   já provou o salto 36% → 88%.
2. **Verticalização**: presets calibrados (enfermagem Grande BH, dados júnior
   Brasília/DF). Concorrente genérico não desce a esse nível.
3. **Humano no loop**: nunca envia candidatura sozinho; reduz risco de conta
   banida e aumenta confiança — discurso forte contra “auto-apply”.
4. **Privacidade**: opção desktop/local-first (o produto atual) como plano
   “Private”, além do SaaS.
5. **Custo Brasil**: preço em real, Pix/boleto, português, WhatsApp.

## 6. Modelo de negócio e preços sugeridos

| Plano | Preço (estimativa) | Escopo |
|---|---|---|
| Grátis | R$ 0 | 1 perfil, 1 atualização/dia, 20 vagas, sem alerta |
| Pro | **R$ 39/mês** ou R$ 299/ano | perfis ilimitados, alerta diário, exportação, 10 textos/mês |
| Pro+ | **R$ 79/mês** | multi-cidade, prioridade, 30 textos, currículo adaptado, análise de ATS |
| Coach / Equipe | **R$ 149/mês** (até 10 clientes) | carteira, relatórios, white-label leve |
| Empresa / API | sob consulta | dados agregados, SLA, integração |

- **Anual com desconto** (2 meses grátis) para combater sazonalidade.
- **Pausa de 60 dias** em vez de cancelamento (retenção).
- **Não vender dados de candidatos**; relatórios de mercado só agregados e
  anonimizados.

## 7. Economia unitária (estimativa por usuário Pro/mês)

| Item | Custo estimado |
|---|---|
| Infra (API, workers, Postgres, storage) | R$ 3–8 |
| Proxies / coleta (se scraping autorizado) | R$ 4–12 |
| LLM (10 cartas/currículos, Gemini Flash) | R$ 0,50–2 |
| Meio de pagamento (~7%) | R$ 2,70 |
| Suporte / observabilidade | R$ 2–5 |
| **COGS total** | **R$ 12–30** |
| **Margem bruta a R$ 39** | **23–69%** |
| **Margem bruta a R$ 79** | **62–85%** |

Conclusão: **R$ 29/mês é apertado** com coleta própria; R$ 39–49 é o piso
saudável para B2C, e B2B é onde a margem fica confortável. CAC viável:
R$ 30–80 via conteúdo/comunidade; LTV de 6–10 meses em plano mensal.

## 8. Arquitetura SaaS sugerida

```
Front (Next.js) ── API (FastAPI) ── Postgres (multi-tenant por user_id)
                        │                │
                        │                └─ S3 (currículos, exports) + KMS
                        ├─ Fila (Redis/Celery): coleta, dedupe, matching, LLM
                        ├─ Coletores por fonte (rate limit, circuito, ToS registry)
                        ├─ Motor de filtros (o atual, portado e testado)
                        ├─ Ranking (regras + feedback + embedding opcional)
                        └─ Alertas (e-mail, WhatsApp/Telegram)
```

- **Multi-tenancy** por `user_id` com RLS no Postgres; PII criptografada.
- **Coletores** idempotentes com fingerprint (já existe `make_dup_key`) e
  “janela de recência”.
- **Observabilidade**: taxa de bloqueio por fonte, latência, custo por usuário,
  precisão@20 por segmento.
- **Reuso direto**: `filtering`, `utils` e `resume_adapter` são bibliotecas
  puras e testadas — o SaaS começa com o motor já validado.

## 9. Legal e compliance — o ponto que decide a tese

1. **Termos de uso**: Indeed, LinkedIn e Glassdoor restringem coleta
   automatizada sem autorização. Violar ToS pode gerar bloqueio de IP/conta e
   ação contratual (a jurisprudência de “dados públicos” **não** elimina a
   quebra de contrato). Não construir o núcleo do negócio sobre isso.
2. **LGPD**: perfil, currículo, telefone e histórico de candidatura são dados
   pessoais. Precisa de base legal (consentimento/execução de contrato),
   minimização, retenção definida, exclusão sob solicitação, registro de
   operações e contrato com subprocessadores (ex.: Google/Gemini, e-mail).
3. **Transferência internacional**: o uso do Gemini envia currículo/descrição
   para fora do Brasil — deve estar explícito e consentido.
4. **Publicidade**: não prometer “vaga garantida” nem “emprego”; deixar claro
   que as vagas vêm da fonte X e podem sair do ar.
5. **Candidatura assistida**: manter o princípio “nunca envia sozinho”. Reduz
   risco de automação abusiva e é argumento de confiança.

### Estratégia de dados recomendada (em ordem)

1. **APIs públicas e feeds**: RemoteOK, Remotive, Arbeitnow, Jobicy (usados no
   protótipo de estudo), além de boards de ATS (Greenhouse, Lever, Ashby,
   Workable) que expõem vagas por empresa.
2. **Parcerias/licença** com agregadores, ATSs e veículos locais.
3. **Conteúdo do próprio usuário** (“traga sua busca/URL autorizada”).
4. **Scraping autorizado/robots-friendly** apenas onde permitido, com limite e
   identificação.
5. LinkedIn/Indeed **somente** com autorização formal ou dados licenciados.

## 10. Roadmap sugerido

**0–90 dias (MVP pago)**
- Web app com login, 2 perfis, motor de filtros atual, kanban de candidaturas.
- 2 fontes com situação legal clara (APIs públicas + 1 parceiro).
- Digest diário por e-mail; exportação CSV/Excel.
- 1 vertical: enfermagem Grande BH **ou** dados júnior Brasília/DF.
- LGPD mínimo: consentimento, exclusão, política de privacidade, DPO contato.

**3–6 meses**
- 2ª vertical, alertas WhatsApp, currículo/carta com créditos.
- Feedback “não é para mim” alimentando ranking; precisão@20 como métrica.
- Plano Coach (carteira de clientes) e white-label leve.

**6–12 meses**
- Análise de mercado agregada (salários por região/cargo) como produto B2B.
- Integrações ATS/parceiros; API; SSO para escolas/outplacement.
- Opção “Private” (desktop/local-first) para quem não quer dados na nuvem.

## 11. Métricas e critérios de go/no-go

| Métrica | Meta inicial |
|---|---|
| Precisão@20 (feedback do usuário) | ≥ 70% |
| Ativação (1ª busca em < 2 min) | ≥ 60% |
| Retenção semanal (D7/D30) | ≥ 30% / ≥ 15% |
| Abertura do digest | ≥ 35% |
| Conversão grátis → pago | 3–5% |
| Churn mensal (mensal/anual) | < 10% / < 3% |
| CAC payback | < 6 meses |

**Gates:** (1) 100 usuários com precisão@20 ≥ 70%; (2) 20 assinantes pagos com
churn < 10%; (3) 3 contratos B2B cobrindo a infra. Sem esses números, não
escalar mídia paga.

## 12. Riscos e mitigação

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Bloqueio/ToS das fontes | Alta | Alto | APIs públicas, licença, parceria, multi-fonte |
| Churn do candidato | Alta | Alto | Anual, pausa, B2B com coach, alertas perpétuos |
| Commoditização (LinkedIn/Indeed com IA) | Média | Alto | Verticalização e fluxo, não só busca |
| Precisão baixa gera cancelamento | Média | Alto | Modo precisão, feedback, presets calibrados |
| Custo de LLM/proxies | Média | Médio | Créditos, cache, modelo flash, limites por plano |
| Incidente de privacidade | Baixa | Alto | Criptografia, RLS, minimização, auditoria |
| Dependência de uma fonte | Alta | Médio | Mínimo de 3 fontes por vertical |

## 13. Variante “Excel-first generalista” (avaliação específica)

Pergunta justa: por que não vender exatamente o formato atual — **planilha com
os links filtrados** — para **qualquer profissão**, já que o coletor já lida
com timeout, retry e bloqueio?

**Resposta curta: é a melhor forma de MVP.** O formato não é o problema; o que
muda de “ferramenta local” para “SaaS” é operação, custo e licença de dados.

### Por que funciona
- **Zero atrito**: o usuário já vive em Excel/WhatsApp; não precisa aprender
  dashboard.
- **Custo de construção baixo**: não há web app — só formulário, agendador,
  worker e e-mail com anexo (já implementado em `notifier`).
- **Generalista de verdade**: o motor é agnóstico de profissão; o que muda é o
  perfil (`termos_busca`, `termos_fortes`, `cidades`, senioridade). Os presets
  de dados e enfermagem provam isso.
- **Entrega recorrente**: planilha diária/semanal + alerta = assinatura natural.
- **Feedback embutido**: coluna “Essa vaga é para mim?” na planilha alimenta a
  precisão (36% → 88% com o modo estrito).

### Arquitetura mínima (1–2 pessoas)
```
Landing + checkout (Stripe/Pix)
        │
Formulário de perfil (profissão, termos, cidades, remoto, nível)
        │
Agendador (cron) ── Fila ── Worker (jobspy + filtros atuais)
        │                         │
        │                         ├─ dedupe global + por usuário
        │                         ├─ xlsx por usuário (export_xlsx)
        │                         └─ e-mail com anexo (notifier)
        └─ Postgres (perfis, histórico, supressão de já enviadas)
```
- 1 worker pequeno atende dezenas/centenas de perfis/dia se as consultas forem
  agrupadas por termo+local (cache compartilhado, não 1 busca por usuário).
- Limite por plano (ex.: 1 atualização/dia, 50 vagas novas) controla custo.

### Custos e preço (estimativas)
| Item | Custo/mês por 100 assinantes |
|---|---|
| Servidor + Postgres + worker | R$ 80–200 |
| E-mail transacional | R$ 20–60 |
| Proxies (se necessários) | R$ 300–1.500 (o maior risco) |
| LLM (opcional, cartas) | R$ 50–300 |
| **Total** | **R$ 450–2.060** |

A R$ 29/mês × 100 = R$ 2.900 de receita: margem confortável **sem** proxies
caros; apertada **com** scraping agressivo. Preço sugerido: **R$ 29–39/mês**
por perfil, R$ 69 para 3 perfis, anual com 2 meses grátis.

### O que “contornar bloqueios” resolve — e o que não resolve
- **Resolve** disponibilidade: retry, jitter, backoff, circuit breaker, rodízio
  de fontes e cache reduzem falhas e bans **por sessão**.
- **Não resolve** permissão: os termos de uso de Indeed/LinkedIn/Glassdoor
  restringem coleta automatizada. Um usuário local é uma coisa; um SaaS
  central fazendo milhares de consultas em nome de terceiros é outra —
  aumenta exposição contratual, risco de bloqueio em massa e custo de proxy.
- **Não resolve** qualidade: cada profissão tem jargão e falsos positivos
  próprios; generalizar exige presets + feedback, não só scraping.

### Estratégia de fontes para generalizar com segurança
1. **APIs/feeds públicos** por nicho e por ATS (Greenhouse, Lever, Ashby,
   Workable, RemoteOK, Remotive, Arbeitnow, Jobicy): cobertura legal e estável.
2. **Parcerias/licença** com portais verticais (saúde, indústria, educação).
3. **Sessão do próprio usuário** (“conecte sua conta”) para fontes que exigem
   login, mantendo a coleta sob o consentimento e a conta dele.
4. **Scraping direto** apenas onde permitido/robots-friendly, com limite,
   identificação e política de remoção.
5. LinkedIn/Indeed: somente com autorização formal ou dados licenciados.

### Plano de 90 dias para essa variante
- **Semanas 1–3**: formulário + checkout + worker agendado + e-mail com xlsx
  (o núcleo já existe) e 3 presets generalistas (dados, enfermagem, vendas).
- **Semanas 4–6**: 3 fontes legais, dedupe “já enviadas”, página de privacidade
  e exclusão de conta; medir precisão@20 por profissão.
- **Semanas 7–10**: 50 usuários beta pagantes, feedback na planilha, ajuste de
  presets; WhatsApp/Telegram como canal opcional.
- **Semanas 11–13**: decidir se vale web app (só se o feedback pedir). Até lá,
  Excel + e-mail é suficiente.

### Variante “roda na máquina do usuário”
Se a coleta rodar no PC do cliente (IP dele) com licença paga, o custo de
infra e o bloqueio caem bastante. Os detalhes de licenciamento, cobrança e
limites estão em [`MODELO_DESKTOP_LICENCIADO.md`](MODELO_DESKTOP_LICENCIADO.md).

### Veredito desta variante
**Sim, é o caminho mais racional para começar** — desde que o produto seja
vendido como **curadoria entregue em Excel**, com fontes legais e limite de
uso, e não como “scraping ilimitado de LinkedIn/Indeed”. O diferencial
continua sendo precisão + recorrência + confiança, não o volume bruto.

## 14. Recomendação final

1. **Não** lançar como “scraper de LinkedIn/Indeed por assinatura”. É a versão
   mais frágil jurídica e operacionalmente.
2. **Começar pela variante Excel-first generalista** (§13): formulário +
   agendador + e-mail com planilha anexada, 3–5 presets de profissão e fontes
   legais. É o menor custo de construção e o formato que o usuário já quer.
3. **Verticalizar a curadoria** (enfermagem Grande BH/DF, dados júnior
   Brasília/DF + remoto, vendas etc.) sem verticalizar a infraestrutura: o
   mesmo motor, presets e feedback por profissão.
4. **Evoluir para web/kanban** só quando o uso pedir; até lá, Excel + e-mail
   resolve e reduz custo.
5. **Cobrar por curadoria e fluxo** (precisão, alerta, kanban, currículo),
   não por acesso à vaga.
6. **B2C freemium + B2B coach/escola** como motor de receita; o B2B paga a
   infra e reduz o risco de churn.
7. **Manter o desktop local-first** como plano “Private” e prova de confiança.
8. **Medir precisão@20 desde o dia 1** e usá-la como promessa comercial: “não
   te mostramos 200 vagas; mostramos as 20 certas e explicamos por quê.”

Em resumo: o ativo não é o scraper — é o **motor de decisão** que o teste real
demonstrou (36% → 88% de precisão) somado ao fluxo de candidatura. É sobre isso
que um SaaS defensável pode ser construído.
