// Instagram do negócio. Camada rasa: perfil pela Meta Business Discovery (grátis) e, para quem a Meta não devolve,
// apify/instagram-profile-scraper. Camada funda: comentários dos até 3 posts recentes com comentários
// (apify/instagram-comment-scraper). Legendas e comentários são dados não confiáveis: só leitura, e sem nome de cliente.
// normalizar, resumo, engajamento e analisar: de scripts-origem/ig-lista/comum.mjs e camada2.mjs, sem mudança de regra.
import { anonimizar, protegidos } from './nomes.mjs';

export const ATOR_PERFIL = 'apify~instagram-profile-scraper';
export const ATOR_COMENTARIOS = 'apify~instagram-comment-scraper';
export const LIM_COMENTARIOS = 20; // por post, sem respostas aninhadas (o plano FREE não entrega replies)
export const IG_USER_ID = process.env.META_IG_USER_ID || '17841460228743369'; // conta que consulta o Business Discovery (meta.mjs)
const CAMPOS_BD = '{name,biography,followers_count,media_count,website,media.limit(25){caption,timestamp,like_count,comments_count,media_type,permalink}}';
export const CODIGOS_LIMITE = [4, 17, 32, 613];

export const uname = (s) => String(s || '').replace(/^@/, '').toLowerCase();
export const saude = (n) => /odontol|est[ée]tica/i.test(n.nicho || '');
export const um = (s) => String(s || '').replace(/\s+/g, ' ').trim();
export const semSurrogate = (s) => String(s).replace(/[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g, '');
export const cortar = (s, n = 160) => { const a = Array.from(semSurrogate(um(s))); return a.length > n ? a.slice(0, n - 1).join('').trimEnd() + '…' : a.join(''); };
export const fmt = (n) => Number(n).toLocaleString('pt-BR');

// Business Discovery de um username. Com erro de limite (4, 17, 32, 613) espera 10 min e tenta de novo.
export async function businessDiscovery(ctx, u, campos = CAMPOS_BD) {
  for (;;) {
    let j;
    try {
      const r = await ctx.deps.fetch(`https://graph.facebook.com/v23.0/${IG_USER_ID}?fields=business_discovery.username(${encodeURIComponent(u)})${campos}&access_token=${ctx.deps.tokenMeta()}`);
      j = await r.json();
    } catch (e) { ctx.logIg?.(`${u} rede: ${e.message}`); await ctx.deps.sleep(30000); continue; }
    if (j.error && CODIGOS_LIMITE.includes(j.error.code)) { ctx.logIg?.(`${u} limite code=${j.error.code}; esperando 10 min`); await ctx.deps.sleep(600000); continue; }
    if (j.error) return { ok: false, erro: `${j.error.code}/${j.error.error_subcode || ''} ${j.error.message}`.slice(0, 300) };
    return { ok: true, data: j.business_discovery };
  }
}

// item do profile-scraper -> mesmo formato que apify1.mjs guardava em raw-apify.json
export function perfilApify(it) {
  if (it.error || !it.username) return { ok: false, erro: String(it.error || it.errorDescription || 'sem dados').slice(0, 200) };
  return { ok: true, data: { fullName: it.fullName, biography: it.biography, followersCount: it.followersCount, postsCount: it.postsCount, externalUrl: it.externalUrl, private: it.private,
    latestPosts: (it.latestPosts || []).map((p) => ({ caption: p.caption, timestamp: p.timestamp, likesCount: p.likesCount, commentsCount: p.commentsCount, type: p.type, url: p.url, shortCode: p.shortCode })) } };
}

// normaliza a resposta (meta ou apify) num perfil (formato de instagram-perfis.json, lido por leads.save_instagram)
export function normalizar(u, fonte, d, negocio) {
  const prot = protegidos(negocio?.nome, d.name || d.fullName, u.replace(/[._]/g, ' '), d.biography);
  const opt = { saude: saude(negocio || {}), proprio: u, prot };
  let midias = fonte === 'meta'
    ? (d.media?.data || []).map((m) => ({ url: m.permalink, ts: m.timestamp, curtidas: m.like_count ?? null, comentarios: m.comments_count ?? 0, tipo: m.media_type, legenda: m.caption || '' }))
    : (d.latestPosts || []).map((m) => ({ url: m.url || (m.shortCode ? `https://www.instagram.com/p/${m.shortCode}/` : null), ts: m.timestamp, curtidas: (m.likesCount >= 0 ? m.likesCount : null), comentarios: m.commentsCount ?? 0, tipo: m.type, legenda: m.caption || '' }));
  midias.sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
  midias = midias.map((m) => ({ ...m, data: String(m.ts || '').slice(0, 10), legenda: cortar(anonimizar(m.legenda, opt), 160) }));
  return { username: u, fonte, nome: um(d.name || d.fullName || ''), seguidores: d.followers_count ?? d.followersCount ?? null,
    posts_total: d.media_count ?? d.postsCount ?? null, bio: cortar(String(d.biography || '').replace(/\n+/g, ' · '), 220), site: d.website || d.externalUrl || null,
    privado: d.private || false, posts_recentes: midias.slice(0, 3).map((m) => ({ data: m.data, legenda: m.legenda })), midias, erro: null };
}

export function resumo(p) {
  const posts = p.posts_recentes.length ? p.posts_recentes.map((m) => `(${m.data}) ${m.legenda || '[sem legenda]'}`).join('; ') : (p.privado ? 'perfil privado' : 'nenhum');
  return `Instagram (@${p.username}): ${fmt(p.seguidores ?? 0)} seguidores, ${fmt(p.posts_total ?? 0)} posts. Bio: ${p.bio ? (/[.!?…]$/.test(p.bio) ? p.bio : p.bio + '.') : '(vazia).'} Posts recentes: ${posts}`.replace(/\s+/g, ' ').trim();
}

// 2 posts com mais curtidas nos últimos 90 dias (dados da camada rasa, custo zero)
export function engajamento(p, hoje) {
  const lim = new Date(new Date(hoje).getTime() - 90 * 864e5).toISOString().slice(0, 10);
  const ms = (p.midias || []).filter((m) => m.data >= lim && m.curtidas != null).sort((a, b) => b.curtidas - a.curtidas).slice(0, 2);
  if (!ms.length) return null;
  return 'Posts que mais engajaram nos últimos 90 dias: ' + ms.map((m) => `(${m.data}, ${fmt(m.curtidas)} curtidas, ${fmt(m.comentarios || 0)} comentários, ${m.tipo === 'VIDEO' || m.tipo === 'Video' ? 'vídeo' : m.tipo === 'CAROUSEL_ALBUM' || m.tipo === 'Sidecar' ? 'carrossel' : 'foto'}) ${cortar(m.legenda || '[sem legenda]', 110)}`).join('; ');
}

// --- camada funda (de camada2.mjs) ---
export const sc = (u) => (String(u).match(/\/(?:p|reel|reels|tv)\/([^/?#]+)/) || [])[1];
const Q = /\?|pre[çc]o|valor|quanto|agenda|hor[áa]rio|atende|endere[çc]o|conv[êe]nio|parcel/i;
export function postsDe(p) { return (p.midias || []).filter((m) => m.comentarios > 0 && sc(m.url)).slice(0, 3); }
const ddmm = (d) => (d ? d.slice(8, 10) + '/' + d.slice(5, 7) : '?');

// itens do comment-scraper -> {shortcode: [{t, o, ts}]}
export function agruparComentarios(items) {
  const por = {};
  for (const it of items || []) { const k = sc(it.postUrl || it.commentUrl || ''); if (!k || it.error) continue; (por[k] ??= []).push({ t: String(it.text || ''), o: String(it.ownerUsername || '').toLowerCase(), ts: it.timestamp || '' }); }
  return por;
}

export function analisar(u, p, neg, raw) {
  const ps = postsDe(p); if (!ps.length) return { linha: 'Comentários nos posts recentes: os posts recentes não têm comentários.', perguntas: 0 };
  const opt = { saude: saude(neg), proprio: u, prot: protegidos(neg.nome, p.nome, u.replace(/[._]/g, ' ')) };
  let lidos = 0, postsLidos = 0; const perg = [];
  for (const m of ps) {
    const cs = raw[sc(m.url)]; if (!cs) continue; postsLidos++; lidos += cs.length;
    const completo = m.comentarios <= LIM_COMENTARIOS && cs.length >= m.comentarios; // sem respostas aninhadas no post
    const doNeg = cs.filter((c) => c.o === u);
    for (const c of cs) {
      if (c.o === u) continue; const t = c.t.replace(/@[A-Za-z0-9._]+/g, '').trim(); if (!t || !Q.test(c.t)) continue;
      const depois = doNeg.filter((b) => b.ts > c.ts);
      const resp = depois.some((b) => b.t.toLowerCase().includes('@' + c.o)) || depois.some((b) => !/@[A-Za-z0-9._]/.test(b.t));
      perg.push({ st: resp ? 'resp' : completo ? 'sem' : 'ind', txt: cortar(anonimizar(t, opt), 90), data: m.data });
    }
  }
  if (!postsLidos) return null;
  const n = perg.length, sem = perg.filter((x) => x.st === 'sem'), resp = perg.filter((x) => x.st === 'resp'), ind = perg.filter((x) => x.st === 'ind');
  if (!n) return { linha: `Comentários nos posts recentes: ${lidos} comentários lidos em ${postsLidos} posts, nenhuma pergunta de cliente.`, perguntas: 0 };
  const ex = (sem.length ? sem : perg).slice(0, 2).map((x) => `um cliente perguntou '${x.txt.replace(/'/g, '"')}' no post de ${ddmm(x.data)}`).join('; ');
  let s = `Comentários nos posts recentes: ${n} ${n > 1 ? 'perguntas' : 'pergunta'} de clientes em ${postsLidos} posts, ${sem.length} sem resposta do perfil`;
  if (resp.length) s += `, ${resp.length} respondida${resp.length > 1 ? 's' : ''} pelo perfil`;
  if (ind.length) s += `, ${ind.length} sem como confirmar (o post tem respostas que não dá para ler)`;
  return { linha: s + ` (ex.: ${ex}).`, perguntas: n, sem: sem.length, resp: resp.length, ind: ind.length };
}
