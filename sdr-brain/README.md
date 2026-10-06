# sdr-brain

Serviço FastAPI do SDR (Python 3.13, porta 8090). Estado SQLite fica em `/data` e é persistido entre reinícios.

| Variável | Uso | Padrão |
|---|---|---|
| `SDR_BRAIN_TOKEN` | Bearer token obrigatório nas rotas protegidas | sem padrão (503) |
| `SDR_BRAIN_DB` | arquivo SQLite | `/data/sdr-brain.db` |
| `SDR_BRAIN_LLM_URL`, `SDR_BRAIN_LLM_KEY`, `SDR_BRAIN_MODEL` | endpoint, chave e modelo OpenAI-compatible | OmniRoute / `agy/gemini-3.7-flash-low` |
| `BRIDGE_URL` | URL da bridge | `http://integration_bridge:8080` |
| `CHATWOOT_URL`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_API_TOKEN` | transcript | `http://chatwoot_rails:3000` |
| `OPENREPLY_DSN` | Postgres somente leitura | vazio (desabilitado) |
| `META_GRAPH_TOKEN`, `IG_BUSINESS_ID` | Business Discovery opcional | vazio (desabilitado) |
| `SDR_STEP_DUE_HOUR` | hora local em que vence um próximo passo datado sem hora (`proximo_passo_em = AAAA-MM-DD`) | `10` |
| `SDR_STEP_ACTIVITY_DELAY` | segundos de espera para juntar `proximo_passo` e `proximo_passo_em` numa linha "📌 Próximo passo" no Chatwoot | `3` |

Os fatos das ofertas não ficam aqui: chegam em `context.ofertas`, que a bridge lê de `hermes-sdr/ofertas.json`. `oferta.py` gera a lista de fatos para o revisor e faz a verificação automática do Instalador (preço inexistente, link fora da oferta, pedido de senha, promessa de faturamento, desconto, prazo de 24 h, nomes proibidos); o que sobrar depois do modelo vira `bloquear`.

Rotas: `GET /health` (sem autenticação), `POST /review`, `POST /events/exchange`, `POST /events/lead` e `POST /events/record` (Bearer obrigatório).

Para executar: `pip install -r requirements.txt && SDR_BRAIN_TOKEN=dev uvicorn app:app --port 8090`. Para testar: `python -m unittest -v` ou `sudo docker build -t sdr-brain:dev sdr-brain && sudo docker run --rm sdr-brain:dev python -m unittest -v`.
