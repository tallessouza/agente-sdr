// O teto de custo da campanha aborta a etapa ANTES de gastar: nenhuma run começa e o custos.json não muda.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { TetoExcedido } from '../lib/custos.mjs';
import { novaCampanha, limpar, fake, rodar, existe, ler, texto, RAIZ, FIXTURES } from './ajuda.mjs';

after(limpar);

test('coleta acima do teto aborta sem chamar o Apify', async () => {
  // 2 cidades x 2 nichos x 5 = 20 lugares x US$ 0,005 + teste de 5 = US$ 0,1256 > 0,05
  const raiz = novaCampanha({ teto_usd: { coleta: 0.05 } });
  const fx = fake();
  await assert.rejects(rodar(raiz, fx, 'coletar', 'exemplo'), (e) => e instanceof TetoExcedido && e.etapa === 'coleta' && e.teto === 0.05);
  assert.equal(fx.chamadas.apifyRuns.length, 0, 'nenhuma run iniciada');
  assert.equal(fx.chamadas.apify.length, 0, 'nem consulta de saldo');
  assert.equal(existe(raiz, 'custos.json'), false);
  assert.equal(existe(raiz, 'negocios.json'), false);
  assert.match(texto(raiz, 'coleta.log'), /ABORTADO: teto de US\$ 0\.05/);
});

test('o teto conta o que já foi gasto: a segunda etapa que passaria do teto aborta', async () => {
  const raiz = novaCampanha({ teto_usd: { instagram_fundo: 0.01 } }); // 3 posts com comentários: estimativa US$ 0,065
  const fx = fake();
  await rodar(raiz, fx, 'coletar', 'exemplo');
  await rodar(raiz, fx, 'enriquecer', 'exemplo', '--camada', 'site');
  await rodar(raiz, fx, 'enriquecer', 'exemplo', '--camada', 'ig-raso');
  const antes = ler(raiz, 'custos.json');
  const runsAntes = fx.chamadas.apifyRuns.length;
  await assert.rejects(rodar(raiz, fx, 'enriquecer', 'exemplo', '--camada', 'ig-fundo'), (e) => e instanceof TetoExcedido && e.etapa === 'instagram_fundo');
  assert.equal(fx.chamadas.apifyRuns.length, runsAntes, 'nenhuma run de comentários');
  assert.deepEqual(ler(raiz, 'custos.json'), antes, 'custos.json igual');
});

test('cada run recebe como teto de cobrança só o que sobra do teto da etapa', async () => {
  const raiz = novaCampanha({ teto_usd: { coleta: 0.13 } });
  const fx = fake();
  await rodar(raiz, fx, 'coletar', 'exemplo');
  const tetos = fx.chamadas.apifyRuns.map((r) => r.teto);
  assert.equal(tetos[0], 0.13);
  const c = ler(raiz, 'custos.json');
  assert.ok(c.etapas.coleta.gasto_usd <= 0.13);
  // a segunda run só pode cobrar o que sobrou depois da primeira
  assert.ok(Math.abs(tetos[1] - Number((0.13 - c.etapas.coleta.runs[0].custo_usd).toFixed(3))) < 0.0011);
});

test('pela linha de comando, o teto sai com código 2', () => {
  const raiz = novaCampanha({ teto_usd: { coleta: 0.01 } });
  const r = spawnSync(process.execPath, [path.join(RAIZ, 'prospeccao.mjs'), 'coletar', 'exemplo', '--campanhas', raiz, '--fixtures', FIXTURES], { encoding: 'utf8' });
  assert.equal(r.status, 2, r.stderr);
  assert.match(r.stderr, /TETO: teto de US\$ 0\.01 da etapa coleta passaria/);
});
