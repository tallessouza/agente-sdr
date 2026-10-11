"""Lead tables (leads.py), the JSON import (importar_leads.py) and the queue reading from the tables."""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import app
import handover
import importar_leads
import leads
import prospeccao
import sdr

TZ = sdr.BUSINESS_TZ
A, B, C = "5548999990101", "5548999990102", "5548999990103"   # A and B in the files; C only in sdr_prospects.dados
HOURS_A = ("segunda-feira: 08:00 to 12:00, 13:30 to 18:00; terça-feira: 08:00 to 18:00; quarta-feira: 08:00 to 18:00; "
           "quinta-feira: 08:00 to 18:00; sexta-feira: 08:00 to 18:00; sábado: 09:00 to 12:00; domingo: Fechado")
HOURS_B = ("segunda-feira: Atendimento 24 horas; terça-feira: Atendimento 24 horas; quarta-feira: Atendimento 24 horas; "
           "quinta-feira: Atendimento 24 horas; sexta-feira: Atendimento 24 horas; sábado: Atendimento 24 horas; domingo: Atendimento 24 horas")


def maps_item(numero, nome, horario):
    return {"nome": nome, "nicho": "clínica odontológica", "categoria": "Dentista", "cidade": "São José", "uf": "SC",
            "cidade_maps": "São José", "telefone_e164": numero, "provavel_whatsapp": True, "site": "https://exemplo.com.br/",
            "nota": 5, "avaliacoes": 120, "endereco": "R. Um, 10 - Centro, São José - SC, 88100-000, Brasil",
            "url_maps": "https://www.google.com/maps/search/?api=1&query=x&query_place_id=PID" + numero[-3:], "placeId": "PID" + numero[-3:],
            "horario": horario}


def write_files(folder: Path) -> Path:
    base = [maps_item(A, "Clínica A", HOURS_A), maps_item(B, "Clínica B", HOURS_B)]
    enriched = []
    for item in base:
        enriched.append({**item, "prioridade": 90, "bairro": "Centro", "categorias": ["Dentista", "Clínica odontológica"],
                         "descricao_maps": None, "horario_resumo": "seg a sex 8h–18h", "instagram": "@clinica_" + item["nome"][-1].lower(),
                         "facebook": None, "site_leva_pro_whatsapp": item["nome"].endswith("A"), "site_whatsapp": "5548999990000",
                         "servicos": ["Implante", "Ortodontia"], "site_titulo": "Clínica", "site_descricao": None, "site_erro": None,
                         "gancho": "Vocês têm 5,0 com 120 avaliações no Google.", "dossie": "Dossiê novo de " + item["nome"],
                         "enriquecido": True, "gancho_tipo": "avaliacoes",
                         "dias_abertos": [0, 1, 2, 3, 4, 5] if item["nome"].endswith("A") else [0, 1, 2, 3, 4, 5, 6],
                         "instagram_resumo": "Instagram: 10 seguidores", "decisor": "Decisor: Dra. Ana (dono; confiança alta)."})
    (folder / "negocios.json").write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    (folder / "negocios-enriquecidos.json").write_text(json.dumps(enriched, ensure_ascii=False), encoding="utf-8")
    decisores = {A: {"nome_negocio": "Clínica A", "prioridade": 1, "nicho": "clínica odontológica", "cidade": "São José",
                     "cnpj": "35604397000105", "razao_social": "CLINICA A LTDA", "socios": [{"nome": "ANA SOUZA", "qualificacao": "Sócio-Administrador"}],
                     "porte": "MICRO EMPRESA", "abertura": "25/11/2019",
                     "decisor": {"nome": "Ana Souza", "papel": "dono", "como_chamar": "Dra. Ana", "instagram_pessoal": "@ana",
                                 "contato_direto": None, "fonte_contato": None},
                     "evidencias": [{"fonte": "Receita", "url": "https://brasilapi.com.br/x", "trecho": "ANA SOUZA"}], "confianca": "alta"},
                 B: {"nome_negocio": "Clínica B", "prioridade": 2, "nicho": "clínica odontológica", "cidade": "São José", "cnpj": None,
                     "razao_social": None, "socios": [], "porte": None, "abertura": None, "decisor": None, "evidencias": [],
                     "confianca": "baixa", "nota": "sem CNPJ achado"}}
    (folder / "decisores.json").write_text(json.dumps(decisores, ensure_ascii=False), encoding="utf-8")
    perfis = {"clinica_a": {"username": "clinica_a", "fonte": "meta", "nome": "Clínica A", "seguidores": 10, "posts_total": 3, "bio": "bio",
                            "site": None, "privado": False, "erro": None,
                            "posts_recentes": [{"data": "2026-10-09", "legenda": "post 1"}],
                            "midias": [{"url": "https://www.instagram.com/p/1/", "ts": "2026-10-09T14:04:38+0000", "curtidas": None, "comentarios": 2,
                                        "tipo": "VIDEO", "legenda": "post 1", "data": "2026-10-09"},
                                       {"url": "https://www.instagram.com/p/2/", "ts": "2026-08-01T10:00:00+0000", "curtidas": 7, "comentarios": 0,
                                        "tipo": "IMAGE", "legenda": "post 2", "data": "2026-08-01"}]},
              "clinica_b": {"username": "clinica_b", "fonte": "falhou", "erro": "meta: 110/2207013 Invalid user id"}}
    (folder / "instagram-perfis.json").write_text(json.dumps(perfis, ensure_ascii=False), encoding="utf-8")
    fila = {"negocios": [{"telefone_e164": A, "nome": "Clínica A", "dossie": "Dossiê velho da fila"}]}
    (folder / "fila-prospeccao.json").write_text(json.dumps(fila, ensure_ascii=False), encoding="utf-8")
    report = [{"numero_fim": A[-4:], "nome": "Clínica A", "nicho": "clínica odontológica", "cidade": "São José", "canal": "oficial",
               "status": "respondeu", "conversa": 70, "tipo_resposta": "pessoa", "msgs_lead": 2, "msgs_agente": 3, "parou_em": "x",
               "etapa_spiced": "S", "quem_respondeu": "dono", "desfecho": None, "proximo_passo": None, "followup": "nenhum toque",
               "sinais_dossie": ["site", "bairro"], "usados": ["site"]},
              {"resumo": {"contatados": 1}}]
    (folder / "funil-10-10.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in report) + "\n", encoding="utf-8")
    classified = folder / "funil-classificado.json"
    classified.write_text(json.dumps([{"conversation": 70, "etapa_max": 2, "etapa_nome": "respondeu", "tipo": "pessoa", "parou_em": None,
                                       "objecao": None, "camada": None, "perda": "sem resposta", "prova": "Boa noite"}], ensure_ascii=False),
                          encoding="utf-8")
    return classified


def run_import(*argv: str) -> tuple[int, dict]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = importar_leads.main(list(argv))
    return code, json.loads(out.getvalue())


class LeadsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db)]
        for p in self.patches:
            p.start()
        self.folder = Path(self.tmp.name) / "dados"
        self.folder.mkdir()
        self.classified = write_files(self.folder)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def production_rows(self):
        """What production had before the import: A sent (older dossier, legado mark), C only in dados."""
        with prospeccao.connect() as c:
            c.execute("INSERT INTO sdr_prospects(numero,dados,status,enfileirado,jid,conversation,texto,enviado_em) VALUES (?,?,?,?,?,?,?,?)",
                      (A, json.dumps({"nome": "Clínica A", "dossie": "Dossiê de produção", "dias_abertos": [0, 1, 2, 3, 4, 5],
                                      "status_antes_legado": "enviado", "legado_em": "2026-10-10T21:27"}), "legado", 1.0,
                       A + "@s.whatsapp.net", 70, "Oi", 2.0))
            c.execute("INSERT INTO sdr_prospects(numero,dados,status,enfileirado) VALUES (?,?,?,?)",
                      (C, json.dumps({"nome": "Só na fila", "nicho": "imobiliária", "servicos": ["Locação"], "dias_abertos": [5],
                                      "site_leva_pro_whatsapp": False, "nota": 4.5}), "fila", 3.0))

    def test_import_is_idempotent_and_fills_every_table(self):
        self.production_rows()
        code, first = run_import("--dados", str(self.folder), "--classificacao", str(self.classified))
        self.assertEqual(code, 0)
        self.assertEqual(first["sdr_prospects_sem_lead"], 0)
        counts = first["tabelas_depois"]
        self.assertEqual((counts["leads"], counts["lead_decisores"], counts["lead_instagram"], counts["funil_classificacao"]), (3, 2, 2, 1))
        self.assertEqual((counts["lead_instagram_posts"], counts["lead_socios"], counts["lead_decisor_evidencias"], counts["funil_relatorio"]), (2, 1, 1, 1))
        self.assertEqual(counts["lead_horarios"], 8 + 7 + 7)   # A: 2 spans on Monday; B: 24 h every day; C: only the open days known
        code, second = run_import("--dados", str(self.folder), "--classificacao", str(self.classified))
        self.assertEqual(code, 0)
        self.assertEqual(second["tabelas_depois"], counts)
        self.assertEqual({k: v["alterados"] for k, v in second["por_destino"].items() if v["alterados"]}, {})
        with leads.connect() as c:
            self.assertEqual(c.execute("SELECT status_antes_legado, legado_em FROM sdr_prospects WHERE numero=?", (A,)).fetchone(),
                             ("enviado", "2026-10-10T21:27"))
            self.assertEqual(c.execute("SELECT fonte FROM leads WHERE numero=?", (C,)).fetchone()[0], "sdr_prospects")
            self.assertEqual(c.execute("SELECT numero FROM funil_classificacao WHERE conversation=70").fetchone()[0], A)

    def test_simulation_rolls_back(self):
        code, result = run_import("--dados", str(self.folder), "--simular")
        self.assertEqual(result["tabelas_depois"]["leads"], 2)
        self.assertEqual(leads.contagens()["leads"], 0)

    def test_reading_keeps_the_old_field_names(self):
        self.production_rows()
        run_import("--dados", str(self.folder), "--classificacao", str(self.classified))
        a = leads.lead(A)
        self.assertEqual(a["dossie"], "Dossiê de produção")          # production's dados wins for the fields the agent reads
        self.assertEqual(a["nota"], 5)
        self.assertIsInstance(a["nota"], int)
        self.assertEqual(a["servicos"], ["Implante", "Ortodontia"])
        self.assertEqual(a["dias_abertos"], [0, 1, 2, 3, 4, 5])
        self.assertIs(a["site_leva_pro_whatsapp"], True)
        self.assertEqual(a["instagram"], "@clinica_a")
        self.assertTrue(set(a) <= set(leads.FIELDS))
        self.assertEqual(leads.lead(C), {"nome": "Só na fila", "nicho": "imobiliária", "nota": 4.5, "servicos": ["Locação"],
                                         "site_leva_pro_whatsapp": False, "dias_abertos": [5]})
        self.assertIsNone(leads.lead("5548000000000"))
        hours = leads.horarios(A)
        self.assertEqual([(h["abre"], h["fecha"]) for h in hours if h["dia"] == 0], [("08:00", "12:00"), ("13:30", "18:00")])
        self.assertTrue(next(h for h in hours if h["dia"] == 6)["fechado"])
        self.assertTrue(all(h["aberto_24h"] for h in leads.horarios(B)))
        d = leads.decisor(A)
        self.assertEqual((d["decisor"]["como_chamar"], d["abertura"], d["socios"][0]["nome"], d["evidencias"][0]["fonte"]),
                         ("Dra. Ana", "2019-11-25", "ANA SOUZA", "Receita"))
        self.assertIsNone(leads.decisor(B)["decisor"])
        self.assertEqual(leads.decisor(B)["nota"], "sem CNPJ achado")
        ig = leads.instagram("@Clinica_A")
        self.assertEqual((ig["seguidores"], len(ig["midias"]), ig["posts_recentes"]), (10, 2, [{"data": "2026-10-09", "legenda": "post 1"}]))
        self.assertEqual(leads.instagram("clinica_b")["erro"], "meta: 110/2207013 Invalid user id")
        full = leads.ficha(A)
        self.assertEqual((full["place_id"], full["cep"], full["categorias"], full["decisor_resumo"]),
                         ("PID101", "88100-000", ["Dentista", "Clínica odontológica"], "Decisor: Dra. Ana (dono; confiança alta)."))
        self.assertEqual(full["instagram_perfil"]["username"], "clinica_a")
        self.assertEqual(leads.classificacoes()[0]["perda"], "sem resposta")

    def test_prefer_files_option(self):
        self.production_rows()
        run_import("--dados", str(self.folder), "--preferir-arquivos")
        self.assertEqual(leads.lead(A)["dossie"], "Dossiê novo de Clínica A")

    def test_queue_reads_the_tables_not_dados(self):
        self.production_rows()
        run_import("--dados", str(self.folder))
        with prospeccao.connect() as c:   # dados is no longer read: even broken JSON does not matter
            c.execute("UPDATE sdr_prospects SET dados='{quebrado'")
        number, data = prospeccao.next_queued()
        self.assertEqual((number, data["nome"]), (C, "Só na fila"))
        saturday = datetime(2026, 10, 10, 10, 0, tzinfo=TZ)
        sunday = datetime(2026, 10, 11, 10, 0, tzinfo=TZ)
        self.assertEqual(prospeccao.next_queued(local=saturday)[0], C)
        self.assertIsNone(prospeccao.next_queued(local=sunday))       # C opens on Saturday only
        leads.save(C, {"dias_abertos": [5, 6], "gancho": "Vi o site de vocês."})
        self.assertEqual(prospeccao.next_queued(local=sunday)[0], C)
        origin = prospeccao.origin(A + "@s.whatsapp.net")
        self.assertEqual((origin["negocio"]["nome"], origin["negocio"]["dossie"]), ("Clínica A", "Dossiê de produção"))
        self.assertEqual(prospeccao.owner_test_persona()["nome"], "Só na fila")

    def test_enqueue_writes_the_tables_and_keeps_what_they_know(self):
        run_import("--dados", str(self.folder))
        result = prospeccao.enqueue([{"telefone_e164": "+" + B, "nome": "Clínica B (fila)", "dossie": "", "extra": "x"},
                                     {"numero": "5548999990199", "nome": "Nova", "dias_abertos": [0, 1, 2, 3, 4], "servicos": ["Limpeza"]}])
        self.assertEqual(result, {"novos": 2, "repetidos": 0, "invalidos": 0})
        b = prospeccao.next_queued(B)[1]
        self.assertEqual((b["nome"], b["dossie"]), ("Clínica B (fila)", "Dossiê novo de Clínica B"))   # "" never clears
        self.assertNotIn("extra", b)
        self.assertEqual(prospeccao.next_queued("5548999990199")[1], {"nome": "Nova", "servicos": ["Limpeza"], "dias_abertos": [0, 1, 2, 3, 4]})
        with prospeccao.connect() as c:   # dados still written during the transition, from the tables
            self.assertEqual(json.loads(c.execute("SELECT dados FROM sdr_prospects WHERE numero=?", (B,)).fetchone()[0]), b)
            self.assertEqual(c.execute("SELECT fonte FROM leads WHERE numero='5548999990199'").fetchone()[0], "fila")
        self.assertEqual(prospeccao.refresh_data([{"numero": B, "dias_abertos": [5]}]), 1)
        self.assertEqual(prospeccao.next_queued(B)[1]["dias_abertos"], [5])
        self.assertEqual(leads.horarios(B)[0]["abre"], None)   # only the open days known now

    def test_owner_test_persona_lives_in_the_tables_and_is_cleaned(self):
        prospeccao.enqueue([{"numero": A, "nome": "Clínica A", "gancho": "Vocês respondem rápido."}])
        owner = "5564999425822"
        persona = prospeccao.owner_test_persona()
        prospeccao.simulate_owner_test(owner, owner + "@cloud", 90, persona, "Oi", 100.0)
        origin = prospeccao.origin(owner + "@cloud")
        self.assertEqual(origin["negocio"], {"nome": "Clínica A", "gancho": "Vocês respondem rápido.", "teste_do_dono": True})
        self.assertEqual(prospeccao.owner_test_persona()["nome"], "Clínica A")   # never the test copy
        prospeccao.clear_owner_test(owner)
        self.assertIsNone(leads.lead(owner))
        self.assertEqual(leads.lead(A)["nome"], "Clínica A")

    def test_pitch_uses_the_hook_from_the_tables(self):
        prospeccao.enqueue([{"numero": A, "nome": "Clínica A"}])
        prospeccao.update(A, status="enviado", enviado_em=datetime(2026, 10, 13, 19, 0, tzinfo=TZ).timestamp(), conversation=71)
        leads.save(A, {"gancho": "Vi que o site de vocês leva direto pro WhatsApp."})
        prospeccao.schedule_pitch(71, datetime(2026, 10, 13, 19, 0, tzinfo=TZ).timestamp(), now=datetime(2026, 10, 13, 19, 5, tzinfo=TZ).timestamp())
        text = sdr.pending_followups(71)[0][3]
        self.assertIn("Vi que o site de vocês leva direto pro WhatsApp.", text)

    def test_hours_parser(self):
        self.assertEqual(leads.parse_hours("domingo: Fechado; segunda-feira: 9:00 to 12:00"),
                         [(6, 0, None, None, 1, 0), (0, 0, "09:00", "12:00", 0, 0)])
        self.assertEqual(leads.instagram_user("https://www.instagram.com/Foo_Bar/?hl=pt"), "foo_bar")



class Only24hTests(unittest.TestCase):
    """Talles, 11/10: test the businesses that say they are open 24 h, at any hour, and only them."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db)]
        for p in self.patches:
            p.start()
        prospeccao.enqueue([{"telefone_e164": "+5548999990001", "nome": "Escritório Dia", "horario": "segunda-feira: 08:00 to 18:00; domingo: Fechado"},
                            {"telefone_e164": "+5548999990002", "nome": "Advocacia 24h", "horario": "; ".join(f"{d}: Atendimento 24 horas" for d in ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"))}])

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_filter_picks_only_24h_at_any_hour(self):
        from datetime import datetime
        sunday_night = datetime(2026, 10, 11, 2, 0, tzinfo=sdr.BUSINESS_TZ)
        self.assertFalse(prospeccao.in_window(sunday_night))
        prospeccao.kv_set("prospeccao_filtro", "24h")
        self.assertTrue(prospeccao.in_window(sunday_night))
        self.assertEqual(prospeccao.next_queued(None, sunday_night)[0], "5548999990002")
        prospeccao.update("5548999990002", status="enviado")
        self.assertIsNone(prospeccao.next_queued(None, sunday_night))  # the daytime office never goes out under the filter
        prospeccao.kv_set("prospeccao_filtro", "")
        monday = datetime(2026, 10, 19, 10, 0, tzinfo=sdr.BUSINESS_TZ)  # a Monday morning: the office is open
        self.assertEqual(prospeccao.next_queued(None, monday)[0], "5548999990001")  # filter off: back to normal

if __name__ == "__main__":
    unittest.main()
