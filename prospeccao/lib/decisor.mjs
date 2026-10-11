// Camada decisor: dono ou decisor de cada negócio (CNPJ e QSA na BrasilAPI, site, bio do Instagram).
// A lógica é a de scripts-origem/decisores/*.mjs, juntada num módulo: as funções puras foram copiadas sem mudança de regra
// (comum, baixar, extrair, decidir, ig, final); o que lia arquivo fixo do scratchpad agora recebe os dados por parâmetro,
// e o que ia à rede usa ctx.deps.fetch (mock nos testes). Páginas baixadas são dados não confiáveis: só texto.
// Do decisor, só o contato profissional que ele mesmo publica (bio/link do @ pessoal, e-mail com o nome dele no site).
import { consultarCnpj } from './cnpj.mjs';
import { businessDiscovery } from './instagram.mjs';

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36';

// --- de decisores/comum.mjs ---
export function decode(s) {
  return s.replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'")
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&#(\d+);/g, (_, n) => { try { return String.fromCodePoint(+n); } catch { return ' '; } })
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => { try { return String.fromCodePoint(parseInt(n, 16)); } catch { return ' '; } })
    .replace(/&[a-z]+;/gi, ' ');
}
export function htmlTexto(html) {
  return decode(html.replace(/<script[\s\S]*?<\/script>/gi, ' ').replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<noscript[\s\S]*?<\/noscript>/gi, ' ').replace(/<br\s*\/?>/gi, ' \n ').replace(/<\/(p|div|li|h\d|section|footer|span|a)>/gi, ' | ')
    .replace(/<[^>]+>/g, ' ')).replace(/[ \t\r]+/g, ' ').replace(/(\s*\|\s*)+/g, ' | ').replace(/\s*\n\s*/g, '\n').trim();
}

export function cnpjValido(c) {
  c = c.replace(/\D/g, '');
  if (c.length !== 14 || /^(\d)\1+$/.test(c)) return false;
  const calc = (base) => { let w = base.length - 7, s = 0; for (const ch of base) { s += +ch * w--; if (w < 2) w = 9; } const r = s % 11; return r < 2 ? 0 : 11 - r; };
  const d1 = calc(c.slice(0, 12)); const d2 = calc(c.slice(0, 12) + d1);
  return c.endsWith('' + d1 + d2);
}
export function achaCnpjs(t) {
  const out = new Set();
  for (const m of t.matchAll(/\b\d{2}[.\s]?\d{3}[.\s]?\d{3}\s?[.\/\\]?\s?\d{4}\s?[-–.]?\s?\d{2}\b/g)) {
    const c = m[0].replace(/\D/g, ''); if (cnpjValido(c)) out.add(c);
  }
  return [...out];
}
export const norm = (s) => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();

// --- de decisores/baixar.mjs ---
const KW = /(sobre|quem[-_ ]?somos|institucional|a[-_]empresa|empresa|equipe|nosso[-_]?time|time|profissiona|corpo[-_]?clinico|especialista|dentista|advogad|socio|contato|fale|privacidade|politica|termos|lgpd|doutor|\bdra?\b|dra?[-_.]|fundador|historia|clinica)/i;
const SKIP = /\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|mp4|mp3|css|js)(\?|$)|wp-content\/uploads|\/feed|\/tag\/|\/categoria|\/category|\/imovel\/|\/imoveis\/|\/produto|\/blog\/.+/i;

function tipo(url) {
  let h; try { h = new URL(url).hostname.toLowerCase().replace(/^www\./, ''); } catch { return 'x'; }
  if (/(instagram|facebook|fb|wa\.me|whatsapp|tiktok|youtube|linkedin|twitter|x\.com|linktr\.ee|google|bio\.link|beacons)/.test(h)) return 'social';
  return 'site';
}
function links(html, base) {
  const out = [];
  for (const m of html.matchAll(/<a\b[^>]*href\s*=\s*["']([^"'#]+)["'][^>]*>([\s\S]{0,300}?)<\/a>/gi)) {
    let u; try { u = new URL(decode(m[1].trim()), base).href; } catch { continue; }
    out.push({ u, t: htmlTexto(m[2]).slice(0, 80) });
  }
  return out;
}

// --- de decisores/extrair.mjs ---
const NOME = "[A-ZÀ-Ý][a-zà-ÿ'´]+(?:\\s+(?:d[aeo]s?\\s+|e\\s+)?[A-ZÀ-Ý][a-zà-ÿ'´]+){0,4}";
const RE_TIT = new RegExp(`\\b(Dra|Dr|Doutora|Doutor)\\.?\\s*(${NOME})`, 'g');
const RE_REG = /\b(CRO|OAB|CRECI|CRM|CRC|CRBM|CREFITO|COREN|CRN|CRF)\b\s*[-/:]?\s*(?:[A-Z]{2}\s*[-/:]?\s*)?(?:n[ºo°.]*\s*)?[\d.]{2,}\s*(?:[-/]?\s*[FJ]\b)?(?:\s*[-/]\s*[A-Z]{2}\b)?/g;
const RE_PAPEL = /(respons[áa]vel\s+t[ée]cnic[oa]|\bR\.?\s?T\.?\b\s*[:\-]|fundador[a]?|co-?fundador[a]?|\bs[óo]ci[oa]s?(?![a-zà-ú])[\s-]*(?:fundador[a]?|propriet[áa]ri[oa]|administrador[a]?|diretor[a]?)?|\bCEO\b|diretor[a]?\s+(?:cl[íi]nic[oa]|t[ée]cnic[oa]|geral|executiv[oa])|propriet[áa]ri[oa]|idealizador[a]?|criador[a]? d[ao]|quem sou|advogad[oa] respons[áa]vel|contador[a]? respons[áa]vel|corretor[a]? respons[áa]vel)/gi;
const STOP = new Set(['Dr', 'Dra', 'Clínica', 'Clinica', 'Odontologia', 'Estética', 'Advocacia', 'Imóveis', 'Atendimento', 'Saiba', 'Agende', 'Agendar', 'Conheça', 'Whats', 'WhatsApp', 'Contato']);

function trecho(t, i, len, r = 90) { return t.slice(Math.max(0, i - r), i + len + r).replace(/\s+/g, ' ').trim(); }
function pessoas(t) {
  const out = [];
  for (const m of t.matchAll(RE_TIT)) {
    const nome = m[2].split(/\s+/).filter((w, k) => !(k === 0 && STOP.has(w))).join(' ');
    if (!nome || STOP.has(nome.split(' ')[0])) continue;
    out.push({ tipo: 'titulo', nome: `${m[1]}. ${nome}`.replace('..', '.'), trecho: trecho(t, m.index, m[0].length, 70) });
  }
  for (const m of t.matchAll(RE_REG)) out.push({ tipo: 'registro', reg: m[0].replace(/\s+/g, ' ').trim(), trecho: trecho(t, m.index, m[0].length, 110) });
  for (const m of t.matchAll(RE_PAPEL)) out.push({ tipo: 'papel', papel: m[0], trecho: trecho(t, m.index, m[0].length, 110) });
  return out;
}
const emails = (t) => [...new Set((t.match(/[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}/gi) || []).map((e) => e.toLowerCase()).filter((e) => !/\.(png|jpg|webp|gif)$|sentry|wixpress|example|domain|email\.com$|seuemail|@2x/.test(e)))];
const mencoes = (t) => [...new Set((t.match(/(?<![\w.])@[a-z0-9._]{3,30}/gi) || []).map((x) => x.toLowerCase().replace(/\.$/, '')))];

// --- de decisores/decidir.mjs (BUSCA e o cache da BrasilAPI vêm em `fontes`) ---
const GEN = new Set('ltda me eireli epp sa s a sociedade individual de advocacia advogados associados clinica odontologia odontologica estetica imoveis imobiliaria contabilidade contabil servicos locadora locacao veiculos automoveis assessoria consultoria e da do das dos de em sc sao jose palhoca centro grupo the'.split(' '));
const CNAE = {
  'imobiliária': /imobili|im[oó]ve|corretagem/i, 'clínica de estética': /est[ée]tica|beleza|cabel|m[ée]dic|ambulatori|sa[uú]de|fisiot|massag|depila|cosm/i,
  'clínica odontológica': /odonto/i, 'escritório de advocacia': /jur[ií]dic|advoc/i, 'locadora de veículos': /loca[çc][ãa]o|aluguel|automóve|automove|ve[ií]culo/i, 'escritório de contabilidade': /contab|auditoria|escritura/i,
};
const toks = (s) => norm(s).split(' ').filter((w) => w.length > 2 && !GEN.has(w));
const RUA = /(\b(R|Rua|Av|Avenida|Al|Alameda|Rod|Rodovia|Pç|Praça|Travessa|Tv|Edif[ií]cio|Ed|Hospital|Escola|Col[eé]gio)\.?\s*$)/i;
function titulo(nome) { const m = nome.match(/^(Dra|Dr|Doutora|Doutor)\.?\s+/i); return m ? (/a$/i.test(m[1]) ? 'Dra.' : 'Dr.') : null; }
const BL = new Set('direito imobiliario corretor corretora corretores imoveis imovel clinica odontologia estetica geral advocacia advogados advogado advogada contabilidade contabil medicina integrativa touche full face saude locacao equipe nossa nosso atendimento especialista especialistas harmonizacao facial avancada studio centro rua avenida implantes ortodontia periodontia endodontia protese cirurgia dentista dentistas biomedica biomedico esteticista consultoria assessoria servicos boulevard imob gestao empresa escritorio diretor diretora fundador fundadora socio socia ceo sobre quem somos contato whatsapp instagram agende agendar sua seu agenda trabalhista previdenciario familia civil penal tributario empresarial'.split(' '));
const cap =(w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
const trechoCurto = (t, max = 160) => t.length > max ? t.slice(0, max) + '…' : t;
export function escolherCnpj(e, tel, fontes) {
  let b = tel && fontes.busca[tel]?.achados?.length ? fontes.busca[tel] : null;
  if (b && !b.consultas) {
    const cs = {};
    for (const c of [...new Set(b.achados.map((a) => a.cnpj))].slice(0, 4)) { const x = fontes.lerCnpj(c); if (x) cs[c] = x; }
    b = { ...b, consultas: cs };
  }
  if (!e.cnpj && !b) return null;
  const alvo = new Set([...toks(e.nome), ...toks(e.ig?.name || ''), ...toks(e.ig?.user || '')]);
  let best = null;
  const lst = [...Object.values(e.cnpj?.consultas || {}).map((r) => [r, (e.cnpj.fontes || []).find((f) => f.cnpj === r.cnpj)]),
    ...Object.values(b?.consultas || {}).map((r) => { const a = b.achados.find((x) => x.cnpj === r.cnpj); return [r, a && { cnpj: r.cnpj, fonte: 'busca web', url: a.url, trecho: a.trecho }]; })];
  for (const [r, fonteB] of lst) {
    if (!r.ok) continue;
    if (fonteB?.fonte === 'busca web') {
      const nomes = toks(`${r.razao_social} ${r.nome_fantasia || ''}`);
      const ov = nomes.filter((w) => alvo.has(w)).length;
      const cnaeB = CNAE[e.nicho]?.test(r.cnae || '');
      if (!(ov > 0 && norm(r.municipio) === norm(e.cidade) && (cnaeB || ov >= 2))) continue; // busca web: exige nome, cidade e (CNAE do ramo ou 2 palavras do nome)
    }
    const nomes = toks(`${r.razao_social} ${r.nome_fantasia || ''}`);
    const overlap = nomes.filter((w) => alvo.has(w) || [...alvo].some((a) => a.length > 4 && (a.includes(w) || w.includes(a)) && w.length > 4)).length;
    const cnae = CNAE[e.nicho]?.test(r.cnae || '') ? 1 : 0;
    const cidade = norm(r.municipio) === norm(e.cidade) ? 1 : 0;
    const ativo = r.situacao === 'ATIVA' ? 1 : 0;
    const score = overlap * 3 + cnae * 2 + cidade + ativo;
    const fonte = fonteB;
    const aceito = (overlap > 0 || cnae) && !(fonte?.fonte.startsWith('registro') && !overlap && !cnae);
    if (aceito && (!best || score > best.score)) best = { ...r, score, overlap, cnaeOk: cnae, cidadeOk: cidade, fonte };
  }
  return best;
}
// nomes de pessoas citadas (site + Instagram + nome do negócio)
function citados(e) {
  const out = [];
  const add = (nome, fonte, url, trecho, peso, papel) => {
    nome = nome.replace(/\s+/g, ' ').trim(); if (nome.split(' ').length < 2) return;
    if (nome.replace(/^(Dra|Dr|Doutora|Doutor)\.?\s*/i, '').split(' ').some((w) => BL.has(norm(w)))) return;
    out.push({ nome, fonte, url, trecho: trechoCurto(trecho), peso, papel });
  };
  for (const x of e.site_pessoas || []) {
    if (x.tipo !== 'titulo') continue;
    const antes = x.trecho.slice(0, x.trecho.indexOf(x.nome.replace(/^(Dra|Dr|Doutora|Doutor)\.\s*/, '').split(' ')[0]));
    if (RUA.test(antes.replace(/(Dra|Dr|Doutora|Doutor)\.?\s*$/i, '').trim())) continue;
    const papel = /respons[áa]vel t[ée]c|R\.?\s?T[ée]?c?\.?\s*:|\bRT\b/i.test(x.trecho) ? 'responsável técnico' : /fundador|s[óo]ci[oa]\b|\bCEO\b|propriet|idealizador|diretor/i.test(x.trecho) ? 'sócio/fundador' : null;
    add(x.nome, 'site', x.url, x.trecho, papel ? 3 : 1, papel);
  }
  for (const x of e.site_pessoas || []) {
    if (x.tipo === 'papel' && /respons|R\.?\s?T|fundador|CEO|propriet|idealiz|quem sou|s[óo]ci/i.test(x.papel)) {
      const depois = x.trecho.slice(x.trecho.toLowerCase().indexOf(x.papel.toLowerCase()) + x.papel.length);
      const m = depois.match(/^[\s:|–\-·.]*(?:(?:Dra|Dr|Doutora|Doutor)\.?\s*)?([A-ZÀ-Ý][a-zà-ÿ]+(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ý][a-zà-ÿ]+){1,4})/);
      if (m) add(m[1], 'site', x.url, x.trecho, 3, /respons|R\.?\s?T/i.test(x.papel) ? 'responsável técnico' : 'sócio/fundador');
    }
    if (x.tipo === 'registro' && /CRO|OAB|CRM|CRC|CRBM|CRECI\s*[-:]?\s*[\d.]+\s*-?\s*F?\b(?!\s*-?\s*J)/.test(x.reg) && !/J\b/.test(x.reg)) {
      const antes = x.trecho.slice(0, x.trecho.indexOf(x.reg));
      const m = antes.match(/(?:(?:Dra|Dr)\.?\s*)?([A-ZÀ-Ý][a-zà-ÿ]+(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ý][a-zà-ÿ]+){1,4})[\s|–\-·:,]*$/);
      if (m) add(m[1], 'site', x.url, x.trecho, 2, /respons|R\.?\s?T/i.test(antes.slice(-40)) ? 'responsável técnico' : 'registro profissional');
    }
  }
  if (e.ig?.bio) {
    const t = `${e.ig.name || ''} | ${e.ig.bio}`;
    for (const m of t.matchAll(/(?:(Dra|Dr|Doutora|Doutor)\.?\s*|(?:Respons[áa]vel\s*T[ée]c[a-z.]*|R\.?\s?T\.?)\s*:?\s*(?:(?:Dra|Dr)\.?\s*)?)([A-ZÀ-Ý][a-zà-ÿ]+(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ý][a-zà-ÿ]+){0,4})/g)) {
      const nome = (m[1] ? m[1] + '. ' : '') + m[2];
      const rt = /respons|R\.?\s?T/i.test(m[0]);
      if (m[2].split(' ').length >= 2 || m[1]) add(m[1] ? nome : m[2], 'instagram bio', 'https://instagram.com/' + e.ig.user, t.replace(/\n/g, ' / '), rt ? 3 : 2, rt ? 'responsável técnico' : null);
    }
  }
  const mn = e.nome.match(/(Dra|Dr|Doutora|Doutor)\.?\s+([A-ZÀ-Ý][a-zà-ÿ]+(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ý][a-zà-ÿ]+){0,3})/);
  if (mn) add(`${mn[1]}. ${mn[2]}`, 'nome no Google Maps', null, e.nome, 2, null);
  for (const [nome, c] of Object.entries(e.legenda_titulos || {})) if (c >= 2) add(nome, 'legendas do Instagram', 'https://instagram.com/' + e.ig.user, `${nome} citado em ${c} posts recentes`, 1, null);
  return out;
}
function bate(qsaNome, citado) {
  const q = norm(qsaNome).split(' ').filter((w) => w.length > 2 && !['dos', 'das'].includes(w));
  const c = norm(citado.replace(/^(Dra|Dr|Doutora|Doutor)\.?\s*/i, '')).split(' ').filter((w) => w.length > 2 && !['dos', 'das'].includes(w));
  if (!c.length || !q.length) return 0;
  if (q[0] !== c[0]) return 0;
  const sobren = c.slice(1).filter((w) => q.slice(1).includes(w)).length;
  return sobren ? 2 : (c.length === 1 ? 1 : 0);
}
export function decidir(e, tel, fontes) {
  const cn = escolherCnpj(e, tel, fontes);
  const cit = citados(e);
  const socios = cn ? cn.socios.filter((s) => !/conselheir/i.test(s.qualificacao) && !/\b(ltda|s\/?a|eireli|holding|participa\w*)\b/i.test(s.nome)) : [];
  const evid = [];
  let dec = null, conf = null;
  const admin = (s) => /administrador|titular|presidente|diretor|empres[áa]rio/i.test(s.qualificacao);
  const ei = cn && !cn.socios.length && !/\b(ltda|s a|eireli|me|epp|sociedade|associados|advogados|clinica|odontolog\w*|estetica|imov\w*|imobili\w*|contab\w*|servicos|comercio|locac\w*|veiculos|assessoria|consultoria|centro|instituto|grupo|empreendimentos|negocios|administra\w*)\b/i.test(norm(cn.razao_social));
  if (ei) socios.push({ nome: cn.razao_social.replace(/[\d.\-\/\s]+$/, '').trim(), qualificacao: 'Empresário individual (nome na razão social)' });
  if (socios.length) {
    const sc = socios.map((s) => { const m = cit.filter((c) => bate(s.nome, c.nome) > 0); return { s, m, forte: m.some((c) => bate(s.nome, c.nome) === 2), peso: m.reduce((a, c) => a + c.peso * bate(s.nome, c.nome), 0) }; });
    sc.sort((a, b) => b.peso - a.peso || admin(b.s) - admin(a.s));
    const top = sc[0];
    const escolhido = top.peso > 0 ? top : (sc.find((x) => admin(x.s)) || sc[0]);
    const s = escolhido.s;
    const tit = escolhido.m.map((c) => titulo(c.nome)).find(Boolean);
    const pn = norm(s.nome).split(' ')[0]; const grafia = escolhido.m.map((c) => c.nome.replace(/^(Dra|Dr|Doutora|Doutor)\.?\s*/i, '').split(' ')[0]).find((w) => norm(w) === pn); const primeiro = grafia || cap(pn);
    dec = { nome: s.nome.split(' ').map(cap).join(' ').replace(/ (Da|De|Do|Das|Dos|E) /g, (x) => x.toLowerCase()), papel: socios.length === 1 ? 'dono' : 'sócio', como_chamar: tit ? `${tit} ${primeiro}` : primeiro };
    evid.push({ fonte: 'Receita (BrasilAPI)', url: `https://brasilapi.com.br/api/cnpj/v1/${cn.cnpj}`, trecho: `${cn.razao_social}: ${s.nome} (${s.qualificacao})` });
    for (const c of escolhido.m.slice(0, 2)) evid.push({ fonte: c.fonte, url: c.url, trecho: c.trecho });
    conf = escolhido.forte ? 'alta' : (escolhido.m.length ? 'media' : 'media');
  } else if (cit.length) {
    // sem QSA: agrega por nome
    const g = {};
    for (const c of cit) { const k = norm(c.nome.replace(/^(Dra|Dr|Doutora|Doutor)\.?\s*/i, '')).split(' ').slice(0, 2).join(' '); (g[k] ||= []).push(c); }
    const rank = Object.values(g).map((l) => ({ l, peso: l.reduce((a, c) => a + c.peso, 0), fontes: new Set(l.map((c) => c.fonte.split(' ')[0])).size, papel: l.find((c) => c.papel === 'responsável técnico') ? 'responsável técnico' : l.find((c) => c.papel === 'sócio/fundador') ? 'sócio' : null }));
    rank.sort((a, b) => (b.papel ? 1 : 0) - (a.papel ? 1 : 0) || b.fontes - a.fontes || b.peso - a.peso);
    const r = rank[0];
    const nomeLongo = r.l.map((c) => c.nome.replace(/^(Dra|Dr|Doutora|Doutor)\.?\s*/i, '')).sort((a, b) => b.length - a.length)[0];
    const tit = r.l.map((c) => titulo(c.nome)).find(Boolean);
    const forteSemPapel = r.l.some((c) => c.fonte === 'nome no Google Maps');
    if (r.papel || r.fontes >= 2 || forteSemPapel) {
      dec = { nome: nomeLongo, papel: r.papel || 'dono', como_chamar: tit ? `${tit} ${nomeLongo.split(' ')[0]}` : nomeLongo.split(' ')[0] };
      for (const c of r.l.slice(0, 3)) evid.push({ fonte: c.fonte, url: c.url, trecho: c.trecho });
      conf = r.fontes >= 2 ? 'alta' : (r.papel ? 'media' : 'baixa');
    }
  }
  return { cn, socios, dec, conf, evid, cit };
}

// --- de decisores/ig.mjs ---
const GEN_IG = new Set(['silva', 'santos', 'souza', 'sousa', 'oliveira', 'pereira', 'costa', 'lima', 'junior', 'filho', 'neto', 'maria', 'ana']);

export function candidatos(e, nome) {
  const pal = norm(nome).split(' ').filter((w) => w.length >= 4 && !GEN_IG.has(w));
  const prim = norm(nome).split(' ')[0];
  const hs = new Set();
  for (const h of [...(e.ig?.mencoes_bio || []), ...Object.keys(e.ig_mencoes || {})]) hs.add(h.replace(/^@/, ''));
  for (const u of e.site_ig || []) { const m = u.match(/instagram\.com\/([a-z0-9._]{3,30})/i); if (m && !['p', 'reel', 'explore', 'stories'].includes(m[1].toLowerCase())) hs.add(m[1].toLowerCase()); }
  hs.delete(e.ig?.user);
  return [...hs].filter((h) => { const x = h.replace(/[._\d]/g, ''); const sob = pal.filter((w) => w !== prim && x.includes(w)).length; return sob > 0 || (prim.length >= 4 && x.includes(prim) && /^(dra?|doutora?|adv|dr)/.test(x) ) || (prim.length >= 5 && x.startsWith(prim)); });
}

// --- de decisores/final.mjs (ev, ajustes, @ pessoais e fontes vêm por parâmetro) ---
const GEN_F = new Set(['silva', 'santos', 'souza', 'sousa', 'oliveira', 'pereira', 'costa', 'lima', 'junior', 'filho', 'neto', 'maria', 'ana', 'dra', 'doutora', 'doutor']);
const BR = (d) => d ? d.split('-').reverse().join('/') : null;

function bateNome(nome, alvo) {
  const p = norm(nome).replace(/^(dra|dr|doutora|doutor) /, '').split(' ');
  const a = norm(alvo).replace(/[._\d]/g, ' ');
  const sob = p.slice(1).filter((w) => w.length >= 4 && !GEN_F.has(w) && a.replace(/ /g, '').includes(w));
  return a.includes(p[0]) && sob.length > 0;
}
function contatos(txt) {
  const out = [];
  for (const m of (txt || '').matchAll(/wa\.me\/(\d{10,13})|api\.whatsapp\.com\/send\?phone=(\d{10,13})/gi)) out.push({ tipo: 'whatsapp', valor: m[1] || m[2] });
  for (const m of (txt || '').matchAll(/[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}/gi)) out.push({ tipo: 'email', valor: m[0].toLowerCase() });
  for (const m of (txt || '').matchAll(/(?:\+?55\s?)?\(?\b(\d{2})\)?\s?(9\s?\d{4})[-\s.]?(\d{4})\b/g)) out.push({ tipo: 'whatsapp', valor: '55' + m[1] + m[2].replace(/\s/g, '') + m[3] });
  return out;
}
export function final(negocios, { ev, AJ = {}, IGP = {}, fontes }) {
  const F = {};
  for (const n of negocios) {
    const tel = n.telefone_e164; const e = ev[tel]; if (!e) continue;
    const d = decidir(e, tel, fontes);
    const aj = AJ[tel] || {};
    let cn = d.cn;
    if (aj.cnpj === '') cn = null;
    let socios = cn ? cn.socios.map((s) => ({ nome: s.nome, qualificacao: s.qualificacao })) : [];
    let dec = d.dec ? { ...d.dec } : null, conf = d.conf, evid = [...d.evid];
    if (cn && cn.fonte) evid.unshift({ fonte: 'CNPJ: ' + cn.fonte.fonte, url: cn.fonte.url, trecho: (cn.fonte.trecho || `CNPJ ${cn.cnpj}`).slice(0, 200) });
    if ('decisor' in aj) { dec = aj.decisor ? { ...aj.decisor } : null; conf = aj.decisor ? aj.confianca : null; if (aj.evidencias) evid = [...(cn && cn.fonte ? [evid[0]] : []), ...aj.evidencias]; }
    else if (aj.confianca) conf = aj.confianca;
    if (aj.evidencias_extra) evid.push(...aj.evidencias_extra);
    const r = {
      nome_negocio: n.nome, prioridade: n.prioridade, nicho: n.nicho, cidade: n.cidade,
      cnpj: cn ? cn.cnpj : null, razao_social: cn ? cn.razao_social : null, socios, porte: cn ? cn.porte : null, abertura: cn ? BR(cn.abertura) : null,
      decisor: {}, evidencias: [], confianca: null,
    };
    if (dec) {
      dec.instagram_pessoal = dec.instagram_pessoal || null; dec.contato_direto = dec.contato_direto || null; dec.fonte_contato = dec.fonte_contato || null;
      // @ pessoal
      const cands = Object.keys(IGP).filter((h) => IGP[h].ok && (e.ig?.mencoes_bio || []).concat(Object.keys(e.ig_mencoes || {})).concat((e.site_ig || []).map((u) => '@' + ((u.match(/instagram\.com\/([a-z0-9._]+)/i) || [])[1] || '').toLowerCase())).concat(aj.ig_bio_handle ? ['@' + aj.ig_bio_handle] : []).includes('@' + h));
      const hit = cands.find((h) => bateNome(dec.nome, `${IGP[h].data.name || ''} ${h}`));
      if (hit && !dec.instagram_pessoal) {
        const p = IGP[hit].data;
        dec.instagram_pessoal = '@' + hit;
        evid.push({ fonte: 'Instagram pessoal (Business Discovery)', url: 'https://instagram.com/' + hit, trecho: `${p.name || ''} | ${(p.biography || '').replace(/\n/g, ' / ')}`.slice(0, 200) });
        const ct = [...contatos(p.website), ...contatos(p.biography)].filter((c) => c.valor !== tel);
        if (ct.length && !dec.contato_direto) { dec.contato_direto = `${ct[0].tipo}: ${ct[0].valor}`; dec.fonte_contato = `bio/link do Instagram @${hit}`; }
      }
      // e-mail do site com o nome do decisor
      if (!dec.contato_direto) {
        const pal = norm(dec.nome).split(' ').filter((w) => w.length >= 4 && !GEN_F.has(w));
        const em = (e.emails || []).find((x) => { const lp = norm(x.split('@')[0]).replace(/ /g, ''); return pal.some((w) => lp.includes(w)) && !/contato|atendimento|financeiro|comercial|adm|secretaria/.test(lp); });
        if (em) { dec.contato_direto = 'email: ' + em; dec.fonte_contato = 'e-mail com o nome dele(a) no site da empresa'; }
      }
      r.decisor = dec; r.confianca = conf;
    }
    const vistos = new Set();
    r.evidencias = evid.filter((x) => { const k = x.fonte + x.trecho; if (vistos.has(k)) return false; vistos.add(k); return true; }).slice(0, 6).map((x) => ({ fonte: x.fonte, url: x.url || null, trecho: (x.trecho || '').slice(0, 220) }));
    if (aj.nota) r.nota = aj.nota;
    F[tel] = r;
  }
  return F;
}

// --- rede (de decisores/baixar.mjs, cnpj.mjs, busca.mjs e ig.mjs, com ctx.deps) ---
async function get(ctx, url) {
  try {
    const r = await ctx.deps.fetch(url, { headers: { 'user-agent': UA, 'accept-language': 'pt-BR,pt;q=0.9' }, redirect: 'follow', signal: AbortSignal.timeout(12000) });
    const ct = r.headers.get('content-type') || '';
    if (!/html|text/.test(ct)) return { status: r.status, url: r.url, html: '' };
    const buf = await r.arrayBuffer();
    return { status: r.status, url: r.url, html: Buffer.from(buf).subarray(0, 3_000_000).toString('utf8') };
  } catch (e) { return { status: 0, erro: String(e.message || e).slice(0, 80), url }; }
}

// home + até 7 páginas institucionais do mesmo domínio (de baixar.mjs `um`)
export async function baixarPaginas(ctx, neg) {
  const res = { placeId: neg.placeId, site: neg.site, paginas: [], mailto: [], wa: [], instagram: [], tel: [] };
  if (!neg.site || tipo(neg.site) !== 'site') { res.pulado = 'sem site próprio'; return res; }
  const h = await get(ctx, neg.site);
  if (!h.html) { res.erro = h.erro || 'HTTP ' + h.status; return res; }
  const host = new URL(h.url).hostname.replace(/^www\./, '');
  const todas = [{ url: h.url, html: h.html }];
  const cand = [];
  for (const { u, t } of links(h.html, h.url)) {
    let x; try { x = new URL(u); } catch { continue; }
    if (x.hostname.replace(/^www\./, '') !== host) continue;
    if (SKIP.test(x.pathname)) continue;
    if (!(KW.test(x.pathname) || KW.test(t))) continue;
    const k = x.origin + x.pathname.replace(/\/$/, '');
    if (k === new URL(h.url).origin + new URL(h.url).pathname.replace(/\/$/, '')) continue;
    if (!cand.includes(k)) cand.push(k);
  }
  for (const u of cand.slice(0, 7)) {
    await ctx.deps.sleep(800);
    const p = await get(ctx, u);
    if (p.html) todas.push({ url: p.url, html: p.html });
  }
  for (const p of todas) {
    res.paginas.push({ url: p.url, texto: htmlTexto(p.html).slice(0, 60000) });
    for (const { u } of links(p.html, p.url)) {
      if (/^mailto:/i.test(u)) res.mailto.push(decodeURIComponent(u.slice(7).split('?')[0]).toLowerCase());
      else if (/wa\.me|whatsapp\.com/i.test(u)) res.wa.push(u.slice(0, 200));
      else if (/instagram\.com\//i.test(u)) res.instagram.push(u.slice(0, 200));
      else if (/^tel:/i.test(u)) res.tel.push(u.slice(4, 40));
    }
  }
  for (const k of ['mailto', 'wa', 'instagram', 'tel']) res[k] = [...new Set(res[k])];
  return res;
}

// titular CNPJ do domínio .br no registro.br (titular CPF não é guardado)
export async function rdap(ctx, dom) {
  const espera = 4000 - (Date.now() - (ctx._ultimoRdap || 0)); if (espera > 0) await ctx.deps.sleep(espera);
  ctx._ultimoRdap = Date.now();
  try {
    const r = await ctx.deps.fetch('https://rdap.registro.br/domain/' + dom, { headers: { accept: 'application/rdap+json' } });
    if (r.status === 429) { await ctx.deps.sleep(60000); return rdap(ctx, dom); }
    if (r.status !== 200) return { status: r.status };
    const j = await r.json();
    const reg = (j.entities || []).find((e) => (e.roles || []).includes('registrant'));
    const pid = (reg?.publicIds || []).find((p) => p.type === 'cnpj');
    return pid ? { status: 200, cnpj: pid.identifier.replace(/\D/g, ''), nome: (reg.vcardArray?.[1] || []).find((x) => x[0] === 'fn')?.[3] || null } : { status: 200, cnpj: null };
  } catch (e) { return { status: 0, erro: e.message }; }
}

// candidatos de CNPJ: site e Instagram; sem um que bata com a cidade, o titular do domínio .br (de cnpj.mjs)
export async function candidatosCnpj(ctx, n, pag, ig) {
  const fontes = [];
  if (pag) for (const p of pag.paginas) for (const c of achaCnpjs(p.texto)) fontes.push({ cnpj: c, fonte: 'site', url: p.url });
  if (ig?.ok) {
    for (const c of achaCnpjs(ig.data.biography || '')) fontes.push({ cnpj: c, fonte: 'instagram bio', url: 'https://instagram.com/' + n.instagram.replace(/^@/, '') });
    for (const m of ig.data.media?.data || []) for (const c of achaCnpjs(m.caption || '')) fontes.push({ cnpj: c, fonte: 'instagram post', url: m.permalink });
  }
  const consultas = {};
  for (const c of [...new Set(fontes.map((f) => f.cnpj))].slice(0, 4)) consultas[c] = await consultarCnpj(ctx, c);
  const bate = Object.values(consultas).some((r) => r.ok && norm(r.municipio) === norm(n.cidade));
  if (!bate && n.site) {
    let dom; try { dom = new URL(n.site).hostname.toLowerCase().replace(/^www\./, ''); } catch {}
    if (dom && /\.br$/.test(dom)) {
      const r = await rdap(ctx, dom);
      if (r.cnpj && !consultas[r.cnpj]) consultas[r.cnpj] = await consultarCnpj(ctx, r.cnpj);
      if (r.cnpj) fontes.push({ cnpj: r.cnpj, fonte: 'registro.br (titular do domínio)', url: 'https://rdap.registro.br/domain/' + dom });
    }
  }
  return { feito: true, prioridade: n.prioridade, fontes, consultas };
}

// evidências de pessoas (site + Instagram) de um negócio (corpo do laço de extrair.mjs)
export function evidencias(n, pag, ig, cand) {
  const e = { prioridade: n.prioridade, nome: n.nome, nicho: n.nicho, cidade: n.cidade, site: n.site, instagram: n.instagram, site_pags: 0, site_pessoas: [], emails: [], wa: [], ig: null, ig_mencoes: {}, legenda_titulos: {} };
  if (pag) {
    e.site_pags = pag.paginas.length; e.site_erro = pag.erro || pag.pulado || null;
    const vistos = new Set();
    for (const pg of pag.paginas) {
      for (const x of pessoas(pg.texto)) { const k = x.tipo + (x.nome || x.reg || x.papel) + x.trecho.slice(0, 40); if (vistos.has(k)) continue; vistos.add(k); e.site_pessoas.push({ ...x, url: pg.url }); }
      e.emails.push(...emails(pg.texto));
    }
    e.emails = [...new Set([...e.emails, ...pag.mailto])];
    e.wa = pag.wa; e.site_ig = pag.instagram;
  }
  const u = n.instagram?.replace(/^@/, '').toLowerCase();
  if (ig?.ok) {
    const d = ig.data;
    e.ig = { user: u, name: d.name, bio: d.biography, website: d.website, seguidores: d.followers_count, pessoas: pessoas(`${d.name || ''} | ${d.biography || ''}`), mencoes_bio: mencoes(d.biography || '') };
    for (const m of d.media?.data || []) {
      for (const h of mencoes(m.caption || '')) if (h !== '@' + u) e.ig_mencoes[h] = (e.ig_mencoes[h] || 0) + 1;
      for (const x of pessoas(m.caption || '')) if (x.tipo === 'titulo') e.legenda_titulos[x.nome] = (e.legenda_titulos[x.nome] || 0) + 1;
    }
  } else if (u) e.ig = { user: u, erro: ig ? ig.erro : 'ainda não coletado' };
  e.cnpj = cand ? { fontes: cand.fontes, consultas: cand.consultas } : null;
  return e;
}

// busca web (DuckDuckGo HTML) "<nome> <cidade> CNPJ" para quem ficou sem CNPJ aceito (de busca.mjs)
export async function buscaWeb(ctx, q) {
  for (let t = 0; t < 3; t++) {
    try {
      const r = await ctx.deps.fetch('https://html.duckduckgo.com/html/?q=' + encodeURIComponent(q), { headers: { 'user-agent': UA, 'accept-language': 'pt-BR,pt;q=0.9' } });
      const h = await r.text();
      if (r.status !== 200 || /anomaly|captcha/i.test(h.slice(0, 5000)) && !/result__body/.test(h)) { await ctx.deps.sleep(90000); continue; }
      const out = [];
      for (const b of h.split(/class="result__body|class="result results_links/).slice(1)) {
        const u = (b.match(/href="[^"]*uddg=([^"&]+)/) || [])[1];
        const txt = htmlTexto(b.slice(0, 4000));
        for (const c of achaCnpjs(txt)) {
          const i = txt.search(/CNPJ/i);
          out.push({ cnpj: c, url: u ? decodeURIComponent(u) : null, trecho: txt.slice(Math.max(0, i - 60), i + 140).replace(/\s+/g, ' ') });
        }
      }
      return out;
    } catch { await ctx.deps.sleep(20000); }
  }
  return [];
}

export async function buscarCnpjNaWeb(ctx, n) {
  const curto = n.nome.split(/\s+[-|–(]\s*|\s*\|\s*/)[0].trim();
  const q = `"${curto.length >= 4 ? curto : n.nome}" ${n.cidade} CNPJ`;
  let achados = await buscaWeb(ctx, q);
  await ctx.deps.sleep(5000 + Math.random() * 3000);
  if (!achados.length) { achados = await buscaWeb(ctx, `${n.nome} ${n.cidade} ${n.uf} CNPJ`); await ctx.deps.sleep(5000 + Math.random() * 3000); }
  const res = { buscado: true, prioridade: n.prioridade, q, achados: achados.slice(0, 12), consultas: {} };
  for (const c of [...new Set(res.achados.map((a) => a.cnpj))].slice(0, 4)) res.consultas[c] = await consultarCnpj(ctx, c);
  res.consultado = true;
  return res;
}

// @ pessoal: Business Discovery só de nome, bio, seguidores e site (de ig.mjs `bd`), 5 s entre chamadas
export async function perfilPessoal(ctx, u) {
  const r = await businessDiscovery(ctx, u, '{username,name,biography,followers_count,website}');
  await ctx.deps.sleep(5000);
  return r.ok ? r : { ok: false, erro: r.erro.split(' ')[0] };
}
