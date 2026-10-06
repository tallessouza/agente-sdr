# Oferta atual: Time de IA Instalado

Estado em 06/10/2026, 18h40 (Brasília). Fontes abreviadas: **SPEC** = `orca/instalador/docs/SPEC.md` · **COPY** = `instalador/docs/COPY.md` · **FUNIL** = `instalador/docs/FUNIL-KIWIFY.md` (commit a61fd44, 06/10 18:20) · **PÁG** = instalador.talles.dev lida em 06/10 18:35 · **ANU** / **PUB** / **MV** / **LIVRO** / **BRIEF** = `screener/14-oferta-instalador/` ANUNCIOS-RODADA-1, PUBLICOS-E-REGRAS, MANUAL-DE-VENDAS, LIVRO-DA-OFERTA, BRIEFING. Sessões: id curto + data e hora de Brasília.

## 1. O que é

O cliente já tem uma VPS e a assinatura do Codex. A gente instala nela um time de IA que chega pronto no Telegram dele, sem aula e sem ele abrir terminal (COPY:16; sessão 4df93c3b 03/10 21:02).

## 2. Pré-requisitos (obrigatórios antes de comprar)

- **VPS:** Ubuntu, 8 GB de RAM, referência Hostinger KVM2, cerca de R$ 119/mês (COPY:47; SPEC:13). Com 4 GB roda só o Hermes e mais 1 módulo (SPEC:13).
- **Codex:** plano pago do ChatGPT, Plus ou maior. Conta grátis não funciona. Referência: R$ 100/mês (SPEC:13; COPY:48; PÁG).
- **Sem os dois, não compra:** `/antes` só libera o checkout com os 2 checks (SPEC:32, 210). Previsto mandar os vídeos de como contratar e lembrar em 24 h (SPEC:527), mas os vídeos ainda não existem (PÁG: "vídeo em breve").
- Lembrar dos dois na hora da compra (sessão 6dfb301a 06/10 18:06).

## 3. Produto principal

- **Instalação do Time de IA: R$ 47, pagamento único.** Checkout em pay.kiwify.com.br/ju44Xqc (FUNIL:11; COPY:55; PÁG).
- **Prazo:** até 48 h depois do formulário completo, por ordem de chegada (COPY:17, 63). A fila só começa a contar com o formulário completo (COPY:123).
- **Capacidade:** 15 instalações por dia. A 16ª fica para o dia seguinte (COPY:17; SPEC:308, 313).
- **Garantia "Pronto em 48 h":** se o time não avisar "Pronto." em até 48 h depois do formulário completo e correto, a gente continua até ficar pronto; se não ficar, devolve tudo. Valem ainda os 7 dias de arrependimento do CDC (COPY:57; PÁG). Para pedir: botão em `/app/garantia`, com reembolso em até 48 h (SPEC:443-445).
- Reembolso ou chargeback da instalação bloqueia a área do cliente (memória app-instalador.md:22).

## 4. Bumps, upsells e downsell

| Item | Preço | Cobrança | Onde | É | NÃO é |
|---|---|---|---|---|---|
| **Time de agentes** | sem preço (sugestão R$ 27–47) | único | bump do checkout | orquestrador + 4 papéis (operação, dev, copy, atendimento) (SPEC:470; FUNIL:43) | **ainda não existe na Kiwify** (FUNIL:18) |
| **Conta do Gemini** | R$ 100 | único | bump do checkout | conta ligada ao time, "enquanto disponível" (FUNIL:12, 44; SPEC:473) | — |
| **Gestão do time** | quinzenal R$ 150 · semanal R$ 450 · diário R$ 1.300 | mensal | upsell 1, `/oferta/gerenciamento` | sugestões do que melhorar e automatizar (COPY:98; PÁG) | **não mexe no que foi instalado**; quem executa é o cliente (sessão 34bcad80 05/10 21:50; COPY:100) |
| **Monitoramento** (Básico) | R$ 150/mês | mensal | downsell de quem recusa a Gestão, `/oferta/monitoramento` | vigia de 5 em 5 min, alerta no Telegram dele e no nosso, resumo mensal (COPY:106-107) | **conserto não incluso** (SPEC:20) |
| **Atendimento no WhatsApp** | R$ 3.000 | único | upsell 2, `/oferta/whatsapp` | configurado no número dele; responde, qualifica e passa o lead (COPY:113-114) | — |
| **RAIOX da Operação** | R$ 12.000 | único | fora do checkout, link na conversa | diagnóstico pago das rotinas: o que automatizar primeiro e quais módulos servem (SPEC:557-559; FUNIL:16, 28) | — |
| **Copiar a minha operação** | R$ 48.000 | único | fora do checkout, depois do Raio-X | reproduz no servidor do cliente a operação da VM1 do Talles (núcleo + módulos) (SPEC:476, 483-494; FUNIL:17) | nunca leva as contas, bots, números, memória, bancos nem a persona do Talles (SPEC:502) |

- Monitoramento e Gestão são planos independentes. O cliente pode ter um, outro ou os dois (SPEC:20; sessão 34bcad80 05/10 21:50).
- Cancelou um plano: a instalação continua na VPS dele (SPEC:20; PÁG/termos).

## 5. A escada do funil

1. Comentário "TIME" no Instagram, em qualquer post, só a palavra exata (sessão 6dfb301a 06/10 18:29; PUB:126).
2. Conversa com o agente.
3. `instalador.talles.dev` → `/antes` → checkout de R$ 47 + bumps (sessão 6dfb301a 06/10 18:06; FUNIL:24).
4. Gestão do time → se recusar, Monitoramento → Atendimento no WhatsApp → `/obrigado` (FUNIL:25-27).
5. Raio-X da operação, já por conversa (FUNIL:28).
6. Copiar a minha operação, com o valor do Raio-X abatido (SPEC:554, 474).

O Raio-X é um degrau lá na frente do mesmo funil: um Hermes só, com as duas ofertas, e SPICED nas duas (sessão 6dfb301a 06/10 18:29; sessão 34bcad80 05/10 21:43).

**Quando oferecer** (leitura da sessão 6dfb301a 06/10 18:31, sem regra escrita pelo Talles): a quem já é cliente ou tem negócio grande o bastante. Lead que chega direto pelo Raio-X segue o caminho atual. MV:69: nada de call de implantação antes de 10 "Pronto." reais.

## 6. Fluxo de compra

1. O agente manda `instalador.talles.dev`; o `/antes` confere os pré-requisitos (sessão 6dfb301a 06/10 18:06; COPY:74-80).
2. Pagamento na Kiwify, depois as páginas de oferta e `/obrigado` (FUNIL:24-27).
3. Entrada na área do cliente com o mesmo e-mail da compra e um código de 6 números (COPY:123, 133).
4. Formulário de 5 campos (IP, usuário, senha, token do bot, ID do Telegram), mais o check "tenho Codex" e até 3 objetivos; cifrado no envio (COPY:155-163).
5. Passo 0 da instalação: a senha é usada uma vez para colocar uma chave SSH nossa (uma por cliente) e apagada em seguida (SPEC:342, 289; sessão 34bcad80 05/10 21:55).
6. Passo 4: o cliente autoriza o Codex por link e código, na conta dele (SPEC:322, 346).
7. **"Pronto."** no Telegram. O time faz 15 perguntas e, no dia seguinte, manda a primeira "Pauta do dia" (COPY:34, 148).
8. A área avisa para trocar a senha. O login por senha **continua ligado**: tem fail2ban e alerta (SPEC:350; sessão 34bcad80 05/10 21:57).

## 7. O que o agente NUNCA faz ou diz

- Prometer faturamento (SPEC:528; COPY:65) ou dar desconto (SPEC:528; LIVRO:33).
- Mostrar ou descrever tela que não existe; hoje não há vídeos nem prova de instalação (SPEC:55, 528; PÁG).
- Pedir senha, token ou IP na conversa: só pelo formulário cifrado (SPEC:528, 533).
- Revender servidor ou assinatura (COPY:49).
- Citar preço, prazo ou garantia fora deste arquivo (SPEC:532).
- Dizer que é curso; quem quer aprender vai para outro caminho (COPY:61; MV:262).
- Usar texto, nome, número, imagem ou depoimento do Denderson ("Naia" inclusa); dele só a estrutura dos argumentos de triagem (SPEC:3, 45; BRIEF:208; sessão 6dfb301a 06/10 18:06).
- Usar "bom dia" como marca: a assinatura é "Pronto." (ANU:5-7).
- Usar contador ou escassez falsos (MV:64, 254), ou dar suporte grátis fora de produto (MV:29, 265).

## 8. Divergências e pontos em aberto

1. **Prazo:** página 48 h (COPY:17); anúncios "em até 24 h" (ANU:26) e LIVRO:245 24 h; SPEC:18 ainda aberto.
2. **O que a garantia devolve:** "tudo" (COPY:57); "100% do P0 e dos bumps" (LIVRO:397); instalação + avulsos + 1ª mensalidade (SPEC:444); termos no ar: só "o valor da instalação" (`src/app/termos/page.tsx:4`).
3. **Preço fixo ou lote:** R$ 47 único (FUNIL:11); anúncio 6 "na nº 50 vai para R$ 97" (ANU:81-85); lotes 47→97→147→197 (LIVRO:320-325); SPEC:17 aberto.
4. **Revenda de IA:** "não revende assinatura" (COPY:49) × bump Conta do Gemini R$ 100 (FUNIL:12). "IA inclusa" do Google One ainda aparece em memória instalador-hermes-produto.md:28, LIVRO:174 e MV:134, 220 (modelo de 3 conjuntos, substituído em 05/10, SPEC:14).
5. **Funil na Kiwify não terminado:** Time de agentes não existe, o checkout não tinha bumps e o upsell estava sendo configurado no painel (FUNIL:18, 46-49; sessão 8277a4f1 06/10 18:25). Falta decidir o preço do Time de agentes e se o Gemini fica como bump ou vira o 3º upsell (FUNIL:48-49).
6. **Gestão do time:** "relatório mensal de sugestões" (COPY:99) × planos de acompanhamento quinzenal/semanal/diário (PÁG); formato e quantidade em aberto (SPEC:17, 472). FAQ e termos ainda dizem "Gerenciamento" (`src/app/page.tsx:22`).
7. **Raio-X:** o SOUL do container o vende como 7 dias, 4 vagas/mês, âncora "implantação R$ 48 mil", vagas desatualizadas desde 27/09 (levantamento da VM1, sessão 6dfb301a 06/10 18:21); SPEC:474 diz "sessão agendada + relatório"; R$ 48 mil hoje é o "Copiar" (FUNIL:17).
8. **VPS:** "Ubuntu ou Debian" (SPEC:13) × só Ubuntu (COPY:47).
9. **Instalação manual (Mágico de Oz), script inexistente** (SPEC:336; COPY:146): não decidido se o agente diz isso.
10. Sem preço: conserto avulso fora do Monitoramento (SPEC:20). Não implementado: link de afiliado da VPS (memória instalador-hermes-produto.md:22). Não escrita: a regra de quando passar para o Talles (SPEC:520).

## 9. Decisões do Talles em 06/10 (resolvem a seção 8; valem acima de tudo o que está acima)

- **Prazo:** o agente promete **até 48 h** depois do formulário completo (igual à página e à garantia). Pode dizer que costuma sair antes, sem prometer. Os anúncios que dizem 24 h ficam desatualizados.
- **Garantia "Pronto em 48 h":** cobre **só a instalação**. Bumps e planos mensais seguem as regras próprias (7 dias de arrependimento do CDC). A página e a FAQ do app passam a dizer isso.
- **Pré-requisito de IA:** **assinatura do Codex OU a Conta do Gemini comprada como bump.** A Conta do Gemini **substitui** o Codex, e só nesse caso (comprada como bump na instalação). O agente diz isso quando o lead não tem Codex: "sem Codex? dá para levar a Conta do Gemini junto na compra". A VPS continua obrigatória para todos.
- **Na instalação**, quem levou o Gemini autoriza pelo OAuth do Gemini (no lugar do device code do Codex). A página `/antes` aceita "tenho o Codex" ou "vou levar a Conta do Gemini".
- **O agente passa a conversa para o Talles** (`[[ESCALAR]]`) quando:
  1. o lead tem perfil para o Raio-X ou o Copiar a minha operação (negócio com equipe e faturamento para o degrau de cima);
  2. há pedido de reembolso ou reclamação sobre compra feita;
  3. surge dúvida técnica fora do roteiro (servidor diferente, outro sistema, integração específica);
  4. a pessoa pede para falar com um humano.
- **Mágico de Oz:** a instalação é feita pela equipe (o agente diz "a nossa equipe instala", sem dizer que é automática e sem detalhar o processo interno).
