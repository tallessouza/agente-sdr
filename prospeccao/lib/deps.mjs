// Dependências externas do pipeline, num lugar só, para os testes e o modo --fixtures trocarem tudo de uma vez:
// fetch (Apify, Meta, sites, BrasilAPI, registro.br, busca web), spawnSync (ssh na VM1), tokens do cofre e sleep.
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { segredo, ITENS } from './cofre.mjs';
import { PRECOS } from './custos.mjs';

export function depsReais() {
  return {
    fetch: globalThis.fetch,
    spawnSync,
    sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
    tokenApify: (conta) => { if (!ITENS.apify[conta]) throw new Error(`conta do pool desconhecida: ${conta}`); return segredo(ITENS.apify[conta]); },
    tokenMeta: () => segredo(ITENS.meta),
  };
}

const resposta = (corpo, { status = 200, tipo = 'application/json', url = '' } = {}) => {
  const r = new Response(typeof corpo === 'string' ? corpo : JSON.stringify(corpo), { status, headers: { 'content-type': tipo } });
  Object.defineProperty(r, 'url', { value: url });
  return r;
};
const lerSe = (f) => (fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : null);

// Dependências falsas a partir de uma pasta de fixtures (ver test/fixtures/exemplo). Nada sai da máquina.
// opcoes.falhar(url, opts) -> true faz o fetch lançar erro (para testar retomada).
// chamadas: registro de tudo o que seria externo, para os testes conferirem.
export function depsFixtures(dir, opcoes = {}) {
  const manifesto = JSON.parse(lerSe(path.join(dir, 'manifesto.json')) || '{}');
  const J = (rel, padrao) => { const t = lerSe(path.join(dir, rel)); return t ? JSON.parse(t) : padrao; };
  const chamadas = { apify: [], apifyRuns: [], meta: [], sites: [], cnpj: [], outros: [], ssh: [] };
  const runs = new Map();
  let seq = 0;

  function itensDoAtor(ator, input) {
    if (ator === 'compass~crawler-google-places') {
      const cidade = String(input.locationQuery).split(',')[0].trim();
      const out = [];
      for (const busca of input.searchStringsArray) {
        out.push(...J('apify/maps.json', []).filter((i) => i._cidade === cidade && i.searchString === busca).slice(0, input.maxCrawledPlacesPerSearch).map(({ _cidade, ...i }) => i));
      }
      return { items: out, custo: out.length * PRECOS.maps_lugar + PRECOS.maps_inicio, eventos: { 'place-scraped': out.length, 'filter-applied': out.length, 'apify-actor-start': 4 } };
    }
    if (ator === 'apify~instagram-profile-scraper') {
      const todos = J('apify/instagram-perfis.json', []);
      const items = input.usernames.map((u) => todos.find((p) => p.username === u) || { inputUrl: u, error: 'not_found' });
      return { items, custo: input.usernames.length * PRECOS.ig_perfil, eventos: { result: input.usernames.length } };
    }
    if (ator === 'apify~instagram-comment-scraper') {
      const todos = J('apify/instagram-comentarios.json', []);
      const items = input.directUrls.flatMap((u) => todos.filter((c) => c.postUrl === u).slice(0, input.resultsLimit));
      return { items, custo: items.length * PRECOS.ig_comentario, eventos: { result: items.length } };
    }
    throw new Error('ator sem fixture: ' + ator);
  }

  function apify(u, opts) {
    const conta = String(opts.headers?.Authorization || '').replace(/^Bearer fixture:/, '');
    chamadas.apify.push({ metodo: opts.method || 'GET', caminho: u.pathname, conta });
    let m;
    if (u.pathname === '/v2/users/me/limits') {
      const livre = (manifesto.saldo_apify || {})[conta] ?? 5;
      return resposta({ data: { current: { monthlyUsageUsd: 5 - livre }, limits: { maxMonthlyUsageUsd: 5 } } });
    }
    if ((m = u.pathname.match(/^\/v2\/acts\/([^/]+)\/runs$/)) && opts.method === 'POST') {
      const input = JSON.parse(opts.body);
      const teto = Number(u.searchParams.get('maxTotalChargeUsd'));
      const r = itensDoAtor(m[1], input);
      const id = `fx${++seq}`;
      const run = { id, actId: m[1], status: 'SUCCEEDED', defaultDatasetId: `ds-${id}`, usageTotalUsd: Math.min(r.custo, teto), chargedEventCounts: r.eventos, _items: r.items };
      runs.set(id, run);
      chamadas.apifyRuns.push({ ator: m[1], input, teto, conta, runId: id });
      return resposta({ data: { ...run, status: 'RUNNING', _items: undefined } });
    }
    if ((m = u.pathname.match(/^\/v2\/actor-runs\/([^/]+)$/))) { const { _items, ...run } = runs.get(m[1]) || {}; return resposta({ data: run }); }
    if ((m = u.pathname.match(/^\/v2\/datasets\/ds-([^/]+)\/items$/))) return resposta(runs.get(m[1])?._items || []);
    return resposta({ error: { message: 'rota sem fixture ' + u.pathname } }, { status: 404 });
  }

  async function fetchFalso(url, opts = {}) {
    if (opcoes.falhar?.(String(url), opts)) throw new Error('falha simulada: ' + url);
    const u = new URL(url);
    if (u.hostname === 'api.apify.com') return apify(u, opts);
    if (u.hostname === 'graph.facebook.com') {
      const user = decodeURIComponent((String(url).match(/business_discovery\.username\(([^)]+)\)/) || [])[1] || '');
      chamadas.meta.push(user);
      const f = J(`meta/${user}.json`, null);
      if (!f) return resposta({ error: { code: 110, error_subcode: 2207013, message: 'Invalid user id' } }, { status: 400 });
      if (f.error) return resposta(f, { status: 400 });
      return resposta({ business_discovery: f, id: 'fixture' });
    }
    if (u.hostname === 'brasilapi.com.br' || u.hostname === 'minhareceita.org') {
      const c = u.pathname.split('/').pop();
      chamadas.cnpj.push(c);
      const f = J(`cnpj/${c}.json`, null);
      return f ? resposta(f) : resposta({ message: 'CNPJ não encontrado' }, { status: 404 });
    }
    if (u.hostname === 'rdap.registro.br') { chamadas.outros.push(String(url)); return resposta({}, { status: 404 }); }
    if (u.hostname === 'html.duckduckgo.com') { chamadas.outros.push(String(url)); return resposta('<html><body>sem resultados</body></html>', { tipo: 'text/html' }); }
    const host = u.hostname.replace(/^www\./, '');
    const rota = u.pathname.replace(/\/+$/, '').replace(/\//g, '_');
    chamadas.sites.push(host + u.pathname);
    const html = lerSe(path.join(dir, 'sites', `${host}${rota}.html`));
    return html ? resposta(html, { tipo: 'text/html; charset=utf-8', url: String(url) }) : resposta('<html>não encontrado</html>', { status: 404, tipo: 'text/html', url: String(url) });
  }

  function spawnFalso(cmd, args, opts) {
    const remoto = args[args.length - 1];
    const entrada = JSON.parse(opts.input);
    chamadas.ssh.push({ cmd, args, entrada });
    if (/importar_leads\.py --stdin/.test(remoto)) {
      const por = Object.fromEntries(Object.entries(entrada.arquivos).map(([k, v]) => [k, { lidos: Array.isArray(v) ? v.length : Object.keys(v).length, alterados: Array.isArray(v) ? v.length : Object.keys(v).length }]));
      return { status: 0, stdout: JSON.stringify({ banco: '/data/bridge.db (fixture)', simulado: /--simular/.test(remoto), por_destino: por }), stderr: '' };
    }
    if (/prospeccao\.enqueue/.test(remoto)) {
      const r = entrada.modo === 'fila' ? { novos: entrada.negocios.length, repetidos: 0, invalidos: 0 } : { atualizados: 0 };
      return { status: 0, stdout: JSON.stringify(r), stderr: '' };
    }
    return { status: 1, stdout: '', stderr: 'comando sem fixture' };
  }

  return {
    manifesto, chamadas,
    deps: { fetch: fetchFalso, spawnSync: spawnFalso, sleep: async () => {}, tokenApify: (c) => `fixture:${c}`, tokenMeta: () => 'fixture-meta' },
  };
}
