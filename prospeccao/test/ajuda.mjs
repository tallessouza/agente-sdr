// Ajudantes dos testes: campanha numa pasta temporária, fake de rede/ssh das fixtures e execução dos comandos.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { executar } from '../prospeccao.mjs';
import { depsFixtures } from '../lib/deps.mjs';

export const RAIZ = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
export const FIXTURES = path.join(RAIZ, 'test', 'fixtures', 'exemplo');
export const CAMPANHA_EXEMPLO = JSON.parse(fs.readFileSync(path.join(RAIZ, 'campanhas', 'exemplo', 'campanha.json'), 'utf8'));

const pastas = [];
// Cria campanhas/<slug>/campanha.json numa pasta temporária (com ajustes) e devolve a raiz.
export function novaCampanha(ajustes = {}, slug = 'exemplo') {
  const raiz = fs.mkdtempSync(path.join(os.tmpdir(), 'prospeccao-teste-'));
  pastas.push(raiz);
  fs.mkdirSync(path.join(raiz, slug));
  const c = { ...CAMPANHA_EXEMPLO, slug, ...ajustes, teto_usd: { ...CAMPANHA_EXEMPLO.teto_usd, ...(ajustes.teto_usd || {}) } };
  fs.writeFileSync(path.join(raiz, slug, 'campanha.json'), JSON.stringify(c, null, 1));
  return raiz;
}
export function limpar() { for (const p of pastas.splice(0)) fs.rmSync(p, { recursive: true, force: true }); }

export function fake(opcoes) { return depsFixtures(FIXTURES, opcoes); }

// Roda um comando com as fixtures; `fx` é o mesmo fake entre comandos (as runs do Apify falso continuam lá).
export async function rodar(raiz, fx, ...argv) {
  const extra = argv.includes('--sem-fixtures') ? [] : ['--fixtures', FIXTURES];
  const args = [...argv.filter((a) => a !== '--sem-fixtures'), '--campanhas', raiz, '--silencioso', ...extra];
  return executar(args, { fixturesProntas: fx, deps: fx?.deps });
}

export const ler = (raiz, rel, slug = 'exemplo') => JSON.parse(fs.readFileSync(path.join(raiz, slug, rel), 'utf8'));
export const existe = (raiz, rel, slug = 'exemplo') => fs.existsSync(path.join(raiz, slug, rel));
export const texto = (raiz, rel, slug = 'exemplo') => fs.readFileSync(path.join(raiz, slug, rel), 'utf8');

export async function pipelineAteFila(raiz, fx, ...extra) {
  await rodar(raiz, fx, 'coletar', 'exemplo', ...extra);
  for (const c of ['site', 'ig-raso', 'ig-fundo', 'decisor']) await rodar(raiz, fx, 'enriquecer', 'exemplo', '--camada', c, ...extra);
  await rodar(raiz, fx, 'qualificar', 'exemplo', ...extra);
  return rodar(raiz, fx, 'fila', 'exemplo', ...extra);
}
