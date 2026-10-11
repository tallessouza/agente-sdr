// Simulação (o padrão): sem --aplicar nada é gasto e nada vai para o banco central ou para a fila de produção.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { executar } from '../prospeccao.mjs';
import { novaCampanha, limpar, fake, pipelineAteFila, existe, ler, texto } from './ajuda.mjs';

after(limpar);

// Dependências que explodem se alguém tentar gastar ou gravar na produção.
function depsQueNaoPodemSerUsadas() {
  const tentativas = [];
  return {
    tentativas,
    deps: {
      fetch: async (url) => { tentativas.push(String(url)); throw new Error('rede não deveria ser usada: ' + url); },
      spawnSync: (cmd, args) => { tentativas.push(`${cmd} ${args.join(' ')}`); throw new Error('ssh não deveria ser usado'); },
      sleep: async () => {},
      tokenApify: () => { tentativas.push('cofre apify'); throw new Error('cofre não deveria ser lido'); },
      tokenMeta: () => { tentativas.push('cofre meta'); throw new Error('cofre não deveria ser lido'); },
    },
  };
}

test('coletar sem --aplicar e sem fixtures: só a estimativa, nenhuma chamada ao Apify nem ao cofre', async () => {
  const raiz = novaCampanha();
  const d = depsQueNaoPodemSerUsadas();
  const { resultado } = await executar(['coletar', 'exemplo', '--campanhas', raiz, '--silencioso'], { deps: d.deps });
  assert.equal(resultado.simulado, true);
  assert.deepEqual(d.tentativas, []);
  assert.equal(existe(raiz, 'negocios.json'), false);
  assert.equal(existe(raiz, 'custos.json'), false);
  assert.match(texto(raiz, 'coleta.log'), /simulação: Apify NÃO chamado; nada gasto/);
  assert.match(texto(raiz, 'coleta.log'), /estimativa .*US\$ 0\.1256/);
});

test('pipeline inteiro em simulação: nenhum ssh, prévia do que iria ao banco no formato do importar_leads', async () => {
  const raiz = novaCampanha();
  const fx = fake();
  await pipelineAteFila(raiz, fx);
  assert.deepEqual(fx.chamadas.ssh, [], 'nada foi enviado à VM1');
  const previa = ler(raiz, 'banco-simulado/coleta.json');
  assert.deepEqual(Object.keys(previa), ['arquivos']);
  assert.deepEqual(previa.arquivos['negocios.json'], ler(raiz, 'negocios.json'));
  for (const etapa of ['enriquecer-site', 'enriquecer-ig-raso', 'enriquecer-ig-fundo', 'enriquecer-decisor', 'qualificar']) assert.ok(existe(raiz, `banco-simulado/${etapa}.json`), etapa);
  assert.equal(existe(raiz, 'fila-envio.json'), false);
  assert.match(texto(raiz, 'fila.log'), /simulação: nada enfileirado na produção/);
  assert.equal(ler(raiz, 'estado.json').fila.modo, 'simulacao');
});

test('--aplicar e --simular juntos são recusados', async () => {
  const raiz = novaCampanha();
  await assert.rejects(executar(['coletar', 'exemplo', '--campanhas', raiz, '--aplicar', '--simular', '--silencioso'], { deps: depsQueNaoPodemSerUsadas().deps }), /não os dois/);
});
