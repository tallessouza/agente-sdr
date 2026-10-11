// Lente "tem dinheiro e investe em marketing" (feita em 11/10). Nota, motivos e provas de scripts/qualificar-riqueza.mjs;
// a linha "Sinais de investimento" do dossiê de scripts/lente-riqueza.mjs. Grátis e determinística.
// CNPJ não ativo na Receita vai para o fim da fila (nota -1).

export const norm = (s) => String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
  .replace(/\s*[-|–]\s*.*$/, '').replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
export const domain = (u) => { try { return new URL(/^https?:/.test(u) ? u : 'https://' + u).hostname.replace(/^www\./, ''); } catch { return ''; } };
export const SOCIAL = /(instagram|facebook|linktr\.ee|wa\.me|whatsapp|google\.|bit\.ly|linkr|beacons|taplink)/i;
const NICHO_ALVO = /(imobili|concession|seminov|ve[ií]culos|autom[oó]ve|estetic|est[eé]tica|odonto|dentist)/i;
const seguidoresDe = (s) => { const m = String(s || '').match(/([\d.]+)\s+seguidores/); return m ? Number(m[1].replace(/\./g, '')) : null; };

// CNPJ a consultar de cada negócio: o do decisores.json, senão o primeiro válido do rodapé do site
export function cnpjDoNegocio(n, decisores, sites) {
  const d = decisores[n.telefone_e164] || decisores[String(n.telefone_e164).replace('+', '')] || {};
  return { d, cnpj: (d.cnpj || (sites[n.site]?.cnpjs || [])[0] || '').replace(/\D/g, '') };
}

// todos: lista completa (para contar unidades); negocios: os que entram na fila; sites: url -> sinais; cnpjs: cnpj -> consulta
export function qualificar({ todos, negocios, decisores, sites, cnpjs }) {
  const porNome = {}, porDominio = {};
  for (const n of todos) {
    const key = norm(n.nome);
    if (key) (porNome[key] ||= new Set()).add(n.endereco || n.placeId);
    const dom = n.site && !SOCIAL.test(n.site) ? domain(n.site) : '';
    if (dom) (porDominio[dom] ||= new Set()).add(n.endereco || n.placeId);
  }
  const out = negocios.map((n) => {
    const { d, cnpj: cnpjNum } = cnpjDoNegocio(n, decisores, sites);
    const site = n.site ? sites[n.site] : null;
    const cj = cnpjNum ? cnpjs[cnpjNum] : null;
    const unidades = Math.max(porNome[norm(n.nome)]?.size || 1, n.site && !SOCIAL.test(n.site) ? (porDominio[domain(n.site)]?.size || 1) : 1);
    const sinais = {
      site_lido: site ? (site.ok ? true : 'erro') : null,
      meta_pixel: site ? (site.ok ? site.pixels.meta_pixel : 'erro') : null,
      google_ads: site ? (site.ok ? site.pixels.google_ads : 'erro') : null,
      gtm: site?.ok ? site.pixels.gtm : site ? 'erro' : null,
      ga: site?.ok ? site.pixels.ga : site ? 'erro' : null,
      tiktok: site?.ok ? site.pixels.tiktok : site ? 'erro' : null,
      hotjar_clarity: site?.ok ? site.pixels.hotjar_clarity : site ? 'erro' : null,
      cnpj: cnpjNum || null, cnpj_fonte: d.cnpj ? 'decisores.json' : cnpjNum ? 'rodapé do site' : null,
      capital_social: cj?.ok && Number.isFinite(cj.capital_social) ? cj.capital_social : null,
      porte: cj?.ok ? cj.porte : (d.porte || null), matriz: cj?.ok ? cj.matriz : null, situacao: cj?.ok ? cj.situacao : null,
      unidades, avaliacoes: n.avaliacoes ?? null, seguidores: seguidoresDe(n.instagram_resumo),
    };
    const provas = {};
    if (site?.ok) for (const [k, v] of Object.entries(site.provas || {})) provas[k] = `${site.final || site.url}: ${v}`;
    if (cj?.ok) provas.cnpj = `https://brasilapi.com.br/api/cnpj/v1/${cnpjNum}`;
    let nota = 0; const motivos = [];
    if (sinais.meta_pixel === true || sinais.google_ads === true) { nota += 3; motivos.push(`anuncia: ${[sinais.meta_pixel === true && 'Meta Pixel', sinais.google_ads === true && 'tag do Google Ads'].filter(Boolean).join(' e ')} no site`); }
    const tags = ['gtm', 'ga', 'tiktok', 'hotjar_clarity'].filter((k) => sinais[k] === true);
    if (tags.length) { nota += Math.min(2, tags.length); motivos.push(`ferramentas de marketing no site: ${tags.join(', ')}`); }
    if (sinais.capital_social >= 100000) { nota += 2; motivos.push(`capital social R$ ${sinais.capital_social.toLocaleString('pt-BR')}`); }
    else if (sinais.capital_social >= 30000) { nota += 1; motivos.push(`capital social R$ ${sinais.capital_social.toLocaleString('pt-BR')}`); }
    if (/^DEMAIS$/i.test(String(sinais.porte || '').trim())) { nota += 2; motivos.push('porte DEMAIS (acima de EPP)'); }
    if (unidades >= 2) { nota += 2; motivos.push(`${unidades} unidades na lista`); }
    if (sinais.avaliacoes >= 200) { nota += 2; motivos.push(`${sinais.avaliacoes} avaliações no Google`); }
    else if (sinais.avaliacoes >= 50) { nota += 1; motivos.push(`${sinais.avaliacoes} avaliações no Google`); }
    if (sinais.seguidores >= 5000) { nota += 1; motivos.push(`${sinais.seguidores.toLocaleString('pt-BR')} seguidores no Instagram`); }
    if (NICHO_ALVO.test(`${n.nicho} ${n.categoria || ''}`)) { nota += 1; motivos.push(`nicho alvo (${n.nicho})`); }
    if (sinais.situacao && sinais.situacao !== 'ATIVA') { nota = -1; motivos.unshift(`CNPJ ${sinais.situacao} na Receita: fim da fila`); }
    return { telefone_e164: n.telefone_e164, nome: n.nome, nicho: n.nicho, cidade: n.cidade, prioridade: n.prioridade, sinais, provas,
      socios_cnpj: cj?.ok ? cj.socios : undefined, nota, motivos };
  });
  out.sort((a, b) => b.nota - a.nota || (a.prioridade ?? 9999) - (b.prioridade ?? 9999));
  return out;
}

// O que é público e do próprio negócio pode ser dito; cadastro (capital, porte, situação) é só para o agente.
export function linhaLente(x) {
  const fmt = (v) => Number(v).toLocaleString('pt-BR');
  const s = x.sinais, pode = [], interno = [];
  if (s.meta_pixel === true) pode.push('investem em anúncio na Meta (Instagram/Facebook)');
  if (s.google_ads === true) pode.push('investem em anúncio no Google');
  if (s.meta_pixel === true || s.google_ads === true) interno.push('como sabemos: código de anúncio no site (não diga isso)');
  else if (s.gtm === true || s.ga === true) interno.push('site com ferramentas de medição (Tag Manager/Analytics)');
  if (s.unidades >= 2) pode.push(`${s.unidades} unidades`);
  if (s.avaliacoes >= 50) pode.push(`${fmt(s.avaliacoes)} avaliações no Google`);
  if (s.seguidores >= 1000) pode.push(`${fmt(s.seguidores)} seguidores no Instagram`);
  if (s.capital_social != null) interno.push(`capital social R$ ${fmt(s.capital_social)}`);
  if (s.porte) interno.push(`porte ${s.porte}`);
  if (s.situacao && s.situacao !== 'ATIVA') interno.push(`CNPJ ${s.situacao}`);
  return `Sinais de investimento (lente, nota ${x.nota}): ${pode.length ? pode.join('; ') : 'nenhum sinal público de anúncio ou de porte'}.`
    + (interno.length ? ` Só para você, nunca cite: ${interno.join('; ')}.` : '');
}
