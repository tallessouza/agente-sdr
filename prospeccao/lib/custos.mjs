// Custo por etapa: estimativa antes de gastar, teto da campanha, registro de cada run no custos.json e no log.
//
// Preços usados na estimativa (fonte: o que os scripts de 09/10 usaram e o que as runs cobraram):
// - Maps (compass/crawler-google-places): place-scraped 0,004 + filter-applied 0,001 por lugar, apify-actor-start 0,00005
//   (tabela P de maps/run.mjs; coleta.log de 09/10: 150 lugares = US$ 0,7502, 5 lugares = US$ 0,0252).
// - Instagram, perfil (apify/instagram-profile-scraper): 0,0026 por perfil (PRECO de ig-lista/apify1.mjs).
// - Instagram, comentários (apify/instagram-comment-scraper): 0,0026 por comentário (PRECO de ig-lista/camada2.mjs).
// O valor que conta é o cobrado (usageTotalUsd da run); a estimativa só decide se a etapa pode começar.
import { lerJson, gravarJson, logar } from './campanha.mjs';

export const PRECOS = {
  maps_lugar: 0.004 + 0.001,
  maps_inicio: 0.00005 * 4,
  ig_perfil: 0.0026,
  ig_comentario: 0.0026,
};

export const ETAPAS_PAGAS = ['coleta', 'instagram_raso', 'instagram_fundo'];

export class TetoExcedido extends Error {
  constructor(etapa, gasto, estimativa, teto) {
    super(`teto de US$ ${teto.toFixed(2)} da etapa ${etapa} passaria: já gasto US$ ${gasto.toFixed(4)} + estimativa US$ ${estimativa.toFixed(4)} = US$ ${(gasto + estimativa).toFixed(4)}. Nada foi gasto agora. Suba o teto no campanha.json (com o OK do Talles) ou reduza a campanha.`);
    Object.assign(this, { etapa, gasto, estimativa, teto });
  }
}

export function lerCustos(ctx) {
  const c = lerJson(ctx, 'custos.json', null) || {};
  c.etapas ||= {};
  for (const e of ETAPAS_PAGAS) c.etapas[e] ||= { gasto_usd: 0, runs: [] };
  return c;
}

export function gasto(ctx, etapa) { return lerCustos(ctx).etapas[etapa]?.gasto_usd || 0; }
export function teto(ctx, etapa) { return ctx.campanha.teto_usd[etapa] ?? 0; }
export function restante(ctx, etapa) { return Math.max(0, teto(ctx, etapa) - gasto(ctx, etapa)); }

// Chamada antes de qualquer gasto: aborta (TetoExcedido) se o já gasto mais a estimativa passar do teto.
export function garantirTeto(ctx, etapa, estimativa, oQue) {
  const g = gasto(ctx, etapa), t = teto(ctx, etapa);
  logar(ctx, etapa, `estimativa ${oQue}: US$ ${estimativa.toFixed(4)} (gasto até agora US$ ${g.toFixed(4)}, teto US$ ${t.toFixed(2)})`);
  if (g + estimativa > t + 1e-9) {
    const e = new TetoExcedido(etapa, g, estimativa, t);
    logar(ctx, etapa, `ABORTADO: ${e.message}`);
    throw e;
  }
}

export function registrarRun(ctx, etapa, run) {
  const c = lerCustos(ctx);
  const reg = { quando: new Date(ctx.agora()).toISOString(), ...run, custo_usd: Number((run.custo_usd || 0).toFixed(6)) };
  if (ctx.fixtures) reg.fixture = true;
  c.etapas[etapa].runs.push(reg);
  c.etapas[etapa].gasto_usd = Number(c.etapas[etapa].runs.reduce((s, r) => s + (r.custo_usd || 0), 0).toFixed(6));
  c.total_usd = Number(ETAPAS_PAGAS.reduce((s, e) => s + c.etapas[e].gasto_usd, 0).toFixed(6));
  c.atualizado_em = reg.quando;
  gravarJson(ctx, 'custos.json', c);
  logar(ctx, etapa, `custo run=${run.runId} conta="${run.conta}" ator=${run.ator} itens=${run.itens ?? '?'} status=${run.status} custo_usd=${reg.custo_usd.toFixed(4)} acumulado_etapa_usd=${c.etapas[etapa].gasto_usd.toFixed(4)} teto_usd=${teto(ctx, etapa).toFixed(2)}${ctx.fixtures ? ' (fixture)' : ''}`);
  return c;
}
