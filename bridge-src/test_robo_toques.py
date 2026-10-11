"""Touches for robots and the 2 h gap between touches (Talles, 10/10/2026)."""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import app
import cloud
import fila
import handover
import monitor
import sdr

JID = "5548999990000@cloud"


def put(conversation, field, value):
    with sdr.connect() as c:
        c.execute("INSERT INTO sdr_records VALUES (?,?,?,?)", (conversation, field, value, time.time()))


def inbound(message_id, content):
    return {"event": "message_created", "id": message_id, "message_type": "incoming", "private": False, "content": content,
            "inbox": {"id": 2}, "conversation": {"id": 900, "display_id": 77, "inbox_id": 2}, "attachments": []}


class RobotTouchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db),
                        patch.object(fila, "DB_PATH", db), patch.object(fila, "MEDIA_DIR", Path(self.tmp.name) / "turnos"),
                        patch.object(cloud, "CLOUD_INBOX_ID", 2)]
        for p in self.patches:
            p.start()
        app.db().close()
        fila.connect().close()
        app.hermes_pending.clear()
        conn = app.db()
        conn.execute("INSERT INTO contacts (jid, source_id, conversation_id, internal_id) VALUES (?,?,?,?)", (JID, "5548999990000", 77, 900))
        conn.commit(); conn.close()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def robot(self):
        put(77, "resposta_automatica", "sim")
        put(77, "desfecho", "avaliar_dono")

    def send_due(self, now):
        with patch.object(app, "SDR_BRAIN_URL", "http://brain"), patch.object(app.handover, "paused", new=AsyncMock(return_value=False)), \
                patch.object(app, "SDR_BUSINESS_START_HOUR", 0), patch.object(app, "SDR_BUSINESS_END_HOUR", 24), \
                patch.object(app, "agent_presence", new=AsyncMock()), patch.object(app.sdr, "typing_seconds", return_value=0), \
                patch.object(cloud, "post_message", new=AsyncMock()) as post:
            asyncio.run(app.process_followups_once(now))
        return post

    def test_robot_outcome_does_not_stop_touches_but_a_real_one_does(self):
        self.robot()
        self.assertFalse(sdr.outcome_stops_touches(77))
        put(78, "resposta_automatica", "sim"); put(78, "desfecho", "desqualificado")  # #143: a person said it closed
        self.assertTrue(sdr.outcome_stops_touches(78))
        now = time.time()
        sdr.touch_activity(77, lead=True, ts=now - 3600); sdr.touch_activity(77, agent=True, ts=now - 3500)
        sdr.add_followup(77, now - 10, "Pra quem cuida do WhatsApp aí: a boas-vindas chegou em 5 segundos.", "robo", after_ts=now - 3600, stage="2h")
        post = self.send_due(now)
        post.assert_awaited_once()
        self.assertEqual(post.await_args.kwargs["attributes"], {"bridge_followup": True})

    def test_two_touches_never_closer_than_two_hours(self):
        # 10/10: the Nóris (#77) got 4 touches between 21:12 and 21:15.
        now = time.time()
        sdr.touch_activity(77, lead=True, ts=now - 3600); sdr.touch_activity(77, agent=True, ts=now - 3500)
        first = sdr.add_followup(77, now - 10, "Toque um", "t", after_ts=now - 3600, stage="2h")
        self.send_due(now).assert_awaited_once()
        second = sdr.add_followup(77, now + 60, "Toque dois", "t", after_ts=now - 3600, stage="d1")
        self.send_due(now + 90).assert_not_called()  # 90 s later: it waits
        with sdr.connect() as c:
            self.assertEqual(c.execute("SELECT status FROM sdr_followups WHERE id=?", (second,)).fetchone()[0], "pending")
        later = time.time() + 2 * 3600 + 5
        self.send_due(later).assert_awaited_once()
        with sdr.connect() as c:
            self.assertEqual([r[0] for r in c.execute("SELECT status FROM sdr_followups WHERE id IN (?,?) ORDER BY id", (first, second))], ["sent", "sent"])

    def test_same_touch_asked_twice_is_queued_once(self):
        now = time.time()
        first = sdr.add_followup(77, now, "Toque", "t", after_ts=now - 3600, stage="2h")
        self.assertEqual(sdr.add_followup(77, now + 5, "Toque de novo", "t", after_ts=now - 3600, stage="2h"), first)
        self.assertNotEqual(sdr.add_followup(77, now, "Outro estágio", "t", after_ts=now - 3600, stage="d1"), first)
        with sdr.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM sdr_followups WHERE conversation=77").fetchone()[0], 2)

    def test_robot_echo_does_not_reach_the_agent(self):
        self.robot()
        now = time.time()
        sdr.touch_activity(77, lead=True, ts=now - 3600); sdr.touch_activity(77, agent=True, ts=now - 3500)
        sdr.add_followup(77, now - 10, "Pra quem cuida do WhatsApp aí", "robo", after_ts=now - 3600, stage="2h")
        self.send_due(now)
        with patch.object(app, "queue_hermes_turn") as queue:
            asyncio.run(app.cloud_inbox_event(inbound(700, "Olá! Digite 1 para agendar, 2 para valores.")))  # seconds after the touch
            queue.assert_not_called()
        self.assertAlmostEqual(sdr.activity(77)[0], now - 3600)  # not the lead speaking: the touches go on
        with sdr.connect() as c:
            c.execute("UPDATE sdr_followups SET sent_at=sent_at-600")  # ten minutes later a person writes
        with patch.object(app, "queue_hermes_turn") as queue:
            asyncio.run(app.cloud_inbox_event(inbound(701, "Oi, sou a dona, pode falar")))
            queue.assert_called_once()
        with patch.object(app, "queue_hermes_turn") as queue:
            # The same menu text again, long after: still the robot.
            asyncio.run(app.cloud_inbox_event(inbound(702, "Olá! Digite 1 para agendar, 2 para valores.")))
            queue.assert_not_called()

    def test_monitor_does_not_count_touches_as_talking_to_the_robot(self):
        msgs = [{"id": 1, "message_type": 1, "created_at": 0, "content": "Oi, bom dia! Consigo falar com alguém?", "content_attributes": {"bridge_agent": True}},
                {"id": 2, "message_type": 0, "created_at": 5, "content": "Olá! Digite 1 para agendar."},
                {"id": 3, "message_type": 1, "created_at": 60, "content": "Também sou uma IA, de colega pra colega...", "content_attributes": {"bridge_agent": True}}]
        t = 60
        for i in range(4):
            t += 3 * 3600
            msgs.append({"id": 10 + i, "message_type": 1, "created_at": t, "content": f"Toque {i} pra quem cuida do WhatsApp aí",
                         "content_attributes": {"bridge_agent": True, "bridge_followup": True}})
            msgs.append({"id": 20 + i, "message_type": 0, "created_at": t + 4, "content": "Olá! Digite 1 para agendar."})
        self.assertFalse([f for f in monitor.patrol_findings(msgs, robot=True) if f[0] == "seguiu conversando com robô"])
        msgs.append({"id": 99, "message_type": 1, "created_at": t + 100, "content": "Opção 1, por favor", "content_attributes": {"bridge_agent": True}})
        self.assertTrue([f for f in monitor.patrol_findings(msgs, robot=True) if f[0] == "seguiu conversando com robô"])


if __name__ == "__main__":
    unittest.main()
