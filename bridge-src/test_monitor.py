import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import app
import handover
import monitor
import sdr


def msg(i, kind, text, agent=False, ts=None):
    return {"id": i, "message_type": 1 if kind == "nós" else 0, "content": text, "created_at": ts or i,
            "content_attributes": {"bridge_agent": True} if agent else {}}


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db),
                        patch.object(monitor, "DB_PATH", str(db))]
        for p in self.patches:
            p.start()
        app.db().close()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_prospect_reply_about_the_installer_or_a_price_is_held(self):
        installer = ["Como corretor, o time de IA no Telegram te ajuda no dia a dia.", "A instalação é R$ 47, pagamento único."]
        reasons = monitor.pre_send(installer, "atendimento", sdr.FALLBACK_REPLY)
        self.assertIn("preço na conversa", reasons)
        self.assertIn("oferta do Instalador (Telegram)", reasons)
        self.assertEqual(monitor.pre_send(installer, "instalador", sdr.FALLBACK_REPLY), [])  # right offer, right words
        self.assertEqual(monitor.pre_send(["Sou o agente do Talles. Quem responde o WhatsApp aí hoje?"], "atendimento", sdr.FALLBACK_REPLY), [])

    def test_waiting_phrase_is_held_only_in_a_prospect(self):
        self.assertTrue(monitor.pre_send([sdr.FALLBACK_REPLY], "atendimento", sdr.FALLBACK_REPLY))
        self.assertEqual(monitor.pre_send([sdr.FALLBACK_REPLY], "instalador", sdr.FALLBACK_REPLY), [])

    def test_model_error_text_is_held_anywhere(self):
        reasons = monitor.pre_send(["All credentials for model gemini-3.7-flash-high are cooling down"], None, sdr.FALLBACK_REPLY)
        self.assertTrue(any("cooling down" in r for r in reasons))
        self.assertEqual(monitor.pre_send(["Você assina a Conta do Gemini?"], "instalador", sdr.FALLBACK_REPLY), [])

    def test_held_reply_is_not_sent_and_the_conversation_pauses(self):
        with patch.object(sdr, "lead_state", return_value={"oferta": "atendimento"}), patch.object(app, "review_reply", new=AsyncMock(side_effect=lambda j, c, l, p, d: (p, d))), \
                patch.object(app, "agent_send_text", new=AsyncMock()) as send, patch.object(handover, "pause", new=AsyncMock()) as pause, \
                patch.object(sdr, "private_note", new=AsyncMock()) as note, patch.object(sdr, "add_label", new=AsyncMock()), \
                patch.object(app.prospeccao, "bot_loop", return_value=False):
            delivered = asyncio.run(app.deliver_agent_reply("5548999990000@cloud", "5548999990000", 77, "A instalação é R$ 47, pagamento único.", None, "quanto custa?"))
        self.assertTrue(delivered)
        send.assert_not_called()
        pause.assert_awaited_once_with(77)
        self.assertIn("R$ 47", note.await_args.args[1])
        self.assertEqual(monitor.recent_alerts()[0]["conversation"], 77)

    def test_patrol_finds_repeats_bursts_opt_out_errors_and_robot_chatter(self):
        repeated = [msg(1, "nós", "Oi, boa noite! Vocês atendem por aqui? Queria tirar uma dúvida.", True),
                    msg(2, "eles", "Oi"), msg(3, "nós", "Oi, boa noite! Vocês atendem por aqui? Queria tirar uma dúvida.", True)]
        self.assertEqual([f[0] for f in monitor.patrol_findings(repeated)], ["mensagem repetida"])
        burst = [msg(i, "nós", f"mensagem {i}", True) for i in range(1, 7)]
        self.assertIn("muitas mensagens seguidas sem resposta", [f[0] for f in monitor.patrol_findings(burst)])
        optout = [msg(1, "nós", "teste", True), msg(2, "eles", "Não tenho interesse, obrigado"), msg(3, "nós", "Entendo! Mas posso te mostrar em 20 minutos?", True)]
        self.assertIn("resposta depois de pedido para parar", [f[0] for f in monitor.patrol_findings(optout)])
        error = [msg(1, "nós", "HTTP 429: rate limit exceeded", True)]
        self.assertIn("texto interno vazou", [f[0] for f in monitor.patrol_findings(error)])
        robot = [msg(1, "nós", "teste", True), msg(2, "eles", "Olá! Sou a assistente virtual."), msg(3, "nós", "Oi, colega!", True),
                 msg(4, "eles", "Como posso ajudar?"), msg(5, "nós", "mais uma", True), msg(6, "nós", "e outra", True)]
        self.assertIn("seguiu conversando com robô", [f[0] for f in monitor.patrol_findings(robot, robot=True)])
        human = [msg(1, "nós", "Oi, boa noite! Vocês atendem por aqui?", True), msg(2, "eles", "Boa noite, pois não?"),
                 msg(3, "nós", "Sou o agente do Talles, foi um teste.", True)]
        self.assertEqual(monitor.patrol_findings(human), [])

    def test_each_alert_acts_once(self):
        messages = [msg(1, "nós", "Oi, boa noite! Vocês atendem por aqui? Queria tirar uma dúvida.", True),
                    msg(2, "nós", "Oi, boa noite! Vocês atendem por aqui? Queria tirar uma dúvida.", True)]
        pause, note, label = AsyncMock(), AsyncMock(), AsyncMock()
        with patch.object(monitor, "messages_of", new=AsyncMock(return_value=messages)):
            first = asyncio.run(monitor.patrol([(77, False)], pause, note, label))
            second = asyncio.run(monitor.patrol([(77, False)], pause, note, label))
        self.assertEqual((first, second), (1, 0))
        pause.assert_awaited_once_with(77)
        label.assert_awaited_once_with(77, "monitor-alerta")


if __name__ == "__main__":
    unittest.main()
