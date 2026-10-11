// Montagem do dossiê: ordem das linhas, idempotência, item da fila com os FIELDS da bridge, dias abertos, anonimização.
import { test, after, before } from 'node:test';
import assert from 'node:assert/strict';
import { montarDossie, filaItem, linhaDecisor, FIELDS, poeLinha } from '../lib/dossie.mjs';
import { diasAbertos } from '../lib/enriquecer.mjs';
import { anonimizar, protegidos } from '../lib/nomes.mjs';
import { validar } from '../lib/campanha.mjs';
import { novaCampanha, limpar, fake, pipelineAteFila, ler } from './ajuda.mjs';

after(limpar);

test('dossiê junta as camadas na ordem fixa e não duplica ao remontar', () => {
  const n = { dossie_base: 'Clínica em Centro, X/SC.\nHorário no Google: seg a sex 8h–18h.', decisor: 'Decisor: Dra. Ana (dono; confiança alta).',
    instagram_resumo: 'Instagram (@x): 10 seguidores.', sinais_investimento: 'Sinais de investimento (lente, nota 3): nenhum.', instagram_comentarios: 'Comentários nos posts recentes: nenhuma.' };
  const d = montarDossie(n);
  assert.deepEqual(d.split('\n').map((l) => l.split(/[ :(]/)[0]), ['Clínica', 'Horário', 'Instagram', 'Comentários', 'Decisor', 'Sinais']);
  assert.equal(montarDossie({ ...n, dossie: d }), d, 'idempotente');
  assert.equal(montarDossie({ ...n, decisor: null }).includes('Decisor'), false, 'linha sai quando a camada some');
  assert.equal(poeLinha('a\nDecisor: x', /^Decisor:/, 'Decisor: y'), 'a\nDecisor: y');
});

test('item da fila tem exatamente telefone + FIELDS de leads.py, vazios como null', () => {
  const it = filaItem({ telefone_e164: '5548999990001', nome: 'X', dossie: 'd', extra: 'não vai', placeId: 'p' });
  assert.deepEqual(Object.keys(it), ['telefone_e164', ...FIELDS]);
  assert.equal(it.extra, undefined);
  assert.equal(it.bairro, null);
});

test('linha do decisor no formato de 09/10', () => {
  assert.equal(linhaDecisor({ decisor: { nome: 'Sâmea Rebelo', como_chamar: 'Dra. Sâmea', papel: 'dono' }, confianca: 'alta' }), 'Decisor: Dra. Sâmea (dono; confiança alta).');
  assert.equal(linhaDecisor({ decisor: {} }), null);
});

test('dias abertos: 0 = segunda ... 6 = domingo, sem horário = null', () => {
  const oh = [['segunda-feira', 'Fechado'], ['terça-feira', '08:00 to 18:00'], ['quarta-feira', '08:00 to 18:00'], ['quinta-feira', '08:00 to 18:00'], ['sexta-feira', '08:00 to 18:00'], ['sábado', '08:00 to 12:00'], ['domingo', 'Fechado']].map(([day, hours]) => ({ day, hours }));
  assert.deepEqual(diasAbertos(oh), [1, 2, 3, 4, 5]);
  assert.equal(diasAbertos([]), null);
});

test('sem nome de cliente vindo de legenda; nome de profissional (Dr./Dra.) e do próprio negócio fica', () => {
  const o = { saude: true, proprio: 'sorrisopleno', prot: protegidos('Clínica Sorriso Pleno') };
  assert.equal(anonimizar('Depoimento da Juliana sobre o implante.', o), 'Depoimento de uma paciente sobre o implante.');
  assert.equal(anonimizar('Equipe e Marcos Silva no evento', o), 'Equipe e um paciente no evento');
  assert.equal(anonimizar('Dra Juliana Souza atende hoje', o), 'Dra Juliana Souza atende hoje');
  assert.equal(anonimizar('Parabéns, Fernanda! @amiga.dela', o), 'Parabéns, uma paciente! (perfil marcado)');
});

test('campanha.json inválido é recusado com o motivo', () => {
  assert.throws(() => validar({ slug: 'x', cidades: [{ nome: 'A', uf: 'sc' }], nichos: [], por_busca: 0, teto_usd: {} }, 'x'), /cidades.*nichos.*por_busca/);
});

describeDossieReal();
function describeDossieReal() {
  let raiz;
  before(async () => { raiz = novaCampanha(); await pipelineAteFila(raiz, fake()); });
  test('dossiê do pipeline: todas as camadas no primeiro da fila, e nada de nome de cliente', () => {
    const [x] = ler(raiz, 'fila.json').negocios;
    assert.equal(x.nome, 'Clínica Sorriso Pleno');
    for (const re of [/^Clínica odontológica em Kobrasol, São José\/SC\. Nota 4,9 com 320/m, /^Horário no Google:/m, /^Site sorrisopleno\.com\.br/m, /^Instagram \(@sorrisopleno\)/m,
      /^Posts que mais engajaram/m, /^Comentários nos posts recentes: 2 perguntas/m, /^Decisor: Dra\. Marina \(sócio; confiança alta\)\./m, /^Sinais de investimento \(lente, nota 14\)/m]) assert.match(x.dossie, re);
    assert.doesNotMatch(x.dossie, /Juliana/);
    assert.deepEqual(x.dias_abertos, [0, 1, 2, 3, 4, 5]);
    const dec = ler(raiz, 'decisores.json')[x.telefone_e164];
    assert.equal(dec.decisor.contato_direto, 'email: marina.duarte@sorrisopleno.com.br', 'contato que ela mesma publica');
  });
}
