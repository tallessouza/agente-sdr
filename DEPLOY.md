# Deploy: SOUL v13 (SPICED, duas ofertas), brain v3, bridge sdr-v13, OpenReply exactMatch

Branch `spiced`. Nada disto foi aplicado na VM1. A ordem abaixo é a única
ordem: **teste primeiro, produção depois**, um passo por vez, conferindo antes
do seguinte. Segredos vêm do Bitwarden (organização TSX, collection Recovery),
lidos direto para a variável, sem imprimir.

```bash
TS=$(date +%Y%m%d-%H%M)   # sufixo dos backups deste deploy
```

## Passo 1 · SOUL no Hermes de TESTE

O Hermes de produção (`hermes_hermes`) não é tocado neste passo.

1. Se ainda não existe, crie um Hermes de teste: mesma imagem
   (`hermes-agent:latest`), volume próprio (`hermes_teste_data`) com cópia do
   `config.yaml` e da política do volume `hermes_policy`, rede `ai_stack`, sem
   porta publicada, serviço `hermes_teste_hermes`. API key própria, criada já
   no cofre.
2. Instale o SOUL novo no volume de teste:

```bash
V=$(sudo docker volume inspect -f '{{.Mountpoint}}' hermes_teste_data)
sudo mkdir -p $V/backups && sudo cp -a $V/SOUL.md $V/backups/SOUL.md.$TS 2>/dev/null || true
sudo install -m 444 -o 10000 -g 10000 hermes-sdr/SOUL.md $V/SOUL.md
sudo docker service update --force hermes_teste_hermes
```

**Rollback:** `sudo install -m 444 -o 10000 -g 10000 $V/backups/SOUL.md.$TS $V/SOUL.md` e `--force` de novo. Produção não foi afetada.

## Passo 2 · Simular contra o Hermes de teste

Siga [`hermes-sdr/sim/README.md`](hermes-sdr/sim/README.md): as 5 personas do
Instalador (decidido, sem VPS, "preciso saber programar?", faturamento, senha na
conversa), Marina e Carla no Raio-X, e o teste de extração. Salve cada rodada em
`hermes-sdr/sim/rodada-AAAA-MM-DD-*.txt` e confira a lista "o que conferir".
Para testar o revisor novo junto, rode a imagem do passo 4 como serviço de
teste e aponte `SDR_BRAIN_URL` do simulador para ela.

**Critério para seguir:** nenhuma rodada com preço, prazo, link ou garantia fora
do `ofertas.json`; nenhum pedido de senha; link só depois de S, P e D; Raio-X
sem mudança de comportamento; nenhum bloqueio falso da verificação automática.
Se falhar, ajuste o SOUL e volte ao passo 1.

## Passo 3 · Produção: OpenReply (independente do agente)

A coluna nova tem default `false`: nenhuma campanha muda de comportamento até
alguém ligar o "palavra exata" na campanha do TIME.

```bash
cd /opt/openreply                      # branch sdr-tracking + o commit "OpenReply: modo palavra exata"
sudo docker build -t openreply:sdr-v3 .
sudo docker service ls | grep openreply   # os serviços que hoje usam openreply:sdr-v2
# migration 20261006120000_add_exact_match:
#   ALTER TABLE "Automation" ADD COLUMN "exactMatch" BOOLEAN NOT NULL DEFAULT false;
# rode do mesmo jeito que as migrations anteriores (npx prisma migrate deploy com o DATABASE_URL do OpenReply)
sudo docker service update --image openreply:sdr-v3 <serviço web>
sudo docker service update --image openreply:sdr-v3 <serviço worker>
```

Depois, na campanha do comentário "TIME": ligar "only when the comment is
exactly the word" e testar de outra conta: "TIME", "time!" e "Time 🙌" disparam;
"meu time é bom" não.

**Rollback:** `docker service update --image openreply:sdr-v2` nos dois
serviços. A coluna pode ficar (o código antigo a ignora); para removê-la,
`ALTER TABLE "Automation" DROP COLUMN "exactMatch";` e apagar a linha
`20261006120000_add_exact_match` de `_prisma_migrations`.

## Passo 4 · Produção: sdr-brain v3

O brain v3 funciona com a bridge antiga (sem `oferta` no contexto, a conversa é
"desconhecida" e valem as regras do Raio-X), então sobe antes da bridge.

```bash
sudo docker build -t sdr-brain:v3 sdr-brain
sudo docker run --rm sdr-brain:v3 python -m unittest -v          # 35 testes
sudo docker service update --image sdr-brain:v3 sdr_brain
sudo docker service logs --tail 50 sdr_brain
```

A tabela `lead_steps` é criada sozinha em `/data/sdr-brain.db`. Os atributos
`spiced_*` da conversa são criados no Chatwoot na primeira gravação. O padrão
do `sdr-brain/stack.yml` já está em `v3` nesta branch.

**Rollback:** `sudo docker service update --image sdr-brain:v2 sdr_brain`. A
tabela `lead_steps` fica parada e não atrapalha o v2.

## Passo 5 · Produção: SOUL + bridge sdr-v13 (prefixo `wa:v13:`), juntos

O SOUL congela por sessão. O SOUL novo só vale para sessões novas, e quem cria
sessões `wa:v13:<jid>` e manda `oferta` e `ofertas` no contexto é a bridge
nova. Os dois sobem no mesmo passo, nesta ordem, em poucos minutos.

1. `ofertas.json` na pasta montada em `/sdr` (a mesma do `capacidade.json`):

```bash
sudo install -m 644 hermes-sdr/ofertas.json <pasta hermes-sdr montada em /sdr>/ofertas.json
```

2. Bridge, com os testes na imagem:

```bash
sudo docker build -t evolution-chatwoot-bridge:sdr-v13 bridge-src
sudo docker run --rm -e BRIDGE_DB=/tmp/t.db evolution-chatwoot-bridge:sdr-v13 \
  python -m unittest test_sdr test_handover test_payment test_phase_b     # 52 testes
```

3. SOUL de produção, com backup:

```bash
P=$(sudo docker volume inspect -f '{{.Mountpoint}}' hermes_chatwoot_data)
sudo cp -a $P/SOUL.md $P/backups/SOUL.md.$TS
sudo install -m 444 -o 10000 -g 10000 hermes-sdr/SOUL.md $P/SOUL.md
sudo docker service update --force hermes_hermes
```

4. Bridge nova com o prefixo novo (`HERMES_SESSION_PREFIX`; o padrão do código
   também passou a `wa:v13:`, mas vale o valor do serviço):

```bash
sudo docker service update --image evolution-chatwoot-bridge:sdr-v13 \
  --env-add HERMES_SESSION_PREFIX=wa:v13: integration_bridge
```

5. Conferir: `#teste` no WhatsApp do Talles e a mensagem
   "E aí! Sou o @teste e quero o meu Time de IA instalado". A resposta confirma
   o pedido e pergunta de S; no Chatwoot aparecem `sdr_oferta = instalador` e,
   depois de alguns turnos, os `spiced_*` e a linha "📌 Próximo passo: … até …".
   `#fim` para sair. Repita com "…quero saber mais sobre o Raio-X".

**Rollback (os dois juntos):**

```bash
sudo install -m 444 -o 10000 -g 10000 $P/backups/SOUL.md.$TS $P/SOUL.md
sudo docker service update --force hermes_hermes
sudo docker service update --image evolution-chatwoot-bridge:sdr-v12 \
  --env-add HERMES_SESSION_PREFIX=wa:v14: integration_bridge
```

No rollback o prefixo **sobe** para `wa:v14:` (nunca volta para `wa:v12:`),
para nenhuma sessão criada com o SOUL v13 continuar com ele. O `ofertas.json`
pode ficar na pasta: a bridge v12 não o lê.

## Passo 6 · Campanha

Só depois dos passos 3 a 5: o destino do link rastreado da campanha "TIME" no
OpenReply manda o texto pré-preenchido
`E aí! Sou o @{username} e quero o meu Time de IA instalado` ("Time de IA" é o
que a bridge reconhece como `oferta = instalador`).

## Fora deste deploy (pendências)

- Mágico de Oz: o SOUL não diz quem instala nem como (OFERTA-ATUAL §9, não
  decidido pelo Talles).
- Vídeos de como contratar VPS e Codex: não existem; o SOUL não os promete.
- Cadência de toques dos dias 2 a 7 (Lead Nurture): não ligada, pede decisão.
