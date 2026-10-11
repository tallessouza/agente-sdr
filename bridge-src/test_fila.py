import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import app
import fila
import handover
import monitor
import sdr


class FilaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db),
                        patch.object(fila, "DB_PATH", db), patch.object(fila, "MEDIA_DIR", Path(self.tmp.name) / "turnos"),
                        patch.object(monitor, "DB_PATH", str(db))]
        for p in self.patches:
            p.start()
        app.db().close()
        app.hermes_pending.clear()
        app.hermes_tasks.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_turn_and_its_media_are_stored_once(self):
        media = [(b"OggS-audio", "audio/ogg", "audio.ogg")]
        self.assertTrue(fila.save_turn("5548@cloud", 7, "5548", "Boa noite", media, "cw:1", None))
        self.assertFalse(fila.save_turn("5548@cloud", 7, "5548", "Boa noite", media, "cw:1", None))  # redelivery
        _, turns = fila.unfinished()
        self.assertEqual([t["external_id"] for t in turns], ["cw:1"])
        self.assertEqual(fila.load_media(turns[0]["media"]), media)

    def test_cut_reply_resumes_only_the_missing_parts(self):
        fila.save_turn("5548@cloud", 7, "5548", "Boa noite", None, "cw:1", None)
        fila.start_batch("l:cw:1", ["cw:1"], "5548@cloud", 7, "5548", "Boa noite", "cw:1")
        reply = "Parte um.\n\nParte dois.\n\nParte três."
        sent = []

        async def send(jid, source, conv, text, reply_to=None):
            if len(sent) == 1:
                raise RuntimeError("bridge restarting")  # the deploy cuts after the first part
            sent.append(text)

        common = [patch.object(app, "review_reply", new=AsyncMock(side_effect=lambda j, c, l, p, d: (p, d))), patch.object(app, "agent_presence", new=AsyncMock()),
                  patch.object(sdr, "typing_seconds", return_value=0), patch.object(app.prospeccao, "bot_loop", return_value=False),
                  patch.object(sdr, "lead_state", return_value={}), patch.object(app, "fire_and_forget"), patch.object(app, "escalate", new=AsyncMock())]
        for p in common:
            p.start()
        try:
            with patch.object(app, "agent_send_text", new=AsyncMock(side_effect=send)):
                with self.assertRaises(RuntimeError):
                    asyncio.run(app.deliver_agent_reply("5548@cloud", "5548", 7, reply, "cw:1", "Boa noite", lote="l:cw:1"))
            parts, _, already = fila.final_parts("l:cw:1")
            self.assertEqual(already, 1)
            batches, _ = fila.unfinished()
            self.assertEqual([b["lote"] for b in batches], ["l:cw:1"])
            with patch.object(app, "agent_send_text", new=AsyncMock()) as resend:
                asyncio.run(app.redeliver_batch(batches[0]))
            self.assertEqual([c.args[3] for c in resend.await_args_list], parts[1:])  # never the first part again
            self.assertEqual(fila.unfinished(), ([], []))
        finally:
            for p in common:
                p.stop()

    def test_unanswered_message_goes_back_in_line_after_a_restart(self):
        fila.save_turn("5548@cloud", 7, "5548", "Boa noite", None, "cw:1", None)
        fila.start_batch("l:cw:1", ["cw:1"], "5548@cloud", 7, "5548", "Boa noite", "cw:1")  # Hermes was thinking when it died

        async def run():
            with patch.object(app, "hermes_batch_worker", new=AsyncMock()) as worker:
                self.assertEqual(app.recover_turns(), 1)
                await asyncio.sleep(0)
                return worker

        worker = asyncio.run(run())
        self.assertEqual(app.hermes_pending["5548@cloud"][0][0], "Boa noite")
        worker.assert_called_once_with("5548@cloud")

    def test_brain_notice_is_retried_until_it_arrives(self):
        with patch.object(app, "SDR_BRAIN_URL", "http://brain"), patch.object(app.httpx, "AsyncClient") as client:
            client.return_value.__aenter__.return_value.post = AsyncMock(side_effect=RuntimeError("brain restarting"))
            asyncio.run(app.brain_event("/events/exchange", {"conversation_id": 69}))
            with fila.connect() as c:
                self.assertEqual(c.execute("SELECT status, tentativas FROM brain_eventos").fetchone(), ("pendente", 1))
                c.execute("UPDATE brain_eventos SET proxima=0")
            ok = AsyncMock()
            ok.return_value.raise_for_status = lambda: None
            client.return_value.__aenter__.return_value.post = ok
            for event_id, path, payload, attempts in fila.due_events():
                asyncio.run(app.deliver_brain_event(event_id, path, payload, attempts))
            with fila.connect() as c:
                self.assertEqual(c.execute("SELECT status FROM brain_eventos").fetchone()[0], "feito")
            self.assertEqual(ok.await_args.kwargs["json"], {"conversation_id": 69})


if __name__ == "__main__":
    unittest.main()
