// Site do negócio: só a página inicial, 1 requisição por site, em sequência, timeout 10 s, 1-2 s entre sites.
// O HTML é tratado só como texto (dado não confiável): nada dele é executado.
// SERVICOS, extrair e lerCorpo são cópia de scripts-origem/enriquecer/baixar-sites.mjs; tipoSite de enriquecer/comum.mjs;
// scanHtml (pixels, tags e CNPJ no código) de scripts/qualificar-riqueza.mjs, aplicado ao mesmo HTML para a lente não baixar de novo.
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36';
const LIMITE_BYTES = 3 * 1024 * 1024;
const SERVICOS = {
  'clínica odontológica': ['implante dentário', 'implantes dentários', 'implante', 'implantes', 'protocolo', 'ortodontia', 'aparelho ortodôntico', 'alinhadores invisíveis', 'alinhador invisível', 'invisalign', 'clareamento dental', 'clareamento', 'lentes de contato dental', 'lente de contato dental', 'facetas', 'prótese', 'próteses', 'endodontia', 'tratamento de canal', 'periodontia', 'odontopediatria', 'harmonização facial', 'bichectomia', 'extração de siso', 'cirurgia', 'limpeza dental', 'restauração', 'restaurações', 'toxina botulínica', 'botox', 'preenchimento labial', 'urgência', 'emergência', 'estética dental', 'odontologia estética', 'dentística', 'radiologia', 'bruxismo', 'DTM'],
  'clínica de estética': ['harmonização facial', 'toxina botulínica', 'botox', 'preenchimento labial', 'preenchimento', 'bioestimulador', 'bioestimuladores', 'limpeza de pele', 'peeling', 'microagulhamento', 'depilação a laser', 'criolipólise', 'drenagem linfática', 'massagem modeladora', 'massagem relaxante', 'radiofrequência', 'ultraformer', 'skinbooster', 'fios de PDO', 'design de sobrancelhas', 'micropigmentação', 'lash lifting', 'extensão de cílios', 'emagrecimento', 'tratamento facial', 'tratamentos faciais', 'tratamento corporal', 'tratamentos corporais', 'rinomodelação', 'lipo enzimática', 'enzimas', 'estrias', 'celulite', 'flacidez', 'manchas', 'HIFU', 'fotodepilação', 'lavieen', 'endermoterapia', 'carboxiterapia', 'mesoterapia', 'podologia'],
  'escritório de contabilidade': ['abertura de empresa', 'abertura de empresas', 'contabilidade consultiva', 'imposto de renda', 'IRPF', 'departamento pessoal', 'folha de pagamento', 'MEI', 'Simples Nacional', 'planejamento tributário', 'BPO financeiro', 'assessoria contábil', 'consultoria contábil', 'consultoria tributária', 'escrituração fiscal', 'escrita fiscal', 'contabilidade digital', 'contabilidade para médicos', 'regularização de empresas', 'alteração contratual', 'encerramento de empresa', 'baixa de empresa', 'recuperação tributária', 'recuperação de créditos', 'certificado digital', 'holding', 'gestão financeira', 'auditoria', 'perícia contábil', 'terceiro setor', 'contabilidade rural', 'eSocial'],
  'escritório de advocacia': ['direito previdenciário', 'aposentadoria', 'aposentadorias', 'INSS', 'direito trabalhista', 'direito do trabalho', 'direito de família', 'divórcio', 'pensão alimentícia', 'guarda', 'inventário', 'direito civil', 'direito do consumidor', 'direito imobiliário', 'usucapião', 'direito empresarial', 'direito tributário', 'direito criminal', 'direito penal', 'direito médico', 'direito da saúde', 'direito bancário', 'revisão de contrato', 'revisão de contratos', 'BPC', 'LOAS', 'auxílio-doença', 'planejamento sucessório', 'holding familiar', 'recuperação judicial', 'direito digital', 'direito condominial', 'direito ambiental', 'direito administrativo', 'direito do agronegócio', 'contratos', 'cobrança', 'sucessões'],
  'imobiliária': ['venda de imóveis', 'compra e venda', 'locação de imóveis', 'locação', 'aluguel', 'administração de imóveis', 'administração de aluguéis', 'administração de condomínios', 'avaliação de imóveis', 'avaliação', 'lançamentos', 'imóveis na planta', 'financiamento', 'financiamento imobiliário', 'aluguel por temporada', 'temporada', 'permuta', 'consórcio', 'alto padrão', 'imóveis comerciais', 'regularização de imóveis', 'documentação', 'loteamentos', 'frente mar'],
  'locadora de veículos': ['aluguel de carros', 'aluguel de carro', 'locação de veículos', 'locação de carros', 'aluguel de vans', 'aluguel de van', 'locação de vans', 'locação mensal', 'aluguel mensal', 'terceirização de frota', 'gestão de frota', 'carro para aplicativo', 'carros para aplicativo', 'motorista de aplicativo', 'aluguel de motos', 'locação de motos', 'transfer', 'carro por assinatura', 'carros por assinatura', 'quilometragem livre', 'km livre', 'locação diária', 'diárias', 'aeroporto', 'blindados', 'utilitários', 'caminhões', 'carros executivos', 'motorista', 'seminovos', 'venda de seminovos'],
};

function reAcento(termo) {
  const mapa = { a: '[aáàâã]', e: '[eéê]', i: '[ií]', o: '[oóôõ]', u: '[uúü]', c: '[cç]' };
  const sem = termo.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const corpo = sem.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/[aeiouc]/g, (ch) => mapa[ch]).replace(/[- ]/g, '[-\\s]');
  return new RegExp('(?<![\\p{L}\\p{N}])' + corpo + '(?![\\p{L}\\p{N}])', 'giu');
}

function decodificarEntidades(s) {
  return s
    .replace(/&#(\d+);/g, (_, n) => { try { return String.fromCodePoint(+n); } catch { return ' '; } })
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => { try { return String.fromCodePoint(parseInt(n, 16)); } catch { return ' '; } })
    .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&([a-z]+);/gi, (m, n) => ({ aacute: 'á', eacute: 'é', iacute: 'í', oacute: 'ó', uacute: 'ú', atilde: 'ã', otilde: 'õ', ccedil: 'ç', acirc: 'â', ecirc: 'ê', ocirc: 'ô', agrave: 'à', ndash: '–', mdash: '—', Aacute: 'Á', Eacute: 'É', Ccedil: 'Ç', Atilde: 'Ã', Otilde: 'Õ', Oacute: 'Ó', Iacute: 'Í', Uacute: 'Ú', Ecirc: 'Ê', Acirc: 'Â', Ocirc: 'Ô', middot: '·', bull: '•', raquo: '»', laquo: '«', hellip: '…', rsquo: '’', lsquo: '‘', ldquo: '“', rdquo: '”' }[n] ?? m));
}

const limpo = (s) => decodificarEntidades(String(s || '')).replace(/\s+/g, ' ').trim();

function meta(html, nome) {
  const re = new RegExp(`<meta\\b[^>]*(?:name|property)\\s*=\\s*["']${nome}["'][^>]*>`, 'i');
  const tag = html.match(re)?.[0];
  if (!tag) return '';
  return limpo(tag.match(/content\s*=\s*"([^"]*)"/i)?.[1] ?? tag.match(/content\s*=\s*'([^']*)'/i)?.[1] ?? '');
}

const IG_RESERVADO = new Set(['p', 'reel', 'reels', 'explore', 'stories', 'accounts', 'tv', 'share', 'about', 'legal', 'developer', 'direct', 'web', 'instagram', 'sharer', 'sharer.php', 'embed.js']);
const FB_RESERVADO = new Set(['sharer', 'sharer.php', 'share', 'share.php', 'plugins', 'tr', 'dialog', 'login', 'policy.php', 'privacy', 'help', 'groups', 'events', 'watch', 'business', 'ads', 'profile.php', 'pages', 'facebook', 'home.php', 'l.php', 'v2.0', 'v3.0', 'photo.php', 'story.php', 'permalink.php', 'hashtag', 'people', 'media', 'apps', 'legal', 'about', 'settings', 'search', 'notes', 'pg', 'gaming']);

function contarMaisFrequente(lista) {
  const c = new Map();
  lista.forEach((x, i) => { const v = c.get(x) || { n: 0, i }; v.n++; c.set(x, v); });
  return [...c.entries()].sort((a, b) => b[1].n - a[1].n || a[1].i - b[1].i).map((e) => e[0]);
}

export function extrair(html, nicho) {
  const titulo = limpo(html.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1] ?? '').slice(0, 200);
  const descricao = (meta(html, 'description') || meta(html, 'og:description')).slice(0, 400);

  const ig = [...html.matchAll(/instagram\.com\/([A-Za-z0-9_.]{2,30})/gi)].map((m) => m[1].replace(/\.+$/, '').toLowerCase()).filter((h) => !IG_RESERVADO.has(h));
  const fb = [...html.matchAll(/facebook\.com\/([A-Za-z0-9_.\-]{2,80})/gi)].map((m) => m[1].replace(/\.+$/, '')).filter((h) => !FB_RESERVADO.has(h.toLowerCase()));

  const wa = [];
  for (const m of html.matchAll(/(?:https?:)?(?:\/\/)?(?:wa\.me\/(\+?\d{8,15})|(?:api|web)\.whatsapp\.com\/send\/?\?[^"'\s<>]*?phone=(?:%2B|\+)?(\d{8,15})|(?:www\.)?whatsapp\.com\/send\/?\?[^"'\s<>]*?phone=(?:%2B|\+)?(\d{8,15})|wa\.link\/([A-Za-z0-9]+))/gi)) {
    if (m[1] || m[2] || m[3]) wa.push((m[1] || m[2] || m[3]).replace(/^\+/, ''));
    else if (m[4]) wa.push('wa.link/' + m[4]);
  }
  // Plugins comuns de botão (joinchat, click-to-chat) guardam o número em atributos/JSON.
  for (const m of html.matchAll(/"(?:telephone|phone|whatsapp|number)"\s*:\s*"\+?(\d{12,13})"[^}]{0,200}?(?:joinchat|whatsapp)/gi)) wa.push(m[1]);
  if (/class=["'][^"']*joinchat[^"']*["']/i.test(html) && !wa.length) wa.push('plugin-joinchat');

  const texto = limpo(
    html.replace(/<script\b[\s\S]*?<\/script>/gi, ' ').replace(/<style\b[\s\S]*?<\/style>/gi, ' ').replace(/<noscript\b[\s\S]*?<\/noscript>/gi, ' ').replace(/<!--[\s\S]*?-->/g, ' ').replace(/<[^>]+>/g, ' ')
  );
  const alvo = (titulo + ' . ' + descricao + ' . ' + texto);
  const achados = [];
  for (const termo of SERVICOS[nicho] || []) {
    const ms = [...alvo.matchAll(reAcento(termo))];
    if (!ms.length) continue;
    let forma = ms[0][0];
    if (forma === forma.toUpperCase() && forma.length > 4 && !/^(INSS|IRPF|MEI|BPC|LOAS|HIFU|DTM|PDO|BPO)$/.test(forma)) forma = forma.toLowerCase();
    achados.push({ termo, forma: forma.replace(/\s+/g, ' '), n: ms.length, pos: ms[0].index });
  }
  // remove termos contidos em outro termo achado (ex.: "implante" quando já há "implante dentário")
  const filtrados = achados.filter((a) => !achados.some((b) => b !== a && b.termo.length > a.termo.length && b.termo.toLowerCase().includes(a.termo.toLowerCase())));
  const vistos = new Set();
  const servicos = filtrados.sort((a, b) => b.n - a.n || a.pos - b.pos).filter((a) => { const k = a.forma.toLowerCase(); if (vistos.has(k)) return false; vistos.add(k); return true; }).slice(0, 6).map((a) => a.forma);

  return {
    titulo, descricao,
    instagram: contarMaisFrequente(ig).slice(0, 3),
    facebook: contarMaisFrequente(fb).slice(0, 3),
    whatsapp: contarMaisFrequente(wa).slice(0, 3),
    servicos,
    texto_chars: texto.length,
    texto_amostra: texto.slice(0, 4000),
  };
}

async function lerCorpo(res) {
  const reader = res.body.getReader();
  const partes = []; let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    partes.push(value); total += value.length;
    if (total > LIMITE_BYTES) { try { await reader.cancel(); } catch {} break; }
  }
  const buf = Buffer.concat(partes.map((p) => Buffer.from(p)));
  let cs = (res.headers.get('content-type') || '').match(/charset=([\w-]+)/i)?.[1];
  if (!cs) cs = buf.subarray(0, 4096).toString('latin1').match(/<meta[^>]+charset=["']?([\w-]+)/i)?.[1];
  cs = (cs || 'utf-8').toLowerCase();
  try { return new TextDecoder(cs).decode(buf); } catch { return new TextDecoder('utf-8').decode(buf); }
}


export async function baixar(ctx, url) {
  const res = await ctx.deps.fetch(url, {
    redirect: 'follow',
    signal: AbortSignal.timeout(10000),
    headers: { 'User-Agent': UA, Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8' },
  });
  const ct = res.headers.get('content-type') || '';
  if (!res.ok) { try { await res.body?.cancel(); } catch {} return { erro: `HTTP ${res.status}`, final_url: res.url }; }
  if (ct && !/html|xml|text\/plain/i.test(ct)) { try { await res.body?.cancel(); } catch {} return { erro: `tipo ${ct.split(';')[0]}`, final_url: res.url }; }
  const html = await lerCorpo(res);
  return { html, final_url: res.url, status: res.status };
}

// Lê o site e devolve o registro do cache (o mesmo formato de cache-sites/<placeId>.json, mais `sinais` da lente).
export async function lerSite(ctx, n) {
  const t0 = Date.now();
  let out;
  try {
    const r = await baixar(ctx, n.site);
    if (r.erro) out = { ok: false, erro: r.erro, final_url: r.final_url };
    else {
      const ex = extrair(r.html, n.nicho);
      out = { ok: true, status: r.status, final_url: r.final_url, ...ex, sinais: scanHtml(r.html) };
      if (ex.texto_chars < 200 && !ex.titulo) { out.ok = false; out.erro = 'página vazia (provável JS)'; }
    }
  } catch (e) {
    const causa = e?.cause?.code || e?.cause?.message || '';
    out = { ok: false, erro: (e.name === 'TimeoutError' ? 'timeout 10s' : (e.message || String(e))) + (causa ? ` (${causa})` : '') };
  }
  out.url = n.site; out.placeId = n.placeId; out.ms = Date.now() - t0; out.quando = new Date(ctx.agora()).toISOString();
  return out;
}

// tipo do link de site: 'site' (baixar), 'instagram', 'facebook', 'whatsapp', 'social', 'nenhum'
export function tipoSite(url) {
  if (!url) return 'nenhum';
  let h;
  try { h = new URL(url).hostname.toLowerCase().replace(/^www\./, ''); } catch { return 'invalido'; }
  if (/(^|\.)instagram\.com$/.test(h)) return 'instagram';
  if (/(^|\.)(facebook\.com|fb\.com|fb\.me)$/.test(h)) return 'facebook';
  if (/(^|\.)(wa\.me|whatsapp\.com|api\.whatsapp\.com|wa\.link)$/.test(h)) return 'whatsapp';
  if (/(^|\.)(tiktok\.com|youtube\.com|linkedin\.com|twitter\.com|x\.com)$/.test(h)) return 'social';
  return 'site';
}

// --- de scripts/qualificar-riqueza.mjs ---
const PIXELS = {
  meta_pixel: [/fbq\(\s*['"]init/i, /connect\.facebook\.net\/[^"']*fbevents\.js/i],
  google_ads: [/['"]AW-\d{6,}/, /googleads\.g\.doubleclick\.net/i, /googleadservices\.com\/pagead\/conversion/i],
  gtm: [/googletagmanager\.com\/gtm\.js/i, /['"]GTM-[A-Z0-9]{4,}/],
  ga: [/googletagmanager\.com\/gtag\/js\?id=(G|UA)-/i, /['"]G-[A-Z0-9]{6,}['"]/, /google-analytics\.com\/(analytics|ga)\.js/i],
  tiktok: [/analytics\.tiktok\.com/i],
  hotjar_clarity: [/static\.hotjar\.com|hotjar\.com\/c\/hotjar/i, /clarity\.ms\/tag/i],
};

export function validCnpj(digits) {
  if (!/^\d{14}$/.test(digits) || /^(\d)\1{13}$/.test(digits)) return false;
  const calc = (len) => {
    const weights = len === 12 ? [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2] : [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
    const sum = weights.reduce((s, w, i) => s + w * Number(digits[i]), 0);
    const r = sum % 11;
    return r < 2 ? 0 : 11 - r;
  };
  return calc(12) === Number(digits[12]) && calc(13) === Number(digits[13]);
}

export function scanHtml(html) {
  const pixels = {}, provas = {};
  for (const [name, patterns] of Object.entries(PIXELS)) {
    for (const re of patterns) {
      const m = html.match(re);
      if (m) { pixels[name] = true; provas[name] = html.slice(Math.max(0, m.index - 40), m.index + 80).replace(/\s+/g, ' '); break; }
    }
    if (!pixels[name]) pixels[name] = false;
  }
  const found = new Set();
  for (const m of html.matchAll(/\b(\d{2})\.?(\d{3})\.?(\d{3})\/?(\d{4})-?(\d{2})\b/g)) {
    const digits = m.slice(1).join('');
    if (validCnpj(digits)) found.add(digits);
  }
  return { pixels, provas, cnpjs: [...found] };
}
