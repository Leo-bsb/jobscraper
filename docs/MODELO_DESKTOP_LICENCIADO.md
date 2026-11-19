# Modelo “roda na máquina do usuário + licença paga”

Variante em que a coleta acontece **no computador do cliente** (IP dele), e o
programa deixa de funcionar (ou entra em modo limitado) sem pagamento.

## 1. O que esse modelo resolve de verdade

| Problema do SaaS centralizado | Como o modelo local resolve |
|---|---|
| Bloqueio por IP de datacenter | Cada usuário usa o IP residencial dele; muito menos bloqueio |
| Custo de proxies (R$ 300–1.500/mês) | Zero para o fornecedor |
| Custo de servidores/workers | Zero (compute é do usuário) |
| Privacidade/LGPD | Currículo e histórico ficam na máquina do usuário |
| Latência de fila | A busca roda na hora, localmente |
| Escala | Cada cliente é uma “unidade de processamento” |

Tecnicamente, é a forma mais barata de operar: você vende **software**, não
infraestrutura.

## 2. O que ele NÃO resolve

1. **Permissão/termos de uso** não mudam. O software continua automatizando
   sites cujos termos restringem coleta. Rodar no IP do usuário reduz a
   exposição prática, mas não cria autorização; o fornecedor que distribui a
   ferramenta ainda pode ser alvo de notificação/ação. Isso precisa de revisão
   jurídica e de uma estratégia de fontes legais (APIs, ATS, parcerias).
2. **Bloqueio individual**: o IP do usuário também é limitado (CAPTCHA, 429,
   ban temporário). Ele vai culpar o produto. Precisa de retry/backoff (já
   existe), limites por execução e mensagens claras.
3. **Pirataria**: Python + PyInstaller é reversível. Qualquer checagem
   “if not pago: exit” é patchável. Enforcement forte exige **valor no
   servidor**, não só no binário.
4. **Suporte e distribuição**: antivírus/SmartScreen, assinatura de código,
   atualizações, máquinas corporativas com proxy — custo real de operação.
5. **Métricas**: sem telemetria (opt-in), você não sabe o que o usuário usa,
   o que dificulta melhorar precisão e reter.

## 3. Como fazer o licenciamento (do mais fraco ao mais forte)

### Nível 0 — chave fixa no instalador
Não recomendado: vaza na primeira semana.

### Nível 1 — token assinado + verificação offline (recomendado como base)
- Servidor gera um **token Ed25519** (ou JWT RS256) com: cliente, plano,
  features, `exp`, `iat`, `machine_id` opcional, assentos.
- O app embute só a **chave pública** e valida a assinatura offline.
- Guarda o token localmente e renova a cada 7–30 dias (TTL curto permite
  revogar/refundir sem lista de revogação complexa).
- **Grace period** de 7 dias sem internet; depois, modo somente leitura.
- **Detecção de relógio voltado**: guardar o maior timestamp visto do servidor.
- **Vínculo de máquina** (hash de CPU/disco/MAC) com tolerância; 2 ativações;
  desativação self-service no portal.

### Nível 2 — funcionalidades que exigem servidor
O que realmente segura a assinatura:
- **digest diário por e-mail** (servidor envia a planilha);
- **presets curados e atualizados** (baixados assinados);
- **créditos de carta/currículo** (LLM no servidor);
- **sincronização/multi-dispositivo**;
- **suporte prioritário**.
Assim, quem pirateia o binário continua sem o serviço.

### Nível 3 — anti-tamper
Ofuscação/empacotamento ajuda pouco e encarece manutenção. Prefira:
- assinatura de código (EV certificate) e **atualizações assinadas**;
- verificação de integridade de módulos críticos;
- limites por licença no servidor (rate limit por customer_id).

## 4. UX de cobrança (não sequestrar dados)

- Aviso aos 7, 3 e 1 dia antes do vencimento; link de pagamento no app.
- Após o prazo: **modo somente leitura** (planilha/DB continuam acessíveis,
  exportação liberada), coleta bloqueada até regularizar.
- Nunca apagar histórico do usuário por inadimplência (LGPD/confiança).
- Período de graça configurável (ex.: 3 dias) para falha de cartão/Pix.

## 5. Modelos de cobrança que combinam com desktop

| Modelo | Preço sugerido | Prós | Contras |
|---|---|---|---|
| Licença vitalícia + updates 12 meses | R$ 97–197 | simples, converte bem | LTV baixo, pirataria |
| Assinatura mensal com token | R$ 19–29/mês | receita recorrente | atrito de cobrança, crack |
| **Híbrido** (recomendado) | app R$ 97 + nuvem R$ 19/mês | receita recorrente no que dá para controlar | duas ofertas para explicar |
| Equipe/Private | R$ 249–499/ano | ticket maior | suporte |

O híbrido é o mais realista: o **núcleo local** pode até ser gratuito; a
assinatura paga o **digest, presets, LLM e atualizações** — que são
verificáveis no servidor.

## 6. Provedores (Brasil)

- **Pagamento**: Stripe, Asaas, Pagar.me, Mercado Pago (Pix + cartão +
  webhook de assinatura/cobrança).
- **Licenças prontas** (mais rápido): Lemon Squeezy, Paddle, Gumroad
  (validam chave via API, cuidam de imposto internacional).
- **Assinatura de código**: Certum/Sectigo/DigiCert (EV, ~US$ 200–500/ano) —
  reduz SmartScreen/antivírus.
- **Servidor de licença**: FastAPI + Postgres (pequeno) ou Cloudflare Workers +
  KV; custo ~R$ 0–50/mês.

## 7. Arquitetura mínima

```
App desktop (Tkinter atual)
  ├─ license client: verifica token Ed25519, grace, machine_id
  ├─ coleta local (jobspy) + filtros atuais + SQLite + Excel
  ├─ updater assinado
  └─ telemetria opt-in (anonimizada)
        │ HTTPS
Servidor de licença (FastAPI)
  ├─ /activate, /refresh, /deactivate
  ├─ webhook Stripe/Asaas → emite/renova token
  ├─ TTL 7–30 dias + revogação
  └─ rate limit por licença (anti-abuso)
```

### Esforço estimado
- MVP com Lemon Squeezy/Paddle + token assinado + grace: **1–2 semanas**.
- Completo (portal, máquina, dunning, updater assinado, telemetria):
  **3–4 semanas** + revisão jurídica.

## 8. Riscos e mitigação

| Risco | Nível | Mitigação |
|---|---|---|
| Crack/pirataria | Alto | preço baixo, valor no servidor, updates assinados |
| ToS/notificação das plataformas | Médio-alto | fontes legais, EULA, sem bypass de CAPTCHA/login, jurídico |
| Usuário bloqueado no IP dele | Médio | limites, backoff, mensagens claras, multi-fonte |
| Suporte/antivírus | Médio | code signing, instalador limpo, logs fáceis |
| Chargeback/refund | Médio | Pix/cartão, dunning, prazo de graça |
| Métricas fracas | Médio | telemetria opt-in e NPS |

## 9. Veredito

- **Como operação, é excelente**: menor custo, menos bloqueio, mais privacidade.
- **Como negócio, é “software licenciado com serviços”**, não SaaS clássico:
  o controle do pagamento no binário é frágil; o controle real está no
  serviço (digest, presets, LLM, updates).
- **Recomendação**: núcleo local + assinatura híbrida; bloqueio após grace
  apenas da coleta, com dados do usuário sempre acessíveis. Isso combina com o
  formato Excel-first e mantém a margem alta sem depender de proxies.
