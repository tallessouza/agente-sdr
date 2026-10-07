# Relatório · Correções da auditoria do SOUL v13 (06/10)

Branch `auditoria`, sem commit, sem push, sem deploy, sem acesso à VM. Fatos: `OFERTA-ATUAL.md` (9 e 9.1 vencem).

**Resultado:** brain 66/66 testes (`python -m unittest` em `sdr-brain/`), bridge 63/63 (`bridge-src/`). O script da auditoria (`t_oferta.py`) roda 41/41 certo: nenhuma frase errada passa e nenhuma frase certa é bloqueada. As 41 frases viraram o teste `AuditPhrases` em `sdr-brain/test_oferta_auditoria.py`. No Windows, os testes da bridge rodam com um runner que ignora erro de limpeza do diretório temporário. É a trava de arquivo SQLite do Windows, que já existia antes: 25 testes davam erro só no `tearDown`. No Linux/Docker não muda nada.

| # | Achado | Correção | Teste |
|---|---|---|---|
| 1 | R$ 47 vendido como atendimento no WhatsApp | SOUL: "O QUE É" diz o que o time faz e o que NÃO faz. Na equação de valor, o resultado é só o da instalação, e o Atendimento no WhatsApp (R$ 3.000, separado) é dito antes do preço. O exemplo do studio.bela virou @ana.consultoria (propostas e organização). `ofertas.json`: `o_que_o_time_faz` e `o_que_nao_faz`. Revisor: regra I9. `oferta.py` reprova "o time atende seus clientes no WhatsApp" | `Finding01*` |
| 2 | Dois produtos de R$ 48.000 | SOUL (escada, R2, "Depois dele") e `ofertas.json` (`raiox.implantacao` e `raiox.copiar_a_minha_operacao`, com nomes separados). Revisor: X7. `oferta.py` reprova a troca (Copiar com 21 dias, fluxos ou sustentação; implantação que "reproduz a operação do Talles") | `Finding02*` |
| 3 | Escalada por perfil antes da compra | SOUL (A ESCADA, QUANDO CHAMAR): antes de `comprou = sim`, só `[[REGISTRO: perfil_raiox = sim]]`. Supervisor: escala por perfil só com `spiced.comprou = sim`. Código: o brain segura a escalada do supervisor (`profile_too_early`) e a bridge troca o `[[ESCALAR: perfil…]]` do Hermes por registro antes da compra (`hold_profile_escalation`). Se o lead pede Raio-X ou uma pessoa, escala na hora; os outros 3 casos da §9 seguem imediatos | `Finding03*`, bridge `ProfileEscalationTests` |
| 4 | `oferta.py` só checava o Instalador | Senha, faturamento, desconto, Denderson, contato e Gemini valem para qualquer oferta e sem oferta. O preço é checado no Raio-X com os valores do Raio-X (comparação, faixas, bônus e sustentação entraram no `ofertas.json`). Sem oferta, vale a união. Preço por produto: "o Raio-X é R$ 9.000" é reprovado | `Finding04*`, `AuditPhrases` |
| 5 | Lacunas e falso positivo | Novos padrões: mandar/enviar/precisar do IP e senha, print com acesso; "ajudar a faturar", "aumenta suas vendas", "se paga"; "em 1 dia", "amanhã já está pronto"; R$ 12.000 e "Raio-X" no Instalador antes da compra; as frases e os 5 nomes; squad(s). A negação vale na mesma oração ("não vou te prometer que…" passa) | `AuditPhrases`, `Finding05*` |
| 6 | Valor citado pelo lead passava direto | Passam só os valores da oferta. Exceção estreita: o custo que o próprio lead paga ("você paga R$ 2.000 pra secretária"), para a comparação tarefa por tarefa do SOUL. "Vai para R$ 97" e "você disse R$ 97" são reprovados. O SOUL ganhou a resposta para anúncio antigo: "o preço hoje é R$ 47 e o prazo é até 48 h" | `Finding06*` |
| 7 | Filtro da bridge barrava respostas legítimas | `SDR_OFFER_PHRASES` aceita: conta grátis do ChatGPT, seu ChatGPT, ChatGPT Plus/Pro, o seu Gemini, Gemini Advanced (o espaço é normalizado). Continua barrado: "eu rodo no ChatGPT Plus" (novo "modelo próprio"), "Gemini" solto, Hermes, Docker | bridge `AuditFilterAndOfferTests` |
| 8 | "Não revende assinatura" | "Não vende o servidor nem o Codex; a Conta do Gemini é opcional na compra" (SOUL e `ofertas.json`) | `Finding08*` |
| 9 | Frase do Denderson ("24 horas por dia…") | Removida. No lugar entrou o que o site diz (Telegram: responde, escreve, organiza, lembra; Pauta do dia) | `Finding09*` |
| 10 | Rótulos da triagem | Agora com palavras próprias, sem "quem vende conhecimento" | `Finding10*` |
| 11 | Lista de proibidos espalhada | Lista única em `oferta.py`. Revisor e FUP recebem por `{{PROIBIDOS}}`; o SOUL é gerado com `python oferta.py soul ../hermes-sdr/SOUL.md`, e um teste falha se divergir. Um nome que o próprio lead usou (ex.: Paulo) não é tratado como o do concorrente | `Finding11*` |
| 12 | Custo mensal no preço | Quem leva a Conta do Gemini paga por mês só a VPS, mais R$ 100 uma vez, sem citar o Codex (SOUL, revisor I8, `ofertas.custo_mensal`) | `Finding12*` |
| 13 | "4 GB" e "módulo" | Saíram do SOUL e do `ofertas.json`: a VPS é só de 8 GB (o "núcleo e módulos" do Copiar ficou, porque é outro produto) | `Finding13*` |
| 14 | Vídeos | O agente não diz que existe vídeo. "Como eu contrato?" ganhou o caminho curto e escala se a pessoa travar. O link avulso do Gemini sai pelo Talles. `oferta.py` reprova "te mando o vídeo" (no Raio-X, o "vídeo do dia 6" segue liberado) | `Finding14*` |
| 15 | "4 vagas" fixo | Agora usa `capacidade.vagas_total` e `vagas_restantes` | `Finding15*` |
| 16 | Sem oferta | O SOUL começa pelo Instalador e nunca abre com o Raio-X. Em `offer_from_text`, o que a pessoa quer vence a palavra citada, e a negação conta. "[R<n>]" continua sendo Raio-X: era o DM dos reels quando só existia o Raio-X (HERMES_OPS_LOG, 27/09). O revisor usa a oferta que o próprio rascunho registra | bridge `AuditFilterAndOfferTests`, `Finding16*` |
| 17 | "Te chamo [dia]" | Volta a regra antiga: o agente não promete contato, diz "fica à vontade para me chamar quando…", e o passo vai para o registro. `oferta.py` reprova "te chamo/te procuro…" | `Finding17*` |
| 18 | Fechamento | Turno do preço sem pergunta (exceção explícita à C8). Turno do link com link, pré-requisitos e o que vem depois juntos (exceção à C7). SOUL e revisor | `Finding18*` |
| A1 | Senha na conversa | A bridge troca o trecho por `[credencial removida]` antes do Chatwoot, do Hermes, do revisor e do supervisor. Vale também para áudio e documento. A própria bridge manda o aviso padrão, registra `mandou_credencial` e avisa o Hermes (`credencial_removida`). O brain repete a regra no transcript do Chatwoot | bridge `CredentialTests`, `ToConfirm.test_credentials_*` |
| A2 | "Reembolso em até 48 h" | Fica: está no `OFERTA-ATUAL.md` §3 (SPEC:443-445) | `ToConfirm.test_refund_*` |
| A3 | Duração da Conta do Gemini | Não se promete prazo (SOUL e nota no `ofertas.json`); `oferta.py` reprova "para sempre / por N meses" | `ToConfirm.test_gemini_*` |
| A4 | Números de cases do Raio-X no Instalador | Regra 2 do SOUL. `oferta.py` reprova os números fora do Raio-X | `ToConfirm.test_raiox_case_*` |
| A5 | Ordem SPICED × abertura do Raio-X | O SPICED diz que no Raio-X a abertura testada já é a pergunta de P, e o S vem depois. Abertura, exemplo, revisor e FUP estão coerentes | `ToConfirm.test_raiox_spiced_*` |

## O que fica para quem decide

- **Prefixo de sessão:** o SOUL mudou. O README do hermes-sdr manda subir `HERMES_SESSION_PREFIX` (hoje `wa:v13:`) no deploy. Não mexi.
- **"Quem levou o Gemini autoriza pelo próprio Gemini":** continua barrado de propósito, porque é o nome da IA solto (regra 9 do SOUL). A forma certa é "pela Conta do Gemini".
- **`validate_fixtures.py` e `simulate_fixtures.py` falham:** já falhavam igual no HEAD (asserção de texto e `fake_add` sem `structured_event`). Fora do escopo.
- **Mágico de Oz** (§9, "não decidido"): não mexi. O SOUL segue sem dizer quem instala.
