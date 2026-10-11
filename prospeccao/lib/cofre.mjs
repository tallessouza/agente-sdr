// Credenciais só do cofre (Vaultwarden em vault.talles.dev, organização TSX, collection Recovery), lidas direto para a
// memória do processo. Nunca vão para arquivo, log ou saída. `sessao.sh` destranca sozinho (senha via DPAPI).
import { execFileSync } from 'node:child_process';

export const ITENS = {
  meta: 'Meta · ads TSX · token sistema',
  // Pool "Apify · screener · pool" (contas FREE). Os ids são os mesmos de ig-lista/pool.mjs; id não é segredo.
  apify: {
    'concept.advice': '20023f45-8276-423a-92f3-7ff98a19adc4',
    'zeique-zgc': 'd76e44a6-623e-4bc6-b49b-8fe3773ce9ad',
    marbly_antlion: '6e33901c-e836-44e3-87b0-17f46f5cf67c',
    formful_buffet: '05cc021b-5f82-4f4b-bb20-4ef8fc91f9c5',
    igorpena: '1ceec6c1-9d9a-43de-8e3f-9d02ab4083b8',
    educacaobilhon: '4f0f69e3-2c86-49ca-89f5-980ba24f6177',
  },
};
// Ordem de uso do pool: a mesma de ig-lista/apify1.mjs e camada2.mjs (educacaobilhon fica de fora, como lá).
export const ORDEM_POOL = ['concept.advice', 'zeique-zgc', 'marbly_antlion', 'formful_buffet', 'igorpena'];

const cache = new Map();
export function segredo(item) {
  if (cache.has(item)) return cache.get(item);
  const v = execFileSync('bash', ['-c', 'source ~/.bw/sessao.sh >/dev/null 2>&1; bw get password "$ITEM_COFRE"'],
    { encoding: 'utf8', env: { ...process.env, ITEM_COFRE: item }, stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  if (!v) throw new Error(`cofre: item "${item}" sem senha visível (destrancou? permissão de ver senha?)`);
  cache.set(item, v);
  return v;
}
