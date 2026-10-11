# AGENTS.md (agente-sdr)

Produção na VM1: menor mudança possível, backup antes, registro no `HERMES_OPS_LOG.md` (`~/orca/projects/portainer-install`). Deploy da bridge só com alguns minutos sem atividade e 0 turnos abertos.

# Decidir antes de agir: objetivo, custo, esforço, impacto, controle e irreversibilidade

Decisão do Talles em 11/10/2026, depois de a Nóris (#77, lead quente) receber 4 toques em 4 minutos porque reprocessei a conversa dela sem olhar o que a fila ia mandar: "mais um lead perdido por burrice". Base: Manual de Inteligência Pragmática (`D:\Sessões\Manuais\IP\manual-operacional-inteligencia-pragmatica.md`, 3.5 DECIDIR e protocolos 3 e 6).

**Quando vale.** Antes de toda ação que sai para fora ou não se desfaz:
- mensagem, toque, retomada ou template para lead;
- reprocessar, destravar ou religar fila;
- deploy, reinício ou troca de imagem;
- escrita em banco de produção;
- instalar SOUL, prompt ou config;
- criar, editar ou apagar template na Meta;
- apagar dado, arquivo ou item do cofre;
- push;
- gasto.

O que é local e reversível (ler, testar, editar com git) não precisa.

**O cartão, escrito na resposta antes de agir.** A profundidade é proporcional a impacto × irreversibilidade.
1. **Objetivo:** a que objetivo da tarefa atual isto serve e que métrica mexe (resposta de lead, call marcada, saúde do número, conta sem bloqueio).
2. **Alternativas:** no mínimo duas, sempre incluindo "não fazer agora" e "fazer menor" (um caso só).
3. **Impacto (3Ps):**
   - potencial na métrica principal;
   - período do efeito;
   - pessoas: quantos e quais leads ou serviços são atingidos.
4. **Custo e esforço:** tempo, dinheiro, atenção do Talles, tokens e risco à conta.
5. **Controle:** o que depende de nós e o que é externo (Meta, lead, Chatwoot, filas); pré-mortem em uma linha.
6. **Irreversibilidade:** dá para desfazer? Rollback em uma linha. Mensagem entregue a lead não volta.
7. **Confiança:** em que a previsão se apoia. Alto impacto e irreversível exige simular antes ("balas antes de canhões"):
   - o que vai sair, para quem e quando;
   - o que a ação destrava: toques vencidos, filas, agendamentos.

**Regras que saem daí.**
- **Destravar fila:** antes de reprocessar ou destravar uma fila, liste o que ela vai mandar em seguida. Se mais de um item estiver vencido, decida um por um.
- **Lead quente na dúvida:** não mande. Lead quente é quem respondeu, tem conversa em andamento ou call marcada.
- **Quem cobra:** o GateGuard do ECC (`scripts/hooks/gateguard-fact-force.js`, no cache e no marketplace do plugin) devolve este cartão em toda barreira. Atualizou o ECC: reaplique com `node ~/.claude/hooks/cartao-gateguard.cjs <caminho do gateguard-fact-force.js>`.
