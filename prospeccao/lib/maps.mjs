// Google Maps pelo Apify (compass/crawler-google-places): input da run (de maps/run.mjs) e processamento dos brutos
// em negocios.json (de maps/processar.mjs: telefone E.164 brasileiro, fechados e duplicados fora).
export const ATOR_MAPS = 'compass~crawler-google-places';

export function inputColeta(cidade, uf, nichos, max) {
  return {
    searchStringsArray: nichos,
    locationQuery: `${cidade}, ${uf}, Brasil`,
    maxCrawledPlacesPerSearch: Number(max),
    language: 'pt-BR',
    skipClosedPlaces: true,
    maxReviews: 0, maxImages: 0, maxQuestions: 0,
    scrapePlaceDetailPage: false, scrapeContacts: false, includeWebResults: false,
    scrapeDirectories: false, scrapeTableReservationProvider: false, enableCompetitorAnalysis: false,
  };
}

const DDD = new Set('11 12 13 14 15 16 17 18 19 21 22 24 27 28 31 32 33 34 35 37 38 41 42 43 44 45 46 47 48 49 51 53 54 55 61 62 63 64 65 66 67 68 69 71 73 74 75 77 79 81 82 83 84 85 86 87 88 89 91 92 93 94 95 96 97 98 99'.split(' '));
export function e164(p) {
  if (!p) return null;
  const bruto = String(p).trim();
  if (bruto.startsWith('+') && !bruto.startsWith('+55')) return null; // número estrangeiro
  let d = bruto.replace(/\D/g, '');
  if (d.startsWith('0055')) d = d.slice(4);
  else if (d.startsWith('55') && (d.length === 12 || d.length === 13)) d = d.slice(2);
  d = d.replace(/^0+/, '');
  if (d.length === 12 || d.length === 13) d = d.slice(2); // 0 + operadora + DDD + número
  if (d.length !== 10 && d.length !== 11) return null; // 0800, 4004 etc. ficam de fora
  if (d.length === 11 && d[2] !== '9') return null;
  if (d.length === 10 && /[6-9]/.test(d[2])) d = d.slice(0, 2) + '9' + d.slice(2); // celular antigo sem o 9
  if (!DDD.has(d.slice(0, 2))) return null; // 0800/0300/4004 e DDD inexistente
  return '55' + d;
}

// brutos: [{cidade, uf, items}] na ordem das cidades da campanha
export function processar(brutosPorCidade) {
  const vistosTel = new Set(), vistosPid = new Set();
  const out = [];
  const c = { brutos: 0, fechados: 0, sem_telefone_valido: 0, duplicados: 0 };
  for (const { cidade, uf, items } of brutosPorCidade) {
    for (const i of items || []) {
      c.brutos++;
      if (i.permanentlyClosed || i.temporarilyClosed) { c.fechados++; continue; }
      const tel = e164(i.phone || i.phoneUnformatted);
      if (!tel) { c.sem_telefone_valido++; continue; }
      if (vistosTel.has(tel) || (i.placeId && vistosPid.has(i.placeId))) { c.duplicados++; continue; }
      vistosTel.add(tel); if (i.placeId) vistosPid.add(i.placeId);
      out.push({
        nome: i.title,
        nicho: i.searchString,
        categoria: i.categoryName || null,
        cidade, uf,
        cidade_maps: i.city || null,
        telefone_e164: tel,
        provavel_whatsapp: tel.length === 13 && tel[4] === '9',
        site: i.website || null,
        nota: i.totalScore ?? null,
        avaliacoes: i.reviewsCount ?? 0,
        endereco: i.address || null,
        url_maps: i.url || null,
        placeId: i.placeId || null,
        horario: Array.isArray(i.openingHours) && i.openingHours.length ? i.openingHours.map((h) => `${h.day}: ${h.hours}`).join('; ') : null,
      });
    }
  }
  c.unicos_com_telefone = out.length;
  c.provavel_whatsapp = out.filter((r) => r.provavel_whatsapp).length;
  return { negocios: out, contagem: c };
}
