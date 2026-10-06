# Portainer e Traefik

Portainer: https://manager.talles.dev

Traefik 3.7.13 roda como serviço da stack `traefik`, com imagem fixada por digest.
O Portainer existente continua como container standalone, com volume
`portainer_data`, reinício automático e acesso alternativo em HTTPS na porta 9443.
O Swarm está ativo; isso não migra automaticamente o container Portainer para serviço.

## Implantação

```bash
sudo docker stack deploy -c traefik-stack.yml traefik
sudo docker service ps traefik_traefik
sudo docker service logs --tail 50 traefik_traefik
```

A stack foi criada via CLI. Aparece no Portainer como stack externa, com controle
limitado; os arquivos neste diretório são a fonte para atualizações.
Ao alterar `traefik-dynamic.yml`, incremente o nome `routes_vN` (atualmente `routes_v4`)
no arquivo da stack,
pois Docker configs são imutáveis.

## Rede e certificados

- DNS A `manager.talles.dev` aponta para `13.140.42.181`, com proxy Cloudflare.
- Cloudflare deve usar SSL/TLS Full (strict).
- Traefik usa rede host, escutando exclusivamente `13.140.42.181:80` e `:443`.
  Isso preserva o Tailscale, que já escuta em seu próprio IP na porta 443.
- HTTP redireciona para HTTPS. O desafio ACME HTTP-01 usa porta 80.
  Mantenha essa porta acessível para renovação e não bloqueie
  `/.well-known/acme-challenge/` na Cloudflare.
- Certificados e chave da conta ACME ficam no volume `traefik_certificates`.
  Faça backup desse volume junto com `portainer_data`; não publique seu conteúdo.
- O backend atual é `https://127.0.0.1:9443`. A verificação do certificado
  autoassinado é desativada apenas nesse transporte local.
- Portas 8000 e 9443 do Portainer continuam publicadas. Não há dashboard
  Traefik exposto publicamente.

## Expansão

O provider Swarm está habilitado com exposição desativada por padrão.
Labels de novos serviços ficam em `deploy.labels`. Como Traefik usa rede host,
não presuma que IPs internos de redes overlay sejam alcançáveis: novos backends
precisam de endereço/porta alcançáveis pelo host. `useBindPortIP` está habilitado
para usar portas publicadas quando disponíveis. Antes de subir n8n, definir a
rede e a proteção das portas de backend, ou migrar o proxy para overlay com uma
estratégia de publicação que preserve o Tailscale.

O proxy está fixado em `vmi3581839` porque IP e certificados são locais. Uma
segunda VM não dá alta disponibilidade automática ao proxy ou ao Portainer.
O n8n e seus PostgreSQL/Redis/workers ainda não foram implantados.
Na instalação atual, a licença do Evolution Go está ativa e o serviço
`integration_bridge` está configurado com uma inbox de API do Chatwoot.
As credenciais ficam somente nos ambientes dos serviços Swarm; não as publique
no repositório.
Abra `https://evolution.talles.dev/manager/login`, informe a URL
`https://evolution.talles.dev` e a `GLOBAL_API_KEY` do serviço Evolution, e conclua
o registro por Magic Link. Depois disso, verifique `/license/status` antes de
testar o webhook.
A instância `whatsapp` já foi criada e seu webhook aponta para
`http://bridge:8080/evolution/webhook`; falta apenas escanear o QR Code para
marcá-la como conectada.

## Bridge Evolution ↔ Chatwoot

`bridge-src` fornece o serviço opcional que sincroniza mensagens da Evolution API
com uma inbox de API do Chatwoot e encaminha respostas do Hermes. Execute-o com
`EVOLUTION_INSTANCE`, `EVOLUTION_API_KEY`, `CHATWOOT_INBOX_IDENTIFIER` e
`CHATWOOT_API_ACCESS_TOKEN`; para respostas do Chatwoot também são necessários
`CHATWOOT_ACCOUNT_ID` e `CHATWOOT_APP_TOKEN`. Configure o webhook da Evolution para
`POST /evolution/webhook` e o webhook de mensagem criada do Chatwoot para
`POST /chatwoot/webhook`. Se `BRIDGE_WEBHOOK_TOKEN` estiver definido, ambos exigem
`Authorization: Bearer <token>`. O bridge usa o endpoint Evolution
`/send/text` por padrão (defina `EVOLUTION_SEND_PATH=/message/sendText/{instance}`
para a API Evolution clássica) e usa `/send/media` para anexos do Chatwoot,
com fallback para `/message/sendMedia/{instance}`. O bridge aceita o evento
`MESSAGES_UPSERT`.

O inventário do comportamento do canal WhatsApp do Hermes e as lacunas de
paridade estão em [`HERMES_CHANNEL_LEDGER.md`](HERMES_CHANNEL_LEDGER.md).

Áudios recebidos são transcritos localmente pela bridge antes de serem enviados
ao Hermes. A configuração usa `BRIDGE_STT_ENABLED=true`, modelo `small` e idioma
`pt`; a primeira mensagem pode demorar enquanto o modelo é baixado. O áudio
original permanece no Chatwoot e a transcrição é incluída no contexto do agente.
PDFs, DOCX e XLSX recebidos também têm o texto extraído localmente e incluído no
contexto do Hermes; PDFs escaneados passam por OCR e o arquivo original permanece
anexado no Chatwoot.
Para habilitar grupos de forma explícita, use `BRIDGE_GROUP_POLICY=open` ou
`BRIDGE_GROUP_POLICY=allowlist` com `BRIDGE_GROUP_ALLOW_FROM` contendo os JIDs.
O padrão continua `disabled` até a política de grupos ser revisada.
Menções podem ser obrigatórias em grupos com `BRIDGE_REQUIRE_MENTION=true` e
`BRIDGE_MENTION_PATTERNS=@Hermes,/hermes`. A bridge mantém um outbox SQLite
persistente para texto e anexos quando a Evolution está indisponível; consulte
`GET /health` para `outbox_pending`, `stt` e `ocr`.
O serviço também monta o volume `hermes_chatwoot_data` como `/hermes-data` somente
leitura. Assim, quando o Hermes responde com `MEDIA:/opt/data/arquivo.ext`, a bridge
valida o caminho dentro dessa raiz, envia o arquivo nativamente pelo Evolution e o
anexa à mesma mensagem no Chatwoot.
Revogações e receipts da Evolution também são projetados para a mensagem
correspondente no Chatwoot quando o ID já foi sincronizado; edições ficam no
`event_history` porque a API atual do Chatwoot não permite substituir o conteúdo.

As primitivas nativas de saída usam `content_attributes` na mensagem de saída do
Chatwoot. Os formatos aceitos são `{"whatsapp_location":{"latitude":-23.5,
"longitude":-46.6,"name":"Local"}}`, `{"whatsapp_poll":{"question":"...",
"options":["A","B"],"selectable_count":1}}` e
`{"whatsapp_reaction":{"message_id":"ID","emoji":"👍"}}`.

Para assumir uma conversa, responda pelo celular ou pelo Chatwoot. A bridge
mantém a mensagem no histórico e aplica a label `hermes-pausado`; enquanto ela
existir, o Hermes não gera respostas. Remova essa label para retomar o agente,
que receberá o contexto acumulado da intervenção.

Fixtures de texto, mídia, reação, grupo e saída ficam em
`bridge-src/fixtures/`. Para validar e simular todos os payloads sem chamar
Evolution, Chatwoot ou Hermes:

```bash
sudo docker run --rm -e PYTHONPATH=/app -e BRIDGE_DB=/tmp/fixture.db \
  -e FIXTURES_DIR=/fixtures/fixtures \
  -v "$PWD/bridge-src/validate_fixtures.py:/fixtures/validate_fixtures.py:ro" \
  -v "$PWD/bridge-src/fixtures:/fixtures/fixtures:ro" \
  evolution-chatwoot-bridge:latest python /fixtures/validate_fixtures.py
sudo docker run --rm -e PYTHONPATH=/app -e BRIDGE_DB=/tmp/fixture.db \
  -e FIXTURES_DIR=/fixtures/fixtures \
  -v "$PWD/bridge-src/simulate_fixtures.py:/fixtures/simulate_fixtures.py:ro" \
  -v "$PWD/bridge-src/fixtures:/fixtures/fixtures:ro" \
  evolution-chatwoot-bridge:latest python /fixtures/simulate_fixtures.py
```

## Verificação

```bash
curl -I https://manager.talles.dev
curl --resolve manager.talles.dev:443:13.140.42.181 -I https://manager.talles.dev
curl https://manager.talles.dev/api/status
```

Em 2026-09-25: HTTPS público e direto na origem retornaram 200, API informou
Portainer 2.45.1, certificado Let's Encrypt emitido para `manager.talles.dev`.

## Credenciais e fluxo bidirecional

As credenciais atuais ficam em `CREDENTIALS.md` (arquivo local ignorado pelo Git). O
fluxo de saída usa o webhook do inbox API no endereço interno `bridge:8080` e o token
da instância Evolution (`whatsapp`) no header `apikey`. O Chatwoot precisa de
`SAFE_FETCH_ALLOW_PRIVATE_NETWORK=true` em Rails e Sidekiq para aceitar o webhook
privado do Docker. Mensagens enviadas pelo Chatwoot são encaminhadas para a Evolution;
mensagens recebidas pela Evolution entram no mesmo inbox e seguem para o Hermes.
O Hermes usa o OmniRoute interno (`omniroute_omniroute:20129`) com o provider
Antigravity já ativo na conta `lsuperagentes@gmail.com`; não foi necessário copiar a
credencial do Codex desta VM. A execução ponta a ponta foi validada em 2026-09-25.
