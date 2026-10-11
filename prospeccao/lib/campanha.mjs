// Campanha: leitura e validação do campanha.json, caminhos, JSON atômico, log por etapa e ordem de prioridade.
// Tudo o que um comando grava fica em campanhas/<slug>/; os caches por item ficam em campanhas/<slug>/cache/.
import fs from 'node:fs';
import path from 'node:path';

export class ErroCampanha extends Error {}

export function carregarCampanha(raiz, slug) {
  if (!slug || !/^[a-z0-9][a-z0-9-]*$/.test(slug)) throw new ErroCampanha(`slug inválido: "${slug}" (use letras minúsculas, números e hífen)`);
  const dir = path.join(raiz, slug);
  const arq = path.join(dir, 'campanha.json');
  if (!fs.existsSync(arq)) throw new ErroCampanha(`não achei ${arq}`);
  const c = JSON.parse(fs.readFileSync(arq, 'utf8'));
  validar(c, slug);
  return { dir, campanha: normalizar(c) };
}

export function validar(c, slug) {
  const erros = [];
  if (c.slug !== slug) erros.push(`slug do arquivo ("${c.slug}") difere da pasta ("${slug}")`);
  if (!Array.isArray(c.cidades) || !c.cidades.length || c.cidades.some((x) => !x?.nome || !/^[A-Z]{2}$/.test(x?.uf || ''))) erros.push('cidades: lista de {"nome", "uf"} com UF de 2 letras');
  if (!Array.isArray(c.nichos) || !c.nichos.length || c.nichos.some((n) => typeof n !== 'string' || !n.trim())) erros.push('nichos: lista de textos');
  if (!Number.isInteger(c.por_busca) || c.por_busca < 1 || c.por_busca > 500) erros.push('por_busca: inteiro de 1 a 500');
  if (!c.teto_usd || typeof c.teto_usd !== 'object') erros.push('teto_usd: {"coleta", "instagram_raso", "instagram_fundo"} em US$');
  else for (const k of ['coleta', 'instagram_raso', 'instagram_fundo']) if (c.teto_usd[k] != null && !(typeof c.teto_usd[k] === 'number' && c.teto_usd[k] >= 0)) erros.push(`teto_usd.${k}: número >= 0`);
  for (const [k, v] of Object.entries(c.camadas || {})) if (!(typeof v === 'boolean' || /^top:\d+$/.test(String(v)) || Number.isInteger(v))) erros.push(`camadas.${k}: true, false ou "top:N"`);
  if (erros.length) throw new ErroCampanha('campanha.json inválido: ' + erros.join('; '));
}

function normalizar(c) {
  return {
    ...c,
    teto_usd: { coleta: 0, instagram_raso: 0, instagram_fundo: 0, ...(c.teto_usd || {}) },
    prioridade: { cidades_primeiro: [], ordem: 'avaliacoes_desc', ...(c.prioridade || {}) },
    camadas: { site: true, instagram_raso: true, instagram_fundo: false, decisor: false, ...(c.camadas || {}) },
  };
}

export const caminho = (ctx, ...p) => path.join(ctx.dir, ...p);

export function lerJson(ctx, rel, padrao) {
  const f = caminho(ctx, rel);
  if (!fs.existsSync(f)) return padrao;
  return JSON.parse(fs.readFileSync(f, 'utf8'));
}

// Escreve em arquivo temporário e renomeia: um processo morto no meio nunca deixa JSON pela metade (a retomada depende disso).
export function gravarJson(ctx, rel, valor) {
  const f = caminho(ctx, rel);
  fs.mkdirSync(path.dirname(f), { recursive: true });
  const tmp = `${f}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(valor, null, 1));
  fs.renameSync(tmp, f);
}

export function existe(ctx, rel) { return fs.existsSync(caminho(ctx, rel)); }

export function logar(ctx, etapa, msg) {
  const linha = `${new Date(ctx.agora()).toISOString()} ${msg}`;
  fs.mkdirSync(ctx.dir, { recursive: true });
  fs.appendFileSync(caminho(ctx, `${etapa}.log`), linha + '\n');
  if (!ctx.silencioso) console.log(`[${etapa}] ${msg}`);
}

// Ordem de prioridade (de enriquecer/comum.mjs, generalizada pela campanha): só prováveis WhatsApp;
// primeiro as cidades de prioridade.cidades_primeiro, depois as demais na ordem do campanha.json;
// dentro da cidade por avaliações (desc), desempate por nota e nome.
export function ordenarPrioridade(lista, campanha) {
  const ordem = [...(campanha.prioridade.cidades_primeiro || []), ...campanha.cidades.map((c) => c.nome)];
  const idx = (c) => { const i = ordem.indexOf(c); return i < 0 ? 999 : i; };
  const porNota = campanha.prioridade.ordem === 'nota_desc';
  return lista.filter((x) => x.provavel_whatsapp === true).sort((a, b) => idx(a.cidade) - idx(b.cidade)
    || (porNota ? (b.nota || 0) - (a.nota || 0) || (b.avaliacoes || 0) - (a.avaliacoes || 0) : (b.avaliacoes || 0) - (a.avaliacoes || 0) || (b.nota || 0) - (a.nota || 0))
    || String(a.nome).localeCompare(String(b.nome)));
}

// "top:150" -> 150; true -> todos; false -> 0 (camada desligada)
export function quantos(spec, total) {
  if (spec === true) return total;
  if (spec === false || spec == null) return 0;
  if (Number.isInteger(spec)) return Math.min(spec, total);
  const m = String(spec).match(/^top:(\d+)$/);
  return m ? Math.min(+m[1], total) : 0;
}

export const slugTexto = (s) => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
