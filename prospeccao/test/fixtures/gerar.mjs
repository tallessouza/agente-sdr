// Gera test/fixtures/exemplo/: respostas falsas de Apify, Meta, sites e BrasilAPI para a campanha de exemplo.
// Negócios, pessoas, CNPJs e telefones são fictícios (telefones 55 48 99999-00xx); o formato é o das respostas reais de 09/10.
//   node test/fixtures/gerar.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), 'exemplo');
const w = (rel, v) => { const f = path.join(DIR, rel); fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, typeof v === 'string' ? v : JSON.stringify(v, null, 1)); };

function cnpj(base12) {
  const dv = (b) => { const pesos = b.length === 12 ? [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2] : [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]; const r = b.split('').reduce((s, d, i) => s + d * pesos[i], 0) % 11; return r < 2 ? 0 : 11 - r; };
  const d1 = dv(base12); return base12 + d1 + dv(base12 + d1);
}
const fmtCnpj = (c) => `${c.slice(0, 2)}.${c.slice(2, 5)}.${c.slice(5, 8)}/${c.slice(8, 12)}-${c.slice(12)}`;
const A = cnpj('112223330001'), B = cnpj('223334440001'), C = cnpj('334445550001'), D = cnpj('445556660001');

const semana = (abre, fecha, sab, dom) => [
  ...['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira'].map((day) => ({ day, hours: `${abre} to ${fecha}` })),
  { day: 'sábado', hours: sab || 'Fechado' }, { day: 'domingo', hours: dom || 'Fechado' },
];
const lugar = (o) => ({ categoryName: o.cat, categories: [o.cat], city: o._cidade, totalScore: 4.5, reviewsCount: 10, permanentlyClosed: false, temporarilyClosed: false, address: `Rua Fictícia, ${o.n} - ${o.bairro || 'Centro'}, ${o._cidade} - SC, 88000-000, Brasil`, neighborhood: o.bairro || null, url: `https://maps.google.com/?cid=${o.placeId}`, openingHours: semana('08:00', '18:00'), ...o });

w('manifesto.json', { hoje: '2026-10-11', saldo_apify: { 'concept.advice': 5, 'zeique-zgc': 5, marbly_antlion: 5, formful_buffet: 5, igorpena: 5 }, nota: 'dados fictícios para os testes do pipeline' });

w('apify/maps.json', [
  lugar({ _cidade: 'São José', searchString: 'clínica odontológica', n: 1, placeId: 'pSJ01', title: 'Clínica Sorriso Pleno', cat: 'Clínica odontológica', phone: '(48) 99999-0001', website: 'https://sorrisopleno.com.br/', totalScore: 4.9, reviewsCount: 320, bairro: 'Kobrasol', openingHours: semana('08:00', '19:00', '08:00 to 12:00') }),
  lugar({ _cidade: 'São José', searchString: 'clínica odontológica', n: 2, placeId: 'pSJ02', title: 'Odonto Vida São José', cat: 'Dentista', phone: '(48) 99999-0002', website: 'https://odontovida.com.br/', totalScore: 4.6, reviewsCount: 80, bairro: 'Campinas' }),
  lugar({ _cidade: 'São José', searchString: 'clínica odontológica', n: 3, placeId: 'pSJ03', title: 'Dentista Dr. Paulo Mendes', cat: 'Dentista', phone: '(48) 3333-0003', website: null }),
  lugar({ _cidade: 'São José', searchString: 'clínica odontológica', n: 4, placeId: 'pSJ04', title: 'Clínica Fechada', cat: 'Dentista', phone: '(48) 99999-0004', permanentlyClosed: true }),
  lugar({ _cidade: 'São José', searchString: 'clínica odontológica', n: 5, placeId: 'pSJ05', title: 'Sorriso Kids', cat: 'Odontopediatra', phone: '(48) 99999-0005', website: 'https://www.instagram.com/sorrisokids/', reviewsCount: 15 }),
  lugar({ _cidade: 'São José', searchString: 'clínica odontológica', n: 6, placeId: 'pSJ06', title: 'Excedente do limite por busca', cat: 'Dentista', phone: '(48) 99999-0006' }),
  lugar({ _cidade: 'São José', searchString: 'imobiliária', n: 7, placeId: 'pSJ07', title: 'Imobiliária Horizonte', cat: 'Imobiliária', phone: '(48) 99999-0007', website: 'https://horizonteimoveis.com.br/', totalScore: 4.8, reviewsCount: 210, bairro: 'Barreiros' }),
  lugar({ _cidade: 'São José', searchString: 'imobiliária', n: 8, placeId: 'pSJ08', title: 'Casa Nova Imóveis', cat: 'Imobiliária', phone: '(48) 99999-0008', website: 'https://wa.me/5548999990008', reviewsCount: 40 }),
  lugar({ _cidade: 'São José', searchString: 'imobiliária', n: 9, placeId: 'pSJ09', title: 'Imóveis Litoral (mesmo telefone)', cat: 'Imobiliária', phone: '(48) 99999-0001' }),
  lugar({ _cidade: 'São José', searchString: 'imobiliária', n: 10, placeId: 'pSJ10', title: 'Imobiliária Ponte', cat: 'Imobiliária', phone: '+1 555 0100' }),
  lugar({ _cidade: 'Palhoça', searchString: 'clínica odontológica', n: 11, placeId: 'pPA11', title: 'Clínica Sorriso Pleno - Palhoça', cat: 'Clínica odontológica', phone: '(48) 99999-0011', website: 'https://sorrisopleno.com.br/', reviewsCount: 120, bairro: 'Pedra Branca' }),
  lugar({ _cidade: 'Palhoça', searchString: 'clínica odontológica', n: 12, placeId: 'pPA12', title: 'OdontoPalhoça', cat: 'Dentista', phone: '(48) 99999-0012', website: 'https://odontopalhoca.com.br/', reviewsCount: 60 }),
  lugar({ _cidade: 'Palhoça', searchString: 'imobiliária', n: 13, placeId: 'pPA13', title: 'Pedra Branca Imóveis', cat: 'Imobiliária', phone: '(48) 99999-0013', website: null, reviewsCount: 5, openingHours: [] }),
  lugar({ _cidade: 'Palhoça', searchString: 'imobiliária', n: 14, placeId: 'pPA14', title: 'Imobiliária Enseada', cat: 'Imobiliária', phone: '(48) 99999-0014', website: 'https://enseadaimoveis.com.br/', reviewsCount: 95, bairro: 'Enseada de Brito', openingHours: semana('09:00', '18:00', '09:00 to 13:00', '10:00 to 12:00') }),
]);

const pagina = (titulo, corpo) => `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>${titulo}</title><meta name="description" content="${titulo}: atendimento na Grande Florianópolis."></head><body>${corpo}<p>${'Texto institucional de exemplo para a página ter conteúdo suficiente. '.repeat(4)}</p></body></html>`;
w('sites/sorrisopleno.com.br.html', pagina('Clínica Sorriso Pleno', `
<script>!function(f,b,e,v,n,t,s){}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');fbq('init','100000000000001');</script>
<script>(function(w,d,s,l,i){j.src='https://www.googletagmanager.com/gtm.js?id='+i;})(window,document,'script','dataLayer','GTM-ABCD12');</script>
<h1>Implante dentário, ortodontia e clareamento dental</h1><p>Lentes de contato dental e harmonização facial.</p>
<a href="https://wa.me/5548999990001">Fale no WhatsApp</a> <a href="https://instagram.com/sorrisopleno">Instagram</a> <a href="/sobre">Sobre nós</a>
<footer>Sorriso Pleno Odontologia LTDA · CNPJ ${fmtCnpj(A)}</footer>`));
w('sites/sorrisopleno.com.br_sobre.html', pagina('Sobre a Sorriso Pleno', `<h2>Quem somos</h2><p>Responsável Técnica: Dra. Marina Duarte CRO/SC 12345.</p><p>Contato: <a href="mailto:marina.duarte@sorrisopleno.com.br">marina.duarte@sorrisopleno.com.br</a></p>`));
w('sites/odontovida.com.br.html', pagina('Odonto Vida', `<h1>Limpeza dental, restauração e tratamento de canal</h1><a href="https://instagram.com/odontovida">@odontovida</a><footer>CNPJ ${fmtCnpj(B)}</footer>`));
w('sites/horizonteimoveis.com.br.html', pagina('Imobiliária Horizonte', `
<script async src="https://www.googletagmanager.com/gtag/js?id=G-ABCDEF1234"></script><script>gtag('config','AW-123456789');gtag('config','G-ABCDEF1234');</script>
<h1>Venda de imóveis, locação e administração de imóveis</h1><p>Financiamento imobiliário e lançamentos.</p>
<a href="https://instagram.com/horizonteimoveis">Instagram</a><footer>CNPJ ${fmtCnpj(C)}</footer>`));
w('sites/enseadaimoveis.com.br.html', pagina('Imobiliária Enseada', `<h1>Aluguel por temporada e venda de imóveis frente mar</h1><a href="/quem-somos">Quem somos</a> <a href="https://instagram.com/enseadaimoveis">Instagram</a><footer>CNPJ ${fmtCnpj(D)}</footer>`));
w('sites/enseadaimoveis.com.br_quem-somos.html', pagina('Quem somos', `<p>A Enseada nasceu em 2015. Sócio fundador: João Pedro Machado, corretor CRECI 12345-F.</p>`));

const post = (id, data, curtidas, comentarios, legenda, tipo = 'IMAGE') => ({ caption: legenda, timestamp: `${data}T12:00:00+0000`, like_count: curtidas, comments_count: comentarios, media_type: tipo, permalink: `https://www.instagram.com/p/${id}/` });
w('meta/sorrisopleno.json', { name: 'Clínica Sorriso Pleno', biography: 'Odontologia completa em São José\nResp. Técnica Dra. Marina Duarte CRO/SC 12345\n@dramarinaduarte', followers_count: 8200, media_count: 410, website: 'https://sorrisopleno.com.br',
  media: { data: [post('SP1', '2026-10-05', 340, 3, 'Clareamento dental com resultado natural. Agende sua avaliação!'), post('SP2', '2026-09-28', 120, 0, 'Equipe pronta para receber você.', 'CAROUSEL_ALBUM'), post('SP3', '2026-09-20', 510, 25, 'Depoimento da Juliana sobre o implante.', 'VIDEO')] } });
w('meta/dramarinaduarte.json', { username: 'dramarinaduarte', name: 'Marina Duarte', biography: 'Dentista em São José · agenda: marina.duarte@sorrisopleno.com.br', followers_count: 1500, website: null });
w('meta/horizonteimoveis.json', { name: 'Horizonte Imóveis', biography: 'Imobiliária em São José', followers_count: 3100, media_count: 800, website: 'https://horizonteimoveis.com.br', media: { data: [post('HZ1', '2026-10-01', 45, 0, 'Apartamento novo no Kobrasol.')] } });
w('meta/enseadaimoveis.json', { name: 'Enseada Imóveis', biography: 'Temporada e venda na Enseada de Brito', followers_count: 950, media_count: 120, website: 'https://enseadaimoveis.com.br', media: { data: [post('EN1', '2026-10-08', 30, 2, 'Casa frente mar disponível para temporada.')] } });
w('meta/sorrisokids.json', { name: 'Sorriso Kids', biography: 'Odontopediatria', followers_count: 400, media_count: 50, website: null, media: { data: [] } });

w('apify/instagram-perfis.json', [{ username: 'odontovida', fullName: 'Odonto Vida', biography: 'Clínica odontológica em São José', followersCount: 1200, postsCount: 90, externalUrl: 'https://odontovida.com.br', private: false,
  latestPosts: [{ caption: 'Limpeza a cada 6 meses.', timestamp: '2026-10-02T12:00:00.000Z', likesCount: 25, commentsCount: 0, type: 'Image', url: 'https://www.instagram.com/p/OV1/', shortCode: 'OV1' }] }]);
w('apify/instagram-comentarios.json', [
  { postUrl: 'https://www.instagram.com/p/SP1/', text: 'Qual o valor do clareamento?', ownerUsername: 'cliente.um', timestamp: '2026-10-05T13:00:00.000Z' },
  { postUrl: 'https://www.instagram.com/p/SP1/', text: '@cliente.um te chamamos no direct!', ownerUsername: 'sorrisopleno', timestamp: '2026-10-05T14:00:00.000Z' },
  { postUrl: 'https://www.instagram.com/p/SP1/', text: 'Lindo resultado', ownerUsername: 'cliente.dois', timestamp: '2026-10-05T15:00:00.000Z' },
  { postUrl: 'https://www.instagram.com/p/SP3/', text: 'Atende convênio?', ownerUsername: 'cliente.tres', timestamp: '2026-09-21T10:00:00.000Z' },
  { postUrl: 'https://www.instagram.com/p/SP3/', text: 'Parabéns pelo trabalho', ownerUsername: 'cliente.quatro', timestamp: '2026-09-21T11:00:00.000Z' },
  { postUrl: 'https://www.instagram.com/p/EN1/', text: 'Quanto custa a diária em janeiro?', ownerUsername: 'turista.um', timestamp: '2026-10-08T18:00:00.000Z' },
  { postUrl: 'https://www.instagram.com/p/EN1/', text: 'Que vista!', ownerUsername: 'turista.dois', timestamp: '2026-10-08T19:00:00.000Z' },
]);

const empresa = (c, razao, municipio, capital, porte, situacao, cnae, socios) => ({ cnpj: c, razao_social: razao, nome_fantasia: '', porte, data_inicio_atividade: '2015-03-10', capital_social: capital,
  descricao_situacao_cadastral: situacao, municipio, uf: 'SC', cnae_fiscal_descricao: cnae, natureza_juridica: 'Sociedade Empresária Limitada', identificador_matriz_filial: 1,
  qsa: socios.map(([nome, q]) => ({ nome_socio: nome, qualificacao_socio: q })) });
w(`cnpj/${A}.json`, empresa(A, 'SORRISO PLENO ODONTOLOGIA LTDA', 'SAO JOSE', 150000, 'DEMAIS', 'ATIVA', 'Atividade odontológica', [['MARINA DUARTE SILVA', 'Sócio-Administrador'], ['RICARDO DUARTE', 'Sócio']]));
w(`cnpj/${B}.json`, empresa(B, 'ODONTO VIDA LTDA', 'SAO JOSE', 20000, 'MICRO EMPRESA', 'BAIXADA', 'Atividade odontológica', [['FERNANDO VIDAL', 'Sócio-Administrador']]));
w(`cnpj/${C}.json`, empresa(C, 'HORIZONTE NEGOCIOS IMOBILIARIOS LTDA', 'SAO JOSE', 50000, 'MICRO EMPRESA', 'ATIVA', 'Corretagem na compra e venda e avaliação de imóveis', [['CARLOS HORIZONTE ALVES', 'Sócio-Administrador']]));
w(`cnpj/${D}.json`, empresa(D, 'ENSEADA IMOVEIS LTDA', 'PALHOCA', 10000, 'MICRO EMPRESA', 'ATIVA', 'Corretagem no aluguel de imóveis', [['JOAO PEDRO MACHADO', 'Sócio-Administrador']]));
console.log('fixtures em', DIR, { A, B, C, D });
