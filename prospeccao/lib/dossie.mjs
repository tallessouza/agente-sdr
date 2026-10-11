// Dossiê: o único campo que a bridge repassa ao agente com tudo junto (FIELDS de leads.py / prospeccao.py).
// Cada camada grava a sua linha num campo próprio do negócio; o dossiê é sempre remontado a partir deles, na mesma
// ordem, então rodar uma camada de novo troca a linha dela e não duplica nada.
//
// Ordem: base do site (categoria e local, horário, site e redes) -> Instagram -> posts que mais engajaram ->
// comentários -> decisor -> sinais de investimento (lente).

// Os campos que o agente recebe (leads.FIELDS em bridge-src/leads.py). Campo novo exige mudar FIELDS e fazer deploy.
export const FIELDS = ['nome', 'nicho', 'categoria', 'cidade', 'uf', 'bairro', 'nota', 'avaliacoes', 'site', 'instagram', 'horario_resumo',
  'servicos', 'site_leva_pro_whatsapp', 'dossie', 'gancho', 'dias_abertos'];

// Campos que outras camadas gravam e que a camada site preserva quando roda de novo.
export const CAMPOS_DE_OUTRAS_CAMADAS = ['instagram_resumo', 'instagram_engajamento', 'instagram_comentarios', 'decisor', 'sinais_investimento', 'lente_nota'];

const LINHAS = ['instagram_resumo', 'instagram_engajamento', 'instagram_comentarios', 'decisor', 'sinais_investimento'];

export function montarDossie(n) {
  const base = String(n.dossie_base || '').split('\n').filter(Boolean);
  return [...base, ...LINHAS.map((k) => n[k]).filter((v) => typeof v === 'string' && v.trim())].join('\n');
}

// troca/acrescenta uma linha com prefixo no dossiê (de ig-lista/comum.mjs; útil para dossiês que vieram de fora)
export function poeLinha(dossie, prefixoRe, linha) {
  const ls = String(dossie || '').split('\n').filter((l) => !prefixoRe.test(l));
  if (linha) ls.push(linha);
  return ls.join('\n');
}

// Item da fila (/prospeccao/fila e prospeccao.enqueue): telefone + FIELDS, vazios como null.
export function filaItem(n) {
  const o = { telefone_e164: n.telefone_e164 };
  for (const k of FIELDS) o[k] = n[k] ?? null;
  return o;
}

export function linhaDecisor(reg) {
  const d = reg?.decisor;
  if (!d?.nome) return null;
  return `Decisor: ${d.como_chamar || d.nome} (${d.papel || 'dono'}${reg.confianca ? `; confiança ${reg.confianca}` : ''}).`;
}
