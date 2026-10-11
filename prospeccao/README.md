# Prospecção: pipeline versionado

Peça 1 de `screener/17-prospeccao/PROSPECCAO-NATIVA.md`. Uma campanha nova roda do zero até a fila só com um
`campanha.json` e os comandos abaixo. Node 22, sem dependências.

## Campanha

`campanhas/<slug>/campanha.json` é a única coisa que muda entre campanhas (exemplo em `campanhas/exemplo/`):

```json
{
  "slug": "odonto-litoral-sc-2026-10",
  "cidades": [{"nome": "Itajaí", "uf": "SC"}],
  "nichos": ["clínica odontológica"],
  "por_busca": 25,
  "teto_usd": {"coleta": 10, "instagram_raso": 2, "instagram_fundo": 8},
  "prioridade": {"cidades_primeiro": ["Itajaí"], "ordem": "avaliacoes_desc"},
  "camadas": {"site": true, "instagram_raso": true, "instagram_fundo": "top:150", "decisor": "top:150"}
}
```

## Do zero até a fila

```bash
cd prospeccao
node prospeccao.mjs coletar    <slug>                    # Maps (Apify), com teste de 5 lugares antes
node prospeccao.mjs enriquecer <slug> --camada site      # site: serviços, WhatsApp, horário, gancho, dias abertos
node prospeccao.mjs enriquecer <slug> --camada ig-raso   # perfil pela Meta (grátis); Apify só para quem falhar
node prospeccao.mjs enriquecer <slug> --camada ig-fundo  # comentários dos posts (Apify)
node prospeccao.mjs enriquecer <slug> --camada decisor   # CNPJ/QSA, site, bio (grátis)
node prospeccao.mjs qualificar <slug>                    # lente de riqueza: nota, motivos, ordem
node prospeccao.mjs fila       <slug>                    # monta o dossiê, ordena pela lente, mostra os primeiros
node prospeccao.mjs custo      <slug> [--conferir]       # gasto por etapa (--conferir lê o cobrado na API do Apify)
node prospeccao.mjs status     <slug>                    # o que já foi feito e o próximo passo
```

- **Simulação é o padrão.** O Apify não é chamado (só a estimativa) e nada vai para o banco central ou para a fila.
  O que iria ao banco fica em `banco-simulado/<etapa>.json`. As leituras grátis (sites, Meta, BrasilAPI) rodam.
- **`--aplicar`** gasta no Apify e grava na produção (decida antes, pelo cartão do `AGENTS.md`):
  - cada etapa grava no banco central pelo mesmo caminho de `scripts-origem/banco.mjs`
    (ssh na VM1, `importar_leads.py --stdin`; com `BANCO_SIMULAR=1`, faz e desfaz);
  - `fila --aplicar` chama `prospeccao.enqueue` na bridge. O que já está na fila fica como está;
    `--atualizar` renova o dossiê. Para reordenar a fila existente, use `17-prospeccao/scripts/aplicar-ordem-fila.py`.
- **Teto:** antes de cada etapa paga, a estimativa somada ao já gasto é comparada com `teto_usd`. Se passar, a etapa
  aborta sem gastar (código de saída 2). Cada run recebe como `maxTotalChargeUsd` só o que sobra do teto.
  O custo de cada run vai para `<etapa>.log` e `custos.json`.
- **Retomada:** rodar o mesmo comando de novo continua de onde parou. Os caches ficam em `cache/`, e uma run do Apify
  interrompida é retomada pela mesma runId (`cache/runs-pendentes.json`).
- **Credenciais** só do cofre, lidas para a memória: `Apify · screener · pool` (ids em `lib/cofre.mjs`) e
  `Meta · ads TSX · token sistema`. O destravamento usa `~/.bw/sessao.sh`.
- **Revisão manual do decisor:** `campanhas/<slug>/ajustes-decisor.json`, no mesmo formato do `ajustes.json` de 09/10.

## Testes e fixtures

```bash
node --test test/*.test.mjs                   # 28 testes; Apify, Meta, sites, BrasilAPI e ssh falsos
node prospeccao.mjs coletar exemplo --fixtures test/fixtures/exemplo   # qualquer comando roda com as fixtures
node test/fixtures/gerar.mjs                  # regenera as fixtures (dados fictícios)
```

## De onde veio cada parte (os scripts antigos continuam como estão)

| Módulo | Origem em `screener/17-prospeccao/` |
|---|---|
| `lib/maps.mjs` | `scripts-origem/maps/run.mjs`, `processar.mjs` |
| `lib/site.mjs`, `lib/enriquecer.mjs` | `scripts-origem/enriquecer/baixar-sites.mjs`, `montar.mjs`, `comum.mjs` |
| `lib/instagram.mjs`, `lib/nomes.mjs` | `scripts-origem/ig-lista/` (`meta`, `apify1`, `build1`, `camada2`, `comum`, `nomes`) |
| `lib/decisor.mjs` | `scripts-origem/decisores/` (`baixar`, `cnpj`, `extrair`, `busca`, `decidir`, `ig`, `final`) |
| `lib/riqueza.mjs`, `lib/cnpj.mjs` | `scripts/qualificar-riqueza.mjs`, `lente-riqueza.mjs` |
| `lib/banco.mjs` | `scripts-origem/banco.mjs`, `ig-lista/enviar-fila.sh` |
| `lib/apify.mjs`, `lib/cofre.mjs` | `scripts-origem/ig-lista/apifyrun.mjs`, `pool.mjs` |

Novo aqui: teto e custos por campanha, retomada de run, `dias_abertos` como etapa, dossiê remontado por camada.
Também foi corrigido o `nomes.mjs`: "Depoimento da Juliana" deixava o nome da cliente passar.
