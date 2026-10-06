# hermes-sdr

Arquivos do SDR que roda no Hermes do Portainer. Arquitetura em
[`ARQUITETURA.md`](ARQUITETURA.md).

| Arquivo | Para quê | Como aplica |
|---|---|---|
| `SOUL.md` | Persona do agente | Copiar para o volume `hermes_chatwoot_data` (`/opt/data/SOUL.md`, somente leitura). Só vale para sessões novas: suba `HERMES_SESSION_PREFIX` na bridge ao trocar a persona. |
| `capacidade.json` | Vagas e horas do mês | Copie `capacidade.exemplo.json`, preencha e atualize `atualizado_em`. A bridge lê a cada turno. Ausente ou com mais de 7 dias, o agente não fala preço e escala. |
| `ofertas.json` | Preços, links, prazos, garantia e regras do Instalador e do Raio-X (fonte: `OFERTA-ATUAL.md`) | Editar à mão, como o `capacidade.json`. A bridge lê a cada turno e manda em `ofertas` no contexto do Hermes, do revisor e do FUP. Mudar preço não exige mexer em prompt (mas confira o SOUL: o teste do brain compara os valores do SOUL com este arquivo). |
| `MAPA-MANUAIS.md` | De onde saiu cada trecho do SOUL (manuais e playbooks) e o que foi descartado | Documento; o revisor cita as regras C12 e I6 dele. |
| `midia/` | Fotos da carteirada | Coloque a imagem e descreva em `midia/descricoes.json` (`{"arquivo.jpg": "o que ela mostra"}`). Foto sem descrição não é oferecida ao agente. |

A pasta é montada na bridge em `/sdr` (somente leitura). Mudanças em
`capacidade.json` e `midia/` valem no próximo turno, sem redeploy.
