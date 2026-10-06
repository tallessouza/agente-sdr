# Mapa dos manuais: de onde sai cada trecho do SOUL

Estado em 06/10/2026, junto com o SOUL v13 (SPICED, duas ofertas). Para cada
trecho do `SOUL.md`, a decisão ou seção dos manuais de onde ele saiu, e o que
foi adaptado. O revisor (`sdr-brain/prompts/revisor.md`) usa este mapa nas
regras **C12** (objeção no ramo certo) e **I6** (equação de valor antes do
preço).

**Ordem de autoridade:** `OFERTA-ATUAL.md` (a seção 9 vence tudo) para fatos;
os manuais só para argumento, ordem e linguagem.

**Fontes e abreviações**
- **LIVRO** · `screener/14-oferta-instalador/LIVRO-DA-OFERTA.md` (manual de Ofertas aplicado; decisões D0–D6).
- **MV** · `screener/14-oferta-instalador/MANUAL-DE-VENDAS.md` (manual de Vendas aplicado).
- **BRIEF** · `screener/14-oferta-instalador/BRIEFING.md`.
- **OF** · `D:\Sessões\Manuais\Ofertas\Ofertas.txt` (linhas).
- **HF** · `D:\Sessões\Manuais\Vendas\hormozi-framework.md` (linhas).
- **LN / LTV / PR / HK / RT** · playbooks $100M Lead Nurture, Lifetime Value,
  Pricing, Hooks e Retention (página do PDF, contada pelos `\f` do
  `pdftotext -layout`).

## 1. Estrutura geral

| Trecho do SOUL | Fonte | Como ficou |
|---|---|---|
| DUAS OFERTAS, UM FUNIL SÓ (a escada) | OFERTA-ATUAL §5 e §9; LTV p. 6, p. 20 ("More of - or more help with - what they just bought"; DIY → DWY → DFY) | Instalação → bump → planos → Raio-X → Copiar. O degrau seguinte é o próximo problema do cliente (LTV p. 4). |
| SPICED (S, P, I, C, D) | Decisão do Talles 06/10 (TAREFA-SPICED); LN p. 22 (quem é, o que quer, o que tentou, o custo de não resolver) | Uma pergunta por turno; registros por letra. |
| "Uma pergunta por vez", balões curtos | LN p. 45 ("Send multiple short messages"; Acknowledge, Compliment, Ask) | Reação ao que ele disse + uma pergunta (já era regra do SOUL v12). |
| Regra 5 (nunca prometer faturamento) | OFERTA §7; BRIEF Parte 1 ("Não usar faturamento"); LIVRO §12 (compliance D5.29) | |
| Regra 6 (nunca pedir senha) | OFERTA §7 e §6.4; SPEC:528, 533 | Reforçada no código (`sdr-brain/oferta.py`). |
| Regra 7 (concorrente proibido) | OFERTA §7; BRIEF Parte 5 ("Sem material do Denderson") | Lista literal no SOUL e no revisor (C4). |
| Regra 8 (escassez real) | OF L453–458 (D5.2, "Se não é auditável, é escassez falsa"), L758 (CDC art. 37); LIVRO §9; MV §2 | 15/dia (Instalador) e `capacidade` (Raio-X). |

## 2. Triagem (estrutura das páginas do concorrente, sem texto, nomes ou números)

| Trecho | Fonte | Como ficou |
|---|---|---|
| Faturamento e pessoas como critério | LIVRO §1 (critérios de inclusão/exclusão); BRIEF Parte 4 (avatar) | No Raio-X é entrada; no Instalador, sinal para a escada. |
| Os três perfis | LIVRO §1 (públicos listados); BRIEF Parte 4 | Conhecimento; serviço/negócio local; pequena empresa. |
| Comparação tarefa por tarefa | LIVRO §6 e D3.6; OF L301–313 (D3.6) | **Só com os números do lead.** A conta "R$ 220/mês × social media júnior" do LIVRO §6 é hipótese e foi descartada. |
| Objeções previstas (programar, computador, e se não funcionar) | BRIEF Parte 5 (tabela de objeções); LIVRO D4.2 (problemas × baldes) | Respostas com os fatos de OFERTA §2, §3, §6. |
| 24 h por dia, "não depende de contratar" | BRIEF Parte 1 (linha da promessa 1); LIVRO §1 | Benefício, nunca promessa de dinheiro. |

## 3. Caminho do Instalador

| Trecho | Fonte | Como ficou |
|---|---|---|
| A ABERTURA | HK p. 6 (call-out + condição de valor; "Oh, this is for me"), p. 20 ("Because you (thing you just did)"), p. 5 (fazer o lead se sentir importante); MV §7 (abertura) | Confirma o pedido com o @ e faz a 1ª pergunta de S. O HK não trata de chat; o resto é adaptação. A pergunta de MV §7 ("aprender ou um agente trabalhando?") não entrou: quem comentou "TIME" já respondeu isso. |
| Equação de valor, item 1 (resultado) | OF L256–265 (**D3.1**); LIVRO §3 (frase de status) | Com a frase do lead (P/I), sem status inventado. |
| item 2 (prova) | OF L267–273 (**D3.2**: "as pessoas pagam por certeza"; garantia é alavanca); LIVRO §14 (prova que falta) | Só a garantia. Não há vídeo nem prova de instalação (OFERTA §7). |
| item 3 (vitória rápida) | OF L275–285 (**D3.3**: "a única coisa que vence o grátis é o rápido"); LIVRO §4 (V1 "Pronto"); RT p. 19–20 (ponto de ativação) | O "Pronto." em até 48 h e a primeira Pauta do dia (OFERTA §6.7). O LIVRO dizia 24 h: vale 48 h (OFERTA §9). |
| item 4 (esforço) | OF L287–292 (**D3.4**); LIVRO D3.4 (tabela custo → como reduzo) | "Não instala nada, 5 campos". As linhas do LIVRO sobre IA inclusa e vídeos foram descartadas. |
| item 5 (alternativas) | OF L301–313 (**D3.6**); LIVRO D3.6 e §14 | Aprender sozinho, curso, pagar alguém, com os números dele. Sem nomear concorrente. |
| D3.5 (solução psicológica) | OF L294–299 | Não entrou como fala: o "Pronto." e a fila são do produto, não do agente. |
| O PREÇO | HF L166–172 (**2.1** "preço com confiança", **2.2** "NÃO falar mais"); PR p. 41 ("The first number… anchors"), p. 52 ("Don't Be A Sneak"), p. 60 (contra descontos); MV §7 (custo mensal dito junto, sem "só"); OF L757 (CDC art. 30) | **Adaptado:** "o preço mais alto primeiro" (HF 2.1, PR p. 54–55) não se aplica, porque os únicos itens mais caros são degraus que não podem aparecer antes da instalação. A âncora é o custo que o próprio lead disse. Pagamento antecipado com desconto (PR p. 41) **descartado** (sem desconto). |
| O FECHAMENTO, a–d | HF L151–186 (**2.2**, Fases 1–3: 1.2 confirmar desejo, 2.1 preço, 2.2 silêncio, 3.x cebola); MV §3.3 | As 3 perguntas finais (HF 3.6) ficaram só no Raio-X: para R$ 47 a decisão é curta (MV §0, venda "por escrito"). |
| Fechamento d (link + VPS/Codex + o que vem depois) | Decisão do Talles 06/10 (link `/antes` e lembrete); OFERTA §6; LN p. 36 e 45 (BAMFAM, "Never let a lead go to no-man's land") | Termina com "hoje ou amanhã?" e o registro do próximo passo. |
| Fechamento e (sem VPS/Codex = pré-requisito) | OFERTA §2 e §9 (Gemini substitui o Codex); SPEC:527 (lembrar em 24 h) | Vira próximo passo com data. Os vídeos de "como contratar" **não existem** (OFERTA §2): o SOUL não promete vídeo, só a página `/antes`. |
| DEPOIS DA COMPRA | RT p. 20 ("Tell them where to start", ativação), p. 21 ("Customers should always know when you'll speak to them next"), p. 34 (tarefa com prazo), p. 11–12 (expectativa realista, não sobrecarregar); OFERTA §6 | Um passo por vez até o "Pronto.". Sem suporte que não está na oferta (MV §0 "nenhuma conversa 1:1 sem um produto que a pague"; MV §10). |
| Planos e WhatsApp depois da compra | LTV p. 26 ("offer it after they've made their first purchase"), p. 6, p. 15 (recorrência); RT p. 30 ("ascend"); OFERTA §4 | Só quando a dor pede. Downsell só para quem não se qualifica (LTV p. 22) fica na página (Monitoramento é o downsell da Gestão). |
| A ESCADA (Raio-X depois da instalação) | Decisão do Talles 06/10; OFERTA §5 e §9.1; LTV p. 18 (oferecer o maior primeiro) **não aplicado** | O Talles decidiu que o Raio-X nunca vem antes da instalação para quem chega pelo TIME. Perfil alto → escalar depois do link. |
| OBJEÇÕES: pré-requisito / pergunta / objeção | HF L188–345 (**2.3** árvore), L174–185 (3.1 nunca discordar, 3.2 camada); MV §4 | Primeiro classificar. Pergunta ≠ resistência (já era regra do SOUL v12). |
| TEMPO (macro, micro, when-then) | HF L190–214; MV §4 TEMPO | Respostas da MV, com "5 campos" no lugar da configuração. |
| DINHEIRO | HF L216–245; MV §4 DINHEIRO ("No conjunto 1 (R$ 47–97), não usar" o skin in the game) | Volta ao número do lead; "pagar com tempo" (HF L648–656, Dimensão 5). "Conjunto 2, a IA vem inclusa" **descartado** (não existe mais). |
| ENCAIXE | HF L247–271; MV §4 FIT ("Se isso fosse perfeito, você faria?") | Identidade "dono decide e delega" (BRIEF Parte 2, "Dono não programa"). |
| OUTRA PESSOA | HF L273–295 (5 passos); MV §4 AUTORIDADE | Só o passo 1 (isolar) e a data. Os passos 2–5 (confronto, kicker) ficaram fora por tom de WhatsApp com R$ 47. |
| ADIAR | HF L297–338, L433–435 ("O que exatamente você vai pensar?"), L440–441 e L658–666 (análise de risco, 3 opções); MV §4 EVITAÇÃO | As 3 opções usam a garantia real (devolve o valor da instalação). Sem decisão: data, não escalação. |
| QUANDO CHAMAR O TALLES | OFERTA §9 (4 casos) | Literal. |

## 4. Caminho do Raio-X

Sem mudança de fatos (preço, âncora, vagas de `capacidade.json`); só a
reorganização em letras. Mapeamento: S = rapport, @, triagem e carteirada;
P = a abertura literal e a dor; I = custo, ganho e faixa de faturamento;
C = urgência, data de lançamento e o espelho; D = certeza, âncora, Raio-X, as
3 perguntas (HF L180–184) e o fechamento escalado. As respostas-modelo de
objeção são as do SOUL v12 (os três testes), com a árvore HF 2.3 como pano de
fundo (C12 no revisor).

## 5. Próximo passo e retomadas

| Trecho | Fonte | Como ficou |
|---|---|---|
| Registrar `proximo_passo` + `proximo_passo_em` em toda troca relevante | Decisão do Talles 06/10; LN p. 36 e 45 (BAMFAM); RT p. 21 | Tabela `lead_steps` no brain e gatilho por prazo no `followup_once`. |
| "te chamo [dia]" só com a data registrada | RT p. 21; LN p. 35 ("They do mind being lied to") | A promessa só vale porque o gatilho por prazo existe. |
| `fup.md`: personalização e mensagem curta | LN p. 29 ("mention it upfront"), p. 45 | O toque cita o que o lead disse logo no começo. |
| `fup.md`: concentrar no começo, parar | LN p. 34 ("front-load the reach-outs"; dia 1 com 3, dias 2–3 com 2, dias 4–7 com 1; depois nutrição longa), p. 33 (opt-in), p. 34 ("Obey the laws") | **Parcial.** A cadência do código continua 5min/30min/2h/d1 (+ d4 depois do preço), que cobre o dia 1 com 3 toques e o limite de 4/dia. Os toques dos dias 2–7 e a nutrição de longo prazo **não** foram ligados: mudam o volume de mensagens e pedem decisão do Talles. |
| Velocidade de resposta | LN p. 20 ("contact all leads in five minutes or less"), p. 44 ("under 60 seconds") | Já atendida: o agente responde em ~10 s de acúmulo + geração. |
| Lembretes de call | LN p. 35, p. 45 | Não se aplica: o agente não marca call. |

## 6. Descartado dos manuais aplicados (modelo antigo dos 3 conjuntos)

O LIVRO, o MV e o BRIEF ainda descrevem o modelo de 04/10, substituído em
05/10. Ficaram de fora do SOUL:

- Os **3 conjuntos** (Instalado / + IA inclusa / Feito por nós) e a ordem 3 → 2 → 1 na página (MV §3.1, LIVRO "Estado em 04/10").
- **IA inclusa** pela revenda do Google One (LIVRO, BRIEF, MV §10). Hoje: assinatura do cliente ou o bump Conta do Gemini (OFERTA §9).
- **Plantão** de 7/30/90 dias, conserto expresso (C2), sessão de 45 min do "Preciso de apoio" (B1), pacote da profissão (B2), "Fazemos por você" (U1/U1-d), Multi-assinatura (PRO) (LIVRO §7).
- **Lotes** 47 → 97 → 147 → 197 e o contador de instalações (LIVRO §7, §10; BRIEF "fundo"): não há contador real; OFERTA §8.3 e §9 não decidem lote.
- **Prazo de 24 h** (LIVRO §2, §4; BRIEF): vale 48 h (OFERTA §9).
- **Biblioteca de vídeos** e "um vídeo de 1 min por campo" (LIVRO §5, §8; MV §1): os vídeos não existem (OFERTA §2).
- **Calculadora** "quanto custa o seu time humano" (LIVRO §8): não existe.
- **Servidor blindado** como bônus nomeado (LIVRO §8): ficou só o fato de OFERTA §6.8 (a área avisa para trocar a senha), sem prometer proteção.
- **Call de implantação** e preços de R$ 1.997 / R$ 4.997 (MV §3.3; LIVRO §7 TOPO): substituídos pelo Raio-X e pelo Copiar.
- A âncora pública "consultoria de R$ 2,5 a 6 mil por mês" (MV §3.3): número de terceiros.
- Valores atribuídos do stack (R$ 497, R$ 997… LIVRO §5): não são fatos da oferta atual.
- "A gente instala" / "nós instalamos" (BRIEF, MV §7): o SOUL fala do que acontece com o lead, sem dizer quem instala (o Mágico de Oz não foi decidido; OFERTA §9).
