# Teste real de usuário — coleta, filtros e qualidade das vagas

Data do teste: **19/11/2026** · Versão testada: **2026.11** · Fonte: **Indeed**
(única fonte usada ao vivo; LinkedIn/Glassdoor não foram acionados para evitar
bloqueio de conta durante o teste).

O teste rodou o fluxo real do produto — `scraper` → `filtering` → `database` →
`export_xlsx` — com dois perfis (“personas”), em diretório temporário, sem
alterar o repositório. As consultas usaram ritmo reduzido de propósito
(2–4 s entre buscas) para caber no tempo do teste; em uso normal o programa
espera 4–12 s.

## 1. Personas e configuração

| Persona | Palavras-chave | Local | Home office | Janela | Vagas/consulta |
|---|---|---|---|---|---|
| Dados júnior (Brasília) | cientista de dados, analista de dados, engenheiro de dados | Brasília/DF + DF | Sim (Brasil) | 14 dias | 25 |
| Enfermagem (Grande BH) | enfermeiro, enfermeira, técnico de enfermagem | 15 cidades da Grande BH | Não | 14 dias | 25 |

Na persona de dados, acrescentei ao perfil: `pleno`, `especialista`,
`coordenador`, `gerente`, `lead`, `principal`, `staff`, `head` e `supervisor`
como proibidos no título, e `junior`/`jr` como termos fracos.

## 2. Volume, tempo e descarte

| Métrica | Dados júnior | Enfermagem |
|---|---|---|
| Consultas feitas | 6 (3 termos × 2 locais) | 3 (3 termos × 1 local) |
| Vagas coletadas | **106** | **54** |
| Aprovadas pelo filtro | **21** (20%) | **49** (91%) |
| Descartadas | **85** | **5** |
| Tempo de coleta | 32 s | 12 s |
| Com link | 21/21 | 40/49 |
| Com salário | 4/21 (19%) | 27/49 (55%) |
| Remotas | 6/21 | 0/49 |
| Presenciais | 1/21 | 13/49 |
| Híbridas | 2/21 | 0/49 |

### Por que as vagas foram descartadas (dados júnior)

| Motivo | Qtd. |
|---|---|
| Fora das cidades aceitas e sem home office | 16 |
| Só termo fraco, sem termo forte | 12 |
| Híbrido fora das cidades aceitas | 10 |
| Título com “pleno” | 9 |
| Título com “senior” | 8 |
| Menos termos que o mínimo | 8 |
| Título com “estagi” | 7 |
| Título com “sr” | 5 |
| Título com “especialista” | 3 |
| Outros (logística, supervisor, gerente, coordenador, lead, contas a pagar) | 7 |

Os descartes de localidade e senioridade estão corretos e mostram o filtro
funcionando. Em enfermagem quase tudo passa porque o perfil é intencionalmente
amplo (`minimo_de_termos = 1` e termo forte `enfermag` casa com qualquer texto
que cite enfermagem).

## 3. Qualidade das vagas aprovadas (o ponto crítico)

### Dados júnior — precisão estimada em ~36%

Das 21–28 aprovadas, uma parte relevante **não era vaga de dados**:

| Vaga aprovada | Por que passou | Veredito |
|---|---|---|
| Analista de Gestão de Pessoas | descrição cita “banco de dados” (LGPD) | falso positivo |
| Analista Jurídico | descrição cita “dados pessoais” | falso positivo |
| Analista de Performance Comercial | “analis” + “dados” na descrição | falso positivo |
| Assistente de Administração Fiduciária | “dados” na descrição | falso positivo |
| Assistente de Projeto / de Engenharia (documentação) | termos genéricos na descrição | falso positivo |
| Analista de Operações Júnior | “analis” + termos fracos | fora do alvo |
| Analista de Dados **PL** | “pl” não era proibido | nível errado (corrigido) |
| **CIENTISTA DE DADOS IV** | numeral romano não é detectado | nível sênior passou |

Vagas realmente boas que apareceram: *Pessoa Analista de Dados Júnior*
(Datum), *ANALISTA DE WEB ANALYTICS JR* (Magalu), *Analista de Dados DB2*,
*Analista de BI*, *Cientista de Dados*, *Engenheiro de Dados Multicloud*,
*Data Engineer*, *Analista de IA*.

### Enfermagem — precisão estimada em ~92%

Das 49 aprovadas, 4 claramente fora do alvo: *Farmacêutico Clínico*,
*Auxiliar de Contas Médicas* (faturamento), *Propagandista Médico* (vendas) e
*Acadêmico de Enfermagem* (estudante). O restante é enfermagem de verdade
(hospitalar, CTI, oncologia, auditoria assistencial, técnico de enfermagem).
Também apareceram vagas sem link (9 de 49), que não servem para abrir/candidatar.

## 4. Experimento: filtro padrão vs. exigir termo forte no título

Mesma coleta (119 vagas), duas configurações:

| Configuração | Aprovadas | Precisão estimada |
|---|---|---|
| Padrão (termo forte em título **ou** descrição) | 28 | **~36%** |
| `exigir_termo_forte_no_titulo = true` | 8 | **~88%** |

No modo estrito sobraram exatamente as vagas de dados: *Data Engineer*,
*Engenheiro de Dados Multicloud*, *Analista de BI*, *Analista de Dados DB2*,
*Cientista de Dados*, *CIENTISTA DE DADOS IV*, *Pessoa Analista de Dados
Júnior* e *Analista de Dados (Planejamento de vendas)*.

O custo é o alcance: vagas de **IA** (“Analista de IA”, “Automação e IA
aplicada”) caíram porque “ia” não é termo forte (sigla de 2 letras casaria com
o verbo “ia” nas descrições) e “inteligência artificial” não estava no título
literal. Recomendação: usar o modo estrito para quem prioriza precisão e
manter o padrão para quem prefere ver tudo.

## 5. Defeitos e ajustes decorrentes do teste

Corrigidos nesta rodada:
- **“PL” de pleno** passava no filtro → incluído em `termos_proibidos_titulo`.
- **“BI”** não era termo forte → incluído (casa só a palavra inteira).
- **Falsos positivos por descrição** → novo `exigir_termo_forte_no_titulo`
  (desligado por padrão), com checkbox na interface e teste de regressão.

Registrados como limitação (não corrigidos agora):
- **Níveis em número romano** (“Analista IV”) não são detectados.
- **Salários do site são inconsistentes**: apareceram “R$ 70” e “R$ 19” em
  vagas cujo valor real provavelmente era outro; 81% das vagas de dados nem
  informam salário. O campo deve ser lido como “informado pelo site”, não como
  verdade.
- **Vagas sem link** entram na planilha (9/49 em enfermagem); são inúteis para
  abrir/candidatar e poderiam ser descartadas por uma opção futura.
- **Descrição é a principal fonte de falso positivo** em buscas amplas; o modo
  estrito resolve, mas reduz o volume.
- **Uma única fonte ao vivo (Indeed)**; LinkedIn e Glassdoor não foram testados
  por risco de bloqueio.

## 6. Conclusão do teste

O produto **funciona de ponta a ponta com dados reais**: coleta, deduplica,
filtra por cidade/senioridade/home office, salva, gera a planilha com aba de
auditoria e mantém o histórico. A experiência de “usuário” é boa, mas a
**precisão é o gargalo**: no modo padrão, mais da metade das vagas aprovadas em
dados não era do alvo. A nova opção de exigir termo forte no título resolve
isso (88%) ao custo de volume.

Para uso pessoal, o ajuste recomendado é: perfil com `pleno/sênior/sr` no
título, `exigir_termo_forte_no_titulo = true` e lista de termos forte bem
calibrada. Para virar produto, precisão e confiança são justamente o que se
pode cobrar — ver [`ESTUDO_SAAS.md`](ESTUDO_SAAS.md).
