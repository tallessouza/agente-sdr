"""Owner alerts, the 131049 resend and the call log (panel next steps, closed on 11/10/2026)."""
import asyncio
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import alertas
import app
import cloud
import handover
import leads
import ligacoes
import prospeccao
import sdr
import template_health as th
from test_cloud import pool_in_db


class AlertasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db),
                        patch.object(cloud, "CLOUD_INBOX_ID", 2), patch.object(sdr, "NOTIFY_NUMBER", "5548999990099")]
        for p in self.patches:
            p.start()
        app.db().close()
        prospeccao.connect().close()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_each_alert_goes_once_through_the_first_channel_that_works(self):
        pool_in_db([{"name": "alerta_interno_01", "category": "UTILITY", "text": alertas.ALERT_TEMPLATE[1], "params": ["texto"]}], tipo="interno")
        with patch.object(cloud, "open_conversation", new=AsyncMock(return_value=("5548999990099", 300, 9300))) as opened, \
                patch.object(cloud, "post_message", new=AsyncMock()) as post:
            self.assertTrue(asyncio.run(alertas.notify("call:82:2026-10-13T10:00", "call", "📅 Call marcada: Visão Automóveis\nterça 10h", 82)))
            self.assertFalse(asyncio.run(alertas.notify("call:82:2026-10-13T10:00", "call", "📅 Call marcada: de novo", 82)))  # once
            self.assertTrue(asyncio.run(alertas.notify("ligar:70:1", "ligar", "📞 Para ligar: Possenti", 70)))
        opened.assert_awaited_once()  # the alert conversation is opened once and reused
        self.assertEqual(post.await_count, 2)
        template = post.await_args_list[0].kwargs["template"]
        self.assertEqual(template["name"], "alerta_interno_01")
        self.assertNotIn("\n", template["processed_params"]["1"])
        self.assertEqual([a["canal"] for a in alertas.recent()], ["oficial", "oficial"])

    def test_no_channel_is_recorded_not_silently_lost(self):
        self.assertFalse(asyncio.run(alertas.notify("canal:x", "canal", "⚠️ teste")))
        self.assertEqual(alertas.recent()[0]["erro"], "nenhum canal configurado")
        # Not lost: once a channel exists, the same alert goes out on the next try.
        with patch.object(alertas, "via_telegram", new=AsyncMock(return_value=True)):
            self.assertTrue(asyncio.run(alertas.notify("canal:x", "canal", "⚠️ teste")))
        self.assertEqual(alertas.recent()[0]["canal"], "telegram")

    def test_people_to_call_arrive_in_one_message_and_only_in_the_day(self):
        sent = []
        with patch.object(alertas, "send_text", new=AsyncMock(side_effect=lambda texto, ev=None: sent.append(texto) or ("oficial", ""))),                 patch.object(alertas, "para_ligar", return_value=[(f"ligar:{i}:1", f"lead {i}", i) for i in range(5)]),                 patch.object(alertas, "calls_marcadas", return_value=[]), patch.object(alertas, "canais", new=AsyncMock(return_value=[])):
            night = datetime(2026, 10, 11, 3, 0, tzinfo=sdr.BUSINESS_TZ).timestamp()
            self.assertEqual(asyncio.run(alertas.patrol(None, night)), 0)  # 3h: nothing for the owner's phone
            day = datetime(2026, 10, 11, 9, 0, tzinfo=sdr.BUSINESS_TZ).timestamp()
            self.assertEqual(asyncio.run(alertas.patrol(None, day)), 5)
            self.assertEqual(asyncio.run(alertas.patrol(None, day)), 0)  # once
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0].startswith("📞 Para ligar (5): lead 0 | lead 1"))

    def test_patrol_finds_booked_calls_and_people_to_call(self):
        now = time.time()
        tomorrow = datetime.fromtimestamp(now + 86400, sdr.BUSINESS_TZ).strftime("%Y-%m-%dT10:00")
        with sdr.connect() as c:
            for field, value in (("proximo_passo", "conversa de 20 min com o Talles"), ("proximo_passo_em", tomorrow)):
                c.execute("INSERT INTO sdr_records VALUES (82, ?, ?, ?)", (field, value, now))
        calls = alertas.calls_marcadas(now)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1][-5:], "(#82)")
        leads.save("5548999990001", {"nome": "Possenti & Silveira"})
        prospeccao.enqueue([{"telefone_e164": "+5548999990001", "nome": "Possenti & Silveira"}])
        prospeccao.update("5548999990001", status="respondeu", conversation=70, respondeu_em=now - 7200)
        sdr.touch_activity(70, lead=True, ts=now - 7200); sdr.touch_activity(70, agent=True, ts=now - 5000)
        self.assertEqual([x[2] for x in alertas.para_ligar(now)], [70])
        with sdr.connect() as c:
            c.execute("INSERT INTO sdr_records VALUES (70, 'resposta_automatica', 'sim', ?)", (now,))
        self.assertEqual(alertas.para_ligar(now), [])  # a robot is not a person to call

    def test_131049_gets_one_utility_resend_on_the_same_conversation(self):
        now = time.time()
        prospeccao.enqueue([{"telefone_e164": "+5548999990001", "nome": "Clínica X"}])
        prospeccao.update("5548999990001", status="enviado", conversation=77, jid="5548999990001@cloud", enviado_em=now - 25 * 3600)
        conn = app.db(); conn.execute("INSERT INTO contacts (jid, source_id, conversation_id, internal_id) VALUES (?,?,?,?)", ("5548999990001@cloud", "5548999990001", 77, 900)); conn.commit(); conn.close()
        failed = {"event": "message_updated", "id": 1, "status": "failed", "message_type": "outgoing", "inbox": {"id": 2},
                  "conversation": {"id": 900, "display_id": 77, "inbox_id": 2},
                  "content_attributes": {"bridge_agent": True, "bridge_template": "vencedor_001", "external_error": "131049: held for engagement"}}
        asyncio.run(app.cloud_inbox_event(failed))
        self.assertEqual(prospeccao.for_jid("5548999990001@cloud")["status"], "reenviar")
        pool_in_db([{"name": "vencedor_001", "category": "UTILITY", "text": "Oi, {{1}}! Consigo falar com alguém por aqui?", "params": ["saudacao_min"]},
                    {"name": "mkt_001", "category": "MARKETING", "text": "Olá, {{1}}! Tudo bem?", "params": ["saudacao_min"]}])
        with patch.object(cloud, "post_message", new=AsyncMock()) as post:
            self.assertEqual(asyncio.run(app.resend_after_131049(now)), "reenviado")
            self.assertIsNone(asyncio.run(app.resend_after_131049(now)))  # once
        self.assertEqual(post.await_args.args[0], 77)
        self.assertEqual(post.await_args.kwargs["template"]["category"], "UTILITY")
        asyncio.run(app.cloud_inbox_event(failed))  # held again: no third try
        self.assertEqual(prospeccao.for_jid("5548999990001@cloud")["status"], "erro")

    def test_short_business_names(self):
        self.assertEqual(alertas.curto("Clínica Odontológica Rident Palhoça | Implantes | Prótese"), "Clínica Odontológica Rident Palhoça")
        self.assertEqual(alertas.curto("Estética Nóris Acosta (Aurora Ramos Clínica Estética)"), "Estética Nóris Acosta")
        self.assertEqual(alertas.curto("J Maurício imobiliária - Especialistas"), "J Maurício imobiliária")
        self.assertEqual(alertas.curto("Possenti & Silveira Advogados"), "Possenti & Silveira Advogados")
        self.assertEqual(alertas.curto(""), "lead")

    def test_call_log(self):
        lid = ligacoes.registrar({"conversation": 82, "atendeu": "sim", "resultado": "agendou", "objecao": "quer ver preço antes", "nota": "dono"})
        self.assertEqual(ligacoes.listar(82)[0]["id"], lid)
        self.assertEqual(ligacoes.listar(82)[0]["atendeu"], 1)
        with self.assertRaises(ValueError):
            ligacoes.registrar({"conversation": 82, "resultado": "talvez"})

    def test_alert_template_never_enters_the_opening_pool(self):
        templates = [{"id": "5", "name": "alerta_interno_01", "status": "APPROVED", "category": "UTILITY", "language": "pt_BR",
                      "components": [{"type": "BODY", "text": alertas.ALERT_TEMPLATE[1]}]}]
        meta = th.load_meta()
        meta["templates"]["alerta_interno_01"] = {"scheme": "interno", "tipo": "interno", "params": ["texto"], "estado": "pronto"}
        self.assertEqual(th.build_pool(templates, meta), [])
        self.assertEqual(th.tipo_of("alerta_interno_01", meta), "interno")


if __name__ == "__main__":
    unittest.main()
