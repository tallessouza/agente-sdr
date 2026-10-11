// Retomada: o que já foi feito (e pago) não é refeito; uma run do Apify interrompida é retomada, não recomeçada.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { novaCampanha, limpar, fake, rodar, existe, ler } from './ajuda.mjs';

after(limpar);

test('coleta que cai na segunda cidade retoma só a cidade que faltou', async () => {
  const raiz = novaCampanha();
  let quebrar = true;
  const fx = fake({ falhar: (url, o) => quebrar && o.method === 'POST' && /Palho/.test(String(o.body)) });
  await assert.rejects(rodar(raiz, fx, 'coletar', 'exemplo'), /falha simulada/);
  assert.ok(existe(raiz, 'raw/teste-5.json'));
  assert.ok(existe(raiz, 'raw/sao-jose-sc.json'));
  assert.equal(existe(raiz, 'raw/palhoca-sc.json'), false);
  const runsAntes = fx.chamadas.apifyRuns.length; // teste + São José
  assert.equal(runsAntes, 2);

  quebrar = false;
  await rodar(raiz, fx, 'coletar', 'exemplo');
  const novas = fx.chamadas.apifyRuns.slice(runsAntes);
  assert.equal(novas.length, 1, 'só uma run nova');
  assert.equal(novas[0].input.locationQuery, 'Palhoça, SC, Brasil');
  assert.equal(ler(raiz, 'custos.json').etapas.coleta.runs.length, 3, 'nenhuma cobrança repetida');
  assert.equal(ler(raiz, 'negocios.json').length, 10);

  // terceira vez: nada a coletar, nada a gastar
  await rodar(raiz, fx, 'coletar', 'exemplo');
  assert.equal(fx.chamadas.apifyRuns.length, runsAntes + 1);
});

test('run interrompida enquanto rodava é retomada pela mesma runId', async () => {
  const raiz = novaCampanha();
  let quebrar = true;
  // cai no primeiro acompanhamento da run (depois de iniciada e registrada como pendente)
  const fx = fake({ falhar: (url) => quebrar && /\/v2\/actor-runs\//.test(url) });
  await assert.rejects(rodar(raiz, fx, 'coletar', 'exemplo'), /falha simulada/);
  const pend = ler(raiz, 'cache/runs-pendentes.json');
  assert.deepEqual(Object.keys(pend), ['coleta:teste-5']);
  const runId = pend['coleta:teste-5'].runId;

  quebrar = false;
  await rodar(raiz, fx, 'coletar', 'exemplo');
  const c = ler(raiz, 'custos.json').etapas.coleta.runs;
  assert.equal(c[0].runId, runId, 'a run retomada é a mesma');
  assert.equal(fx.chamadas.apifyRuns.filter((r) => r.input.maxCrawledPlacesPerSearch === 5 && r.input.searchStringsArray.length === 1).length, 1, 'o teste de 5 não foi iniciado de novo');
  assert.deepEqual(ler(raiz, 'cache/runs-pendentes.json'), {});
});

test('camadas grátis também retomam pelo cache: site e Meta não são lidos de novo', async () => {
  const raiz = novaCampanha();
  const fx = fake();
  await rodar(raiz, fx, 'coletar', 'exemplo');
  await rodar(raiz, fx, 'enriquecer', 'exemplo', '--camada', 'site');
  await rodar(raiz, fx, 'enriquecer', 'exemplo', '--camada', 'ig-raso');
  const sites = fx.chamadas.sites.length, meta = fx.chamadas.meta.length, runs = fx.chamadas.apifyRuns.length;
  assert.ok(sites > 0 && meta > 0);
  const antes = ler(raiz, 'enriquecidos.json');
  await rodar(raiz, fx, 'enriquecer', 'exemplo', '--camada', 'site');
  await rodar(raiz, fx, 'enriquecer', 'exemplo', '--camada', 'ig-raso');
  assert.equal(fx.chamadas.sites.length, sites);
  assert.equal(fx.chamadas.meta.length, meta);
  assert.equal(fx.chamadas.apifyRuns.length, runs, 'o perfil que foi ao Apify não vai de novo');
  // rodar a camada site de novo não apaga o que a camada do Instagram gravou
  assert.deepEqual(ler(raiz, 'enriquecidos.json'), antes);
});
