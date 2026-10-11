// Critério de pronto (sem crédito): a campanha de exemplo roda do zero até a fila, em simulação, só com campanha.json,
// os comandos da linha de comando e as fixtures (Apify, Meta, sites e BrasilAPI falsos). O custo de cada etapa sai no log.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { novaCampanha, limpar, ler, texto, existe, RAIZ, FIXTURES } from './ajuda.mjs';

after(limpar);

test('campanha de exemplo de ponta a ponta pela linha de comando', () => {
  const raiz = novaCampanha();
  const cli = (...a) => {
    const r = spawnSync(process.execPath, [path.join(RAIZ, 'prospeccao.mjs'), ...a, 'exemplo', '--campanhas', raiz, '--fixtures', FIXTURES], { encoding: 'utf8' });
    assert.equal(r.status, 0, `${a.join(' ')}: ${r.stderr}`);
    return r.stdout;
  };
  cli('coletar');
  for (const c of ['site', 'ig-raso', 'ig-fundo', 'decisor']) cli('enriquecer', '--camada', c);
  cli('qualificar');
  const saidaFila = cli('fila');
  const saidaCusto = cli('custo');
  const saidaStatus = cli('status');

  for (const f of ['negocios.json', 'enriquecidos.json', 'instagram-perfis.json', 'decisores.json', 'qualificacao-riqueza.json', 'fila-ordenada-riqueza.json', 'sites-sinais.json', 'cnpj-cache.json', 'fila.json', 'custos.json'])
    assert.ok(existe(raiz, f), f);
  assert.equal(ler(raiz, 'fila.json').negocios.length, 9);
  assert.match(saidaFila, /simulação: nada enfileirado na produção/);
  assert.match(saidaFila, /1\. nota 14 \| Clínica Sorriso Pleno/);
  // custo por etapa no log e no custos.json
  assert.match(texto(raiz, 'coleta.log'), /custo run=\S+ .*custo_usd=0\.0252/);
  assert.match(texto(raiz, 'instagram_raso.log'), /custo run=.*apify~instagram-profile-scraper/);
  assert.match(texto(raiz, 'instagram_fundo.log'), /custo run=.*apify~instagram-comment-scraper/);
  assert.match(texto(raiz, 'enriquecer-site.log'), /custo US\$ 0 \(grátis\)/);
  const c = ler(raiz, 'custos.json');
  assert.equal(c.etapas.coleta.runs.length, 3);
  assert.ok(c.etapas.coleta.runs.every((r) => r.fixture));
  assert.ok(Math.abs(c.total_usd - (c.etapas.coleta.gasto_usd + c.etapas.instagram_raso.gasto_usd + c.etapas.instagram_fundo.gasto_usd)) < 1e-9);
  assert.match(saidaCusto, /total: US\$ 0\.1114/);
  assert.match(saidaStatus, /todas as etapas têm saída/);
});
