// Gravação no banco central pelo mesmo caminho de scripts-origem/banco.mjs (ssh -> docker exec -> importar_leads.py --stdin)
// e fila pela prospeccao.enqueue. Só com --aplicar; o ssh aqui é o fake das fixtures.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { argsImportar } from '../lib/banco.mjs';
import { novaCampanha, limpar, fake, rodar, pipelineAteFila, ler } from './ajuda.mjs';

after(limpar);

// Argumentos de scripts-origem/banco.mjs (copiados de lá para o teste travar o formato).
const BANCO_MJS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'ubuntu@100.83.163.117',
  'B=$(sudo docker ps -q -f name=integration_bridge | head -1); sudo docker exec -i $B python /app/importar_leads.py --stdin'];

test('os argumentos do ssh são os de banco.mjs', () => {
  assert.deepEqual(argsImportar('ubuntu@100.83.163.117', false), BANCO_MJS);
  assert.equal(argsImportar('ubuntu@100.83.163.117', true).at(-1), BANCO_MJS.at(-1) + ' --simular');
  const original = 'C:/Users/talle/orca/screener/17-prospeccao/scripts-origem/banco.mjs';
  if (fs.existsSync(original)) {
    const src = fs.readFileSync(original, 'utf8');
    assert.ok(src.includes("'B=$(sudo docker ps -q -f name=integration_bridge | head -1); '"));
    assert.ok(src.includes('sudo docker exec -i $B python /app/importar_leads.py --stdin'));
    assert.ok(src.includes("['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', vm, cmd]"));
  }
});

test('--aplicar: cada etapa manda {"arquivos": {...}} com os nomes que o importar_leads lê', async () => {
  const raiz = novaCampanha();
  const fx = fake();
  await pipelineAteFila(raiz, fx, '--aplicar');
  const importes = fx.chamadas.ssh.filter((c) => /importar_leads/.test(c.args.at(-1)));
  assert.deepEqual(importes.map((c) => Object.keys(c.entrada.arquivos)), [
    ['negocios.json'], ['negocios-enriquecidos.json'], ['instagram-perfis.json', 'negocios-enriquecidos.json'],
    ['negocios-enriquecidos.json'], ['decisores.json', 'negocios-enriquecidos.json'], ['negocios-enriquecidos.json']]);
  for (const c of importes) { assert.equal(c.cmd, 'ssh'); assert.deepEqual(c.args, BANCO_MJS); assert.deepEqual(Object.keys(c.entrada), ['arquivos']); }
  assert.deepEqual(importes[0].entrada.arquivos['negocios.json'], ler(raiz, 'negocios.json'));
  // decisores.json chaveado por telefone, no formato que leads.save_decisor lê
  const dec = importes[4].entrada.arquivos['decisores.json'];
  const um = Object.values(dec).find((d) => d.decisor.nome);
  for (const k of ['nome_negocio', 'cnpj', 'razao_social', 'socios', 'decisor', 'evidencias', 'confianca']) assert.ok(k in um, k);
});

test('--aplicar: a fila vai para prospeccao.enqueue na ordem da lente, e o resultado fica registrado', async () => {
  const raiz = novaCampanha();
  const fx = fake();
  await pipelineAteFila(raiz, fx, '--aplicar');
  const filas = fx.chamadas.ssh.filter((c) => /prospeccao\.enqueue/.test(c.args.at(-1)));
  assert.equal(filas.length, 1);
  assert.equal(filas[0].entrada.modo, 'fila');
  assert.deepEqual(filas[0].entrada.negocios, ler(raiz, 'fila.json').negocios);
  assert.match(filas[0].args.at(-1), /docker exec -i \$B python -c 'import json,sys,prospeccao; p=json\.load\(sys\.stdin\.buffer\)/);
  assert.deepEqual(ler(raiz, 'fila-envio.json').fila, { novos: 9, repetidos: 0, invalidos: 0 });
});

test('--aplicar --atualizar também chama refresh_data para quem já está na fila', async () => {
  const raiz = novaCampanha();
  const fx = fake();
  await pipelineAteFila(raiz, fx);
  await rodar(raiz, fx, 'fila', 'exemplo', '--aplicar', '--atualizar');
  assert.deepEqual(fx.chamadas.ssh.map((c) => c.entrada.modo).filter(Boolean), ['fila', 'atualizar']);
});

test('se a VM não responder, a etapa falha em voz alta', async () => {
  const raiz = novaCampanha();
  const fx = fake();
  fx.deps.spawnSync = () => ({ status: 255, stdout: '', stderr: 'ssh: connect to host: timed out' });
  await assert.rejects(rodar(raiz, fx, 'coletar', 'exemplo', '--aplicar'), /banco central: falhou \(código 255\): ssh: connect/);
});
