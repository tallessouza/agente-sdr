// Apify: saldo do pool, escolha da conta e run com teto de cobrança (de ig-lista/apifyrun.mjs e pool.mjs, com fetch injetável).
import { ORDEM_POOL } from './cofre.mjs';

const API = 'https://api.apify.com/v2';

export async function saldo(ctx, conta) {
  const r = await ctx.deps.fetch(`${API}/users/me/limits`, { headers: { Authorization: 'Bearer ' + ctx.deps.tokenApify(conta) } });
  const j = (await r.json()).data;
  return { usado: j.current.monthlyUsageUsd, limite: j.limits.maxMonthlyUsageUsd, livre: j.limits.maxMonthlyUsageUsd - j.current.monthlyUsageUsd };
}

// Primeira conta do pool com saldo livre para a estimativa (mais uma folga de 1 centavo). Sem conta: null.
export async function escolherConta(ctx, necessario) {
  for (const c of ORDEM_POOL) {
    try { const s = await saldo(ctx, c); if (s.livre >= necessario + 0.01) return { conta: c, livre: s.livre }; } catch { /* conta com erro: próxima */ }
  }
  return null;
}

// runId: retoma uma run já iniciada (o processo morreu esperando); aoIniciar(runId): grava a run antes de esperar.
export async function rodar(ctx, conta, ator, input, tetoUsd, { runId, aoIniciar } = {}) {
  const H = { Authorization: 'Bearer ' + ctx.deps.tokenApify(conta), 'Content-Type': 'application/json; charset=utf-8' };
  let run;
  if (runId) run = (await (await ctx.deps.fetch(`${API}/actor-runs/${runId}`, { headers: H })).json()).data;
  else {
    const r = await ctx.deps.fetch(`${API}/acts/${ator}/runs?maxTotalChargeUsd=${Number(tetoUsd.toFixed(3))}`, { method: 'POST', headers: H, body: JSON.stringify(input) });
    const j = await r.json();
    if (!j.data) throw new Error('apify start: ' + JSON.stringify(j).slice(0, 300));
    run = j.data;
    aoIniciar?.(run.id);
  }
  while (!['SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'].includes(run.status)) {
    await ctx.deps.sleep(10000);
    run = (await (await ctx.deps.fetch(`${API}/actor-runs/${run.id}`, { headers: H })).json()).data;
  }
  const items = await (await ctx.deps.fetch(`${API}/datasets/${run.defaultDatasetId}/items?clean=true&format=json`, { headers: H })).json();
  return { items, custo: run.usageTotalUsd ?? 0, status: run.status, runId: run.id, eventos: run.chargedEventCounts || {} };
}

export async function lerRun(ctx, conta, runId) {
  const r = await ctx.deps.fetch(`${API}/actor-runs/${runId}`, { headers: { Authorization: 'Bearer ' + ctx.deps.tokenApify(conta) } });
  return (await r.json()).data;
}
