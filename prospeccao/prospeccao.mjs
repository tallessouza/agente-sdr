#!/usr/bin/env node
// Pipeline da prospecção. Uma campanha = campanhas/<slug>/campanha.json; cada comando grava em campanhas/<slug>/.
//
//   node prospeccao.mjs coletar <slug>                         Google Maps pelo Apify (teste de 5 lugares antes)
//   node prospeccao.mjs enriquecer <slug> --camada site|ig-raso|ig-fundo|decisor
//   node prospeccao.mjs qualificar <slug>                      lente "tem dinheiro e investe em marketing"
//   node prospeccao.mjs fila <slug> [--atualizar] [--sem-lente] monta o dossiê, ordena pela lente e enfileira
//   node prospeccao.mjs custo <slug> [--conferir]              gasto por etapa (conferido na API do Apify)
//   node prospeccao.mjs status <slug>                          o que já foi feito e o próximo passo
//
// Opções: --aplicar (gasta no Apify e grava no banco central/fila de produção; sem ela, só simula),
//         --fixtures <dir> (rede e ssh falsos, para testar sem custo), --campanhas <dir> (raiz das campanhas).
// Saída: 0 ok; 1 erro; 2 teto de custo abortou a etapa (nada foi gasto).
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { carregarCampanha, ErroCampanha } from './lib/campanha.mjs';
import { TetoExcedido } from './lib/custos.mjs';
import { depsReais, depsFixtures } from './lib/deps.mjs';
import { VM_PADRAO } from './lib/banco.mjs';
import * as C from './lib/comandos.mjs';

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const COMANDOS = ['coletar', 'enriquecer', 'qualificar', 'fila', 'custo', 'status'];

export function lerArgs(argv) {
  const a = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const x = argv[i];
    if (!x.startsWith('--')) { a._.push(x); continue; }
    const [k, v] = x.slice(2).split('=');
    if (['camada', 'fixtures', 'campanhas', 'vm'].includes(k)) a[k] = v ?? argv[++i];
    else a[k] = true;
  }
  return a;
}

export function criarContexto(args, { deps, chamadas, agora, opcoesFixtures, fixturesProntas } = {}) {
  const raiz = path.resolve(args.campanhas || process.env.PROSPECCAO_CAMPANHAS || path.join(AQUI, 'campanhas'));
  const { dir, campanha } = carregarCampanha(raiz, args._[1]);
  let manifesto = {};
  if (fixturesProntas) ({ deps, chamadas, manifesto } = fixturesProntas); // os testes reaproveitam o mesmo fake entre comandos
  else if (!deps && args.fixtures) ({ deps, chamadas, manifesto } = depsFixtures(path.resolve(args.fixtures), opcoesFixtures));
  if (args.aplicar && args.simular) throw new ErroCampanha('use --aplicar ou --simular, não os dois');
  const agoraFn = agora || (() => Date.now());
  return {
    dir, campanha, deps: deps || depsReais(), chamadas,
    aplicar: !!args.aplicar, fixtures: args.fixtures || null,
    vm: args.vm || process.env.VM || VM_PADRAO,
    agora: agoraFn,
    hoje: process.env.PROSPECCAO_HOJE || manifesto.hoje || new Date(agoraFn()).toISOString().slice(0, 10),
    silencioso: !!args.silencioso,
  };
}

export async function executar(argv, injetar = {}) {
  const args = lerArgs(argv);
  const cmd = args._[0];
  if (!COMANDOS.includes(cmd) || !args._[1]) throw new ErroCampanha(`uso: prospeccao <${COMANDOS.join('|')}> <slug> [--camada X] [--aplicar] [--fixtures DIR]`);
  const ctx = criarContexto(args, injetar);
  if (!ctx.silencioso) console.log(`== ${cmd} ${ctx.campanha.slug} | ${ctx.aplicar ? 'APLICAR (gasta e grava na produção)' : 'simulação'}${ctx.fixtures ? ' | fixtures' : ''}`);
  const resultado = await (async () => {
    switch (cmd) {
      case 'coletar': return C.coletar(ctx);
      case 'enriquecer': if (!args.camada) throw new ErroCampanha('enriquecer precisa de --camada site|ig-raso|ig-fundo|decisor'); return C.enriquecer(ctx, args.camada);
      case 'qualificar': return C.qualificar(ctx);
      case 'fila': return C.fila(ctx, { atualizar: !!args.atualizar, semLente: !!args['sem-lente'] });
      case 'custo': return C.custo(ctx, { conferir: !!args.conferir });
      case 'status': return C.status(ctx);
    }
  })();
  return { ctx, resultado };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  executar(process.argv.slice(2)).then(() => process.exit(0), (e) => {
    if (e instanceof TetoExcedido) { console.error(`TETO: ${e.message}`); process.exit(2); }
    if (e instanceof ErroCampanha || e instanceof C.ErroEtapa) { console.error(e.message); process.exit(1); }
    console.error(e?.stack || e); process.exit(1);
  });
}
