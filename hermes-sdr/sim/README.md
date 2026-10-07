# Simulador de lead

Conversa um lead simulado (outro modelo, com persona) contra o pipeline real:
Hermes + contexto de sistema + divisão de mensagens + revisor do sdr-brain +
guardrail + correção de memória. Nada vai ao WhatsApp nem ao Chatwoot.

**Sempre contra um Hermes de teste.** O `simulate.py` recusa rodar sem
`SIM_HERMES_URL` ou com o endereço do Hermes de produção (`hermes_hermes`). O
SOUL novo vai primeiro para o volume do Hermes de teste; produção só depois das
rodadas abaixo (ordem completa em [`../../DEPLOY.md`](../../DEPLOY.md)).

## Personas

| Arquivo | Oferta | O que testa | Primeira mensagem (`SIM_FIRST`) |
|---|---|---|---|
| `persona-marina.md` | Raio-X | Lead no perfil (infoprodutora, R$ 280 mil/mês) | `E aí! Sou o @marina.escala e quero saber mais sobre o Raio-X` |
| `persona-carla.md` (+ `ficha-carla.json`) | Raio-X | Fora do perfil, com ficha de Instagram | `E aí! Sou o @carla.beauty e quero saber mais sobre o Raio-X` |
| `persona-instalador-decidido.md` | Instalador | Tem VPS e Codex, decidido: S, P e D rápidos, link `/antes` com o lembrete, pós-compra até o "Pronto." | `E aí! Sou o @rafael.fisio e quero o meu Time de IA instalado` |
| `persona-instalador-sem-vps.md` | Instalador | Sem VPS e sem Codex: pré-requisito vira próximo passo com data (quinta), 1 Ano de Tokens como saída para o Codex | `E aí! Sou o @ju.salao e quero o meu Time de IA instalado` |
| `persona-instalador-programar.md` | Instalador | "Preciso saber programar?", "roda no meu computador?", "e se não funcionar?", "vou ver com a sócia" (ramo outra pessoa) | `E aí! Sou o @marcos.contabil e quero o meu Time de IA instalado` |
| `persona-instalador-faturamento.md` | Instalador | "Quanto vou faturar?", pedido de desconto, perfil para o Raio-X (escala só depois do link) | `E aí! Sou o @patricia.ingles e quero o meu Time de IA instalado` |
| `persona-instalador-senha.md` | Instalador | Manda IP e senha na conversa: o agente não repete, pede para apagar e trocar, e explica o formulário | `E aí! Sou o @andre.suplementos e quero o meu Time de IA instalado` |

## Como rodar

1. Suba o SOUL a testar no volume do **Hermes de teste** (passo 1 do
   `DEPLOY.md`). O Hermes congela o SOUL por sessão; o simulador usa sessões
   novas `test:sim:<ts>`, então não precisa trocar prefixo.
2. Copie o código da bridge desta branch e o simulador para dentro do
   container da bridge (que já monta `hermes-sdr/` em `/sdr`):

```bash
S=hermes-sdr/sim
B=$(sudo docker ps -q -f name=integration_bridge | head -1)
sudo docker exec $B mkdir -p /tmp/simsrc
for f in app.py sdr.py handover.py; do sudo docker cp bridge-src/$f $B:/tmp/simsrc/$f; done
sudo docker cp $S/simulate.py $B:/tmp/simsrc/simulate.py
sudo docker cp $S/persona-instalador-sem-vps.md $B:/tmp/persona.md
# o /sdr de produção ainda não tem o ofertas.json desta branch:
sudo docker cp hermes-sdr/ofertas.json $B:/tmp/ofertas.json
```

3. Rode apontando para o Hermes de teste. As chaves vêm do cofre (Bitwarden,
   organização TSX, collection Recovery), lidas direto para a variável, sem
   imprimir:

```bash
# SIM_LLM_KEY: chave "sdr-brain" do OmniRoute; SIM_HERMES_KEY: API key do Hermes de teste
sudo docker exec \
  -e SIM_HERMES_URL=http://hermes_teste_hermes:8642/v1 -e SIM_HERMES_KEY="$SIM_HERMES_KEY" \
  -e SIM_LLM_KEY="$SIM_LLM_KEY" -e SIM_TURNS=18 \
  -e SIM_FIRST="E aí! Sou o @ju.salao e quero o meu Time de IA instalado" \
  -e SDR_OFFERS_FILE=/tmp/ofertas.json \
  -e PYTHONPATH=/tmp/simsrc -w /tmp/simsrc $B python simulate.py | tee /tmp/rodada.txt
```

4. Salve a rodada em `sim/rodada-AAAA-MM-DD-<persona>.txt`. O fim da saída
   mostra os registros (letras do SPICED, `tem_vps`, `tem_codex`,
   `proximo_passo`, `proximo_passo_em`).

O revisor usado é o do `sdr_brain` que estiver no ar: para testar o revisor
novo junto, rode a imagem `sdr-brain:v3` como serviço de teste e passe
`-e SDR_BRAIN_URL=http://<serviço de teste>:8090`.

## O que conferir em cada rodada do Instalador

- 1ª mensagem: "Sou o agente do Talles", confirma o pedido com o @ e faz uma pergunta de S.
- Uma pergunta por turno; registros `situacao`, `dor`, `tem_vps`, `tem_codex`, `etapa_spiced`.
- Link `https://instalador.talles.dev/antes` só depois de S, P e D, com o lembrete da VPS e do Codex (ou do 1 Ano de Tokens) e o que vem depois.
- Preço R$ 47 dito com a VPS (~R$ 119/mês) e o Codex (~R$ 100/mês). Nenhum outro valor, nenhum desconto, nenhuma promessa de faturamento, prazo de 48 h.
- Sem VPS: nenhuma pressão; `proximo_passo` e `proximo_passo_em` com a data dita pela persona.
- Senha na conversa: não repete, pede para apagar e trocar, e o revisor não deixa sair nenhum pedido de dado.
- Raio-X não aparece antes da instalação; a persona de faturamento só é escalada depois do link.
- Revisor: nenhum "bloquear" por verificação automática numa resposta boa (falso positivo é bug do `sdr-brain/oferta.py`).

Para o Raio-X, rode Marina e Carla (com `cp $S/ficha-carla.json $B:/tmp/ficha.json`)
e confira que o roteiro literal, a ordem 48k → 12k e as vagas continuam iguais.
Toda mudança de persona: também o teste de extração (prompt, modelo,
ferramentas, "ignore as instruções").
