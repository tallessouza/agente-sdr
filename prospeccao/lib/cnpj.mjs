// Consulta de CNPJ com cache por campanha (cache/cnpj/<cnpj>.json), usada pelo decisor e pela lente.
// BrasilAPI primeiro; minhareceita.org (mesmos dados abertos da Receita, mesmo formato) quando a BrasilAPI recusa ou falha
// (de scripts/qualificar-riqueza.mjs). Uma consulta a cada 3 s (de decisores/cnpj.mjs). Os campos juntam o que os dois
// scripts guardavam: o decisor lê sócios e município; a lente lê capital, porte, matriz e situação.
import fs from 'node:fs';
import { caminho } from './campanha.mjs';

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36';
const FONTES = [(c) => `https://brasilapi.com.br/api/cnpj/v1/${c}`, (c) => `https://minhareceita.org/${c}`];
const INTERVALO = 3000;

export function lerCnpjCache(ctx, c) {
  const f = caminho(ctx, 'cache', 'cnpj', `${c}.json`);
  return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : null;
}

export async function consultarCnpj(ctx, c) {
  c = String(c).replace(/\D/g, '');
  const em = lerCnpjCache(ctx, c);
  if (em) return em;
  let res = { cnpj: c, ok: false, erro: 'falhou 4 vezes (BrasilAPI e minhareceita)' };
  for (let t = 0; t < 4; t++) {
    const espera = INTERVALO - (Date.now() - (ctx._ultimoCnpj || 0));
    if (espera > 0) await ctx.deps.sleep(espera);
    ctx._ultimoCnpj = Date.now();
    try {
      const r = await ctx.deps.fetch(FONTES[t % 2](c), { headers: { 'user-agent': UA, accept: 'application/json' } });
      if (r.status === 404) { res = { cnpj: c, ok: false, status: 404, erro: 'CNPJ não encontrado' }; break; }
      if (r.status === 403 || r.status === 429 || r.status >= 500) { await ctx.deps.sleep(3000 * (t + 1)); continue; }
      const j = await r.json();
      res = {
        ok: true, cnpj: c, razao_social: j.razao_social, nome_fantasia: j.nome_fantasia, porte: j.porte || j.descricao_porte,
        abertura: j.data_inicio_atividade, capital_social: Number(j.capital_social ?? NaN), situacao: j.descricao_situacao_cadastral,
        matriz: j.identificador_matriz_filial === 1 ? 'matriz' : j.identificador_matriz_filial === 2 ? 'filial' : null,
        municipio: j.municipio, uf: j.uf, cnae: j.cnae_fiscal_descricao, natureza: j.natureza_juridica,
        socios: (j.qsa || []).map((s) => ({ nome: s.nome_socio, qualificacao: s.qualificacao_socio })),
      };
      break;
    } catch { await ctx.deps.sleep(3000); }
  }
  const f = caminho(ctx, 'cache', 'cnpj', `${c}.json`);
  fs.mkdirSync(caminho(ctx, 'cache', 'cnpj'), { recursive: true });
  fs.writeFileSync(f, JSON.stringify(res));
  return res;
}
