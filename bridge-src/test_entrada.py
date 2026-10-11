"""The Instagram "TESTE" entry (Talles 11/10, 17-prospeccao/SDR-ENTRADA-TESTE-INSTAGRAM.md)."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import alertas
import app
import entrada
import handover
import leads
import prospeccao
import sdr

PEDIDO = "Quero o teste de tempo de resposta. O WhatsApp da minha empresa é: (48) 3333-0000"


class EntradaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db),
                        patch.object(sdr, "_chatwoot", new=AsyncMock()), patch.object(sdr, "add_label", new=AsyncMock())]
        for p in self.patches:
            p.start()
        app.db().close()
        prospeccao.connect().close()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_owner_request_then_company_message(self):
        self.assertEqual(asyncio.run(entrada.on_message(300, "5548999990000@cloud", PEDIDO)), "pedido")
        row = entrada.listar()[0]
        self.assertEqual((row["conversa_dono"], row["numero_dono"], row["numero_empresa"], row["status"]), (300, "5548999990000", "554833330000", "pedido"))
        self.assertEqual(sdr.records_of(300).get("origem"), "instagram-teste")
        self.assertEqual(sdr.records_of(300).get("numero_empresa"), "554833330000")
        self.assertIsNotNone(leads.lead("554833330000"))                 # the company is a lead in the central database
        sdr.add_label.assert_awaited_with(300, "teste-instagram")
        with prospeccao.connect() as c:  # the owner shows up like any conversation, never queued for a cold opening
            self.assertEqual(c.execute("SELECT status, conversation FROM sdr_prospects WHERE numero='5548999990000'").fetchone(), ("respondeu", 300))
        self.assertIsNone(prospeccao.next_queued())
        asyncio.run(sdr.record(300, "decisor", "Carlos"))
        with patch.object(handover, "pause", new=AsyncMock()) as pause, patch.object(alertas, "notify", new=AsyncMock(return_value=True)) as notify:
            self.assertEqual(asyncio.run(entrada.on_message(301, "554833330000@cloud", "Quero fazer um teste")), "empresa")
        pause.assert_awaited_once_with(301)                               # Talles sends the test and the result
        texto = notify.await_args.args[2]
        self.assertIn("Carlos", texto); self.assertIn("#300", texto); self.assertIn("#301", texto)
        row = entrada.listar()[0]
        self.assertEqual((row["conversa_empresa"], row["status"]), (301, "empresa_escreveu"))
        self.assertEqual(sdr.records_of(301).get("conversa_dono"), "300")

    def test_other_messages_are_not_entries(self):
        self.assertIsNone(asyncio.run(entrada.on_message(302, "5548999990001@cloud", "Bom dia, vocês atendem?")))
        self.assertIsNone(asyncio.run(entrada.on_message(302, "5548999990001@cloud", "quero fazer um teste de produto amanhã")))
        self.assertEqual(entrada.listar(), [])


class AnexoTests(unittest.TestCase):
    def test_attachment_download_retries_while_chatwoot_stores_the_file(self):
        # 11/10 (#147): the audio's URL answered 404 at webhook time and the voice note never reached the agent.
        import httpx
        nao_achou = httpx.Response(404, request=httpx.Request("GET", "https://cw/x.ogg"))
        ok = httpx.Response(200, content=b"OggS...", headers={"content-type": "audio/ogg"}, request=httpx.Request("GET", "https://cw/x.ogg"))
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock(side_effect=[nao_achou, nao_achou, ok])), \
                patch.object(app.asyncio, "sleep", new=AsyncMock()):
            item = asyncio.run(app.download_chatwoot_attachment({"data_url": "https://cw/x.ogg", "file_type": "audio", "file_name": "File.ogg"}))
        self.assertIsNotNone(item)
        self.assertEqual(item[1], "audio/ogg")


if __name__ == "__main__":
    unittest.main()
