// Banco central (bridge.db na VM1) e fila de produção, pelo mesmo caminho de scripts-origem/banco.mjs:
// ssh na VM1 -> docker exec na bridge -> importar_leads.py --stdin, com {"arquivos": {...}} na entrada padrão (UTF-8).
// Só com --aplicar. Sem ele (simulação) nada sai da máquina: o que iria fica em banco-simulado/<etapa>.json para conferir.
import { gravarJson, logar } from './campanha.mjs';

export const VM_PADRAO = 'ubuntu@100.83.163.117';
const BRIDGE = 'B=$(sudo docker ps -q -f name=integration_bridge | head -1); ';

// Mesmos argumentos e comando de banco.mjs (o teste confere isso).
export function argsImportar(vm, simularNoBanco) {
  const cmd = BRIDGE + `sudo docker exec -i $B python /app/importar_leads.py --stdin${simularNoBanco ? ' --simular' : ''}`;
  return ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', vm, cmd];
}

function ssh(ctx, args, entrada, oQue) {
  const r = ctx.deps.spawnSync('ssh', args, { input: entrada, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, timeout: 10 * 60 * 1000 });
  const saida = String(r.stdout || '');
  if (r.status !== 0 || !saida.includes('{')) throw new Error(`${oQue}: falhou (código ${r.status}): ${String(r.stderr || saida).slice(0, 500)}`);
  return JSON.parse(saida.slice(saida.indexOf('{')));
}

export function gravarNoBanco(ctx, etapa, arquivos) {
  const nomes = Object.keys(arquivos).join(', ');
  if (!ctx.aplicar) {
    gravarJson(ctx, `banco-simulado/${etapa}.json`, { arquivos });
    logar(ctx, etapa, `banco central (simulação): ${nomes} NÃO enviado(s); prévia em banco-simulado/${etapa}.json. Rode com --aplicar para gravar.`);
    return { simulado: true };
  }
  const simularNoBanco = process.env.BANCO_SIMULAR === '1';
  const rel = ssh(ctx, argsImportar(ctx.vm, simularNoBanco), JSON.stringify({ arquivos }), 'banco central');
  const alterados = Object.values(rel.por_destino || {}).reduce((s, v) => s + (v.alterados || 0), 0);
  logar(ctx, etapa, `banco central: ${nomes} gravado(s)${simularNoBanco ? ' (BANCO_SIMULAR=1: rollback no fim)' : ''}; ${alterados} linha(s) alterada(s)`);
  return rel;
}

// prospeccao.enqueue / refresh_data dentro da bridge. A entrada vai como bytes UTF-8 (json.load de sys.stdin.buffer).
const PY_FILA = 'import json,sys,prospeccao; p=json.load(sys.stdin.buffer); '
  + 'r=prospeccao.enqueue(p["negocios"]) if p.get("modo")=="fila" else {"atualizados": prospeccao.refresh_data(p["negocios"])}; '
  + 'print(json.dumps(r, ensure_ascii=False))';
export function argsFila(vm) {
  return ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', vm, BRIDGE + `sudo docker exec -i $B python -c '${PY_FILA}'`];
}

export function enviarFila(ctx, itens, modo = 'fila') {
  if (!ctx.aplicar) throw new Error('enviarFila sem --aplicar');
  const r = ssh(ctx, argsFila(ctx.vm), JSON.stringify({ modo, negocios: itens }), `fila (${modo})`);
  logar(ctx, 'fila', `produção: ${modo === 'fila' ? 'prospeccao.enqueue' : 'prospeccao.refresh_data'} -> ${JSON.stringify(r)}`);
  return r;
}
