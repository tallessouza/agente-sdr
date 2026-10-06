# Tarefa · Agente de vendas: SPICED, duas ofertas no mesmo funil, próximo passo acompanhado

Repositório: snapshot da produção da VM1 (06/10). **Leia antes:** `hermes-sdr/ARQUITETURA.md` (a arquitetura real), `hermes-sdr/SOUL.md`, `sdr-brain/README.md`, `sdr-brain/prompts/*.md`, `bridge-src/app.py` (partes de contexto confiável, `origin_from_text`, `HANDLE_RE`, `FIELD_RE`, `lead_state`, prefixo de sessão) e **`OFERTA-ATUAL.md`, a única fonte de fatos da oferta nova** (preço, prazos, regras, o que nunca dizer). Nada de preço, prazo ou promessa fora desse arquivo e do SOUL atual do Raio-X.

Decisões do Talles (06/10), não rediscutir:
- **Um só Hermes com as duas ofertas.** O Raio-X da Operação **faz parte do mesmo funil**, num degrau lá na frente: Instalação (R$ 47) → bumps/upsells → planos mensais → Raio-X → Copiar a minha operação. Quem chega pelo "TIME" compra a instalação agora; o Raio-X aparece como próximo degrau para quem já é cliente ou tem perfil de negócio para isso. Quem chega direto pelo Raio-X segue o caminho do Raio-X.
- **SPICED nas duas ofertas** (Situation, Pain, Impact, Critical event, Decision), no lugar do roteiro atual (Hormozi + SPIN).
- O agente **acompanha o próximo passo** de cada lead.
- A triagem usa **argumentos estruturais** das páginas do Denderson (abaixo), **nunca o texto, os nomes ou os números dele**.
- Na hora de comprar a instalação, o agente **manda `https://instalador.talles.dev/antes`** (a página que confere as condições) e **lembra que precisa ter uma VPS e a assinatura do Codex**.

## 1. SOUL (`hermes-sdr/SOUL.md`)

- Mantenha as regras gerais que já funcionam (tom, balões curtos, sem travessão nem dois-pontos, diretivas `[[REGISTRO]]`/`[[ESCALAR]]`/`[[FOTO]]`/`[[SILENCIO]]`, segurança).
- Reescreva o roteiro como **SPICED**, comum às duas ofertas, com uma pergunta por vez:
  - **S** situação: o que o negócio faz, como atende hoje, quantas pessoas, canais;
  - **P** dor: o que toma o tempo dele (responder, postar, propostas, organizar o dia);
  - **I** impacto: horas por semana, o que deixa de fazer, quanto custa (sem prometer faturamento);
  - **C** evento crítico: por que agora, até quando precisa;
  - **D** decisão: quem decide e, para o Instalador, **se já tem VPS e assinatura do Codex** (é pré-requisito, não objeção).
- **Seção por oferta**, escolhida pelo campo `oferta` do contexto confiável (`instalador` | `raiox`; sem oferta, o agente descobre pela conversa):
  - **Instalador:** fatos só de `OFERTA-ATUAL.md`. Fechamento: link `https://instalador.talles.dev/antes` + lembrete da VPS e do Codex + o que acontece depois (área do cliente, 5 campos, "Pronto." no Telegram). Quem não tem VPS ou Codex recebe o caminho para contratar (a página `/antes` tem os vídeos) e um próximo passo com data. Nunca pede senha, token nem dados do servidor na conversa (isso é só no formulário cifrado).
  - **Raio-X:** mantenha os fatos atuais (preço, âncora, vagas de `capacidade.json`), só reorganize em SPICED. Para o lead do Instalador, o Raio-X só entra como próximo degrau, e só quando o perfil justificar (negócio com equipe e faturamento para isso), nunca antes de ele ter a instalação.
- **Triagem (argumentos estruturais das páginas do Denderson, sem copiar):**
  - faturamento e número de pessoas como critério de qualificação;
  - os três perfis: quem vende conhecimento, serviço ou negócio local, pequena empresa;
  - comparação tarefa por tarefa contra o custo de alguém fazendo (com os números do próprio lead, nunca números inventados);
  - objeções previstas: "preciso saber programar?" (não), "roda no meu computador?" (roda no servidor dele, que ele mantém), "e se não funcionar?" (a garantia de `OFERTA-ATUAL.md`);
  - atendimento 24/7 e "não depende de contratar" como benefício, sem prometer resultado financeiro;
  - escassez só com dado real (capacidade por dia de `OFERTA-ATUAL.md`).
  - **Proibido:** Naia, Squad, Avalanche, nomes de agentes dele, as frases dele, os números dele ("+4 mil", "R$ 100 mil em 30 dias" etc.).
- **Registros** (via `[[REGISTRO: campo = valor]]`): `oferta`, `situacao`, `dor`, `impacto`, `evento_critico` (com data quando houver), `decisao` (quem decide), `tem_vps` (sim/não), `tem_codex` (sim/não), `proximo_passo` (texto curto), `proximo_passo_em` (data ISO), `etapa_spiced` (S/P/I/C/D/fechamento), mais os que já existem (`arroba`, `desfecho`, `preco_dado`, `objecao`…). O agente **sempre** registra `proximo_passo` e `proximo_passo_em` ao fim de cada troca relevante.

### 1a. Como mostrar a oferta: os manuais do Talles (pedido de 06/10)

**Primeira fonte (indicada pelo Talles em 06/10): os manuais já aplicados a esta oferta**, em `C:\Users\talle\orca\screener\14-oferta-instalador\`:
- `LIVRO-DA-OFERTA.md`: o manual de Ofertas aplicado (equação de valor, problemas → soluções, garantia, escassez desta oferta);
- `MANUAL-DE-VENDAS.md`: o manual de Vendas aplicado (fechamento, objeções e respostas desta oferta);
- `BRIEFING.md`: o briefing de copy (avatar, dores, promessas permitidas e proibidas, tom).

Use-os para **argumentos, objeções, equação de valor e linguagem**. Eles ainda descrevem o modelo antigo dos 3 conjuntos: **preço, cobrança, bumps, planos e regras vêm de `OFERTA-ATUAL.md`**, que reflete as decisões mais recentes. Quando um argumento depender de um conjunto que não existe mais, adapte ao modelo atual ou descarte, e liste no `worker_done`.

Os manuais originais servem para conferir o raciocínio: o SPICED **descobre**; a apresentação e o fechamento seguem:
- **`D:\Sessões\Manuais\Ofertas\Ofertas.txt`** (manual operacional do *$100M Offers*): Fase 3, **Equação de Valor** (D3.1 resultado dos sonhos em termos de status, D3.2 prova visível, D3.3 vitória rápida e em quanto tempo, D3.4 esforço e sacrifício tirados do cliente, D3.5 solução psicológica, D3.6 contra as alternativas) e Fase 4 (promessa central, problemas → soluções, empilhamento, garantia, escassez/urgência só verdadeiras).
- **`D:\Sessões\Manuais\Vendas\hormozi-framework.md`** ("Decision Making & Selling with Logic"): **2.2 processo sequencial de closing**, **2.3 árvore de decisão por tipo de objeção**, 3.3 frases e as fórmulas da Dimensão 5 (custo da ignorância, decisão de compra, análise de risco).

No SOUL:
- Depois do S-P-I-C-D, a oferta é apresentada **pela equação de valor, com as palavras do próprio lead**: o resultado que ele disse querer (P/I), a prova que existe hoje (só a real de `OFERTA-ATUAL.md`), a vitória rápida (o "Pronto." no Telegram e a primeira Pauta do dia), e o esforço que sai das costas dele (não aprende nada técnico, 5 campos). A comparação contra as alternativas (aprender sozinho, curso, consultoria) é feita com os números dele.
- O fechamento segue o processo sequencial do manual de vendas; cada objeção é classificada pela árvore 2.3 e respondida pelo ramo certo. Para o Instalador, "não tenho VPS/Codex" **não é objeção**: é pré-requisito, vira próximo passo com data.
- Escassez e urgência só com dado real (capacidade por dia, lote quando existir contador). Garantia exatamente como em `OFERTA-ATUAL.md`.
- Crie `hermes-sdr/MAPA-MANUAIS.md` mostrando, para cada trecho do SOUL, de qual decisão/seção dos manuais ele saiu (rastreável), e use o mesmo mapa no revisor (o revisor reprova apresentação que pula a equação de valor ou objeção respondida fora do ramo).

### 1b. Playbooks do Hormozi (indicados pelo Talles em 06/10)

PDFs em `C:\Users\talle\Documents\Obsidian\sc\2 - Projetos\Pessoal\Estudos\Inside\Hormozi\08 Playbooks\08 Playbooks\` (extraia com `pdftotext -layout`, que existe no Git Bash). Aplique cada um onde ele manda, citando a página no `MAPA-MANUAIS.md`:
- **$100M Lead Nurture Playbook** → `sdr-brain/prompts/fup.md` e o gatilho do próximo passo: velocidade de resposta, cadência, personalização, quando parar. Respeite os limites que já existem (até 4 toques/dia, opt-out).
- **$100M Lifetime Value Playbook** → a escada no SOUL: quando oferecer bump, plano mensal, Raio-X e Copiar a minha operação (o Raio-X é o degrau lá na frente do mesmo funil; nunca antes de o lead ter a instalação, salvo quem já chega pelo Raio-X).
- **$100M Pricing Playbook** → como apresentar o preço e a âncora (com os preços reais de `OFERTA-ATUAL.md`; nada de desconto inventado).
- **$100M Hooks Playbook** → a primeira mensagem do agente para quem chega pelo "TIME" (o texto pré-preenchido já diz o @ e a oferta: a abertura confirma e faz a 1ª pergunta do S).
- **$100M Retention Playbook** → o que o agente diz depois da compra (próximos passos até o "Pronto.", e o caminho para o degrau seguinte), sem prometer suporte que não está na oferta.
- Os demais (Branding, Fast Cash, Goated Ads, Marketing Machine, Price Raise) não entram no agente agora.

## 2. sdr-brain

- `prompts/revisor.md`: a regra do "antes do preço" vira o checklist SPICED por oferta (Instalador: S, P e D com VPS/Codex antes do link; Raio-X: o checklist atual em letras SPICED). O "ROTEIRO LITERAL" e as regras presas ao Raio-X passam a valer **só quando `oferta = raiox`**. Para `oferta = instalador`, o revisor confere os fatos contra uma lista gerada de `OFERTA-ATUAL.md` (preços, link, garantia) e bloqueia promessa de faturamento, pedido de senha/token e preço que não existe.
- `prompts/supervisor.md`: aponta qual letra do SPICED falta e cobra o registro de `proximo_passo`.
- `prompts/fup.md`: o caminho e as intensidades usam `proximo_passo`, `proximo_passo_em` e `evento_critico`; textos de FUP por oferta.
- `app.py`: tabela `lead_steps` (conversa, oferta, etapa_spiced, proximo_passo, proximo_passo_em, status, atualizado_em) alimentada por `/events/record`; no `followup_once`, gatilho **por prazo do próximo passo vencido**, além do silêncio; o lead do Instalador com `tem_vps`/`tem_codex` = não recebe o FUP no dia combinado para conferir se já contratou.
- `crm.py`: linha de atividade "📌 Próximo passo: … até …" e atributos `spiced_*` na conversa do Chatwoot.
- **Fatos da oferta fora do prompt:** um `ofertas.json` (montado como o `capacidade.json`) com os preços e links do Instalador e do Raio-X, lido pelo revisor e pelo FUP, para mudar preço sem mexer em prompt.

## 3. Bridge

- `origin_from_text`: detecta a oferta pelo texto pré-preenchido do WhatsApp. A campanha nova manda "…Sou o @{username} e quero o meu Time de IA instalado" → `oferta = instalador`; a atual (Raio-X) → `oferta = raiox`. Vai para o contexto confiável do Hermes e para `[[REGISTRO]]` `oferta`.
- `HERMES_SESSION_PREFIX` passa de `wa:v12:` para `wa:v13:` (o SOUL congela por sessão); deixe isso numa variável e documente no `ARQUITETURA.md`.
- `lead_state` já leva os registros; garanta que `proximo_passo`, `proximo_passo_em` e `oferta` chegam ao contexto.

## 4. OpenReply (`openreply/`)

- Modo **palavra exata**: nova coluna `exactMatch Boolean @default(false)` em `Automation` (migration Prisma) e, no `lib/utils/keyword-matcher.ts`, quando `exactMatch` está ligado, o comentário inteiro (sem espaços nas pontas, sem pontuação e emojis no fim, sem diferenciar maiúsculas) tem que ser igual a uma das palavras-chave. Use em `dm-worker.ts` e `comment-reconciler.ts` onde hoje passa `wholeWordMatch`. Teste em `__tests__` ("TIME", "time!", "Time 🙌" casam; "meu time é bom" não casa). Campo opcional no formulário da automação, se o formulário for simples de achar; senão, só banco + API.

## 5. Testes e pronto

- Testes unitários novos no brain (`test_app.py`), na bridge (`test_sdr.py`) e no OpenReply, todos verdes nos comandos que o README de cada um já usa.
- `hermes-sdr/sim/`: personas novas para o Instalador (com VPS e Codex e decidido; sem VPS; "preciso saber programar?"; pergunta de faturamento; tenta mandar a senha na conversa) e o roteiro de como rodar o simulador contra um **Hermes de teste** (não o de produção).
- **Não faça deploy.** Entregue os commits e um `DEPLOY.md` com a ordem exata: subir o SOUL no volume de um Hermes de teste, simular, e só depois produção (SOUL + prefixo v13 + brain v3 + bridge + OpenReply), com o rollback de cada passo.
- `worker_done` com o resumo por arquivo, os testes e qualquer fato que você não achou em `OFERTA-ATUAL.md`.
