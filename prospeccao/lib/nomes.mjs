// Cópia de 17-prospeccao/scripts-origem/ig-lista/nomes.mjs (anonimização de legendas e comentários), com uma correção:
// "Depoimento da Juliana" deixava o nome passar (palavra maiúscula antes do nome). Ver test/dossie.test.mjs.
// Anonimização heurística de legendas/comentários: nomes próprios comuns e @menções viram "uma cliente"/"um paciente"
const F=`Ana Maria Mariana Juliana Fernanda Patrícia Patricia Aline Camila Amanda Bruna Jéssica Jessica Letícia Leticia Júlia Julia Luana Larissa Beatriz Gabriela Rafaela Isabela Isabel Isabella Carolina Caroline Carla Daniela Daniele Danielle Débora Debora Adriana Simone Sandra Cláudia Claudia Márcia Marcia Luciana Vanessa Tatiane Tatiana Renata Priscila Natália Natalia Michele Michelle Kelly Cristina Cristiane Silvia Sílvia Sônia Sonia Regina Rosana Rosângela Rosangela Vera Lúcia Lucia Helena Elaine Eliane Fabiana Fabíola Giovana Giovanna Heloísa Heloisa Ingrid Joana Josiane Jaqueline Jaqueline Karina Karen Kátia Katia Lorena Lívia Livia Luíza Luiza Luisa Laura Manuela Marcela Mirela Mônica Monica Nathalia Nathália Paula Paola Raquel Roberta Sabrina Samara Sara Sarah Sofia Sophia Stephanie Talita Thais Thaís Valéria Valeria Viviane Yasmin Alessandra Andressa Andréa Andrea Ângela Angela Bianca Cecília Cecilia Cíntia Cintia Denise Edna Eduarda Elisa Emanuelle Emily Érica Erica Francine Franciele Gisele Gislaine Graziela Ivone Janaína Janaina Jordana Josefa Kamila Karla Lara Leandra Lilian Lílian Luciene Maiara Marli Marta Milena Nádia Nadia Neide Nicole Olga Pâmela Pamela Rayane Rebeca Rita Rose Sueli Suelen Tânia Tania Teresa Tereza Valentina Vitória Alice Antônia Antonia Catarina Clarice Daiane Elis Estela Evelyn Flávia Flavia Gabriele Graciele Ivana Jussara Leila Lúcia Marina Melissa Mayara Noemi Raíssa Raissa Sílvia Tatyane Vânia Vania Zilda Isabelli Isabelly Emilly Kemilly Thaynara Thayná Heloá Rafaella Gabrielly Maria Eduarda Ketlin Kauane Daniella Bárbara Barbara Ariane Ariadne Aurora Agatha Ágatha Elisângela Elisangela Rosilene Rosimeri Salete Ivete Inês Ines Irene Iara Iracema Juçara Lourdes Madalena Marlene Nair Nilza Odete Rosemeri Terezinha`.split(/\s+/);
const M=`José Joao João Antônio Antonio Francisco Carlos Paulo Pedro Lucas Luiz Luis Luís Marcos Gabriel Rafael Daniel Marcelo Bruno Eduardo Felipe Raimundo Rodrigo Manoel Manuel Mateus Matheus André Andre Fernando Fábio Fabio Leonardo Gustavo Guilherme Leandro Tiago Thiago Anderson Ricardo Márcio Marcio Jorge Alexandre Roberto Edson Diego Vitor Victor Sérgio Sergio Cláudio Claudio Renato Renan Júlio Julio Mauro Maurício Mauricio Wagner Alex Alan Allan Arthur Artur Augusto Caio César Cesar Cristiano Davi David Douglas Elias Emerson Enzo Fabiano Fabrício Fabricio Flávio Flavio Geraldo Gilberto Henrique Heitor Hugo Igor Ivan Jair Jefferson Jean Joaquim Jonas Jonathan Juliano Kaio Leonel Lúcio Lucio Luan Luciano Marcelo Mário Mario Miguel Murilo Nelson Nicolas Otávio Otavio Patrick Paulinho Rafael Reinaldo Ronaldo Rogério Rogerio Samuel Sandro Saulo Sebastião Silvio Sílvio Tomás Thomas Valter Walter Vagner Vinícius Vinicius Wellington Wesley William Willian Yuri Adriano Alberto Alessandro Alisson Ademir Aílton Ailton Benjamin Breno Cauã Cleber Danilo Denis Edgar Edilson Emanuel Evandro Everton Fausto Gean Gerson Giovanni Gilson Hélio Helio Ismael Israel Jaime Jeferson Joel Juan Kevin Lauro Leo Léo Lorenzo Marlon Max Milton Moisés Nathan Natan Nilson Orlando Osmar Pablo Raul Ricardo Robson Rubens Ruan Severino Thales Tales Talles Teodoro Valdir Vicente Wilson Peterson Kauã Davi Emerson Gean Jhonatan Jonatas Jônatas Josué Juarez Kleber Leonidas Luciano Maicon Maycon Michel Mickael Nilton Odair Osvaldo Oswaldo Péricles Railson Rian Ryan Rodolfo Ronan Sidnei Sidney Silas Valmir Vanderlei Wanderley Wellinton Ygor Zeca`.split(/\s+/);
const FEM=new Set(F), MASC=new Set(M);
const CON=new Set(['da','de','do','das','dos','e']);
const TIT=/(?:Dr|Dra|Dr\.|Dra\.|Doutor|Doutora|Advogad[oa]|Adv|Adv\.|Corretor|Corretora|Prof|Profa|Professor|Professora|São|Santa|Santo|Rua|Avenida|Av\.|Av|Praça|Edifício|Residencial|Condomínio|Ed\.|Hospital|Colégio|Escola|Clínica|Instituto)\s*$/i;
export function protegidos(...textos){ const s=new Set(); for(const t of textos) for(const w of String(t||'').split(/[^A-Za-zÀ-ÿ]+/)) if(w) s.add(w.toLowerCase()); return s; }
export function anonimizar(texto, {saude=false, proprio='', prot=new Set()}={}){
  let t=String(texto||'');
  t=t.replace(/@([A-Za-z0-9._]*[A-Za-z0-9_])/g,(m,h)=> h.toLowerCase()===proprio.toLowerCase()? m : '(perfil marcado)');
  const pal=saude?['uma paciente','um paciente']:['uma cliente','um cliente'];
  const NAOMOME=/^(Google|Instagram|Botox|Invisalign|Dia|Natal|Brasil|Black|Friday|Ano|Novo|Páscoa|Clínica|Equipe|Time)$/;
  // "nossa paciente Fulana", "paciente Dra Fulana" -> tira o nome
  t=t.replace(/\b(pacientes?|clientes?)(\s+)(?:Dra?\.?\s+|Sra?\.?\s+)?([A-ZÀ-Ý][a-zà-ÿ]+(?:\s+[A-ZÀ-Ý][a-zà-ÿ]+)*)/g,(m,w,sp,nm)=> prot.has(nm.split(/\s+/)[0].toLowerCase())||NAOMOME.test(nm.split(/\s+/)[0])? m : w);
  // "depoimento/reconhecimento/feedback/avaliação do Fulano", "Parabéns, Fulana" -> "... de um cliente"
  t=t.replace(/\b([Dd]epoimento|[Rr]econhecimento|[Ff]eedback|[Aa]valia[çc][ãa]o|[Pp]arab[ée]ns)(,?\s+(?:d[aoe]\s+|à\s+|ao\s+|a\s+|o\s+)?)(?:Dra?\.?\s+|Sra?\.?\s+)?([A-ZÀ-Ý][a-zà-ÿ]+(?:\s+[A-ZÀ-Ý][a-zà-ÿ]+)*)/g,(m,w,sp,nm)=>{
    const p0=nm.split(/\s+/)[0]; if(prot.has(p0.toLowerCase())||NAOMOME.test(p0)) return m;
    return /parab/i.test(w)? `${w}, ${FEM.has(p0)?pal[0]:pal[1]}` : `${w} de ${FEM.has(p0)?pal[0]:pal[1]}`; });
  // Uma palavra maiúscula que não é nome ("Depoimento da Juliana", "Equipe e Marcos") não pode levar junto o nome que
  // vem depois: o resto da sequência é examinado de novo, com o texto anterior como contexto do título (Dr., Dra.).
  const trocar=(s,antes)=>s.replace(/\b([A-ZÀ-Ý][a-zà-ÿ]+)((?:\s+(?:(?:da|de|do|das|dos|e)\s+)?[A-ZÀ-Ý][a-zà-ÿ]+)*)/g,(m,p1,resto,off,full)=>{
    const fem=FEM.has(p1), masc=MASC.has(p1);
    const ctx=antes+full.slice(0,off);
    if(!fem&&!masc) return resto? p1+trocar(resto,ctx+p1) : m;
    if(prot.has(p1.toLowerCase())) return m;
    if(TIT.test(ctx.slice(-14))) return m;
    return fem?pal[0]:pal[1];
  });
  t=trocar(t,'');
  const MAP={da:"de",do:"de",na:"em",no:"em",pela:"por",pelo:"por",a:"",o:"",A:"",O:""};
  t=t.replace(/\b(da|do|na|no|pela|pelo|a|o|A|O) (uma|um) (cliente|paciente)/g,(m,p,a,c)=>(MAP[p]?MAP[p]+" ":"")+a+" "+c);
  return t.replace(/(^|[.!?]\s+)(um|uma) (cliente|paciente)/g,(m,p,a,c)=>p+a[0].toUpperCase()+a.slice(1)+" "+c);
}
