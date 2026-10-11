"""Nothing depends on JSON (Talles, 11/10/2026): the agenda lives in the database and the collection steps write
straight into it through importar_leads.py --stdin."""
import io
import json
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import importar_leads
import leads
import prospeccao
import sdr


class BancoCentralTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "bridge.db"
        self.offers_file = Path(self.tmp.name) / "ofertas.json"
        self.offers_file.write_text(json.dumps({"atendimento": {"produto": "atendente", "horarios_ocupados": [{"quando": "2020-01-01T10:00", "o_que": "velho"}]}}),
                                    encoding="utf-8")
        self.patches = [patch.object(sdr, "DB_PATH", self.db), patch.object(sdr, "OFFERS_FILE", self.offers_file)]
        for p in self.patches:
            p.start()
        prospeccao.connect().close()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_agenda_comes_from_the_database_never_from_the_file(self):
        tomorrow = datetime.fromtimestamp(time.time() + 86400, sdr.BUSINESS_TZ).strftime("%Y-%m-%dT10:00")
        with sdr.connect() as c:  # the call the agent booked (#82, Ademir)
            for field, value in (("proximo_passo", "conversa de 20 min com o Talles"), ("proximo_passo_em", tomorrow)):
                c.execute("INSERT INTO sdr_records VALUES (82, ?, ?, ?)", (field, value, time.time()))
        sdr.add_busy(tomorrow.replace("T10", "T15"), "reunião do Talles")
        busy = sdr.offers()["atendimento"]["horarios_ocupados"]
        self.assertEqual([b["quando"] for b in busy], [tomorrow, tomorrow.replace("T10", "T15")])
        self.assertIn("conversa 82", busy[0]["o_que"])
        self.assertNotIn("2020-01-01T10:00", [b["quando"] for b in busy])  # what the file says is ignored
        self.assertIn("Nunca ofereça", sdr.offers()["atendimento"]["regra_horarios_ocupados"])
        self.assertEqual(sdr.remove_busy(tomorrow.replace("T10", "T15")), 1)
        self.assertEqual(len(sdr.offers()["atendimento"]["horarios_ocupados"]), 1)

    def run_import(self, payload):
        with patch("sys.stdin", io.StringIO(json.dumps(payload))), patch("sys.stdout", io.StringIO()) as out:
            code = importar_leads.main(["--stdin", "--db", str(self.db)])
        printed = out.getvalue()
        return code, json.loads(printed[printed.index("{"):])["por_destino"]

    def test_collection_step_writes_straight_into_the_database(self):
        payload = {"arquivos": {"negocios-enriquecidos.json": [{"telefone_e164": "+5548999990001", "nome": "Clínica Nova", "nicho": "clínica odontológica",
                                                                "cidade": "São José", "horario_resumo": "seg a sex 8h–18h"}]}}
        self.assertEqual(self.run_import(payload)[0], 0)
        self.assertEqual(leads.lead("5548999990001")["nome"], "Clínica Nova")
        # A newer collection wins over what the bank had (the step sends fresher data).
        payload["arquivos"]["negocios-enriquecidos.json"][0]["nome"] = "Clínica Nova Sorriso"
        self.run_import(payload)
        self.assertEqual(leads.lead("5548999990001")["nome"], "Clínica Nova Sorriso")
        code, report = self.run_import(payload)
        self.assertEqual(code, 0)
        self.assertEqual(sum(v["alterados"] for k, v in report.items() if k.startswith("leads (")), 0)  # idempotent


if __name__ == "__main__":
    unittest.main()
