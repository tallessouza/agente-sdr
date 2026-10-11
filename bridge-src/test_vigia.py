"""The follow-up vigia (Talles, 11/10/2026: "não me faça passar vergonha")."""
import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import alertas
import app
import handover
import prospeccao
import retomada
import sdr
import vigia


def ts(*a):
    return datetime(*a, tzinfo=sdr.BUSINESS_TZ).timestamp()


class VigiaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db)]
        for p in self.patches:
            p.start()
        app.db().close()
        prospeccao.connect().close()
        retomada.connect().close()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def plan(self, conv, *stages, **extra):
        return {str(conv): {"plano": [{"estagio": s, "quando": q, "canal": c, "decidido": d} for s, q, c, d in stages],
                            "pausada": False, "para_toques": False, "objecao": False, "robo": False, "lead_falou_por_ultimo": False, **extra}}

    def kinds(self, found):
        return sorted({f["tipo"] for f in found})

    def test_burst_and_out_of_hours_sends_are_caught(self):
        # 10/10: the Nóris got 4 touches between 21:12 and 21:15.
        with sdr.connect() as c:
            for i, sent in enumerate((ts(2026, 10, 10, 21, 12), ts(2026, 10, 10, 21, 13))):
                c.execute("INSERT INTO sdr_followups(conversation,send_at,text,stage,status,sent_at) VALUES (77,?,?,?,'sent',?)", (sent, "t", f"s{i}", sent))
        found = vigia.findings(self.plan(77), ts(2026, 10, 11, 9, 0))
        self.assertEqual(self.kinds(found), ["fora_de_hora", "rajada"])

    def test_late_touch_pending_send_and_waiting_lead(self):
        now = ts(2026, 10, 13, 15, 0)
        plan = self.plan(70, ("2h", now - 3600, "texto", False), ("d1", now + 3600, "texto", False), ("d3", now + 7200, "texto", False),
                         ("d6", now + 10800, "template", False))
        with sdr.connect() as c:
            c.execute("INSERT INTO sdr_followups(conversation,send_at,text,stage,status) VALUES (70,?,?,?,'pending')", (now - 1800, "t", "2h"))
        sdr.touch_activity(71, lead=True, ts=now - 1200); sdr.touch_activity(71, agent=True, ts=now - 3600)
        plan.update(self.plan(71))
        found = vigia.findings(plan, now)
        self.assertEqual(self.kinds(found), ["esperando", "nao_saiu", "vencido"])
        self.assertTrue(any("toque 2h" in f["detalhe"] for f in found))

    def test_templates_without_a_slot_and_untracked_answers(self):
        now = ts(2026, 10, 13, 10, 0)
        with retomada.connect() as c:
            c.execute("INSERT INTO sdr_retomadas(conversation,familia,template,params,send_at,send_until,status,criado) "
                      "VALUES (201,'sem_resposta','t','[]',?,?,'pendente',?)", (now - 7200, now + 3600, now))
        prospeccao.enqueue([{"telefone_e164": "+5548999990001", "nome": "Rident"}])
        prospeccao.update("5548999990001", status="respondeu", conversation=71, jid="5548999990001@cloud")
        full = [("2h", now - 90000, "texto", True), ("d1", now - 80000, "texto", True), ("d3", now - 70000, "texto", True), ("d6", now + 3600, "template", False)]
        found = vigia.findings(self.plan(70, *full), now, utility_slots_ahead=0)
        self.assertEqual(self.kinds(found), ["sem_acompanhamento", "template", "vaga"])
        self.assertIn("2 toques por template", next(f for f in found if f["tipo"] == "vaga")["detalhe"])

    def test_sequence_ended_before_the_cadence(self):
        now = ts(2026, 10, 13, 10, 0)
        stages = [(s, now - 90000, "texto", True) for s in ("2h", "d1", "d3", "d6")] + [("c1", now + 3600, "template", False)]
        found = vigia.findings(self.plan(31, *stages, encerrada="completa"), now)
        self.assertEqual(self.kinds(found), ["sem_cadencia"])

    def test_problems_are_stored_once_resolved_and_sent_in_one_hourly_message(self):
        now = ts(2026, 10, 13, 10, 0)
        sdr.touch_activity(71, lead=True, ts=now - 1200); sdr.touch_activity(71, agent=True, ts=now - 3600)
        sent = []
        with patch.object(vigia, "fetch_plan", new=AsyncMock(return_value=self.plan(71))), \
                patch.object(alertas, "send_text", new=AsyncMock(side_effect=lambda texto, ev=None: sent.append(texto) or ("oficial", ""))):
            self.assertEqual(asyncio.run(vigia.patrol(None, now)), 1)
            self.assertEqual(asyncio.run(vigia.patrol(None, now + 600)), 0)  # same problem: not again
        self.assertEqual(len(sent), 1)
        self.assertIn("ninguém respondeu", sent[0])
        sdr.touch_activity(71, agent=True, ts=now + 900)  # answered: resolved
        with patch.object(vigia, "fetch_plan", new=AsyncMock(return_value=self.plan(71))):
            asyncio.run(vigia.patrol(None, now + 1200))
        self.assertEqual(vigia.open_findings(), [])

    def test_quiet_at_night(self):
        night = ts(2026, 10, 13, 2, 0)
        sdr.touch_activity(71, lead=True, ts=night - 1200); sdr.touch_activity(71, agent=True, ts=night - 3600)
        with patch.object(vigia, "fetch_plan", new=AsyncMock(return_value=self.plan(71))), \
                patch.object(alertas, "send_text", new=AsyncMock(return_value=("oficial", ""))) as send:
            self.assertEqual(asyncio.run(vigia.patrol(None, night)), 0)
        send.assert_not_called()
        self.assertEqual(len(vigia.open_findings()), 1)  # recorded for the panel, told in the morning


if __name__ == "__main__":
    unittest.main()
