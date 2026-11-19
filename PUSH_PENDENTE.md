# Push pendente — o que falta para publicar

O trabalho está **commitado localmente** e íntegro, mas o `git push` para
`Leo-bsb/jobscraper` foi **recusado pelo GitHub** por falta de permissão de
escrita no token usado.

- Commit pronto: `9c38ebb` — *Revisao 2026.11: seguranca, robustez e qualidade*
- Branch: `main` (2 commits à frente de `origin/main` no momento da revisão)
- Bundle com o histórico completo: `../jobscraper-2026.11.bundle`
  (verificado com `git bundle verify`: história completa, HEAD `9c38ebb`)

## Evidência do bloqueio

```
$ git push https://github.com/Leo-bsb/jobscraper.git main
remote: Permission to Leo-bsb/jobscraper.git denied to Leo-bsb.
fatal: ... The requested URL returned error: 403
```

E, pela API (criar uma referência de teste, sem alterar conteúdo):

```
POST /repos/Leo-bsb/jobscraper/git/refs
403 {"message":"Resource not accessible by personal access token"}
```

O token consegue **ler** o repositório, mas não escrever. Como o repositório é
público, a leitura funciona mesmo que ele **não esteja** na lista de
repositórios selecionados do token — então há duas causas prováveis, e as duas
precisam ser conferidas:

1. o token não tem **Contents: Read and write**; e/ou
2. `Leo-bsb/jobscraper` **não está** entre os repositórios selecionados do token.

Não havia outra credencial do GitHub na máquina (Git Credential Manager sem
entradas; sem `GH_TOKEN`/`GITHUB_TOKEN`; sem `.netrc`/`.git-credentials`).

## Permissões necessárias

Para publicar este commit, o token (fine-grained) precisa de:

| Permissão | Nível | Por quê |
|---|---|---|
| **Contents** | Read and write | enviar commits |
| **Workflows** | Read and write | o commit altera/cria arquivos em `.github/workflows/` |
| Repository access | incluir `Leo-bsb/jobscraper` | o repositório precisa estar na lista do token |

Token fine-grained pode ser **editado** depois de criado: GitHub → *Settings*
→ *Developer settings* → *Fine-grained tokens* → selecione o token → *Edit*
(ajuste as permissões e salve). Alternativamente, crie um novo token com as
permissões acima. Tokens clássicos precisam do escopo `repo` + `workflow`.

## Como publicar

Com o token já configurado no Git Credential Manager (ou embutido na URL):

```bash
cd jobscraper
git push https://github.com/Leo-bsb/jobscraper.git main
```

Ou, explicitamente:

```bash
git push https://<USUARIO>:<TOKEN_COM_ESCRITA>@github.com/Leo-bsb/jobscraper.git main
```

Alternativa a partir do bundle (não depende deste working tree):

```bash
git clone "jobscraper-2026.11.bundle" jobscraper-restaurado
cd jobscraper-restaurado
git remote set-url origin https://github.com/Leo-bsb/jobscraper.git
git push origin main
```

Depois do push, confira na aba **Actions**:

1. Workflow **Testes** deve rodar em `push` e ficar verde.
2. Se quiser os executáveis, rode **Gerar BuscaVagas.exe +
   CandidatarVagas.exe** manualmente.

## Cuidados

- **Não** faça commit de `perfil.json`, `filtros.json`, `vagas.db`,
  `vagas_da_semana*.xlsx`, `buscavagas.log`, `cartas/`, `curriculos_adaptados/`
  ou `navegador_indeed/` — todos já estão no `.gitignore`.
- Não cole o token em arquivos versionados, issues ou prints.
- O token usado nesta revisão expira em **20/11/2026**; se ele for recriado,
  atualize apenas o credential manager, não o `git remote` (que está sem
  credencial embutida).
