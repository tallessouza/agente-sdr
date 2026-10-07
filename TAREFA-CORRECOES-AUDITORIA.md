# Tarefa · Correções da auditoria do SOUL v13 (06/10)

Uma auditoria independente achou 18 problemas no que o agente diria a clientes reais. Corrija todos. Fonte dos fatos: `OFERTA-ATUAL.md` (a seção 9 e a **9.1** vencem o resto). Branch própria, sem push, sem deploy, sem acessar a VM. Cada correção com teste (brain `test_app.py`/`test_oferta*`, bridge `test_sdr.py`) e com as frases abaixo viradas casos de teste. O script de teste da auditoria está em `C:\Users\talle\AppData\Local\Temp\claude\C--Users-talle-orca-screener\6dfb301a-55e7-4979-850a-5b624cdfa206\scratchpad\t_oferta.py` (reaproveite as 41 frases).

## Alta
1. **Instalação de R$ 47 vendida como atendimento no WhatsApp.** `SOUL.md:138-139`, `:205-208`, `:268-269`, exemplo `:617-621`. O resultado mostrado na equação de valor só pode ser o que a instalação faz (o time no Telegram do dono: responde, escreve, organiza, lembra; a Pauta do dia; ver o site). Se a dor do lead for atender clientes no WhatsApp, o agente diz **antes do preço** que isso é o Atendimento no WhatsApp (R$ 3.000), produto separado, e não vem nos R$ 47. Troque o exemplo do studio.bela por um que caiba na instalação.

## Médias
2. **Dois produtos de R$ 48.000 (decisão 9.1):** a implantação do Raio-X (21 dias, 3-5 fluxos, sustentação R$ 7-9 mil/mês) é o passo depois do Raio-X; "Copiar a minha operação" (R$ 48.000, Raio-X abatido) é outro. Nomes separados no SOUL e no `ofertas.json`; o agente nunca usa um pelo outro; o revisor reprova a troca.
3. **Escalada por perfil antes da compra.** `SOUL.md:284-287`, `supervisor.md:13`. Lead do Instalador com perfil Raio-X/Copiar: registra `perfil_raiox = sim` e segue a venda da instalação; só passa ao Talles depois da compra registrada (ou se ele mesmo pedir o Raio-X/humano). Os outros 3 casos de escalar da §9 continuam imediatos.
4. **`oferta.py` só checa o Instalador** (`:93-94`). As checagens de senha/dado sensível, faturamento, desconto e Denderson valem para **qualquer oferta e sem oferta**; a de preço também no Raio-X (com os valores do Raio-X).
5. **Lacunas e falso positivo do `oferta.py`** (`:26-36`): pegar "pode me mandar a senha", "me envia os dados do servidor", "preciso do IP e da senha", "manda um print com o acesso"; "vai te ajudar a faturar mais", "aumenta suas vendas", "se paga no primeiro cliente"; "em 1 dia", "amanhã já está pronto"; o R$ 12.000 do Raio-X citado numa conversa do Instalador antes da compra; "Pare de contratar", "no lugar do Chefe", Rafael/Juliana/Davi/Paulo/Jonathan, "squad(s)". Tratar negação: "não vou te prometer que você vai faturar mais" passa.
6. **Valor citado pelo lead passa direto** (`:97`). Só valores que existem na oferta passam. No SOUL, a resposta para quem chega citando anúncio antigo ("24 h", "depois da nº 50 vai para R$ 97"): o preço hoje é R$ 47 e o prazo é até 48 h; sem discutir o anúncio.
7. **Filtro da bridge barra respostas legítimas** (`bridge-src/sdr.py:67-84`): liberar "conta grátis do ChatGPT", "seu ChatGPT", "ChatGPT Plus/Pro", "o seu Gemini", "Gemini Advanced"; continuar barrando o agente dizer qual modelo ele próprio usa.
8. **"Não revende assinatura"** (`SOUL.md:196`, `ofertas.json:43`): trocar por "não vende o servidor nem o Codex; a Conta do Gemini é opcional na compra".
9. **Frase do Denderson** (`SOUL.md:170-172`, "24 horas por dia… não depende de contratar ninguém"): remover; usar o que o site diz.

## Baixas
10. Os 3 perfis da triagem (`SOUL.md:162-165`): rótulos com palavras próprias (não "quem vende conhecimento").
11. Lista de proibidos completa (Naia, Squad, Avalanche, "Bom dia, Naia", as 3 frases, os 5 nomes) em `SOUL.md:62-63`, `revisor.md:24`, `fup.md:58`, `oferta.py:20`, de uma lista só (gerada de um lugar).
12. Custo mensal no preço (`SOUL.md:222-224`, `revisor.md:44` regra I8): quem vai levar a Conta do Gemini paga só a VPS por mês, mais R$ 100 uma vez; não citar o Codex para ele.
13. "4 GB" (`SOUL.md:184`, `ofertas.json:11`): dizer só 8 GB; tirar "módulo".
14. **Vídeos (decisão 9.1):** o agente não diz que há vídeo; "como eu contrato?" = caminho curto (VPS Ubuntu 8 GB, ex. Hostinger; ChatGPT Plus ou maior, ou a Conta do Gemini na compra; o link avulso do Gemini para quem já comprou a instalação sem ele) e escala se travar.
15. "4 vagas por mês" fixo (`SOUL.md:443`, `:453`): usar `capacidade.vagas_total`.
16. Sem oferta definida (`SOUL.md:33-35`, `offer_from_text`): começar pelo Instalador, nunca abrir com o Raio-X. Precedência: o que a pessoa diz que quer vence a palavra citada ("não quero raio-x, quero o time" = instalador; "vi o raio x e quero montar um time" = instalador). Formato antigo "[R3]" continua reconhecido como Raio-X se o texto antigo era do Raio-X (confira no git log/README da bridge).
17. "Te chamo [dia]" (`SOUL.md:573-575`): volte à regra antiga (não promete nem agenda contato); pode dizer "fica à vontade para me chamar quando…", e o próximo passo vai para o registro.
18. Fechamento: no turno do preço, sem pergunta no fim (exceção explícita à C8 do revisor); no turno do link, link + pré-requisitos + o que vem depois juntos (exceção à C7).

## A confirmar (faça o seguro)
- Senha mandada pelo lead na conversa: a bridge troca o trecho por "[credencial removida]" antes de mandar ao Hermes, ao revisor e ao supervisor, e manda o aviso padrão; não dá para apagar do WhatsApp, mas não propaga para os modelos nem para os registros. Teste.
- `ofertas.json:17` "reembolso em até 48 h": se não estiver no site/termos/`OFERTA-ATUAL.md`, tirar.
- "Enquanto disponível" do Gemini: o agente não promete prazo de duração da Conta do Gemini.
- Regra 2 (`SOUL.md:41-43`): números de cases do Raio-X não entram como prova na conversa do Instalador.
- No Raio-X, a ordem SPICED e a abertura testada ficam coerentes.

Pronto quando todos os testes passam (os comandos do README de cada parte) e o script da auditoria, rodado de novo, não acha nenhuma frase errada passando nem frase certa bloqueada. `worker_done` com a tabela achado → correção → teste.
