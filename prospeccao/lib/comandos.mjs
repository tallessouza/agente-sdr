// Os comandos do pipeline. Cada um lê campanhas/<slug>/campanha.json, grava em campanhas/<slug>/, retoma pelo cache
// (o que já foi feito não é refeito nem pago de novo), registra o custo de cada run e respeita o teto antes de gastar.
//
// Modos:
//   simulação (padrão): o Apify não é chamado (só a estimativa), o banco central e a fila não são tocados.
//     Leituras grátis (sites, Meta Business Discovery, BrasilAPI) rodam de verdade.
//   --aplicar: Apify de verdade (com teto) e gravação no banco central / fila de produção.
//   --fixtures DIR: tudo o que iria à rede (Apify, Meta, sites, BrasilAPI, ssh) vem das fixtures. Sem custo real.
import fs from 'node:fs';
import { caminho, existe, lerJson, gravarJson, logar, ordenarPrioridade, quantos, slugTexto } from './campanha.mjs';
import { PRECOS, garantirTeto, registrarRun, restante, lerCustos, ETAPAS_PAGAS, teto } from './custos.mjs';
import { escolherConta, rodar, lerRun } from './apify.mjs';
import { gravarNoBanco, enviarFila } from './banco.mjs';
import { ATOR_MAPS, inputColeta, processar } from './maps.mjs';
import { lerSite, tipoSite } from './site.mjs';
import { montarSite } from './enriquecer.mjs';
import * as IG from './instagram.mjs';
import * as DEC from './decisor.mjs';
import { consultarCnpj, lerCnpjCache } from './cnpj.mjs';
import { qualificar as notaLente, linhaLente, cnpjDoNegocio, SOCIAL } from './riqueza.mjs';
import { montarDossie, filaItem, linhaDecisor } from './dossie.mjs';

const usaApify = (ctx) => ctx.aplicar || !!ctx.fixtures;
const aleatorio = (a, b) => a + Math.random() * (b - a);

class ErroEtapa extends Error {}
export { ErroEtapa };

function exigir(ctx, rel, comando) {
  if (!existe(ctx, rel)) throw new ErroEtapa(`falta ${rel}: rode antes \`prospeccao ${comando} ${ctx.campanha.slug}\``);
  return lerJson(ctx, rel);
}

function marcarEstado(ctx, etapa, resumo) {
  const e = lerJson(ctx, 'estado.json', {});
  e[etapa] = { quando: new Date(ctx.agora()).toISOString(), modo: ctx.aplicar ? 'aplicar' : 'simulacao', fixtures: !!ctx.fixtures, ...resumo };
  gravarJson(ctx, 'estado.json', e);
}

// Run do Apify que sobrevive a queda: a run fica em cache/runs-pendentes.json enquanto roda; na volta, retoma a mesma run.
async function rodarRetomavel(ctx, etapa, chave, conta, ator, input, tetoRun) {
  const pend = lerJson(ctx, 'cache/runs-pendentes.json', {});
  let runId;
  if (pend[chave]) { ({ conta, runId } = pend[chave]); logar(ctx, etapa, `retomando run ${runId} (${chave}) iniciada antes`); }
  const r = await rodar(ctx, conta, ator, input, tetoRun, {
    runId,
    aoIniciar: (id) => { pend[chave] = { conta, runId: id, ator, quando: new Date(ctx.agora()).toISOString() }; gravarJson(ctx, 'cache/runs-pendentes.json', pend); logar(ctx, etapa, `run ${id} iniciada (${chave}, conta ${conta}, teto da run US$ ${tetoRun.toFixed(3)})`); },
  });
  delete pend[chave]; gravarJson(ctx, 'cache/runs-pendentes.json', pend);
  registrarRun(ctx, etapa, { chave, conta, runId: r.runId, ator, itens: r.items.length, status: r.status, custo_usd: r.custo, eventos: r.eventos });
  return r;
}

async function contaPara(ctx, etapa, estimativa) {
  const c = await escolherConta(ctx, estimativa);
  if (!c) logar(ctx, etapa, `pool "Apify · screener · pool" sem saldo para US$ ${estimativa.toFixed(4)}: parei aqui (crédito novo precisa do OK do Talles)`);
  return c;
}

// ---------------------------------------------------------------- coletar
const rawRel = (c) => `raw/${slugTexto(c.nome)}-${c.uf.toLowerCase()}.json`;

export async function coletar(ctx) {
  const E = 'coleta', { campanha } = ctx;
  const pendentes = campanha.cidades.filter((c) => !existe(ctx, rawRel(c)));
  const testeFeito = existe(ctx, 'raw/teste-5.json');
  const lugaresCidade = campanha.nichos.length * campanha.por_busca;
  const estCidade = lugaresCidade * PRECOS.maps_lugar + PRECOS.maps_inicio;
  const estTeste = testeFeito ? 0 : 5 * PRECOS.maps_lugar + PRECOS.maps_inicio;
  logar(ctx, E, `plano: ${campanha.cidades.length} cidade(s) x ${campanha.nichos.length} nicho(s) x ${campanha.por_busca} por busca; já coletadas ${campanha.cidades.length - pendentes.length}; teste de 5 ${testeFeito ? 'feito' : 'pendente'}`);
  let simulado = false;
  if (pendentes.length) {
    garantirTeto(ctx, E, estTeste + pendentes.length * estCidade, `${pendentes.length} cidade(s) a coletar${testeFeito ? '' : ' + teste de 5 lugares'}`);
    if (!usaApify(ctx)) {
      simulado = true;
      logar(ctx, E, `simulação: Apify NÃO chamado; nada gasto. Iria rodar ${ATOR_MAPS} em: ${pendentes.map((c) => `${c.nome}/${c.uf}`).join(', ')}. Rode com --aplicar para coletar.`);
    } else {
      if (!testeFeito) {
        const [c0] = campanha.cidades;
        const conta = await contaPara(ctx, E, estTeste);
        if (!conta) return { parou: 'pool sem saldo' };
        const r = await rodarRetomavel(ctx, E, 'coleta:teste-5', conta.conta, ATOR_MAPS, inputColeta(c0.nome, c0.uf, [campanha.nichos[0]], 5), Math.min(restante(ctx, E), conta.livre - 0.01));
        if (!r.items.length) throw new ErroEtapa(`teste de 5 lugares voltou vazio (run ${r.runId}, ${r.status}): confira cidade e nicho antes de gastar o resto`);
        gravarJson(ctx, 'raw/teste-5.json', { cidade: c0.nome, uf: c0.uf, nichos: [campanha.nichos[0]], runId: r.runId, items: r.items });
        logar(ctx, E, `teste de 5 ok: ${r.items.length} lugares, ${r.items.filter((i) => i.phone || i.phoneUnformatted).length} com telefone`);
      }
      for (const c of pendentes) {
        const conta = await contaPara(ctx, E, estCidade);
        if (!conta) return { parou: 'pool sem saldo' };
        const r = await rodarRetomavel(ctx, E, `coleta:${slugTexto(c.nome)}-${c.uf}`, conta.conta, ATOR_MAPS, inputColeta(c.nome, c.uf, campanha.nichos, campanha.por_busca), Math.min(restante(ctx, E), conta.livre - 0.01));
        if (!r.items.length) { logar(ctx, E, `${c.nome}/${c.uf}: run ${r.status} sem itens; fica pendente para a próxima rodada`); continue; }
        gravarJson(ctx, rawRel(c), { cidade: c.nome, uf: c.uf, nichos: campanha.nichos, runId: r.runId, status: r.status, items: r.items });
        logar(ctx, E, `${c.nome}/${c.uf}: ${r.items.length} lugares`);
      }
    }
  }
  const brutos = campanha.cidades.filter((c) => existe(ctx, rawRel(c))).map((c) => lerJson(ctx, rawRel(c)));
  if (!brutos.length) { marcarEstado(ctx, E, { simulado, negocios: 0 }); return { simulado, negocios: 0 }; }
  const { negocios, contagem } = processar(brutos);
  gravarJson(ctx, 'negocios.json', negocios);
  logar(ctx, E, `negocios.json: ${JSON.stringify(contagem)}`);
  gravarNoBanco(ctx, E, { 'negocios.json': negocios });
  marcarEstado(ctx, E, { simulado, cidades_coletadas: brutos.length, ...contagem });
  return { simulado, negocios: negocios.length, contagem };
}

// ---------------------------------------------------------------- enriquecer
export async function enriquecer(ctx, camada) {
  const f = { site: camadaSite, 'ig-raso': camadaIgRaso, 'ig-fundo': camadaIgFundo, decisor: camadaDecisor }[camada];
  if (!f) throw new ErroEtapa(`camada desconhecida: "${camada}" (use site, ig-raso, ig-fundo ou decisor)`);
  const chave = { site: 'site', 'ig-raso': 'instagram_raso', 'ig-fundo': 'instagram_fundo', decisor: 'decisor' }[camada];
  if (ctx.campanha.camadas[chave] === false) { logar(ctx, `enriquecer-${camada}`, `camada desligada no campanha.json (camadas.${chave} = false)`); return { desligada: true }; }
  return f(ctx, ctx.campanha.camadas[chave]);
}

function brutosPorPlace(ctx) {
  const m = new Map();
  for (const c of ctx.campanha.cidades) {
    if (!existe(ctx, rawRel(c))) continue;
    for (const it of lerJson(ctx, rawRel(c)).items || []) if (it.placeId && !m.has(it.placeId)) m.set(it.placeId, it);
  }
  return m;
}

async function camadaSite(ctx, spec) {
  const E = 'enriquecer-site';
  const negocios = exigir(ctx, 'negocios.json', 'coletar');
  const prior = ordenarPrioridade(negocios, ctx.campanha);
  const N = quantos(spec, prior.length);
  const fila = prior.slice(0, N).filter((x) => tipoSite(x.site) === 'site');
  let lidos = 0, erros = 0, doCache = 0;
  for (const n of fila) {
    const rel = `cache/sites/${n.placeId || n.telefone_e164}.json`;
    if (existe(ctx, rel)) { doCache++; continue; }
    const out = await lerSite(ctx, n);
    gravarJson(ctx, rel, out);
    lidos++; if (!out.ok) erros++;
    logar(ctx, E, `${lidos}/${fila.length - doCache} ${out.ok ? 'ok ' : 'ERR'} ${n.cidade} | ${String(n.nome).slice(0, 40)} | ${out.ok ? out.servicos.join(', ').slice(0, 60) : out.erro}`);
    await ctx.deps.sleep(aleatorio(1000, 2000));
  }
  const anteriores = new Map((lerJson(ctx, 'enriquecidos.json', []) || []).map((x) => [x.telefone_e164, x]));
  const { saida, stats } = montarSite({ negocios, brutos: brutosPorPlace(ctx), cacheSite: (pid) => lerJson(ctx, `cache/sites/${pid}.json`, null), prioridade: prior, n: N, anteriores });
  gravarJson(ctx, 'enriquecidos.json', saida);
  logar(ctx, E, `sites: ${fila.length} próprios no recorte (${doCache} do cache, ${lidos} lidos agora, ${erros} com erro); custo US$ 0 (grátis); ${JSON.stringify(stats)}`);
  gravarNoBanco(ctx, E, { 'negocios-enriquecidos.json': saida });
  marcarEstado(ctx, E, { recorte: N, ...stats });
  return { stats };
}

function listaIg(ent) { return ent.filter((x) => x.provavel_whatsapp === true && x.instagram && x.enriquecido).sort((a, b) => a.prioridade - b.prioridade); }

async function camadaIgRaso(ctx, spec) {
  const E = 'enriquecer-ig-raso', ETAPA = 'instagram_raso';
  const ent = exigir(ctx, 'enriquecidos.json', 'enriquecer --camada site');
  const L = listaIg(ent);
  const porU = new Map(); for (const n of L) { const u = IG.uname(n.instagram); if (!porU.has(u)) porU.set(u, n); }
  const users = [...porU.keys()].slice(0, quantos(spec, porU.size));
  const meta = lerJson(ctx, 'cache/instagram-meta.json', {}), apify = lerJson(ctx, 'cache/instagram-apify.json', {});
  ctx.logIg = (s) => logar(ctx, E, s);
  // 1. Meta Business Discovery (grátis), uma chamada a cada 5 a 8 s
  const faltaMeta = users.filter((u) => !meta[u]);
  logar(ctx, E, `${users.length} perfis no recorte; ${users.length - faltaMeta.length} já na Meta (cache); ${faltaMeta.length} a consultar (grátis)`);
  for (const u of faltaMeta) {
    meta[u] = await IG.businessDiscovery(ctx, u);
    gravarJson(ctx, 'cache/instagram-meta.json', meta);
    logar(ctx, E, `meta ${u} ${meta[u].ok ? 'ok' : meta[u].erro}`);
    await ctx.deps.sleep(aleatorio(5000, 8000));
  }
  // 2. Apify para quem a Meta não devolve (conta pessoal, por exemplo), com teto
  const falhas = users.filter((u) => !meta[u]?.ok && !apify[u]);
  let parou = null;
  if (falhas.length) {
    const est = falhas.length * PRECOS.ig_perfil;
    garantirTeto(ctx, ETAPA, est, `${falhas.length} perfil(is) pelo ${IG.ATOR_PERFIL}`);
    if (!usaApify(ctx)) logar(ctx, E, `simulação: ${falhas.length} perfil(is) iriam ao Apify (US$ ${est.toFixed(4)}); nada gasto. Rode com --aplicar.`);
    else {
      const fila = [...falhas];
      while (fila.length) {
        const lote = fila.splice(0, 50);
        const estLote = lote.length * PRECOS.ig_perfil;
        const conta = await contaPara(ctx, ETAPA, estLote);
        if (!conta) { parou = 'pool sem saldo'; break; }
        const r = await rodarRetomavel(ctx, ETAPA, `ig-raso:${lote[0]}`, conta.conta, IG.ATOR_PERFIL, { usernames: lote, includeAboutSection: false }, Math.min(restante(ctx, ETAPA), conta.livre - 0.01));
        const vistos = new Set();
        for (const it of r.items) { const u = String(it.username || it.inputUrl || '').toLowerCase(); if (!lote.includes(u)) continue; vistos.add(u); apify[u] = IG.perfilApify(it); }
        for (const u of lote) if (!vistos.has(u)) apify[u] = { ok: false, erro: `apify: perfil não retornado (run ${r.status})` };
        gravarJson(ctx, 'cache/instagram-apify.json', apify);
      }
    }
  }
  // 3. perfis, resumo e engajamento no dossiê (de build1.mjs)
  const perfis = {};
  for (const u of users) {
    const n = porU.get(u);
    if (meta[u]?.ok) perfis[u] = IG.normalizar(u, 'meta', meta[u].data, n);
    else if (apify[u]?.ok) perfis[u] = IG.normalizar(u, 'apify', apify[u].data, n);
    else perfis[u] = { username: u, fonte: 'falhou', erro: [meta[u]?.erro && ('meta: ' + meta[u].erro), apify[u]?.erro && ('apify: ' + apify[u].erro)].filter(Boolean).join(' | ') || 'não consultado' };
  }
  let comResumo = 0;
  for (const n of ent) {
    if (!(n.provavel_whatsapp === true && n.instagram)) continue;
    const p = perfis[IG.uname(n.instagram)]; if (!p) continue;
    if (p.fonte === 'falhou') { n.instagram_resumo = null; n.instagram_engajamento = null; }
    else { n.instagram_resumo = IG.resumo(p); n.instagram_engajamento = IG.engajamento(p, ctx.hoje); comResumo++; }
    n.dossie = montarDossie(n);
  }
  gravarJson(ctx, 'instagram-perfis.json', perfis);
  gravarJson(ctx, 'enriquecidos.json', ent);
  const cont = { meta: 0, apify: 0, falhou: 0 }; for (const p of Object.values(perfis)) cont[p.fonte]++;
  logar(ctx, E, `perfis ${JSON.stringify(cont)}; negócios com Instagram no dossiê: ${comResumo}${parou ? `; parou: ${parou}` : ''}`);
  gravarNoBanco(ctx, E, { 'instagram-perfis.json': perfis, 'negocios-enriquecidos.json': ent });
  marcarEstado(ctx, E, { perfis: users.length, ...cont, parou });
  return { perfis: cont, parou };
}

async function camadaIgFundo(ctx, spec) {
  const E = 'enriquecer-ig-fundo', ETAPA = 'instagram_fundo';
  const ent = exigir(ctx, 'enriquecidos.json', 'enriquecer --camada site');
  const perfis = exigir(ctx, 'instagram-perfis.json', 'enriquecer --camada ig-raso');
  const porU = new Map();
  for (const n of listaIg(ent)) { const u = IG.uname(n.instagram); if (!porU.has(u) && perfis[u] && perfis[u].fonte !== 'falhou') porU.set(u, n); }
  const users = [...porU.keys()].slice(0, quantos(spec, porU.size));
  const raw = lerJson(ctx, 'cache/instagram-comentarios.json', {});
  const urls = [];
  for (const u of users) for (const m of IG.postsDe(perfis[u])) if (!raw[IG.sc(m.url)]) urls.push({ u, url: m.url, est: Math.min(IG.LIM_COMENTARIOS, m.comentarios) * PRECOS.ig_comentario });
  let parou = null;
  logar(ctx, E, `${users.length} perfis no recorte; ${urls.length} post(s) com comentários a ler`);
  if (urls.length) {
    const est = urls.reduce((s, x) => s + x.est, 0);
    garantirTeto(ctx, ETAPA, est, `${urls.length} post(s) pelo ${IG.ATOR_COMENTARIOS} (até ${IG.LIM_COMENTARIOS} comentários cada)`);
    if (!usaApify(ctx)) logar(ctx, E, `simulação: ${urls.length} post(s) iriam ao Apify (US$ ${est.toFixed(4)}); nada gasto. Rode com --aplicar.`);
    else {
      let pend = [...urls];
      while (pend.length) {
        const sub = pend.slice(0, 75), estSub = sub.reduce((s, x) => s + x.est, 0);
        const conta = await contaPara(ctx, ETAPA, estSub);
        if (!conta) { parou = 'pool sem saldo'; break; }
        const r = await rodarRetomavel(ctx, ETAPA, `ig-fundo:${IG.sc(sub[0].url)}`, conta.conta, IG.ATOR_COMENTARIOS,
          { directUrls: sub.map((x) => x.url), resultsLimit: IG.LIM_COMENTARIOS, includeNestedComments: false }, Math.min(restante(ctx, ETAPA), conta.livre - 0.01));
        const por = IG.agruparComentarios(r.items);
        for (const x of sub) { const k = IG.sc(x.url); if (por[k] || r.status === 'SUCCEEDED') raw[k] = por[k] || []; }
        gravarJson(ctx, 'cache/instagram-comentarios.json', raw);
        pend = pend.filter((x) => !raw[IG.sc(x.url)]);
        if (r.status !== 'SUCCEEDED' && !Object.keys(por).length) { parou = 'run ' + r.status; break; }
      }
    }
  }
  let comLinha = 0, perguntas = 0;
  for (const u of users) {
    const p = perfis[u];
    if (IG.postsDe(p).some((m) => !raw[IG.sc(m.url)])) continue; // só com todos os posts lidos
    const a = IG.analisar(u, p, porU.get(u), raw); if (!a) continue;
    perguntas += a.perguntas || 0;
    for (const n of ent) if (n.provavel_whatsapp === true && n.instagram && IG.uname(n.instagram) === u) { n.instagram_comentarios = a.linha; n.dossie = montarDossie(n); comLinha++; }
  }
  gravarJson(ctx, 'enriquecidos.json', ent);
  logar(ctx, E, `negócios com linha de comentários: ${comLinha}; perguntas de clientes: ${perguntas}${parou ? `; parou: ${parou}` : ''}`);
  gravarNoBanco(ctx, E, { 'negocios-enriquecidos.json': ent });
  marcarEstado(ctx, E, { perfis: users.length, com_linha: comLinha, perguntas, parou });
  return { comLinha, parou };
}

async function camadaDecisor(ctx, spec) {
  const E = 'enriquecer-decisor';
  const ent = exigir(ctx, 'enriquecidos.json', 'enriquecer --camada site');
  const lista = ent.filter((x) => x.provavel_whatsapp === true && x.enriquecido).sort((a, b) => a.prioridade - b.prioridade);
  const alvo = lista.slice(0, quantos(spec, lista.length));
  const meta = lerJson(ctx, 'cache/instagram-meta.json', {});
  const cand = lerJson(ctx, 'cache/decisor-cnpj.json', {});
  const busca = lerJson(ctx, 'cache/decisor-busca.json', {});
  const IGP = lerJson(ctx, 'cache/decisor-ig-pessoal.json', {});
  const AJ = lerJson(ctx, 'ajustes-decisor.json', {}); // revisão manual (mesmo formato do ajustes.json de 09/10)
  const fontes = { busca, lerCnpj: (c) => lerCnpjCache(ctx, c) };
  ctx.logIg = (s) => logar(ctx, E, s);
  logar(ctx, E, `${alvo.length} negócios no recorte (custo US$ 0: site, BrasilAPI, registro.br, busca web e Meta são grátis)`);
  const ev = {};
  for (const n of alvo) {
    const tel = n.telefone_e164, relPag = `cache/paginas/${n.placeId || tel}.json`;
    let pag = lerJson(ctx, relPag, null);
    if (!pag) { pag = await DEC.baixarPaginas(ctx, n); gravarJson(ctx, relPag, pag); await ctx.deps.sleep(500); }
    const ig = n.instagram ? meta[IG.uname(n.instagram)] : null;
    if (!cand[tel]?.feito) { cand[tel] = await DEC.candidatosCnpj(ctx, n, pag, ig); gravarJson(ctx, 'cache/decisor-cnpj.json', cand); }
    ev[tel] = DEC.evidencias(n, pag, ig, cand[tel]);
  }
  for (const n of alvo) {
    const tel = n.telefone_e164;
    if (busca[tel]?.buscado || DEC.escolherCnpj(ev[tel], tel, fontes)) continue;
    busca[tel] = await DEC.buscarCnpjNaWeb(ctx, n);
    gravarJson(ctx, 'cache/decisor-busca.json', busca);
    logar(ctx, E, `#${n.prioridade} busca web: ${new Set(busca[tel].achados.map((a) => a.cnpj)).size} CNPJ(s)`);
  }
  // @ pessoal do decisor (Business Discovery), depois o registro final com os ajustes manuais
  const F0 = DEC.final(alvo, { ev, AJ, IGP, fontes });
  for (const n of alvo) {
    const tel = n.telefone_e164, f = F0[tel];
    if (!f?.decisor?.nome) continue;
    const extra = AJ[tel]?.ig_bio_handle ? [AJ[tel].ig_bio_handle] : [];
    for (const h of [...new Set([...DEC.candidatos(ev[tel], f.decisor.nome), ...extra])]) {
      const k = h.toLowerCase();
      if (IGP[k]) continue;
      IGP[k] = meta[k]?.ok ? { ok: true, data: meta[k].data, fonte: 'cache' } : await DEC.perfilPessoal(ctx, k);
      gravarJson(ctx, 'cache/decisor-ig-pessoal.json', IGP);
    }
  }
  const F = DEC.final(alvo, { ev, AJ, IGP, fontes });
  gravarJson(ctx, 'cache/decisor-evidencias.json', ev);
  gravarJson(ctx, 'decisores.json', F);
  let comDecisor = 0;
  for (const n of ent) {
    const reg = F[n.telefone_e164]; if (!reg) continue;
    n.decisor = linhaDecisor(reg); if (n.decisor) comDecisor++;
    n.dossie = montarDossie(n);
  }
  gravarJson(ctx, 'enriquecidos.json', ent);
  const v = Object.values(F), conta = (fn) => v.filter(fn).length;
  const resumo = { processados: v.length, com_cnpj: conta((x) => x.cnpj), com_decisor: comDecisor, alta: conta((x) => x.confianca === 'alta'), media: conta((x) => x.confianca === 'media'), baixa: conta((x) => x.confianca === 'baixa'), com_instagram_pessoal: conta((x) => x.decisor.instagram_pessoal), com_contato_direto: conta((x) => x.decisor.contato_direto) };
  logar(ctx, E, `decisores: ${JSON.stringify(resumo)}`);
  gravarNoBanco(ctx, E, { 'decisores.json': F, 'negocios-enriquecidos.json': ent });
  marcarEstado(ctx, E, resumo);
  return resumo;
}

// ---------------------------------------------------------------- qualificar (lente de riqueza)
export async function qualificar(ctx) {
  const E = 'qualificar';
  const ent = exigir(ctx, 'enriquecidos.json', 'enriquecer --camada site');
  const decisores = lerJson(ctx, 'decisores.json', {});
  const negocios = ent.filter((n) => n.provavel_whatsapp === true && n.enriquecido);
  // sites: o cache da camada site já tem os sinais; o que faltar é lido agora (grátis)
  const sites = {};
  let lidosAgora = 0;
  for (const n of negocios) {
    if (!n.site || SOCIAL.test(n.site) || sites[n.site]) continue;
    const rel = `cache/sites/${n.placeId || n.telefone_e164}.json`;
    let c = lerJson(ctx, rel, null);
    if (!c && tipoSite(n.site) === 'site') { c = await lerSite(ctx, n); gravarJson(ctx, rel, c); lidosAgora++; await ctx.deps.sleep(aleatorio(1000, 2000)); }
    if (!c) continue;
    sites[n.site] = c.ok && c.sinais ? { url: n.site, ok: true, final: c.final_url, ...c.sinais } : { url: n.site, ok: false, erro: c.erro || 'sem sinais' };
  }
  const cnpjs = {};
  let consultados = 0;
  for (const n of negocios) {
    const { cnpj } = cnpjDoNegocio(n, decisores, sites);
    if (!cnpj || cnpjs[cnpj]) continue;
    const antes = lerCnpjCache(ctx, cnpj);
    cnpjs[cnpj] = antes || await consultarCnpj(ctx, cnpj);
    if (!antes) consultados++;
  }
  const q = notaLente({ todos: ent, negocios, decisores, sites, cnpjs });
  gravarJson(ctx, 'qualificacao-riqueza.json', q);
  gravarJson(ctx, 'fila-ordenada-riqueza.json', q.map((o) => o.telefone_e164));
  gravarJson(ctx, 'sites-sinais.json', sites);
  gravarJson(ctx, 'cnpj-cache.json', cnpjs);
  const porTel = new Map(q.map((x) => [x.telefone_e164, x]));
  for (const n of ent) {
    const x = porTel.get(n.telefone_e164); if (!x) continue;
    n.sinais_investimento = linhaLente(x); n.lente_nota = x.nota; n.dossie = montarDossie(n);
  }
  gravarJson(ctx, 'enriquecidos.json', ent);
  const dist = {}; for (const o of q) dist[o.nota] = (dist[o.nota] || 0) + 1;
  logar(ctx, E, `${q.length} negócios com nota; sites lidos agora ${lidosAgora}; CNPJs consultados agora ${consultados}; custo US$ 0 (grátis); notas ${JSON.stringify(dist)}`);
  gravarNoBanco(ctx, E, { 'negocios-enriquecidos.json': ent });
  marcarEstado(ctx, E, { negocios: q.length, notas: dist });
  return { q };
}

// ---------------------------------------------------------------- fila
export async function fila(ctx, { atualizar = false, semLente = false, mostrar = 10 } = {}) {
  const E = 'fila';
  const ent = exigir(ctx, 'enriquecidos.json', 'enriquecer --camada site');
  let ordem = lerJson(ctx, 'fila-ordenada-riqueza.json', null);
  if (!ordem && !semLente) throw new ErroEtapa(`falta fila-ordenada-riqueza.json: rode antes \`prospeccao qualificar ${ctx.campanha.slug}\` (ou use --sem-lente para ordenar só pela prioridade)`);
  const elegiveis = ent.filter((n) => n.provavel_whatsapp === true && n.enriquecido && n.telefone_e164);
  const pos = new Map((ordem || []).map((t, i) => [t, i]));
  elegiveis.sort((a, b) => (pos.get(a.telefone_e164) ?? 1e9) - (pos.get(b.telefone_e164) ?? 1e9) || a.prioridade - b.prioridade);
  const itens = elegiveis.map((n) => filaItem({ ...n, dossie: montarDossie(n) }));
  gravarJson(ctx, 'fila.json', { slug: ctx.campanha.slug, gerado_em: new Date(ctx.agora()).toISOString(), ordem: ordem ? 'lente de riqueza (nota desc), depois prioridade' : 'prioridade', negocios: itens });
  const notas = new Map(ent.map((n) => [n.telefone_e164, n.lente_nota]));
  logar(ctx, E, `fila.json: ${itens.length} negócios. Os primeiros a sair (a bridge segue janela, rampa e dias abertos):`);
  for (const [i, x] of itens.slice(0, mostrar).entries()) logar(ctx, E, `  ${i + 1}. nota ${notas.get(x.telefone_e164) ?? '-'} | ${x.nome} | ${x.cidade} | ${x.nicho}`);
  let resultado = null;
  if (!ctx.aplicar) logar(ctx, E, 'simulação: nada enfileirado na produção. Rode com --aplicar para chamar prospeccao.enqueue (números já na fila ficam como estão; --atualizar renova o dossiê deles).');
  else {
    resultado = { fila: enviarFila(ctx, itens, 'fila') };
    if (atualizar) resultado.atualizar = enviarFila(ctx, itens, 'atualizar');
    gravarJson(ctx, 'fila-envio.json', { quando: new Date(ctx.agora()).toISOString(), ...resultado });
  }
  marcarEstado(ctx, E, { negocios: itens.length, resultado });
  return { itens, resultado };
}

// ---------------------------------------------------------------- custo e status
export async function custo(ctx, { conferir = false } = {}) {
  const c = lerCustos(ctx);
  if (conferir) {
    for (const e of ETAPAS_PAGAS) for (const r of c.etapas[e].runs) {
      if (r.fixture && !ctx.fixtures) continue;
      const d = await lerRun(ctx, r.conta, r.runId);
      if (d && d.usageTotalUsd != null && Math.abs(d.usageTotalUsd - r.custo_usd) > 1e-6) { r.custo_usd_registrado = r.custo_usd; r.custo_usd = Number(d.usageTotalUsd.toFixed(6)); }
      r.conferido_em = new Date(ctx.agora()).toISOString();
    }
    for (const e of ETAPAS_PAGAS) c.etapas[e].gasto_usd = Number(c.etapas[e].runs.reduce((s, r) => s + (r.custo_usd || 0), 0).toFixed(6));
    c.total_usd = Number(ETAPAS_PAGAS.reduce((s, e) => s + c.etapas[e].gasto_usd, 0).toFixed(6));
  }
  const linhas = ETAPAS_PAGAS.map((e) => ({ etapa: e, gasto_usd: c.etapas[e].gasto_usd, teto_usd: teto(ctx, e), runs: c.etapas[e].runs.length }));
  c.total_usd = Number(linhas.reduce((s, l) => s + l.gasto_usd, 0).toFixed(6));
  gravarJson(ctx, 'custos.json', c);
  for (const l of linhas) logar(ctx, 'custo', `${l.etapa}: US$ ${l.gasto_usd.toFixed(4)} de US$ ${l.teto_usd.toFixed(2)} (${l.runs} run(s))`);
  logar(ctx, 'custo', `total: US$ ${c.total_usd.toFixed(4)}${conferir ? ' (conferido na API do Apify)' : ' (do registro local; --conferir lê o cobrado de cada run na API)'}`);
  return { linhas, total_usd: c.total_usd };
}

export function status(ctx) {
  const n = (rel, f = (x) => (Array.isArray(x) ? x.length : Object.keys(x || {}).length)) => (existe(ctx, rel) ? f(lerJson(ctx, rel)) : null);
  const contaDir = (rel) => { const d = caminho(ctx, rel); return fs.existsSync(d) ? fs.readdirSync(d).length : 0; };
  const est = lerJson(ctx, 'estado.json', {});
  const c = lerCustos(ctx);
  const etapas = [
    ['coletar', 'negocios.json', n('negocios.json'), `${ctx.campanha.cidades.filter((x) => existe(ctx, rawRel(x))).length}/${ctx.campanha.cidades.length} cidades`],
    ['enriquecer --camada site', 'enriquecidos.json', n('enriquecidos.json', (x) => x.filter((y) => y.enriquecido).length), `${contaDir('cache/sites')} sites no cache`],
    ['enriquecer --camada ig-raso', 'instagram-perfis.json', n('instagram-perfis.json'), `${Object.keys(lerJson(ctx, 'cache/instagram-meta.json', {})).length} na Meta (cache)`],
    ['enriquecer --camada ig-fundo', 'enriquecidos.json', n('enriquecidos.json', (x) => x.filter((y) => y.instagram_comentarios).length), `${Object.keys(lerJson(ctx, 'cache/instagram-comentarios.json', {})).length} posts lidos`],
    ['enriquecer --camada decisor', 'decisores.json', n('decisores.json'), `${contaDir('cache/paginas')} sites com páginas`],
    ['qualificar', 'qualificacao-riqueza.json', n('qualificacao-riqueza.json'), ''],
    ['fila', 'fila.json', n('fila.json', (x) => x.negocios.length), est.fila?.resultado ? `enviado: ${JSON.stringify(est.fila.resultado.fila)}` : 'não enviado à produção'],
  ];
  const linhas = etapas.map(([cmd, arq, qtd, extra]) => ({ comando: cmd, arquivo: arq, itens: qtd, extra, ultima: est[{ coletar: 'coleta', fila: 'fila', qualificar: 'qualificar' }[cmd] || `enriquecer-${cmd.split(' ').pop()}`] || null }));
  const proximo = linhas.find((l) => l.itens == null);
  const pend = Object.keys(lerJson(ctx, 'cache/runs-pendentes.json', {}));
  console.log(`campanha ${ctx.campanha.slug} (${ctx.dir})`);
  for (const l of linhas) console.log(`  ${l.itens == null ? '[ ]' : '[x]'} ${l.comando.padEnd(30)} ${l.arquivo.padEnd(27)} ${l.itens == null ? '-' : l.itens} ${l.extra}${l.ultima ? ` | última: ${l.ultima.quando} (${l.ultima.modo}${l.ultima.fixtures ? ', fixtures' : ''})` : ''}`);
  for (const e of ETAPAS_PAGAS) console.log(`  custo ${e}: US$ ${c.etapas[e].gasto_usd.toFixed(4)} de US$ ${teto(ctx, e).toFixed(2)}`);
  if (pend.length) console.log(`  runs do Apify pendentes (serão retomadas): ${pend.join(', ')}`);
  console.log(proximo ? `  próximo: prospeccao ${proximo.comando} ${ctx.campanha.slug}` : '  todas as etapas têm saída');
  return { linhas, pendentes: pend, proximo: proximo?.comando || null };
}
