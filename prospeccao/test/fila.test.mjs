// A fila sai na ordem da lente de riqueza (nota desc, depois prioridade), com CNPJ não ativo no fim.
import { test, after, before } from 'node:test';
import assert from 'node:assert/strict';
import { novaCampanha, limpar, fake, rodar, pipelineAteFila, ler } from './ajuda.mjs';
import { FIELDS } from '../lib/dossie.mjs';

after(limpar);
let raiz, fx;
before(async () => { raiz = novaCampanha(); fx = fake(); await pipelineAteFila(raiz, fx); });

test('fila.json segue a ordem da qualificação', () => {
  const q = ler(raiz, 'qualificacao-riqueza.json');
  const fila = ler(raiz, 'fila.json').negocios;
  assert.deepEqual(fila.map((x) => x.telefone_e164), q.map((x) => x.telefone_e164));
  const notas = q.map((x) => x.nota);
  assert.deepEqual(notas, [...notas].sort((a, b) => b - a), 'nota decrescente');
  assert.deepEqual(ler(raiz, 'fila-ordenada-riqueza.json'), q.map((x) => x.telefone_e164));
});

test('quem anuncia e tem porte vem primeiro; CNPJ baixado vai para o fim com o motivo', () => {
  const q = ler(raiz, 'qualificacao-riqueza.json');
  assert.equal(q[0].nome, 'Clínica Sorriso Pleno');
  assert.ok(q[0].motivos.some((m) => /Meta Pixel/.test(m)));
  assert.ok(q[0].motivos.some((m) => /2 unidades/.test(m)));
  const ultimo = q[q.length - 1];
  assert.equal(ultimo.nome, 'Odonto Vida São José');
  assert.equal(ultimo.nota, -1);
  assert.match(ultimo.motivos[0], /CNPJ BAIXADA na Receita: fim da fila/);
});

test('empate de nota desempata pela prioridade da campanha', () => {
  const q = ler(raiz, 'qualificacao-riqueza.json');
  for (let i = 1; i < q.length; i++) if (q[i].nota === q[i - 1].nota) assert.ok(q[i].prioridade > q[i - 1].prioridade, `${q[i - 1].nome} antes de ${q[i].nome}`);
});

test('só entram prováveis WhatsApp enriquecidos, com os campos que a bridge lê', () => {
  const fila = ler(raiz, 'fila.json').negocios;
  assert.equal(fila.length, 9); // 10 únicos com telefone, 1 fixo
  assert.ok(!fila.some((x) => x.nome === 'Dentista Dr. Paulo Mendes'), 'telefone fixo fica fora');
  for (const x of fila) assert.deepEqual(Object.keys(x).sort(), ['telefone_e164', ...FIELDS].sort());
});

test('sem a qualificação, a fila recusa (ou ordena só pela prioridade com --sem-lente)', async () => {
  const r2 = novaCampanha(); const f2 = fake();
  await rodar(r2, f2, 'coletar', 'exemplo');
  await rodar(r2, f2, 'enriquecer', 'exemplo', '--camada', 'site');
  await assert.rejects(rodar(r2, f2, 'fila', 'exemplo'), /falta fila-ordenada-riqueza\.json/);
  await rodar(r2, f2, 'fila', 'exemplo', '--sem-lente');
  const ent = ler(r2, 'enriquecidos.json');
  const prio = new Map(ent.map((n) => [n.telefone_e164, n.prioridade]));
  const ps = ler(r2, 'fila.json').negocios.map((x) => prio.get(x.telefone_e164));
  assert.deepEqual(ps, [...ps].sort((a, b) => a - b));
});
