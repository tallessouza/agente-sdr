"""Retomada templates: who gets one, the 80/20 slot, sent once (Talles, 10/10/2026)."""
import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from test_cloud import pool_in_db

import app
import cloud
import fila
import handover
import prospeccao
import retomada
import sdr
import template_health as th

APPROVED_UTILITY = [{"name": "vencedor_001", "category": "UTILITY", "text": "Oi, {{1}}! Consigo falar com alguém por aqui? Tenho uma dúvida.", "params": ["saudacao_min"]}]


def prospect(numero, conversation, status, enviado_em, respondeu_em=None):
    import leads
    leads.save(numero, {"nome": f"Negócio {conversation}"})
    with prospeccao.connect() as c:
        c.execute("INSERT INTO sdr_prospects(numero,dados,status,enfileirado,jid,conversation,texto,enviado_em,respondeu_em) VALUES (?,?,?,?,?,?,?,?,?)",
                  (numero, json.dumps({"nome": f"Negócio {conversation}"}), status, enviado_em, f"{numero}@cloud", conversation, "Oi", enviado_em, respondeu_em))


def record(conversation, field, value):
    with sdr.connect() as c:
        c.execute("INSERT INTO sdr_records VALUES (?,?,?,?)", (conversation, field, value, time.time()))


class RetomadaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db),
                        patch.object(fila, "DB_PATH", db), patch.object(cloud, "CLOUD_INBOX_ID", 2)]
        for p in self.patches:
            p.start()
        app.db().close()
        prospeccao.connect().close()
        retomada.connect().close()
        pool_in_db([{"name": name, "category": "MARKETING", "text": text, "familia": familia, "saude": "UNKNOWN"}
                    for name, (familia, text, _example) in th.RETOMADAS.items()]
                   + [{"name": "retomada_sem_resposta_u01", "category": "UTILITY", "familia": "sem_resposta", "saude": "UNKNOWN",
                       "text": "Oi, {{1}}. Aqui é o agente do Talles, uma IA. {{2}} fiz um teste de atendimento no WhatsApp de vocês. {{3}} Pode me responder por aqui quando puder."}],
                   tipo="retomada")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_templates_respect_meta_shape(self):
        for name, (familia, text, example) in th.RETOMADAS.items():
            self.assertFalse(text.startswith("{{") or text.endswith("}}"), name)
            self.assertNotRegex(text, r"\}\}\s*\{\{", name)  # never two variables side by side
            self.assertEqual(text.count("{{"), 3, name)
            self.assertEqual(len(example), 3, name)
            fixed_words = len([w for w in text.split() if "{{" not in w])
            self.assertGreaterEqual(fixed_words, 3 * 3 + 1, name)
            self.assertTrue(text.rstrip().endswith("?"), name)  # ends in the question with the honest way out

    def test_who_may_get_a_retomada(self):
        from datetime import datetime
        now = datetime(2026, 10, 13, 10, 0, tzinfo=sdr.BUSINESS_TZ).timestamp()  # a Tuesday: the cadence runs on working days
        prospect("5548000000001", 201, "enviado", now - 20 * 3600)            # never answered, a day ago
        prospect("5548000000002", 202, "enviado", now - 2 * 3600)             # never answered, too soon
        prospect("5548000000003", 203, "respondeu", now - 30 * 3600, now - 29 * 3600)
        sdr.touch_activity(203, lead=True, ts=now - 29 * 3600); sdr.touch_activity(203, agent=True, ts=now - 28 * 3600)
        prospect("5548000000004", 204, "respondeu", now - 3 * 3600, now - 2 * 3600)  # window still open
        sdr.touch_activity(204, lead=True, ts=now - 2 * 3600)
        prospect("5548000000005", 205, "automatica", now - 30 * 3600, now - 30 * 3600)
        sdr.touch_activity(205, lead=True, ts=now - 30 * 3600); sdr.touch_activity(205, agent=True, ts=now - 30 * 3600)
        record(205, "resposta_automatica", "sim"); record(205, "desfecho", "avaliar_dono")
        prospect("5548000000006", 206, "respondeu", now - 30 * 3600, now - 30 * 3600)
        sdr.touch_activity(206, lead=True, ts=now - 30 * 3600)
        record(206, "opt_out", "sim")
        prospect("5548000000007", 207, "respondeu", now - 30 * 3600, now - 30 * 3600)  # a person said it closed
        sdr.touch_activity(207, lead=True, ts=now - 30 * 3600)
        record(207, "desfecho", "desqualificado")
        found = {c["conversation_id"]: c["familia"] for c in retomada.candidates(now)}
        # Only who never answered: who talked (203) and robots (205) follow the brain's sequence and its c1..c3 cadence.
        self.assertEqual(found, {201: "sem_resposta"})
        sunday = datetime(2026, 10, 11, 10, 0, tzinfo=sdr.BUSINESS_TZ).timestamp()
        self.assertEqual(retomada.candidates(sunday), [])  # working days only
        self.assertTrue(all(c["template"]["name"].startswith(f"retomada_{c['familia']}") for c in retomada.candidates(now)))
        self.assertEqual({c["negocio"]["nome"] for c in retomada.candidates(now)}, {"Negócio 201"})  # from the leads table

    def test_retomadas_have_their_own_80_20(self):
        # Talles 11/10: "uma farm de 80/20 pra abertura e outra de 80/20 pra retomada": utility first, marketing every 5th.
        self.assertEqual(retomada.pick("sem_resposta")["category"], "UTILITY")
        self.assertIsNone(retomada.pick("conversa"))  # no UTILITY of that family: none goes yet
        day = app.datetime_local(time.time()).strftime("%Y-%m-%d")
        prospeccao.kv_set(f"tpl:{day}:RET_UTILITY", "4")
        self.assertEqual(retomada.pick("sem_resposta")["category"], "MARKETING")
        self.assertTrue(th.is_utility_variant("retomada_robo_u03") and not th.is_utility_variant("retomada_robo_03"))
        self.assertEqual(th.familia_of("retomada_sem_resposta_u01"), "sem_resposta")

    def test_goes_out_only_in_the_marketing_slot_and_once(self):
        now = time.time()
        prospect("5548000000001", 201, "enviado", now - 20 * 3600)
        conn = app.db(); conn.execute("INSERT INTO contacts (jid, source_id, conversation_id, internal_id) VALUES (?,?,?,?)", ("5548000000001@cloud", "5548000000001", 201, 9201)); conn.commit(); conn.close()
        rid = retomada.schedule(201, "sem_resposta", "retomada_sem_resposta_01", ["pessoal do Negócio 201", "Ontem às 19h40",
                                "Quem chama depois do expediente\nfecha com quem responde primeiro."], now - 60, now + 3600, "tempo")
        day = app.datetime_local(now).strftime("%Y-%m-%d")
        with patch.object(cloud, "approved_templates", return_value=APPROVED_UTILITY), patch.object(app.handover, "paused", new=AsyncMock(return_value=False)), \
                patch.object(cloud, "post_message", new=AsyncMock()) as post, patch.object(sdr, "private_note", new=AsyncMock()):
            self.assertIsNone(asyncio.run(app.send_due_retomada(now)))  # 0 utility retomadas today: no marketing one yet
            prospeccao.kv_set(f"tpl:{day}:RET_UTILITY", "4")  # the openings' counters do not count (own 80/20)
            self.assertEqual(asyncio.run(app.send_due_retomada(now)), "retomada")
            self.assertIsNone(asyncio.run(app.send_due_retomada(now)))  # never twice
        post.assert_awaited_once()
        text = post.await_args.args[1]
        template = post.await_args.kwargs["template"]
        self.assertIn("Ontem às 19h40 mandei uma mensagem", text)
        self.assertNotIn("\n", template["processed_params"]["3"])  # Meta refuses line breaks inside a variable
        self.assertEqual(template["name"], "retomada_sem_resposta_01")
        self.assertEqual(post.await_args.kwargs["attributes"], {"bridge_retomada": rid, "bridge_template": "retomada_sem_resposta_01"})
        self.assertEqual(prospeccao.kv_get(f"tpl:{day}:RET_MARKETING"), "1")
        self.assertIsNone(prospeccao.kv_get(f"tpl:{day}:MARKETING"))  # the openings' 80/20 untouched
        self.assertEqual(retomada.history(201)[0]["status"], "enviada")
        self.assertEqual(retomada.candidates(now + 60), [])  # one a working day at most

    def test_past_business_window_expires(self):
        now = time.time()
        retomada.schedule(201, "sem_resposta", "retomada_sem_resposta_01", ["a", "b", "c"], now - 7200, now - 60)
        self.assertIsNone(retomada.due(now))
        self.assertEqual(retomada.history(201)[0]["status"], "expirada")

    def test_retomadas_never_enter_the_first_contact_pool_nor_get_trimmed(self):
        templates = [{"id": "9", "name": "retomada_conversa_01", "status": "APPROVED", "category": "MARKETING", "language": "pt_BR",
                      "components": [{"type": "BODY", "text": th.RETOMADAS["retomada_conversa_01"][1]}]}]
        if True:
            meta = th.load_meta()
            meta["templates"]["retomada_conversa_01"] = {"scheme": "retomada", "tipo": "retomada", "params": ["p1", "p2", "p3"], "estado": "pronto"}
            self.assertEqual(th.build_pool(templates, meta), [])
            with patch.object(th, "graph", new=AsyncMock()) as graph:
                self.assertEqual(asyncio.run(th.trim_marketing(templates, meta)), [])
                graph.assert_not_called()

    def test_generator_is_throttled_and_follows_the_winners(self):
        meta = {"submetidos": {}}
        now = time.time()
        self.assertEqual(th.new_batch_size(18, 27, meta, now), 0)   # 10/10: 18 approved + 27 pending already cover the target
        self.assertEqual(th.new_batch_size(5, 0, meta, now), 10)    # at most 10 a day
        today = time.strftime("%Y-%m-%d", time.gmtime(now - 3 * 3600))
        meta["submetidos"][today] = 8
        self.assertEqual(th.new_batch_size(5, 0, meta, now), 2)
        self.assertEqual(th.ACTIVE_SCHEMES, ["vencedor"])
        body = lambda text: [{"type": "BODY", "text": text}]
        decided = [{"name": f"vencedor_{i:03d}", "status": "APPROVED", "category": cat, "components": body(text)} for i, (cat, text) in enumerate([
            ("UTILITY", "Oi, {{1}}! Consigo falar com o atendimento por aqui? Tenho uma dúvida."),
            ("UTILITY", "Opa, {{1}}! Consigo falar com o atendimento por aqui? Tenho uma pergunta."),
            ("MARKETING", "Oi, {{1}}! Tem alguém atendendo agora? Tenho uma dúvida."),
            ("MARKETING", "Oi, {{1}}! Tem alguém atendendo agora? Tenho uma pergunta.")])]
        w = th.phrase_weights(decided)["pergunta"]
        self.assertGreater(w["Consigo falar com o atendimento por aqui"], w["Tem alguém atendendo agora"])


if __name__ == "__main__":
    unittest.main()
