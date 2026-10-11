// Camada site: junta Maps bruto + cache dos sites em enriquecidos.json (bairro, horário, serviços, WhatsApp do site,
// Instagram/Facebook, gancho e a parte base do dossiê). Funções de horário, gancho e dossiê copiadas sem mudança de
// scripts-origem/enriquecer/montar.mjs; montarSite é o laço principal de lá, com os caminhos vindos da campanha.
// Novo aqui: dias_abertos (antes era um comando avulso de 09/10), no formato de leads.py (0 = segunda ... 6 = domingo).
import { tipoSite } from './site.mjs';
import { montarDossie, CAMPOS_DE_OUTRAS_CAMADAS } from './dossie.mjs';

const DIAS = [['segunda-feira', 'seg'], ['terça-feira', 'ter'], ['quarta-feira', 'qua'], ['quinta-feira', 'qui'], ['sexta-feira', 'sex'], ['sábado', 'sáb'], ['domingo', 'dom']];
const hora = (hhmm) => { const [h, m] = hhmm.split(':'); return `${+h}h${m === '00' ? '' : m}`; };
function faixa(s) {
  if (!s) return null;
  if (/fechado/i.test(s)) return 'fechado';
  if (/24 horas/i.test(s)) return '24h';
  const partes = s.split(',').map((p) => p.trim().match(/^(\d{1,2}:\d{2})\s*to\s*(\d{1,2}:\d{2})$/));
  if (partes.some((p) => !p)) return s.trim();
  return partes.map((p) => (p[1] === '00:00' && p[2] === '23:59') ? '24h' : `${hora(p[1])}–${hora(p[2])}`).join(' e ');
}
function porDia(oh) {
  const m = new Map((oh || []).map((o) => [o.day, o.hours]));
  return DIAS.map(([d, ab]) => ({ ab, f: faixa(m.get(d)), bruto: m.get(d) }));
}
function horarioResumo(oh) {
  if (!oh || !oh.length) return 'sem horário no Google';
  const d = porDia(oh);
  if (d.every((x) => x.f === d[0].f)) return d[0].f === '24h' ? 'aberto 24h todos os dias' : `todos os dias ${d[0].f}`;
  const grupos = [];
  for (const x of d) { const g = grupos[grupos.length - 1]; if (g && g.f === x.f) g.dias.push(x.ab); else grupos.push({ f: x.f, dias: [x.ab] }); }
  return grupos.map((g) => {
    const dias = g.dias.length === 1 ? g.dias[0] : g.dias.length === 2 ? `${g.dias[0]} e ${g.dias[1]}` : `${g.dias[0]} a ${g.dias[g.dias.length - 1]}`;
    return `${dias} ${g.f ?? 'sem horário'}`;
  }).join(', ');
}
// fechamento único de seg a sex (fim do último intervalo), ou null
function fechamentoSemana(oh) {
  if (!oh || !oh.length) return null;
  const d = porDia(oh).slice(0, 5);
  const fins = d.map((x) => { const ms = [...String(x.bruto || '').matchAll(/to (\d{1,2}:\d{2})/g)]; return ms.length ? ms[ms.length - 1][1] : null; });
  if (fins.some((f) => !f) || new Set(fins).size !== 1) return null;
  const [h] = fins[0].split(':').map(Number);
  if (h < 12 || fins[0] === '23:59') return null; // fecha de madrugada ou 24h: não serve de gancho
  return hora(fins[0]);
}
const domingoFechado = (oh) => /fechado/i.test(porDia(oh)[6].bruto || '');

function bairroDoEndereco(end, cidade) {
  // "Rua X, 123 - Bairro, Cidade - UF, CEP, Brasil"
  const m = String(end || '').match(/ - ([^,]+), ([^,]+) - [A-Z]{2}\b/);
  if (m && m[2].trim() === cidade) return m[1].trim();
  return null;
}

const virgula = (n) => String(n).replace('.', ',');
const nota1 = (n) => virgula((Math.round(n * 10) / 10).toFixed(1));
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return u; } };
const igDaUrl = (u) => { const m = String(u).match(/instagram\.com\/([A-Za-z0-9_.]{2,30})/i); return m && !['p', 'reel', 'explore', 'stories'].includes(m[1].toLowerCase()) ? m[1].replace(/\.+$/, '').toLowerCase() : null; };
const fbDaUrl = (u) => { const m = String(u).match(/facebook\.com\/([^?#]+)/i); return m ? 'facebook.com/' + m[1].replace(/\/+$/, '') : null; };
const so = (t) => String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');

// escolhe o Instagram mais parecido com o nome/domínio quando o site lista mais de um
function escolherIg(lista, n) {
  if (!lista || !lista.length) return null;
  const ref = so(n.nome) + so(host(n.site || ''));
  const pont = (h) => { const s = so(h); let k = 0; for (let L = Math.min(s.length, 8); L >= 4; L--) { for (let i = 0; i + L <= s.length; i++) if (ref.includes(s.slice(i, i + L))) { k = L; break; } if (k) break; } return k; };
  const melhor = [...lista].sort((a, b) => pont(b) - pont(a))[0];
  return pont(melhor) >= 4 || lista.length === 1 ? melhor : null;
}

function gancho(n, e) {
  const fecha = fechamentoSemana(e._oh);
  const vinteQuatro = /24h/.test(e.horario_resumo || '');
  const muitas = (n.avaliacoes || 0) >= 50 && (n.nota || 0) >= 4.5;
  if (e.site_leva_pro_whatsapp && e._wa_origem === 'site' && e._wa_confiavel && fecha && !vinteQuatro)
    return { t: `Vi que o site de vocês leva o cliente direto pro WhatsApp, e o horário no Google vai até as ${fecha} durante a semana.`, tipo: 'site_whatsapp+horario' };
  if (e.site_leva_pro_whatsapp && e._wa_origem === 'maps' && fecha && !vinteQuatro)
    return { t: `Vi que o link de vocês no Google já abre direto o WhatsApp, e o horário de vocês vai até as ${fecha} durante a semana.`, tipo: 'maps_whatsapp+horario' };
  if (muitas)
    return { t: `Vocês têm ${nota1(n.nota)} com ${n.avaliacoes} avaliações no Google, então tem muita gente procurando vocês.`, tipo: 'avaliacoes' };
  if (fecha && !vinteQuatro && domingoFechado(e._oh))
    return { t: `Vi no Google que o horário de vocês vai até as ${fecha} durante a semana, e no domingo fica fechado.`, tipo: 'horario' };
  return { t: '', tipo: '' };
}

function dossie(n, e) {
  const linhas = [];
  const cats = (e.categorias || []).filter((c) => c !== n.categoria);
  const onde = [e.bairro, `${n.cidade_maps || n.cidade}/${n.uf}`].filter(Boolean).join(', ');
  let l1 = `${n.categoria}${cats.length ? ` (também ${cats.slice(0, 3).join(', ')})` : ''} em ${onde}.`;
  if (n.avaliacoes) l1 += ` Nota ${nota1(n.nota)} com ${n.avaliacoes} avaliações no Google.`; else l1 += ' Sem avaliações no Google.';
  linhas.push(l1);
  linhas.push(`Horário no Google: ${e.horario_resumo}.`);
  if (e._tipo_site === 'site') {
    if (e.site_erro) linhas.push(`Site ${host(n.site)} não abriu (${e.site_erro}).`);
    else {
      let l = `Site ${host(n.site)}`;
      if (e.site_titulo) l += ` ("${e.site_titulo.slice(0, 80)}")`;
      if (e.servicos.length) l += `; serviços citados: ${e.servicos.join(', ')}`;
      l += e.site_leva_pro_whatsapp ? `; tem botão/link de WhatsApp${e.site_whatsapp ? ` (${e.site_whatsapp === n.telefone_e164 ? 'mesmo número deste contato' : 'número ' + e.site_whatsapp}` + ')' : ''}.` : '; sem link de WhatsApp no site.';
      linhas.push(l);
    }
  } else if (e._tipo_site === 'whatsapp') linhas.push('O link de site no Google abre direto o WhatsApp.');
  else if (e._tipo_site === 'instagram' || e._tipo_site === 'facebook') linhas.push(`Sem site próprio; o link no Google vai para o ${e._tipo_site === 'instagram' ? 'Instagram' : 'Facebook'}.`);
  else linhas.push('Sem site no Google.');
  const redes = [e.instagram && `Instagram ${e.instagram}`, e.facebook && `Facebook ${e.facebook}`].filter(Boolean);
  if (redes.length) linhas[linhas.length - 1] += ` ${redes.join('; ')}.`;
  return linhas.join('\n');
}

export { horarioResumo, fechamentoSemana, gancho, dossie as dossieBase };

// Dias com horário no Google que não seja "Fechado" (0 = segunda ... 6 = domingo). Sem horário: null (a bridge trata
// como "só dia útil").
export function diasAbertos(oh) {
  if (!Array.isArray(oh) || !oh.length) return null;
  const m = new Map(oh.map((o) => [o.day, o.hours]));
  const dias = [];
  DIAS.forEach(([d], i) => { const h = m.get(d); if (h && !/fechado/i.test(h)) dias.push(i); });
  return dias;
}

// negocios: negocios.json; brutos: Map placeId -> item bruto do Maps; cacheSite(placeId) -> registro do cache ou null;
// prioridade: lista já ordenada (ordenarPrioridade); n: quantos enriquecer; anteriores: Map telefone -> registro de
// enriquecidos.json (o que as outras camadas já gravaram é preservado).
export function montarSite({ negocios, brutos, cacheSite, prioridade, n = Infinity, anteriores = new Map() }) {
  const posPrior = new Map(prioridade.map((x, i) => [x.placeId || x.telefone_e164, i + 1]));
  const stats = { enriquecidos: 0, com_site_baixavel: 0, sites_lidos: 0, sites_falharam: 0, sites_pendentes: 0, com_instagram: 0, site_com_whatsapp: 0, ganchos: 0, tipos: {}, sem_horario: 0 };
  const saida = negocios.map((neg) => {
    const b = brutos.get(neg.placeId) || {};
    const p = posPrior.get(neg.placeId || neg.telefone_e164) || null;
    const e = { _oh: b.openingHours || [] };
    const bairroMaps = b.neighborhood || null;
    e.bairro = bairroMaps || bairroDoEndereco(neg.endereco, neg.cidade_maps || b.city);
    e.categorias = b.categories || (neg.categoria ? [neg.categoria] : []);
    e.descricao_maps = b.description || null;
    e.horario_resumo = horarioResumo(e._oh);
    const anterior = anteriores.get(neg.telefone_e164) || {};
    const preservado = Object.fromEntries(CAMPOS_DE_OUTRAS_CAMADAS.filter((k) => k in anterior).map((k) => [k, anterior[k]]));
    const novo = { prioridade: p, bairro: e.bairro, categorias: e.categorias, descricao_maps: e.descricao_maps, horario_resumo: e.horario_resumo,
      dias_abertos: diasAbertos(e._oh), instagram: null, facebook: null, site_leva_pro_whatsapp: null, site_whatsapp: null, servicos: [], site_titulo: null,
      site_descricao: null, site_erro: null, gancho: '', dossie_base: '', dossie: '', enriquecido: false };
    if (!p || p > n) return { ...neg, ...novo, ...preservado };

    stats.enriquecidos++;
    if (!e._oh.length) stats.sem_horario++;
    e._tipo_site = tipoSite(neg.site);
    e.servicos = [];
    if (e._tipo_site === 'site') {
      stats.com_site_baixavel++;
      const c = cacheSite(neg.placeId || neg.telefone_e164);
      if (!c) { e.site_erro = 'não baixado (fila não chegou)'; stats.sites_pendentes++; }
      else if (!c.ok) { e.site_erro = c.erro; stats.sites_falharam++; }
      else {
        stats.sites_lidos++;
        e.site_titulo = c.titulo || null; e.site_descricao = c.descricao || null; e.servicos = c.servicos || [];
        const ig = escolherIg(c.instagram, neg); if (ig) e.instagram = '@' + ig;
        if (c.facebook?.length) e.facebook = 'facebook.com/' + c.facebook[0];
        e.site_leva_pro_whatsapp = (c.whatsapp || []).length > 0;
        if (e.site_leva_pro_whatsapp) {
          e._wa_origem = 'site';
          const nums = c.whatsapp.filter((w) => /^\d+$/.test(w)).map((w) => (w.length <= 11 ? '55' + w : w));
          const tel = neg.telefone_e164;
          const mesmo = nums.find((w) => w.slice(-8) === tel.slice(-8));
          const mesmoDDD = nums.find((w) => w.length >= 12 && w.slice(2, 4) === tel.slice(2, 4));
          e.site_whatsapp = mesmo || mesmoDDD || nums[0] || null;
          // gancho só quando o WhatsApp do site é do próprio negócio (mesmo número ou mesmo DDD) ou é plugin/wa.link sem número
          e._wa_confiavel = !!(mesmo || mesmoDDD) || nums.length === 0;
        }
      }
    } else if (e._tipo_site === 'instagram') { const ig = igDaUrl(neg.site); if (ig) e.instagram = '@' + ig; }
    else if (e._tipo_site === 'facebook') e.facebook = fbDaUrl(neg.site);
    else if (e._tipo_site === 'whatsapp') { e.site_leva_pro_whatsapp = true; e._wa_origem = 'maps'; const m = String(neg.site).match(/(\d{10,15})/); e.site_whatsapp = m ? m[1] : null; }

    if (e.instagram) stats.com_instagram++;
    if (e.site_leva_pro_whatsapp && e._wa_origem === 'site') stats.site_com_whatsapp++;
    const g = gancho(neg, e);
    if (g.t) { stats.ganchos++; stats.tipos[g.tipo] = (stats.tipos[g.tipo] || 0) + 1; }
    const out = { ...neg, ...novo, ...preservado, bairro: e.bairro, instagram: e.instagram ?? null, facebook: e.facebook ?? null, site_leva_pro_whatsapp: e.site_leva_pro_whatsapp ?? null,
      site_whatsapp: e.site_whatsapp ?? null, servicos: e.servicos, site_titulo: e.site_titulo ?? null, site_descricao: e.site_descricao ?? null,
      site_erro: e.site_erro ?? null, gancho: g.t, gancho_tipo: g.tipo || null, dossie_base: dossie(neg, e), enriquecido: true };
    out.dossie = montarDossie(out);
    return out;
  });
  // os campos originais não podem mudar (mesma trava de montar.mjs)
  for (let i = 0; i < negocios.length; i++) for (const k of Object.keys(negocios[i])) {
    if (JSON.stringify(negocios[i][k]) !== JSON.stringify(saida[i][k])) throw new Error(`campo original alterado: ${i} ${k}`);
  }
  return { saida, stats };
}
