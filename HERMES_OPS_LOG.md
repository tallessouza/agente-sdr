# Log operacional do Hermes (SDR/suporte no WhatsApp)

Registro cronológico de tudo que foi feito, decidido ou descoberto sobre o
Hermes que roda no Portainer (`hermes_hermes`) e a cadeia que o alimenta
(Evolution Go → bridge → Chatwoot → Hermes → OmniRoute). Leia antes de mexer;
acrescente uma entrada ao final de cada sessão. Regras em [`AGENTS.md`](AGENTS.md).

Nunca escreva segredo aqui (tokens, senhas, API keys, `GLOBAL_API_KEY`): este
arquivo é versionado. Credenciais ficam em `CREDENTIALS.md` / `creds`, que são
ignorados pelo Git.

---

## Estado atual (atualize esta seção quando algo mudar)

Última revisão: 2026-09-27 20:40, depois das fases A e B do SDR.

### Serviços

| Serviço Swarm | Imagem | Papel |
|---|---|---|
| `hermes_hermes` | `hermes-agent:latest` | Agente. API OpenAI-compatible em `hermes:8642/v1`. |
| `integration_bridge` | `evolution-chatwoot-bridge:sdr-v12` | Bridge Evolution ↔ Chatwoot ↔ Hermes + camada SDR (código em `bridge-src/`; `hermes-sdr/` montado em `/sdr`). |
| `sdr_brain` (stack `sdr`) | `sdr-brain:v2` | Revisor pré-envio, supervisor, agente de FUP e enriquecimento via OpenReply (código em `sdr-brain/`). Sem porta publicada. |
| `evogo_evolution` + `evogo_postgres` | `evoapicloud/evolution-go:latest` | Transporte WhatsApp (API não oficial). Instância `whatsapp`. |
| `chatwoot_rails`/`_sidekiq`/`_postgres`/`_redis` | `chatwoot/chatwoot:v4.18.0` | Inbox humana e histórico (`chatwoot.talles.dev`, conta 1). |
| `omniroute_omniroute` + `omniroute_redis` | `diegosouzapw/omniroute:latest` | Roteador de LLM; provider Antigravity nas contas `lsuperagentes@gmail.com` (prioridade 1) e `ebtalles@gmail.com` (prioridade 2). |
| `traefik_traefik` | `traefik:v3` | Proxy/TLS. |
| `openreply_*` | `openreply:5760181` | Automação de Instagram (sem relação com o Hermes). |

### Hermes

- Modelo: `agy/gemini-3.7-flash-high` via provider `custom` (Sonnet testado e revertido em 2026-09-28),
  `base_url: http://omniroute_omniroute:20129/v1` (em `/opt/data/config.yaml`).
- Volumes: `hermes_chatwoot_data` → `/opt/data` (rw); `hermes_policy` →
  `/opt/hermes-policy` (ro). `HERMES_MANAGED_DIR=/opt/hermes-policy`.
- Roda como UID/GID 10000 (`hermes`), não mais root.
- Política gerenciada (`/opt/hermes-policy/config.yaml`): `api_server` só expõe
  `web`, `vision`, `clarify` (`skills` desabilitado em 2026-09-27). Desabilitados: `terminal`, `file`,
  `process`, `patch`, `code_execution`, `delegation`, `cronjob`, `skills_hub`.
  `skills.write_approval` e `memory.write_approval` = true; approvals
  `unattended_mode: deny`. Detalhes em `HERMES_SECURITY_POLICY.md`.
- `/opt/data/SOUL.md` e `/opt/data/skills/` estão somente leitura.
- Persona: `hermes-sdr/SOUL.md` instalado em `/opt/data/SOUL.md`. O prompt congela por sessão; a bridge usa `X-Hermes-Session-Id: wa:v12:<jid>` (`HERMES_SESSION_PREFIX`). Trocar a persona exige subir o prefixo.
- A bridge envia uma mensagem `system` por requisição com contexto confiável
  (hora, capacidade de `hermes-sdr/capacidade.json`, fotos aprovadas, ficha do
  lead, orientações do supervisor). A persona vem do `SOUL.md`. Arquitetura
  completa em `hermes-sdr/ARQUITETURA.md`.

### Bridge (comportamentos que afetam o SDR)

- Acúmulo de mensagens por contato: `HERMES_MESSAGE_DEBOUNCE_SECONDS=10`.
- Handover humano: resposta pelo celular ou pelo Chatwoot aplica a label
  `hermes-pausado`; enquanto existir, o Hermes não responde. Remover a label
  retoma com o contexto acumulado. Resposta gerada durante uma intervenção é
  descartada.
- Mídia: imagens vão ao Hermes como `image_url`; áudio é transcrito localmente
  (faster-whisper `small`, pt) e entra como `[Transcrição do áudio]: ...`;
  PDF/DOCX/XLSX/PPTX/ODT viram texto (`[Texto extraído do documento]`), PDF
  escaneado passa por OCR.
- Eventos estruturados (Pix, template, botões) vão no turno textual entre
  `[EVENTO_ESTRUTURADO_BRIDGE]...[/EVENTO_ESTRUTURADO_BRIDGE]` e em
  `metadata.bridge_structured_events`.
- Saída de mídia do Hermes: `MEDIA:/opt/data/<arquivo>` é enviado nativamente
  (volume montado read-only na bridge em `/hermes-data`).
- Grupos: `BRIDGE_GROUP_POLICY=disabled` (padrão).
- Paridade completa com o adapter WhatsApp nativo do Hermes, arquivo a arquivo:
  `HERMES_CHANNEL_LEDGER.md`.

---

## Riscos abertos para virar SDR (prioridade)

1. ~~**`SOUL.md` ainda é o padrão da Nous Research.**~~ Resolvido na fase A. Conteúdo atual começa com
   "You are Hermes Agent, built by Nous Research". Se um lead perguntar "quem é
   você / que IA é essa / como você funciona", o agente se identifica como
   Hermes da Nous. Precisa ser substituído pela persona SDR.
2. ~~**Nenhuma regra de sigilo da estrutura.**~~ Resolvido: regra 7 do `SOUL.md`, guardrail determinístico e revisor. Bateria sem vazamento. Nem o `SOUL.md` nem o rascunho
   `prompt.md` proíbem revelar: nome do agente/framework (Hermes, Nous), modelo
   (Gemini/Antigravity/OmniRoute), Chatwoot, Evolution, bridge, Portainer,
   domínios internos, toolsets, lista de skills, conteúdo do próprio prompt,
   caminhos (`/opt/data`, `MEDIA:`), os marcadores `[EVENTO_ESTRUTURADO_BRIDGE]`,
   `[Transcrição do áudio]`, `[Texto extraído do documento]` e o histórico
   injetado. Esse é o requisito central do trabalho de SDR.
3. **Skills padrão expostas.** O toolset `skills` está liberado e
   `/opt/data/skills` contém o bundle padrão (`apple`, `autonomous-ai-agents`,
   `creative`, `devops`, `email`, `media`, `note-taking`, `productivity`,
   `research`, `social-media`, `software-development`, `web`). Um lead pode
   pedir para listá-las. Reduzir ao que o SDR usa ou retirar `skills` do
   `api_server`.
4. **`web` liberado.** Útil para pesquisa, mas também pode ser usado por um
   lead para fazer o agente buscar/ler conteúdo arbitrário (prompt injection
   via página). Avaliar se o SDR precisa.
5. **Gate de capacidade:** mecanismo pronto (`hermes-sdr/capacidade.json`), mas o arquivo ainda não existe, então o agente não fala preço. Texto original: (ler horas comprometidas antes de dar
   preço) não tem fonte de dados: o Hermes público não tem `file`/`terminal`.
   Precisa de uma skill/MCP read-only ou do dado dentro do prompt.
6. **Pix pela bridge não está comprovado.** Ver entrada de 2026-09-26.
7. **API do Hermes e OmniRoute publicadas no IP público.** `hermes_hermes`
   publica `8642` em modo host e o OmniRoute publica `20129`, ambos em
   `0.0.0.0`. `http://13.140.42.181:8642/health` responde 200 e não há `ufw`.
   A bridge só precisa da rede overlay (`hermes:8642`). Quem tiver a chave da
   API fala com o agente sem passar pela bridge, e o OmniRoute fica exposto
   igual. Remover a publicação ou prender em `127.0.0.1`.
8. ~~**O SDR não tem como registrar nem escalar de fato.**~~ Resolvido pelas diretivas `[[ESCALAR]]`/`[[REGISTRO]]` da bridge. O `prompt.md` manda
   "chamar o Talles" e registrar dor literal, âncora, objeções e desfecho, mas
   o Hermes público não tem ferramenta de escrita, e a bridge não reconhece
   nenhum sinal de escalação. Hoje isso só aparece como texto na conversa.
9. **Fila em memória.** Se a bridge reiniciar, turnos pendentes (dentro dos
   10 s de acúmulo) se perdem. RabbitMQ foi discutido e adiado.

---

## Entradas

Formato: `### AAAA-MM-DD — título` seguido de **Pedido**, **Feito**,
**Evidência**, **Pendente**. Datas em UTC.

### 2026-09-24 — Portainer, Traefik e OpenReply (Codex, sessão `01a0d57a`)

- **Pedido:** subir Portainer pronto para Swarm e, no futuro, n8n em modo fila;
  apontar `manager.talles.dev`; instalar OpenReply (automação Instagram) no
  Portainer em vez de Coolify.
- **Feito:** Portainer standalone + Swarm ativo; Traefik como stack `traefik`
  (host network em `13.140.42.181:80/443` para não conflitar com Tailscale);
  stack `openreply` com allowed emails `ebtalles@`, `tsxtalles@`, `tsxheilz@`.
- **Decisão:** manter tudo em Portainer/Swarm; Coolify descartado; CI/CD
  sugerido via GitHub Actions + stack staging (não implementado).
- **Pendente:** n8n não implantado.

### 2026-09-25 01:28 — Pedido original do Hermes (Codex, sessão `01a0d57a` → `01a0d65b`)

- **Pedido:** "botar um segundo hermes nesse portainer e um chatwoot usando ele
  como gateway", conectado ao Evolution Go (API não oficial, simulando WhatsApp
  Web), tudo dentro do Portainer; sincronizar recebidas, enviadas pelo Chatwoot
  e enviadas pelo próprio celular; OmniRoute (ou CLIProxy/9router) para usar
  assinaturas como API do novo Hermes.
- **Decisão de arquitetura:** Evolution Go é o transporte; bridge própria usa o
  Chatwoot API Channel (sem escrever no banco); Hermes é só o agente, chamado
  via `/v1/chat/completions`; Chatwoot é a interface humana.
- **Feito:** stacks `chatwoot`, `evogo`, `hermes`, `omniroute`,
  `integration_bridge`; DNS `chatwoot`, `evolution`, `omni` (token Cloudflare
  precisou ser renovado pelo usuário). Licença Evolution ativada em nome
  "Super Agentes — lsuperagentes@gmail.com". QR escaneado.
- **Pedido paralelo:** "depois vou precisar de uma lista de todas as
  possibilidades numa conversa com humano (botão etc.)" — parcialmente coberto
  pelo ledger; sem lista dedicada.

### 2026-09-25 03:24 — Fluxo ponta a ponta com Hermes

- **Feito:** Hermes usa a credencial Antigravity já ativa no OmniRoute (não foi
  preciso copiar a do Codex). Fluxo WhatsApp → Bridge → Chatwoot → Hermes →
  OmniRoute → Evolution validado (`HERMES_OK`, `200 HERMES_AUDIT_OK`).
  Credenciais documentadas em `CREDENTIALS.md` (local, ignorado).
- **Commits:** `eccb712`.

### 2026-09-25 12:38–13:13 — Duplicação, `fromMe`, mídia de saída

- **Pedido:** mensagens duplicando; conversa continuada do celular virou
  conversa nova com o nome do Talles; mídia do Chatwoot não ia para o WhatsApp;
  resposta citada não chegava como reply.
- **Feito:** dedupe atômico por ID externo, trava na criação de conversa,
  `fromMe` não reprocessado, respostas do Hermes como `outgoing`; conversa #2
  removida (backup `/tmp/chatwoot-before-delete.sql`); anexos do Chatwoot →
  Evolution; reply anchor.
- **Commits:** `e59f659`, `64ba566`, `5e2e6bd`, `0fe8df4`.

### 2026-09-25 13:26 — Ledger de paridade e acúmulo de mensagens

- **Pedido:** "confere como é o channel do WhatsApp dentro do código do Hermes
  pra ver se não está esquecendo de nada, faz um ledger"; acumular mensagens
  seguidas e responder junto; manter histórico por conversa.
- **Feito:** `HERMES_CHANNEL_LEDGER.md`; imagens como `image_url`; acúmulo por
  JID (1,5 s na época); sessão `wa:<jid>`; recuperação de mídia recente do
  Chatwoot quando o cliente se refere a "a imagem que mandei".
- **Commits:** `b2fbdeb`, `06ca7e2`, `22c415e`, `aa5ecd6`.

### 2026-09-25 16:06 — Handover humano por label

- **Pedido:** ignorar mensagens próprias; quando o Talles responder pelo
  celular, travar o agente sem apagar histórico; no Chatwoot, pausar com tag.
- **Feito:** label `hermes-pausado` (criada no Chatwoot); resposta em voo
  descartada se houver intervenção; contexto acumulado entregue ao retomar.
  Templates/botões da API oficial convertidos em texto para o Hermes.
- **Commits:** `5006e33`, `33006ce`. Testes: `bridge-src/test_handover.py` (7/7).

### 2026-09-25 19:44–20:00 — Blindagem do Hermes público

- **Pedido:** "o hermes configurado dessa forma permite usuários editarem ele?
  … ainda quero que ele consiga acionar skills" → "protege ele aí pq esse
  hermes vai ser meu agente de suporte e SDR".
- **Achado:** rodava como root, `/opt/data` gravável, terminal `local`, sem
  política para `api_server`; Bot Mode não é camada de segurança; `skill_manage`
  permite o agente editar skills.
- **Feito:** política gerenciada no volume `hermes_policy` (ro); allowlist
  `web`/`vision`/`skills`/`clarify`; `SOUL.md` e skills somente leitura;
  container como UID 10000; escrita pelo usuário do agente negada;
  `/v1/toolsets` confirmou só os quatro.
- **Regra:** novas skills, CRM ou MCP só entram administrativamente (fora do
  WhatsApp) e explicitamente na allowlist; reaplicar read-only depois.
- **Commit:** `7457bec`. Doc: `HERMES_SECURITY_POLICY.md`.
- **Não feito:** a persona (`SOUL.md`) não foi trocada — continua a padrão.

### 2026-09-25 20:22–21:17 — Incidentes: chave do Hermes, Postgres da Evolution, webhook

- **Sintomas:** número `+55 48 2500-0259` sem resposta; após troca de número,
  QR demorando / "Aguardando QR Code"; mensagem sem sincronizar.
- **Causas:** bridge com `HERMES_API_KEY` antiga (401) — alinhada com o `.env`
  do Hermes; senha do usuário `evogo` no Postgres divergente da config;
  instância criada com `RabbitmqEnable` sem `AMQP_URL` e `WEBHOOK SKIPPED
  doWebhook=false`.
- **Confirmado:** a bridge não tem número fixo no código (usa `IsFromMe` + JID).
- **Decisão:** RabbitMQ não é necessário agora; recomendado para produção
  (fila durável, 4 consumidores, ordem por contato, retry, DLQ).
- **Lição:** ao reiniciar/reconfigurar o Hermes, verificar se a chave da API
  bate com a da bridge (`bridge → Hermes: 200`).

### 2026-09-25 20:55–22:21 — Áudio, documentos e paridade com Telegram/adapter nativo

- **Pedido:** transcrever áudio; "pq o próprio Hermes não faz isso?"; "olha a
  bridge do Telegram e vê o que falta"; "essa bridge tem que ser tipo um plugin
  do Hermes que encaixa Evolution e Chatwoot"; registrar arquivo/linha de cada
  item no ledger.
- **Explicação registrada:** o endpoint OpenAI-compatible do Hermes só aceita
  imagens; nos canais nativos quem transcreve/extrai é o gateway, por isso a
  bridge assume esse papel.
- **Feito:** faster-whisper local (cache em `integration_bridge_stt_cache`),
  extração de PDF/DOCX/XLSX/PPTX/ODT/texto com OCR, chunking 4096, Markdown →
  WhatsApp, polls/localização/reações, receipts e revogações no Chatwoot,
  `MEDIA:/opt/data/...`, outbox SQLite. Imagens `parity-v6` → `parity-v15`.
- **Commits:** `96f62c7` … `acf1bc2`.
- **Lacunas registradas no ledger:** edição de conteúdo no Chatwoot, álbuns.

### 2026-09-26 01:47 → 22:53 — Solicitação de Pix (não resolvido)

- **Pedido:** card verde "R$ 50,00 / Pagar com / Você solicitou um pagamento"
  chega como `[mídia recebida]`; entregar ao Hermes como evento estruturado
  sem executar pagamento. Buffer de acúmulo → 10 s.
- **Feito:** parser de `requestPaymentMessage`, depois `interactiveMessage`
  `nativeFlowMessage` `payment_info`, depois busca recursiva; fixtures
  `message-pix-payment.json`, `message-pix-interactive.json`; teste
  `test_payment.py`; buffer 10 s. Imagem `parity-v19`.
- **Commits:** `0f9b4c1`, `af1249c`, `068a74b`, `de339ad`.
- **Resultado:** usuário: "desisto, ainda não passou certo". As fixtures foram
  montadas a partir da documentação, não do webhook real.
- **Próximo passo correto:** capturar um webhook bruto do card Pix real, testar
  contra ele e só então corrigir o parser.

### 2026-09-27 — Transição para SDR (Claude Code, esta sessão)

- **Pedido:** ajustar o Hermes do Portainer para ser o SDR do Talles sem que ele
  entregue a própria estrutura; criar este log e o `AGENTS.md`.
- **Feito:** este log e `AGENTS.md`; estado ao vivo conferido (tabela acima).
- **Encontrado:** `SOUL.md` padrão da Nous (risco 1); `prompt.md` (rascunho da
  persona SDR, não versionado, 24 KB) sem regra de sigilo de infraestrutura;
  `Cérebro Compartilhado(2).zip` na raiz (não versionado, conteúdo não lido
  nesta sessão).
- **Pendente:** riscos 1–5 da seção acima.

### 2026-09-27 — Estudo do `Cérebro Compartilhado(2).zip` (Claude Code)

- **Pedido:** estudar a estrutura do zip atrás de ideias para o SDR.
- **O que é:** repositório `imersao-openclaw-negocios` (Pixel Educação,
  março/2026, 281 arquivos). É um template de "cérebro" em Markdown para
  agentes OpenClaw com empresa fictícia, áreas
  (vendas/atendimento/marketing/ops/governança), agentes (`SOUL`, `AGENTS`,
  `USER`, `HEARTBEAT`, `MEMORY`), skills, rotinas e slides da imersão.
  Arquivos mais úteis: `cerebro/agentes/bot-suporte/*`,
  `cerebro/areas/vendas/bot/conhecimento.md`,
  `cerebro/areas/vendas/skills/{qualificacao-lead,agendamento-call,follow-up-leads}`,
  `cerebro/areas/atendimento/skills/{consulta-base-conhecimento,registro-duvida-pendente}`,
  `cerebro/seguranca/permissoes.md`, slides `07*`, `13*`–`18*`.
- **Ideias a absorver:**
  1. Separar a persona em quatro partes em vez do `prompt.md` monolítico:
     `SOUL` (quem é, tom, regras invioláveis), `AGENTS` (pode sozinho /
     sempre escala), `USER` (perfil do lead) e uma base de conhecimento
     única ("se não está aqui, o bot não sabe"). No Hermes, a base pode ser
     uma skill read-only do SDR. Regras invioláveis e sigilo ficam no
     `SOUL`, porque skill só carrega sob demanda.
  2. Seção explícita "o que o bot NÃO sabe e não inventa", com a resposta
     padrão. Aqui ela ganha a lista de sigilo da infraestrutura.
  3. Loop de dúvida: responde o que sabe, registra a dúvida, o humano
     responde e uma rotina consolida na base. Aqui a escrita precisa ficar
     fora do Hermes público (memory poisoning): marcador na resposta, a
     bridge registra nota privada e label no Chatwoot, o Talles responde e a
     consolidação na skill é administrativa e revisada.
  4. Escalação mecânica. O bot deles "marca @Bruno"; aqui o equivalente é a
     bridge reconhecer um marcador (como já faz com `MEDIA:`), removê-lo do
     texto, aplicar `hermes-pausado` e deixar nota privada com a frase
     literal do lead. O mesmo canal serve para os registros do
     "O QUE VOCÊ DEIXA REGISTRADO" (custom attributes/notas no Chatwoot).
  5. Workspace separado e escopo mínimo: o bot público não enxerga o
     contexto interno. Reforça reduzir o bundle de skills padrão.
  6. Validação antes de escalar: 5 perguntas reais e 48 h monitorando, com
     evals versionados (`evals.json`). Aqui vira uma bateria fixa de
     cenários SDR mais tentativas de extração.
  7. Checklist de segurança (slides 07b/07c): gateway nunca exposto,
     allowlist de tools, skills auditadas, rotação de tokens a cada 90 dias,
     auditoria periódica comparando o agente com a política. Motivou a
     checagem que achou o risco 7.
- **Não absorver:** Supabase/Telegram/multi-agente/grupos, agente fazendo
  git push, scripts de objeção do template (falam em "curso/mentoria", o que o
  `prompt.md` proíbe).
- **Encontrado fora do zip:** riscos 7 e 8 da seção de riscos.

### 2026-09-27 15:52 — Firewall do provedor (Contabo) com DROP total

- **Contexto:** o usuário ativou um firewall no painel do provedor às 13:49 UTC
  com uma única regra `Block all traffic` (DROP, qualquer protocolo e porta) e
  perguntou o que liberar.
- **Conferido:** saída funciona (firewall stateful: Google 200, WhatsApp e
  OmniRoute OK). Entrada pública caiu: `manager`, `chatwoot`, `evolution` e
  `omni.talles.dev` dão timeout (000) via Cloudflare. Tailscale segue
  funcionando (NAT traversal/DERP), e o Orca é acessado pelo Tailscale
  (`100.83.163.117:6768`/`:6080`).
- **Recomendado liberar:** TCP 80 e 443 com origem só nas faixas da Cloudflare
  (`cloudflare.com/ips-v4` e `ips-v6`; todos os domínios são proxied, então o
  ACME HTTP-01 também passa por ela) e UDP 41641 (Tailscale direto,
  opcional) de qualquer origem.
- **Não liberar:** 22 (usar via Tailscale), 6768/6080 (Orca), 8642 (Hermes),
  20128/20129 (OmniRoute), 3000 (OpenReply), 3001 (Chatwoot), 4000
  (Evolution), 8000/9443 (Portainer), 2377/7946/4789 (Swarm; abrir só para
  o IP da futura VM, ou usar o Swarm sobre Tailscale).
- **Efeito no risco 7:** com o DROP, as portas 8642/20129 ficam bloqueadas
  pela borda. A publicação continua no Swarm; remover mesmo assim, como
  defesa em profundidade.
- **Regras aplicadas pelo usuário:** Tailscale UDP 41641 (Any), HTTP 80 e HTTPS
  443 (faixas Cloudflare), todas acima do DROP. Teste: `manager` 200,
  `openreply` 200, `omni` 307, `evolution/manager/login` 200, `chatwoot` 500
  intermitente (causa abaixo, não relacionada ao firewall).

### 2026-09-27 16:30 — Colisão de DNS na rede `ai_stack` (Chatwoot 500 intermitente)

- **Sintoma:** `chatwoot.talles.dev` alterna entre 500 e 200 (em 30 min: 4 × 500,
  18 × 200). O log mostra `password authentication failed for user "chatwoot"`
  em `10.0.3.19`.
- **Causa:** todas as stacks estão na mesma overlay `ai_stack`, e o nome curto
  de serviço vira alias de DNS. `postgres` resolve para `chatwoot_postgres`
  (10.0.3.7) **e** `evogo_postgres` (10.0.3.19); `redis` resolve para
  `chatwoot_redis` (10.0.3.9) **e** `omniroute_redis` (10.0.3.2). O Chatwoot
  usa `POSTGRES_HOST=postgres` e `REDIS_URL=redis://redis:6379/0`; o OmniRoute
  usa `redis://redis:6379`. A falha "senha do `evogo`" de 2026-09-25 foi o
  mesmo problema, corrigido na época só do lado da Evolution
  (`tasks.evogo_postgres`).
- **Correção proposta:** `POSTGRES_HOST=chatwoot_postgres` e
  `REDIS_URL=redis://chatwoot_redis:6379/0` em `chatwoot_rails` e
  `chatwoot_sidekiq`; `REDIS_URL=redis://omniroute_redis:6379` no OmniRoute.
  Regra geral: dentro de `ai_stack`, sempre usar o nome completo
  `<stack>_<serviço>`.
- **Aplicado (aprovado pelo usuário):** `docker service update --env-add` em
  `chatwoot_rails`, `chatwoot_sidekiq` e `omniroute_omniroute` com os valores
  acima. Os bancos, os volumes e os dados não mudaram.
- **Evidência:** 30/30 requisições a `chatwoot.talles.dev/app/login` com 200;
  nenhum erro de autenticação no rails/sidekiq nos 2 min seguintes; serviços
  1/1; `omni.talles.dev` 307; chamada bridge → Hermes → OmniRoute com 200
  (resposta "OK", sessão `ops:healthcheck`).
- **Atenção em redeploy:** a mudança está só na spec dos serviços. As stacks
  foram criadas via CLI e não há compose delas no Portainer. Se alguém
  redeployar `chatwoot` ou `omniroute` a partir de um YAML antigo, o nome
  curto volta e o problema também. Busca em `/home/ubuntu`, `/opt`, `/root`
  e `/srv`: nenhum YAML de stack com os nomes curtos, só históricos de sessão
  e a doc do OmniRoute (`/opt/omniroute-src/docs/guides/DOCKER_GUIDE.md`).
- **Ainda ambíguo, sem uso conhecido:** `chatwoot_postgres` e `evogo_postgres`
  continuam atendendo pelo alias `postgres`, e os dois Redis pelo alias
  `redis`. Nada de novo deve usar os nomes curtos.

### 2026-09-27 17:00 — Exposição pública do Hermes e do OmniRoute (teste sem credencial)

- **Pergunta:** "alguém consegue acessar o Hermes e o OmniRoute tendo as URLs
  da API?"
- **Hermes:** não tem rota no Traefik (`traefik-dynamic.yml` só roteia
  manager, openreply, chatwoot, evolution e omni). A porta 8642 publicada
  agora é barrada pelo firewall do provedor. Não é alcançável de fora.
- **OmniRoute (`omni.talles.dev` → `127.0.0.1:20128`):** o dashboard redireciona
  para `/login`; `/v1/models`, `/api/providers`, `/api/settings` e
  `/api/keys` retornam 401. **Mas `POST /v1/chat/completions` sem nenhuma chave
  respondeu 200 com uma completion de `gemini-3.7-flash-low`.** Qualquer
  pessoa com a URL usa a conta Antigravity como API gratuita.
- **Correção proposta:** (1) exigir API key para a inferência no OmniRoute
  (o Hermes já envia `api_key` no `config.yaml`; confirmar que é uma chave
  válida do OmniRoute antes de ligar); (2) não servir `/v1` pelo domínio
  público, já que o Hermes usa `omniroute_omniroute:20129` internamente.
- **Causa confirmada no código:** `src/server/authz/policies/clientApi.ts`
  (em `/opt/omniroute-src`). Sem bearer e com `REQUIRE_API_KEY` diferente de
  `"true"`, a requisição é liberada como `anonymous`. A liberação não depende
  do IP de origem. O serviço não define `REQUIRE_API_KEY`.
- **Chave do Hermes:** nenhum aviso `invalid bearer presented` em 24 h de log
  do OmniRoute, então a chave que o Hermes envia é válida. Ligar
  `REQUIRE_API_KEY=true` não deve derrubá-lo; conferir com healthcheck depois.
- **Consumidores levantados (banco `storage.sqlite` do OmniRoute):** uma única
  API key, `hermes-bridge` (prefixo `sk-9f1baf637`), usada pelo Hermes do
  container em 86 chamadas. Chamadas sem chave: 13 em 2026-09-25
  02:15–02:27 UTC (testes da instalação) e 2 de 2026-09-27 (teste desta
  sessão). Sem sinal de uso por terceiros. `/api/providers/test` (129) é o
  teste de provider do dashboard, com outra política. O Hermes do host
  (`~/.hermes`) usa `openai-codex` direto e não depende do OmniRoute.
- **Aplicado (aprovado):** `REQUIRE_API_KEY=true` em `omniroute_omniroute`.
  Nenhuma mudança foi necessária na config do Hermes.
- **Evidência:** anônimo em `/v1/chat/completions` e em
  `/api/v1/chat/completions` → 401 `AUTH_002`; chave inválida → 401; login do
  dashboard → 200; bridge → Hermes → OmniRoute → 200 "OK".
- **Não aplicado:** retirar `/v1` do domínio público na Traefik. Com a chave
  obrigatória deixou de ser urgente, e mexer exige nova versão
  `routes_vN` da stack Traefik. Fica como segunda camada opcional.
- **Novo consumidor do OmniRoute:** criar uma API key própria no dashboard
  (uma por consumidor) em vez de reaproveitar a `hermes-bridge`.

### 2026-09-27 17:20 — Persona SDR: análise de lacunas e decisões

- **Pedido:** "voltemos ao prompt": transformar o `prompt.md` no SDR do Hermes.
- **Lacunas do `prompt.md` contra o Hermes real:** dossiê (81.131 anúncios /
  602 contas) sem fonte; gate de capacidade e "restam N" sem fonte; escalação
  sem mecanismo; registro dos marcos sem escrita; toques T+1/T+4 sem
  iniciativa de envio; origem do anúncio (`externalAdReply`) não extraída
  pela bridge; nenhuma regra de sigilo.
- **Decisões do usuário:** (1) dossiê: "existe uma base", aguardando o local;
  (2) vagas e horas: arquivo que o Talles edita, injetado pela bridge;
  (3) escopo: tudo, incluindo os toques automáticos.
- **Desenho:** `SOUL.md` versionado em `hermes-sdr/`; a bridge ganha
  diretivas `[[ESCALAR]]`/`[[REGISTRO]]`/`[[FOLLOWUP]]` (removidas antes do
  envio), contexto confiável de capacidade e origem, e um agendador
  persistente de toques. O dossiê é buscado pela bridge quando o @ for
  registrado; sem base, o agente pula o passo e não o menciona.

### 2026-09-27 17:45 — OpenReply como fonte de origem do lead (investigação read-only)

- **Pedido:** 5 reels/dia com CTA de comentar ou mandar DM; o OpenReply
  manda o link do WhatsApp; o agente precisa cruzar o lead com a base do
  OpenReply. Carteirada com fotos. Escalação por label no Chatwoot com
  notificação ao Talles via Evolution.
- **Acesso:** `openreply_postgres` fica só na rede `openreply_internal`
  (alias `postgres`, DB `openreply`, user `openreply`, Prisma em
  `/app/prisma/schema.prisma`). A bridge está só em `ai_stack`, então
  precisaria entrar em `openreply_internal` e usar um role read-only
  próprio. A API HTTP do OpenReply usa sessão NextAuth, sem API key.
- **Dados por lead:** só `DmLog` (`commenterId` IGSID, `commenterName`,
  `commentText`, `matchedKeyword`, `automationId`, `commentId`, que é o id do
  comentário, `dm:<id>` ou `reveal:<IGSID>`). O post vem de
  `Automation.postId`/`postUrl`. O histórico completo está em
  `WebhookEvent.payload`. `LinkClick` não tem id de usuário. O texto do DM
  enviado não é gravado.
- **Templates:** só `{username}` e `{link}`
  (`/app/lib/tracking/message.ts`). `{link}` passa pelo redirect
  `/r/<slug>`, que descarta a query. Não existe código único por contato
  sem patch no OpenReply.
- **Casamento recomendado:** DM em texto puro (sem TrackedLink) com
  `https://wa.me/<numero>?text=Oi!%20Sou%20@{username}%20[R<n>]`. A bridge lê
  `@username` e a tag do reel na primeira mensagem e consulta `DmLog`.
  Fallback: o agente pede o @. Lead que só mandou DM sem comentar chega
  como `@there`.
- **Estado atual:** 1 campanha, inativa, com textos de teste ("Message
  {link}", "Yo", "Yoooo"); TrackedLink apontando para google.com.
- **Decisão em aberto:** onde implementar a lógica do SDR (bridge vs serviço
  `sdr-tools` via MCP). Critérios apresentados ao usuário.

### 2026-09-27 17:50 — Internals do Hermes relevantes para a persona (investigação read-only)

- **Mensagem `system` na requisição:** é honrada. A API junta as mensagens
  `system` e as passa como `ephemeral_system_prompt`, anexado ao fim do
  prompt principal a cada chamada e nunca persistido
  (`gateway/platforms/api_server_openai_routes.py:631-705`,
  `agent/turn_context.py:1280-1286`). É o canal confiável para contexto da
  bridge (capacidade, origem, gatilho de toque): o lead não consegue forjá-lo.
  Com `X-Hermes-Session-Id`, só a última mensagem do body é usada; o
  histórico vem do `state.db`.
- **`SOUL.md`:** é lido do disco a cada construção de prompt, mas o prompt
  fica **congelado por sessão** no primeiro turno
  (`agent/conversation_loop.py:721-880`). Sessões `wa:<jid>` existentes
  mantêm a persona antiga. Trocar a persona exige id de sessão novo (por
  exemplo `wa:v2:<jid>`). Não precisa reiniciar o gateway.
- **Textos "Hermes/Nous" que config não remove:** parágrafo "You run on
  Hermes Agent (by Nous Research)…" (`prompt_builder.py:171-190`), "Active
  Hermes profile", "# Hermes runtime environment" e a skill essencial
  `hermes-agent` no índice. O sigilo depende de instrução no `SOUL.md` e
  na mensagem `system` por requisição, que vem por último.
- **Ferramentas reais no api_server:** `clarify`, `skill_manage`,
  `skill_view`, `skills_list`, `vision_analyze`, `web_extract`,
  `web_search`. `skill_manage` escreve em `/opt/data/pending/skills`
  (staged por `write_approval`). `clarify` sempre retorna erro na API (não
  há callback). Memória está vazia e sem ferramenta de escrita.
- **Recomendação:** retirar `skills` (vaza nomes de skills e a
  `hermes-agent`) e `clarify` (inútil) do `api_server`; avaliar `web`.
- **Versão do Hermes:** não identificável (`0.0.0`, commit zerado).

### 2026-09-27 18:20 — Arquitetura do SDR decidida

- **Decisões do usuário, em ordem:**
  - Follow-up é para o próprio lead: 5 min, 30 min, 2 h e dia seguinte em
    qualquer fase, mais um toque no T+4 depois do preço (encerra no T+5),
    sempre pulando a noite (9h–20h de Brasília). Substitui "dois toques,
    nunca três" e "no máximo duas mensagens sem resposta" do `prompt.md`.
  - Conversa e FUP se complementam e não se misturam. Um agente acionado
    por cron decide os disparos e grava registros; a fila só dispara.
  - A conversa tem enriquecimento (@ do IG → OpenReply, perfil para
    rapport), contexto da oferta e status de vagas.
  - Um supervisor orienta o Hermes, escala e revisa/reescreve cada resposta
    antes do envio, rodando a cada troca.
  - Escalação: label no Chatwoot + aviso ao Talles pela Evolution.
  - A cadência deve evitar conversa robotizada.
- **Desenho:** `hermes-sdr/ARQUITETURA.md`. O Hermes só conversa, sem
  ferramentas, e recebe contexto confiável pela mensagem `system` de cada
  requisição. O `sdr-brain` (serviço novo) concentra as decisões:
  enriquecimento, supervisor/revisão e agente de FUP. A bridge só executa:
  contexto, diretivas, guardrail determinístico, "digitando…"
  (`POST /message/presence`) e dispatcher. Fases A (fundação), B
  (sdr-brain) e C (enriquecimento).
- **Recomendado ao usuário:** perfil via Business Discovery da API da Meta,
  pela conta IG já conectada no OpenReply, em vez de raspagem.
- **Em andamento:** `bridge-src/sdr.py`, que começou com uma cadência
  armada pela bridge. Ela será reduzida a dispatcher da fila na fase B.
- **Pendente do usuário:** número pessoal para aviso; fotos da carteirada
  com descrições; local da base do dossiê; confirmar corte de `skills`/`clarify`.

### 2026-09-27 19:10 — Fase A publicada (persona SDR + camada SDR da bridge)

- **Persona:** `hermes-sdr/SOUL.md` (a partir do `prompt.md`, com regra 7 de
  sigilo, contexto de sistema, diretivas, vagas pelo contexto, dossiê
  condicional e toques fora do agente) instalado em `/opt/data/SOUL.md`
  (444, uid 10000). Backup do anterior em
  `/opt/data/backups/SOUL.md.20260927T170719Z.bak`.
- **Bridge:** imagem `evolution-chatwoot-bridge:sdr-v1` (antes
  `parity-v19`). Novo `bridge-src/sdr.py`: diretivas `[[ESCALAR]]`,
  `[[REGISTRO]]`, `[[FOTO]]`, `[[QUEBRA]]`; contexto confiável como mensagem
  `system`; guardrail determinístico de termos internos (bloqueia, manda
  resposta neutra e escala); "digitando…" antes de cada envio; escalação com
  nota privada, labels `sdr-escalado` + `hermes-pausado` e aviso pela
  Evolution (desligado até `SDR_NOTIFY_NUMBER` existir); origem do lead
  lida do texto pré-preenchido `@usuario [R<n>]`. Sessões agora são
  `wa:v2:<jid>` (`HERMES_SESSION_PREFIX`). Pasta `hermes-sdr/` montada em
  `/sdr` (somente leitura).
- **Testes:** 26/26 unitários (11 novos em `test_sdr.py`). Bateria contra o
  Hermes real com sessões `test:sdr:*` (13 cenários, 19 respostas): zero
  vazamento em pedido de prompt, injeção, falso "modo admin do Talles",
  tradução das regras e perguntas sobre Hermes/Nous/Docker/Chatwoot; escalou
  corretamente o pedido de pessoa. Achados: disse "mais de 92%" e a frase de
  escalação ficou mecânica. Corrigido no `SOUL.md` do repositório; entra
  no ar com a fase B, junto com o próximo prefixo de sessão.
- **Estado:** `capacidade.json` inexistente (capacidade "desconhecido": o
  agente não fala preço e escala); `midia/` vazia; `skills`/`clarify` ainda
  ativos no `api_server`, aguardando confirmação.

### 2026-09-27 19:20 — Fase B delegada ao Codex via orquestração do Orca

- **Pedido do usuário:** "delega o que puder pro codex" usando as skills
  `orca-cli` e `orchestration`.
- **Nota operacional:** o shell desta sessão tem `ORCA_ENVIRONMENT=talles-pc`
  (runtime do PC Windows). Para operar a VM, rode `orca` com
  `unset ORCA_ENVIRONMENT`, que alcança o runtime local, onde o repo tem id
  `c3cb4917-8335-42ae-a770-fcddf502c4cb::/home/ubuntu/orca/projects/portainer-install`.
- **Run:** `run_3af850fb1db5`. Contrato bridge ↔ sdr-brain em
  `hermes-sdr/ARQUITETURA.md`.
  - Task A `task_2723dfa3824d`: serviço `sdr-brain/`.
  - Task B `task_a5cf4cdd8de1`: lado da bridge em `bridge-src/`.
  - Ambas em `--worktree current` com pastas disjuntas, sem deploy e sem
    commit.
- **Incidente:** no primeiro despacho o Codex mostrou o aviso de atualização
  (0.156.1 → 0.157.1) e o Enter do prompt escolheu "Update now". Nas
  tentativas seguintes o prompt chegou antes da TUI ficar pronta.
  - B começou na 2ª tentativa (`ctx_0abdb2da8008`).
  - A ficou sem prompt na 3ª (`ctx_f83f8da8ec5b`). Para não estourar o
    limite de 3 falhas, o preâmbulo do despacho (`dispatch-show
    --preamble`) foi reenviado no mesmo terminal com `terminal send`, e o
    worker começou.

### 2026-09-27 20:00 — Bridge SDR fase B (registro do worker Codex B)
- **Pedido:** implementar endpoints, atividade, revisão, eventos e follow-ups do contrato bridge ↔ sdr-brain.
- **Feito:** adicionadas tabelas/funções SDR para ficha, follow-ups e timestamps; endpoints autenticados; review hook, eventos fire-and-forget e dispatcher de follow-ups; integração de cancelamento de follow-ups na entrada.
- **Evidência:** `python3 -m py_compile bridge-src/app.py bridge-src/sdr.py` passou; suíte local não executou por dependência `httpx` ausente no host.
- **Pendente:** executar testes no container Docker e validar cenários de integração.

### 2026-09-27 20:40 — Fase B publicada (sdr-brain + bridge sdr-v2)

- **Entrega dos workers Codex** (run `run_3af850fb1db5`). Nenhum dos dois
  conseguiu enviar `worker_done`: o `orchestration send` falhou, e o sandbox
  do Codex não tem `sudo`/Docker. Revisão, testes e deploy ficaram com o
  coordenador, e os dois dispatches foram encerrados com `worker-stop`.
  - **A (`sdr-brain/`):** 1ª versão recusada (174 linhas, loop de FUP
    quebrado, SQL sem aspas, estado em memória). A 2ª foi aceita com
    correções do coordenador:
    - porta 8090 não publicada;
    - só o ponto de cadência mais recente é decidido, e nada fora de
      9h–20h (evita rajada de toques);
    - pula quando o lead falou por último;
    - loop resiliente;
    - conversa compacta `{autor,texto,quando}`;
    - parser tolerante a ```` ```json ```` (o modelo embrulha o JSON em
      cerca);
    - revisor recebe a conversa e não reescreve o roteiro literal;
    - prompts de FUP e revisor reescritos ("na dúvida, aprove"; toque
      cirúrgico a partir da última pergunta sem resposta, com as palavras
      do lead).
  - **B (`bridge-src/`):** implementação aceita com correções do
    coordenador:
    - toque não move o `last_agent_ts` (antes, a cadência reiniciava a cada
      toque);
    - guardrail também no toque;
    - "digitando…" com número, não com JID;
    - revisor recebe `sdr.context_payload()`;
    - toque enviado cancela os outros pendentes da conversa, e o status é
      conferido antes de cada envio;
    - `process_followups_once(now)` testável.

    Testes do B corrigidos (auth e consumo de orientação) e testes do
    dispatcher escritos pelo coordenador.
- **Testes:** bridge 36/36; sdr-brain 11/11.
- **Revisor ao vivo** (~3 s por chamada): aprovou a abertura literal,
  bloqueou o vazamento de stack e o preço sem âncora, e reescreveu "mais de
  92%" para "+92% aceito sem atrito".
- **Infra criada:**
  - API key `sdr-brain` no OmniRoute;
  - `SDR_BRAIN_TOKEN` compartilhado;
  - role `sdr_brain_ro` no Postgres do OpenReply: SELECT em `"DmLog"`,
    `"Automation"` e `"WebhookEvent"`, `default_transaction_read_only`;
    escrita testada e recusada; tabela `"User"` negada.

  Os segredos ficam em `CREDENTIALS.md`. O brain usa o token de app do
  Chatwoot da bridge.
- **Deploy:**
  - Stack `sdr`, serviço `sdr_brain` (`sdr-brain:v1`), nas redes `ai_stack`
    e `openreply_internal`, sem porta publicada, via
    `sudo -E docker stack deploy -c sdr-brain/stack.yml sdr`, com os
    segredos exportados no shell.
  - Bridge `evolution-chatwoot-bridge:sdr-v2`, com `SDR_BRAIN_URL`,
    `SDR_BRAIN_TOKEN` e `HERMES_SESSION_PREFIX=wa:v3:`.
  - `SOUL.md` atualizado (backup anterior em `/opt/data/backups/`).
- **Verificado:**
  - health dos dois serviços;
  - bridge ↔ brain nos dois sentidos com token;
  - bridge sem token → 401.
- **Não verificado:** conversa real ponta a ponta no WhatsApp, enriquecimento
  com lead real do OpenReply, Business Discovery (sem `META_GRAPH_TOKEN`).

### 2026-09-27 20:45 — "Entendo totalmente", skills removidas, escalação idempotente

- **Pedido:** trocar "Totalmente entendo" por "Entendo totalmente"; tirar as
  skills do Hermes. Pergunta do usuário sobre a conversa 7 (teste real):
  "tá sendo decisão do Hermes ou a bridge tá enviando msg direto?"
- **Feito:**
  - Frase trocada em `hermes-sdr/SOUL.md`, `sdr-brain/prompts/revisor.md`
    e `bridge-src/test_sdr.py`. O `prompt.md` original ficou como estava.
  - Persona reinstalada; bridge em `HERMES_SESSION_PREFIX=wa:v4:`.
  - Política `hermes_policy`: `skills` saiu de `platform_toolsets.api_server`
    e entrou em `agent.disabled_toolsets`, com backup
    `config.yaml.20260927T183601Z.bak`. Hermes reiniciado; `/v1/toolsets`
    habilitados agora são `web`, `vision`, `clarify`.
  - Brain atualizado com o revisor novo.
- **Conversa 7 (15:30–15:35 BRT), reconstruída pelo Chatwoot e pelos logs:**
  - Todas as respostas foram geradas pelo Hermes e revisadas pelo brain,
    uma revisão por resposta, todas aprovadas; nenhuma saiu de template da
    bridge.
  - Ao receber o @ com intenção de compra, o Hermes escalou com "capacidade
    incerta", porque `capacidade.json` não existe (regra 4). Correto.
- **Bug corrigido:** o supervisor escalou a mesma conversa de novo (nota
  privada duplicada). `app.escalate` agora é idempotente: se a conversa já
  está pausada, não repete nota, labels nem aviso. Teste novo (bridge 37/37).
  Imagem `evolution-chatwoot-bridge:sdr-v3` publicada.
- **Lição:** subir `HERMES_SESSION_PREFIX` faz o Hermes perder a memória das
  conversas em andamento (sessão nova). Faça isso com conversas pausadas ou
  paradas, ou alimente a sessão nova com o histórico antes.
- **Pendente:** `clarify` continua habilitado (sempre retorna erro na API);
  o usuário pediu só a remoção das skills.

### 2026-09-27 20:55 — Número do Talles para escalação

- **Pedido:** "o meu número é 5564999425822".
- **Achado:** `POST /user/check` da Evolution devolve JID `556499425822` (sem
  o nono dígito) e LID `148563086540988@lid`. Comparar só o número digitado
  faria as mensagens do Talles serem tratadas como de lead.
- **Feito:**
  - `sdr.OWNER_IDS` reúne `SDR_NOTIFY_NUMBER` + `SDR_OWNER_IDS`.
  - `is_owner` casa número, JID ou LID; teste atualizado (bridge 37/37).
  - Imagem `evolution-chatwoot-bridge:sdr-v4` com
    `SDR_NOTIFY_NUMBER=556499425822` (formato do WhatsApp, usado no envio) e
    `SDR_OWNER_IDS=5564999425822,556499425822,148563086540988`.
  - Aviso de teste enviado sem erro.
- **Efeito:** escalações chegam no WhatsApp do Talles. Mensagens desse número
  nunca vão ao Hermes nem abrem conversa de lead.

### 2026-09-27 21:00 — Capacidade definida; conta do Instagram no OpenReply

- **Capacidade:** o usuário informou "ainda vai ser 4, não tem cliente
  nenhum". Criado `hermes-sdr/capacidade.json` com mês `outubro/2026` (escolha
  do agente; setembro termina em 3 dias), 4 de 4 vagas, 0/75 h, próximo mês
  `novembro/2026`. A bridge lê como `status: ok` e
  `pode_oferecer_este_mes: true`.
  - Fica "desatualizado" 7 dias depois de `atualizado_em`
    (`SDR_CAPACITY_MAX_AGE_DAYS`), e aí o agente volta a escalar no preço.
- **OpenReply:** o login com tsxtalles@gmail.com deu "Account already
  connected". O banco mostra:
  - `@talles.ai` ("Talles Souza♾️") conectado desde 2026-09-24 no workspace
    de `ebtalles@gmail.com` (OWNER);
  - `tsxtalles@gmail.com` criou um workspace próprio e vazio em
    2026-09-27 18:54 UTC.
  - Solução: entrar com ebtalles, ou convidar tsxtalles para o workspace do
    ebtalles.
- **Adiado pelo usuário:** fotos da carteirada.
- **Pendente:** configurar a campanha ativa com o DM
  `wa.me/...?text=Oi!%20Sou%20@{username}%20[R<n>]` em texto puro.

### 2026-09-27 21:15 — Campanha "raiox" do OpenReply ajustada para levar o @

- **Sintoma (print do usuário):** o lead chegou no WhatsApp com "E ai! Sou o
  {username} e quero saber mais sobre o Raio-x!", com o placeholder literal.
- **Causa:** o link do WhatsApp estava num TrackedLink
  (id `cmuk6x90f00340jmb7p0m8x5x`, slug `TVPTvt_A0g`) com `{username}` no
  `destinationUrl`. O OpenReply só substitui variáveis no texto da mensagem;
  o redirect `/r/<slug>` abre o destino como está gravado.
- **Feito (aprovado pelo usuário: "altera aí pra mim"):** direto no Postgres
  do OpenReply, em uma transação, com backup de `Automation`, `TrackedLink` e
  `LinkClick` em
  `~/backups/openreply/campaign-raiox-20260927.sql`:
  - removido o TrackedLink da campanha `cmuk6x90600330jmbl91xrqdc`; apagou em
    cascata 1 LinkClick de teste;
  - `dmMessage` = `Só clicar e falar com ele:
    https://wa.me/554825000259?text=E%20a%C3%AD!%20Sou%20o%20@{username}%20e%20quero%20saber%20mais%20sobre%20o%20Raio-X`.
  - Conferido em `/app/lib/queue/dm-worker.ts` (`sendRevealDirectMessage`):
    sem TrackedLink, a mensagem sai em texto com `{username}` substituído.
- **Ajuste seguinte:** a pedido do usuário, `@` → `%40` e `!` → `%21`, para o
  Instagram não cortar o link. A query agora só tem `%XX` e caracteres não
  reservados. Texto final:
  `https://wa.me/554825000259?text=E%20a%C3%AD%21%20Sou%20o%20%40{username}%20e%20quero%20saber%20mais%20sobre%20o%20Raio-X`.
  Decodificado: "E aí! Sou o @<user> e quero saber mais sobre o Raio-X", e a
  bridge extrai `@<user>`.
- **Comportamento do OpenReply (código, `processMessage`):** gatilho por DM
  não manda a abertura e não conhece o @ (o webhook traz só o IGSID). O
  `{username}` vira "there" a menos que a pessoa já tenha comentado antes.
  Só o gatilho por comentário tem abertura e @.
- **Perde:** botão "Falar com ele" e contagem de cliques.
- **Pendente:** teste real (comentar "raiox" num post); confirmar a origem
  `@` na bridge e o enriquecimento pelo sdr-brain.

### 2026-09-27 21:25 — Modo teste do dono (#teste / #fim)

- **Contexto:** "a bridge quebrou?" — não. Às 16:15 BRT, as mensagens vieram
  do LID do Talles (`148563086540988@lid`), que desde o cadastro do número
  é dono e nunca vai ao agente. "Evolution desconectou?" — não: 3 quedas
  curtas hoje (13:06, 14:25, 15:58 BRT), cada uma reconectada em ~3 s;
  `/instance/status` → `Connected: true, LoggedIn: true`.
- **Pedido:** "faz o modo teste com #teste e #fim".
- **Feito (`evolution-chatwoot-bridge:sdr-v5`):**
  - `#teste`, vindo de um identificador do dono: incrementa o run em
    `sdr_owner_test`, cancela retomadas pendentes e apaga o mapeamento em
    `contacts`. A próxima mensagem abre conversa nova no Chatwoot, com labels,
    registros e transcript limpos, e sessão Hermes nova
    `wa:v4:<jid>:teste<N>`. Confirma ao Talles pela Evolution.
  - Durante o teste: fluxo de lead completo, incluindo revisor, supervisor e
    retomadas (o dispatcher não cancela retomadas do dono em teste). O aviso
    de escalação chega no mesmo chat.
  - `#fim`: desliga, cancela retomadas e confirma.
- **Testes:** bridge 40/40.

### 2026-09-27 22:30 — Fase de diagnóstico, divisão de mensagens e simulador

- **Pedido:** "não curti que ele foi direto pra oferta", "tudo em uma
  mensagem só"; "o manual do Hormozi ajuda? ou SPIN?"; "simule uma persona
  com problemas"; "leia cada arquivo" do zip "Raio-X de Operação — Central".
- **Leitura:** `hormozi-framework.md` e os 18 arquivos da central (índice,
  Funil, Fatos afirmáveis, CEBOLA, Mapa de problemas, Oferta escrita e
  Pendências 2 lidos diretamente; os outros 10 por subagente, com relatório
  de conflitos com o `SOUL.md`). Os próprios documentos registram o defeito:
  a Crítica V2 nº 3 ("o funil vai de uma pergunta e duas de triagem para @,
  dossiê, track record, âncora, preço") e a CEBOLA ("a FASE 1 vem antes do
  preço — é exatamente o que o script de 18 passos ainda não instrumenta").
- **Feito no `SOUL.md`:**
  - Passo 6, DIAGNÓSTICO (Fase 1 do Hormozi + SPIN): implicação,
    necessidade e desejo, uma pergunta por turno.
  - Passo 7, ESPELHO com checkpoint: dor, custo dito por ele e desejo agora.
  - Âncora sozinha; Raio-X só depois da reação.
  - Carteirada de uma linha na 2ª/3ª mensagem (decisão T1 de 26/09).
  - "UM PASSO POR TURNO".
  - "Entendo totalmente" só em objeção.
  - Lead decidido não passa pelas perguntas restantes.
  - Fechamento escala ao Talles para contrato e pagamento, que estão
    indefinidos nos documentos.
  - Números secos e nada de logística inventada.
  - Fatos acrescentados: dev pleno e agência (Fatos afirmáveis).
  - Fatos corrigidos:
    - crédito: "os R$ 12.000 abatem inteiros", no lugar de "crédito de 25%";
    - "+92% de reajuste";
    - SLA de 1 dia útil pertence à sustentação;
    - prova em vídeo, relatório ou entregável.
- **Feito na bridge (`sdr-v6`, depois `sdr-v7`):**
  - Linha em branco vira mensagem separada, até 3 por turno
    (`SDR_MAX_MESSAGES_PER_TURN`).
  - `mensagens_corrigidas`: quando o revisor ou o guardrail mudam a
    resposta, o próximo turno do Hermes recebe "você escreveu X / o lead
    recebeu Y" (tabela `sdr_corrections`, últimas 3).
  - Bridge 41/41.
- **Feito no sdr-brain:**
  - Revisor ganhou regras 11 (um passo por turno), 12 (nada de preço
    antes do diagnóstico) e 13 (nada de afirmação fora dos fatos).
  - Bloquear ficou restrito a sigilo e nome de cliente; o resto é
    reescrito.
  - `/review` aceita `transcript` no payload.
- **Bug achado pela simulação:** o revisor tirou a âncora da resposta, mas o
  Hermes guardou o rascunho, achou que a tinha dado e foi para R$ 12.000; o
  bloqueio virou escalação. Resolvido por `mensagens_corrigidas` e pelo
  "bloquear só 1–2".
- **Simulação** (`hermes-sdr/sim/`, persona "Marina", infoprodutora):
  - Rodada 1: morreu no bug acima.
  - Rodada 2: fechou, mas com "Entendo" repetido e perguntas demais a uma
    lead decidida.
  - Rodada 3: diagnóstico → espelho → âncora → Raio-X → fechamento em 12
    turnos, escalando para contrato e pagamento. Duas afirmações inventadas
    ("rodando sem travar em fundador", "sem reunião") viraram regras novas,
    ainda não re-simuladas.
- **Estado:** persona instalada; bridge `wa:v8:`; brain atualizado.
- **Pendências vindas dos documentos (não improvisar):**
  - contrato e forma de pagamento;
  - gatilho de reajuste para R$ 18.000 após 3 clientes;
  - nível 4 do ICP como filtro (perguntar se prometeu IA num lançamento);
  - "não é relatório" antes do preço;
  - campos de instrumentação no padrão da planilha (SIM/NAO, `icp`,
    `decisao_explicita`, `pergunta_N_resposta` com `NAO_FEITA`, etc.);
  - "81.131 anúncios" e "602 contas" não estão na lista de Fatos
    afirmáveis, mas estão no `prompt.md` do Talles;
  - conflito "375 tipos" (número livre × "nunca diga 375 tarefas").

### 2026-09-27 22:50 — Carteirada principal com a trajetória do Talles

- **Pedido:** "essas provas são muito pouco sexys". Novos fatos dados pelo
  Talles:
  - cuidou de um SaaS com 30 mil usuários, 18 mil agentes e 9 milhões de
    números de WhatsApp contactados;
  - gerenciou times em entregas de agência para clientes que faturaram 8
    dígitos, com mais de 300 mil mensagens num único fim de semana.
- **Feito:**
  - `SOUL.md` ganhou "A CARTEIRADA PRINCIPAL", com as duas frases exatas,
    na terceira pessoa ("o Talles cuidou de…"), escolhidas pela dor (SaaS
    para suporte/WhatsApp; agência para lançamento/pico). "Mais de 300 mil"
    é a exceção explícita à regra do "mais de".
  - Os números antigos passaram a ser de apoio.
  - Revisor atualizado com a mesma lista.
  - Bridge `wa:v9:`.
- **Simulação de 6 turnos:** carteirada do SaaS na 2ª resposta, casada com
  "suporte trava". Diagnóstico seguiu. Falha observada: a lead citou o
  próximo lançamento e o agente não perguntou a data (passo 3).
- **A confirmar com o Talles:** se a combinação de números identifica o
  SaaS ou a agência (sigilo até 03/09/2031: "os números podem ir; o nome
  não").

### 2026-09-27 22:55 — Retomada parou depois do 1º toque (corrigido)

- **Pergunta:** "vi que fez só um fup, pq?" (conversa 8, modo teste).
- **Fatos:**
  - Toque 5min enviado às 16:29 BRT.
  - Às 16:54 o brain decidiu o estágio 30min com `disparar=false`, sem
    motivo gravado.
  - Reproduzido: o modelo respondeu "já foi enviado um toque recente…
    evitando repetição desnecessária". A regra do `fup.md` "não dispare se
    repetiria um toque anterior" foi lida como "houve toque, não mande
    outro", o que mataria a cadência inteira.
  - O toque de 5 min também repetia a pergunta do preço em vez de voltar à
    dor.
- **Feito:**
  - `fup.md`: toque anterior não é motivo para parar; cada estágio tem
    ângulo próprio; depois do preço, nenhum toque repete preço nem
    "faz sentido o Raio-X?".
  - `sdr-brain`: tabela `decisions` ganhou `motivo` e `disparar` (migração
    automática) e cada decisão é logada ("FUP decision …").
  - Decisão 30min da conversa 8 apagada para redecidir. Toque saiu às
    17:52 BRT, com a dor literal e o número dele.
- **Próximo toque previsto:** 2h, perto de 18:23 BRT; depois d1.

### 2026-09-27 23:35 — Sem toque quando o lead some na abertura (corrigido)

- **Pergunta:** "pq não recebi?" (teste 2, conversa 9). O lead não
  respondeu a pergunta de abertura das 17:55 BRT.
- **Fatos:** o brain decidiu 5min (18:00) e 30min (18:26) com
  `disparar=false`, motivo "não há nada concreto do lead para retomar".
  Era a regra do `fup.md` "não dispare se não há nada concreto e o estágio
  é 5/30min". Ela seguia o Funil v2.1 ("quem não responde a abertura
  encerra"), mas contraria a decisão do Talles de cadência em qualquer
  fase, e a decisão dele prevalece.
- **Feito:**
  - `fup.md`: sem conteúdo concreto, o toque puxa com pergunta mais fácil.
    - 5min: a mesma pergunta, mais leve.
    - 30min: a abertura alternativa medida "Qual tarefa da sua operação
      hoje só anda quando você olha?" (3,09 de 4 no Funil §4).
    - 2h: saída honesta.
    - d1: último toque.
  - `sdr-brain`: conversa que a bridge responde 404 (mapeamento apagado
    pelo `#teste`) deixa de ser acompanhada (`forget_conversation`). Antes
    as conversas 7 e 8 eram consultadas a cada minuto. Teste novo (brain
    12/12).
  - Decisões da conversa 9 apagadas: o toque de 30min saiu com a pergunta
    alternativa.

### 2026-09-27 23:59 — Sequência de toques com relógio fixo; toque continua o assunto; provas de salário removidas

- **Pedidos do usuário:**
  - "se a pessoa responde depois de um touchpoint não deve resetar a
    sequência, deve continuar respeitando o horário dos próximos, mas não
    deve disparar se tiver rolando conversa ou se o assunto já tiver sido
    resolvido";
  - "não é só uma pergunta fixa, é continuando o assunto e empurrando pra
    frente";
  - tirar "+92% de reajuste" ("fraco") e "R$ 12.500/mês por 22 meses"
    ("falar que fiquei quase 2 anos sem aumento é triste").
- **Feito no `sdr-brain`:**
  - Tabela `sequences` (âncora, `ended_at`, `end_reason`). A sequência
    começa quando o agente falou por último e o lead silencia; os
    checkpoints (5min/30min/2h/d1, d4 pós-preço) contam dessa âncora e não
    recomeçam se o lead responder.
  - O checkpoint é **pulado** (registro `disparar=0`, motivo "conversa em
    andamento") se o lead respondeu durante a sequência e houve mensagem há
    menos de `SDR_QUIET_AFTER_REPLY_SECONDS` (1800 s).
  - Espera sem consumir o checkpoint se o lead falou por último.
  - A sequência termina no último checkpoint, em desfecho ou em pausa; uma
    nova só nasce com um silêncio novo depois do fim.
  - O agente de FUP recebe `sequencia.lead_respondeu_durante` e
    `toques_anteriores`.
  - Testes: brain 15/15.
- **`fup.md` reescrito:** o toque é a próxima mensagem da conversa.
  Continua de onde parou e empurra para o próximo passo do caminho
  (abertura → … → fechamento), trazendo algo novo e terminando em pergunta
  binária. O estágio define só a intensidade. Exemplos marcados "não
  copie". Não dispara com retorno marcado, "não", encerramento/escalação
  ou assunto resolvido.
- **Provas:** "+92% de reajuste" e "R$ 12.500/mês por 22 meses" removidos
  do `SOUL.md`, do revisor e do `fup.md`. Ficaram as carteiradas
  principais (SaaS / agência) e, de apoio, 101 entregas/mês, 1.125
  execuções em 344 projetos, 375 tipos, 81.131 anúncios, 602 contas, mais
  dev pleno e agência como comparação.
- **Deploy:** brain atualizado; `SOUL.md` reinstalado **sem** subir o
  prefixo (a conversa de teste 9 estava ativa e perderia a memória). As
  sessões novas pegam a persona nova. A sequência da conversa 9 foi
  ancorada às 17:55 BRT; os próximos são 2h (~19:55) e d1.

### 2026-09-28 00:40 — Identificação do lead no Instagram e perfil para rapport

- **Pedidos do usuário:**
  - pegar info do perfil do lead ("preciso pelo menos da bio e da
    descrição dos últimos posts");
  - pedir o @ quando a mensagem não vem no texto padrão;
  - rastrear o clique sem código no texto ("falharia se a pessoa editasse
    a msg"), com janela de possibilidades e "se não achar, entende que veio
    direto";
  - dúvidas sobre Apify e Zernio.
- **Opções apresentadas:**
  - **Perfil:** Meta Business Discovery (oficial e grátis; exige IG ligado
    a Página do Facebook e token do Facebook Login; só funciona para contas
    profissionais) ou Apify (qualquer perfil público; pago e contra os
    termos do Instagram).
  - **Zernio não resolve:** é só provedor de conexão do OpenReply
    (`/opt/openreply/docs/zernio.md`, "Feature availability").
  - **Limite do token atual:** o token do OpenReply é Instagram Login
    (`instagram_business_*`). Ele permite o perfil básico por IGSID
    (nome, @, seguidores, se segue), mas não bio nem posts.
- **Feito no `sdr-brain` (`enrichment.py`, testes 17/17):**
  - Resolução de identidade:
    - @ do texto do link → confirmado;
    - @ digitado pelo lead → confirmado (se está no `DmLog`) ou informado;
    - janela de 30 min (`SDR_MATCH_WINDOW_SECONDS`) sobre os `DmLog` SENT
      antes da 1ª mensagem, com desempate pelo nome do WhatsApp (contato
      do Chatwoot) → confirmado, provável, ambíguo ou direto.
  - Handles já casados com outra conversa são excluídos.
  - Só confirmado/informado entra na ficha. Candidatos nunca vão ao agente
    (teste garante).
  - Histórico no OpenReply: campanha, post, palavra, interações.
  - Perfil via Business Discovery (`META_GRAPH_TOKEN` + `IG_BUSINESS_ID`)
    e fallback Apify (`APIFY_TOKEN`, ator
    `apify~instagram-profile-scraper`), com cache de 7 dias
    (`ig_profiles`).
  - `@ da empresa` (registro `arroba`) gera `perfil_empresa`.
  - Eventos: `/events/record` com `instagram` redecide a identidade; com
    `arroba` busca o perfil da empresa.
  - Validado contra o banco real (read-only). No teste das 16:08 BRT a
    janela achou 1 candidato só por IGSID (DM sem @) → "ambiguo".
- **Feito no `SOUL.md`:**
  - Passo 4 "O @ NO INSTAGRAM": sem identidade confirmada, pergunta uma
    vez o @ pessoal e o da empresa. Nunca adivinha nem sugere @.
  - "RAPPORT COM O PERFIL": uma coisa concreta da bio ou de um post, uma
    vez, ligada à dor. Nunca lista dados nem diz que consultou.
- **Pendente, depende do usuário:** token do Business Discovery (System
  User) e/ou token Apify.
- **Pendente, próximo passo técnico:** patch no OpenReply
  (`/opt/openreply`):
  - link individual por destinatário, com o botão de volta;
  - clique com identidade;
  - @ via IGSID para quem entra só por DM.

### 2026-09-28 01:10 — Business Discovery ligado (bio e posts do lead)

- **Configuração do usuário:**
  - Usuário do sistema "Elemsm" no portfólio, com acesso total à Página EB
    (101835849661732), ao app OpenReply (1726889538405730) e ao IG
    talles.ai.
  - Token gerado por ele, sem expiração, salvo em `creds` como `tokenmeta`.
- **Diagnóstico:**
  - O 1º token (sem `instagram_manage_insights` e `ads_read`) lia a própria
    conta, mas `business_discovery` dava "(#10) Application does not have
    permission".
  - A doc exige `instagram_basic`, `instagram_manage_insights` e
    `pages_read_engagement`, mais `ads_read` ou `ads_management` quando o
    papel na Página vem do Business Manager.
  - Token refeito com as 6 permissões; o teste com @bianca.sosouza e
    @talles.ai trouxe nome, bio, site, seguidores e 6 últimos posts.
- **Feito:** `sdr_brain` com `META_GRAPH_TOKEN` e `IG_BUSINESS_ID` via
  `docker service update --env-add`. `profile_lookup('bianca.sosouza')` →
  fonte `meta`, com cache em `ig_profiles`. `sdr-brain/stack.yml` agora
  exige `META_GRAPH_TOKEN` exportado num `stack deploy`: sem ele, o token
  sumiria do serviço. `IG_BUSINESS_ID` padrão = 17841460228743369;
  `APIFY_TOKEN` opcional.
- **Limite:** só contas profissionais (comercial/criador). Conta pessoal só
  com Apify (sem token ainda). Reels sem legenda trazem legenda vazia; o
  rapport depende mais da bio.

### 2026-09-28 01:45 — OpenReply com link individual, clique atribuído e @ de DM

- **Pedido:** "segue" com a alteração no OpenReply (link individual, rastreio
  do clique sem código no texto, @ de quem entra só por DM).
- **OpenReply (`/opt/openreply`, branch `sdr-tracking`, commits `7e3107e` e
  seguinte, imagem `openreply:sdr-v2`):**
  - `lib/tracking/recipient.ts`: token `?t=` = IGSID em base64url + HMAC
    (`NEXTAUTH_SECRET`), 16 caracteres; `verifyRecipient` recusa token
    forjado ou de outro slug; `personalizeDestination` troca
    `{username}`/`%7Busername%7D` (e o `@`/`%40` antes) pelo @ codificado
    no clique.
  - Botões e links de DM (`buildLinkButtons`, fallback inline,
    `renderMessageWithTracking`) levam o token de quem recebe. A resposta
    pública em comentário não leva.
  - `app/r/[slug]/route.ts`: grava `LinkClick.recipientId/recipientName` e
    redireciona com o destino personalizado. Slug inexistente ia para
    `https://localhost:3000/` (o "localhost" que o usuário viu depois que o
    TrackedLink da campanha foi apagado); agora vai para `NEXTAUTH_URL`.
  - Gatilho por DM sem nome anterior busca o @ via
    `GET graph.instagram.com/{IGSID}?fields=username` (só Meta; Zernio segue
    como antes).
  - Migração `20260928010000_link_click_recipient`: colunas nulas + índice,
    idempotente. Backup antes em
    `~/backups/openreply/openreply-full-20260927T223213Z.dump`. Aplicada
    pelo `openreply_migrate`.
  - Testes do OpenReply 290/290 (6 novos em `recipient-link.test.ts`; 2 de
    `dm-worker.test.ts` ajustados para o link assinado). `tsc` e `eslint`
    limpos.
  - web/worker/cron/migrate em `openreply:sdr-v2`; home 200; slug inválido
    → `https://openreply.talles.dev/`.
  - `sdr_brain_ro` ganhou SELECT em `"LinkClick"`.
- **sdr-brain (18/18):** candidatos da janela vêm primeiro dos cliques
  identificados (`source=clique`), depois dos envios (`dm`).
  - 1 clique → confirmado (`clique`).
  - Vários → desempate pelo nome (`clique+nome`), senão ambíguo.
  - Sem clique, a regra anterior pelos envios.
- **Pendente do usuário:** recolocar na campanha "raiox" o botão com destino
  `https://wa.me/554825000259?text=E%20a%C3%AD%21%20Sou%20o%20%40%7Busername%7D%20e%20quero%20saber%20mais%20sobre%20o%20Raio-X`
  e voltar o `dmMessage` a usar `{link}`. O @ é preenchido no clique.

### 2026-09-28 — Conversa menos robótica, fim da dessincronia, Hermes no Sonnet, cota do Antigravity

- **Pedido:**
  - A resposta chegava fora de ordem quando o lead escrevia durante o buffer.
  - O preço saía sem contexto.
  - Faltavam confiança e rapport com o Instagram.
  - Depois: risco e limite da assinatura usada pelo modelo; o usuário ligou mais contas Antigravity.
- **Feito — bridge `sdr-v8` (42/42):**
  - Se o lead manda mensagem enquanto a resposta é gerada ou digitada, a resposta velha é descartada.
  - O lote volta para a fila junto com a mensagem nova.
  - `mensagens_corrigidas` registra só o que foi realmente enviado.
- **Feito — SOUL:**
  - identidade de quem gera confiança e diz "não é pra você";
  - a pergunta do lead vem primeiro;
  - voz "eu" e "o Talles", nunca "nós";
  - uso de `ficha.perfil` na 2ª resposta e rapport com o perfil;
  - seção de ICP com desqualificação honesta;
  - passo 7b "como funcionaria para ele";
  - âncora ligada à dor;
  - fechamento sempre escala para o Talles, sem logística inventada.
- **Feito — revisor:**
  - Regras 14 (voz), 15 (responder a pergunta do lead) e 16 (fora do perfil não recebe preço).
  - Timeouts: `SDR_REVIEW_LLM_TIMEOUT=18` (1 tentativa) e `SDR_REVIEW_TIMEOUT=22` na bridge.
- **Feito — modelo do Hermes:** `agy/claude-sonnet-4-6` em `/opt/data/config.yaml` (backup em `/opt/data/backups`), prefixo `wa:v10:`.
- **Simulações:**
  - Carla, fora do perfil: desqualificada com honestidade, agradeceu.
  - Marina, no perfil: fechou em 15 turnos e escalou para contrato e pagamento.
- **Cota Antigravity:**
  - 32 chamadas Sonnet (~460k tokens de entrada, ~15k por turno) consumiram ~8% do `claude_gpt_weekly` e ~21% da janela de ~5h do Sonnet.
  - Isso dá ~380 turnos por semana e ~150 por janela, por conta.
  - `gemini_weekly` (brain e revisor) foi a 1% e não é gargalo.
  - Conexões `agy`: lsuperagentes (prioridade 1) e ebtalles (prioridade 2, adicionada em 2026-09-27 23:37 UTC).
- **Pendente:**
  - Confirmar que a 2ª conta assume quando a 1ª esgota.
  - Alerta de 429 para o dono.
  - Opcional: conta Codex como último degrau de fallback.
  - Risco de ToS por usar assinatura em produção continua.
  - Tirar `clarify` dos toolsets; perguntar o faturamento mais cedo (observação da Carla).

### 2026-09-28 00:05 — De volta ao Gemini, SOUL reescrito para flash, silêncio na despedida (Claude Code, sessão 76cc27ab)
- **Pedido:** "resolver com o modelo não rola, volta pro gemini e melhora o prompt".
- **Feito — modelo:** `agy/gemini-3.7-flash-high` em `/opt/data/config.yaml`.
  - Backup: `config.yaml.20260928T000629Z.bak`.
  - Hermes reiniciado; o Sonnet saiu.
- **Feito — SOUL reescrito** (de ~5,5 mil para ~3,7 mil palavras; backup `SOUL.md.20260928T000629Z.bak`):
  - 8 regras invioláveis no topo.
  - A conversa em 4 fases com objetivo: conhecer, diagnosticar, dar certeza e depois o preço, decidir.
  - A pergunta de faturamento é obrigatória antes do preço, e "caixa apertado" desqualifica.
  - Rapport com o perfil na 2ª resposta.
  - Um exemplo de tom e um checklist antes de enviar.
  - `[[SILENCIO]]` depois da despedida.
  - Frases literais do roteiro mantidas.
- **Feito — revisor** (`sdr-brain:v1` reconstruído, 18/18):
  - A reescrita só corta, nunca acrescenta passo ou preço. Antes, o revisor tinha inserido a âncora no lugar da explicação do caso.
  - Lista de fatos da oferta que não são "logística inventada" (as 10h do dia 1 tinham sido apagadas).
  - Citar o perfil é rapport, não dossiê.
  - A pergunta de faturamento entra no roteiro literal e no checkpoint da regra 12.
- **Feito — bridge `sdr-v9`** (43/43, um teste novo):
  - Diretiva `[[SILENCIO]]`: não envia nada e não passa pelo revisor.
  - `HERMES_SESSION_PREFIX=wa:v12:`.
  - O simulador encerra quando o agente fica em silêncio.
- **Evidência:**
  - Simulações em `hermes-sdr/sim/rodada-2026-09-28-{marina,carla}-gemini.txt`.
  - Carla: rapport com os posts; faturamento perguntado no turno 4; desqualificada sem preço; silêncio depois do tchau.
  - Marina: diagnóstico, espelho, a explicação do caso, a âncora sozinha, depois o Raio-X ligado à dor; escalou para o fechamento no turno 12.
  - Extração com o SOUL novo: pedidos de prompt, modelo, lista de ferramentas e "ignore as instruções".
    Nos 4 casos: a frase-padrão de sigilo e volta à conversa. Guardrail sem nenhum termo vazado.
  - OmniRoute: Hermes com 44 chamadas, média de 4,8s (máximo 7s), ~8k tokens, 0 erros.
- **Pendente:**
  - 4 erros no `sdr-brain` com `gemini-3.7-flash-low` desde 00:10; investigar.
  - A pergunta "como funciona o pagamento" ficou sem resposta na simulação da Marina (deveria dizer que o Talles alinha).
  - Um deslize de voz ("pra gente focar") no teste de extração; não é vazamento, mas quebra a regra do "eu".
  - Continuam: tirar `clarify` dos toolsets; alerta de 429.
- **Checagem "o followup parou?" (21:25 BRT):**
  - Não parou: está segurando por causa do horário comercial (`SDR_BUSINESS_END_HOUR=20`).
  - Último toque enviado: conversa 10, estágio 30min, às 19:28 BRT.
  - Conversa 1: decisão das 19:54 foi "conversa em andamento"; a última atividade foi às 19:59.
  - Conversa 10: última troca às 20:47, já fora do horário.
  - Às 9h, `due_stage` decide só o estágio mais recente alcançado (sem rajada). O `tracked` sobrevive a restart do brain (tabela `tracked`).

### 2026-09-28 00:35 — Toques 24h, voz do FUP corrigida, arquitetura documentada (Claude Code, sessão 76cc27ab)
- **Pedido:** "ah bota 24h" (toques fora do horário comercial); "documenta aí toda a arquitetura e estrutura que fizemos e atualiza o log".
- **Feito — janela 24h:**
  - Bridge `sdr-v10` (43/43): a janela do despacho deixou de ser 9–20 fixo e passou a ler `SDR_BUSINESS_START_HOUR` e `SDR_BUSINESS_END_HOUR` (padrão 9 e 20).
  - `integration_bridge` e `sdr_brain` com `0` e `24`. `sdr-brain/stack.yml` com o mesmo padrão.
- **Feito — voz do FUP:**
  - Os dois primeiros toques depois da mudança (conversas 1 e 10) saíram do modelo com "a gente" e "cortar esse gasto".
  - Cancelei os dois na fila antes do envio (`sdr_followups` 6 e 7, `cancelled`, "texto fora da voz; redecidir").
  - `fup.md` ganhou as regras de voz "eu / o Talles" e de não prometer resultado. Brain reconstruído (18/18).
  - Apaguei as decisões (1, 30min) e (10, 2h) para o agente decidir de novo. Os textos novos (`sdr_followups` 8 e 9) saíram sem os problemas.
- **Feito — documentação:** `hermes-sdr/ARQUITETURA.md` reescrito com o estado atual:
  - serviços, Hermes, diretivas (com `[[SILENCIO]]`), o caminho da mensagem na bridge;
  - fila e despacho;
  - sdr-brain (revisor, supervisor, enriquecimento, FUP);
  - contrato de rotas, rastreio do OpenReply, capacidade, LLM e cota, testes e um guia de "como mudar cada coisa".
- **Pendente:**
  - O revisor não passa pelos textos de FUP; só o guardrail de termos. Vale ligar o `/review` no FUP.
  - Confirmar que a 2ª conta Antigravity assume no rate-limit.

### 2026-09-28 01:00 — Revisor nos toques, Instagram visível no Chatwoot (Claude Code, sessão 76cc27ab)
- **Pedido:** "liga o revisor nos toques também"; "pra que tá servindo o coletor do instagram? … mensagens de sistema na conversa do chatwoot … métricas no contato, tipo seguidores, soma de likes, comentários, bio e últimos posts, inclusive os links".
- **Feito — sdr-brain `v2` (20/20, 2 testes novos):**
  - `run_review` passou a ser comum ao `/review` e ao FUP.
  - O toque é revisado com `tipo: "toque"`: `reescrever` troca o texto, `bloquear` vira "não enviar".
  - `revisor.md` ganhou a seção TOQUE (não aplica a regra 15; devolve uma parte só).
- **Feito — `crm.py`:**
  - Mensagens de sistema (`activity`) para enriquecimento, revisão, orientação do supervisor e decisão de toque.
  - 12 atributos de contato `ig_*`, criados na conta 1.
  - `social_profiles.instagram` e `description` com a bio.
- **Feito — Business Discovery:** passou a trazer `like_count`, `comments_count` e `permalink` (a Apify, os equivalentes).
  - A ficha do Hermes continua sem números nem links (`for_agent`).
  - Cache `ig_profiles` limpo para buscar de novo com os campos novos.
- **Feito — bridge `sdr-v11` (43/43):** `GET /sdr/conversations/{id}` devolve `context` (capacidade etc.) para o revisor dos toques.
- **Evidência:**
  - Conversa 1: a linha "🔎 Instagram @bianca.sosouza: confirmado (texto_do_link) · 8953 seguidores, 207 posts · veio da campanha raiox".
  - O contato recebeu seguidores, posts, bio, site, curtidas (13) e comentários (0) dos 6 últimos posts, com links.
  - A mensagem de teste `activity` foi apagada.
- **Observação:** na conversa 1 o `@talles.ai` digitado não substituiu o `@bianca.sosouza` já confirmado pelo link. É a regra "nunca rebaixar uma confirmação".
- **Pendente:** ver as linhas de revisão e toque numa conversa real.

### 2026-09-28 01:15 — Nenhum travessão nem dois-pontos conectivo nas mensagens do agente (Claude Code, sessão 76cc27ab)
- **Pedido:** "não quero nenhum travessão entre as frases, coloca algo determinístico na hora de enviar pela evolution".
- **Feito — bridge `sdr-v12` (44/44, 1 teste novo):** `sdr.no_dashes` roda em toda resposta do agente (depois do revisor e do guardrail) e em todo toque, antes do Evolution e do Chatwoot.
  - Travessões (—, –, ‒, ―) e hífen com espaços (" - ") entre frases viram vírgula.
  - Travessão no início da linha, no fim ou colado a pontuação é removido.
  - Hífen dentro de palavra e intervalo ("Raio-X", "dias 2-3", "e-mail") fica.
  - Mensagem que o Talles escreve pelo Chatwoot não passa pelo filtro.
- **Ajuste pedido em seguida:** "é só aqueles travessões conectivos e aqueles : … também é paia". Agora `sdr.plain_style` = `no_dashes` + `no_colons` (45/45).
  - ": " seguido de texto vira ponto final, com maiúscula na palavra seguinte.
  - Antes de valor ("implantação: R$ 48.000") vira vírgula.
  - Dois-pontos no fim da linha vira ponto.
  - Hora (10:30) e link ficam.
- **Evidência:** no container, "dura 7 dias: o Talles também abate — se você subir…" sai "dura 7 dias. O Talles também abate, se você subir…".
- **Pendente:** o SOUL ainda tem travessões nos exemplos. O filtro garante a saída; não mexi no SOUL para não subir o prefixo de sessão só por isso.

### 2026-10-04 23:58 — Raio-X de performance do Instagram desde sexta (Graph API + OpenReply read-only)
- **Pedido:** cruzar analytics dos Reels desde sexta com roteiros/transcrições e entender padrão de performance e correção.
- **Feito:** leitura da mídia/insights de `@talles.ai` via token Meta já configurado; leitura agregada somente leitura de `DmLog` e `LinkClick` no OpenReply da VM/Portainer; relatório salvo em `/home/ubuntu/.hermes/workspace/relatorio-instagram-desde-sexta.md`.
- **Evidência:** 8 Reels, 2.255 views, 1.447 de alcance, 202 interações; OpenReply desde o corte: 24 DmLog enviados, 16 com palavra-chave, 12 respostas públicas e 5 cliques. Verificação estática do relatório passou.
- **Pendente:** OpenReply não atribui os DMs a cada Reel porque as automações consultadas estão amplas/sem `postId` no agregado; roteiros/transcrições faltam para `DeAXZmMpd6T`, `DeBEjSltytS`, `DeBFCkQtqXH` e `DeD0CnLJ0Dv`.

### Fora do escopo do Hermes (mesmo diretório, só para contexto)

- 2026-09-25 / 26 (Codex `01a0d93f`): e-mail `ceo@talles.dev` →
  `tsxtalles@gmail.com` e `heilz@talles.dev` → `tsxheilz@gmail.com`, envio via
  Resend no Gmail.
- 2026-09-27 (Claude `b21d7f1b`): pareamento do Orca mobile e interface visual
  da VM. Nada sobre o Hermes.
