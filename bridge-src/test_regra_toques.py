"""Talles 11/10: opening in the business's hours; no answer -> 3 retomadas inside 24 h (6 h, sliding to 2 h while open,
or as soon as it opens); queue over -> pause and tell."""
import json
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import app
import handover
import leads
import prospeccao
import retomada
import sdr
import vigia

WEEKDAYS_8_18 = ("segunda-feira: 08:00 to 18:00; terça-feira: 08:00 to 18:00; quarta-feira: 08:00 to 18:00; "
                 "quinta-feira: 08:00 to 18:00; sexta-feira: 08:00 to 18:00; sábado: Fechado; domingo: Fechado")


def ts(*a):
    return datetime(*a, tzinfo=sdr.BUSINESS_TZ).timestamp()


def hm(t):
    return datetime.fromtimestamp(t, sdr.BUSINESS_TZ).strftime("%a %H:%M")


class RegraToquesTests(unittest.TestCase):
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

    def queue(self, numero, horario=None):
        if horario:
            leads.save(numero, {"nome": f"Negócio {numero[-3:]}", "horario_google": horario})
        with prospeccao.connect() as c:
            c.execute("INSERT INTO sdr_prospects(numero,dados,status,enfileirado) VALUES (?,?,?,?)", (numero, json.dumps({}), "fila", time.time()))

    def test_three_retomadas_inside_24h_sliding_in_open_hours(self):
        leads.save("5548000000101", {"nome": "Negócio 101", "horario_google": WEEKDAYS_8_18})
        self.assertTrue(retomada.leads.horarios("5548000000101"))
        opened = ts(2026, 10, 13, 10, 0)  # Tuesday 10h
        slots = retomada.slot_times("5548000000101", opened)
        shown = [hm(s) for s in slots]
        self.assertEqual(len(slots), 3, shown)
        self.assertTrue(all(b - a >= 2 * 3600 for a, b in zip([opened] + slots, slots)), shown)
        self.assertTrue(all(8 <= datetime.fromtimestamp(s, sdr.BUSINESS_TZ).hour < 18 for s in slots), shown)
        self.assertLessEqual(slots[-1], opened + 24 * 3600, shown)  # all 3 inside the 24 h
        # 6 h (16h) would leave no room for the other 2 inside the 24 h: the gaps shrink so the 3 fit, in open hours.
        self.assertEqual(shown, ["Tue 15:30", "Tue 17:30", "Wed 09:00"])

    def test_slides_back_before_closing_or_to_the_opening(self):
        # Opening 15h, closes 18h: 6 h (21h) is closed -> slides back to 17h (2 h) while open; then next morning.
        leads.save("5548000000102", {"nome": "Negócio 102", "horario_google": WEEKDAYS_8_18})
        slots = retomada.slot_times("5548000000102", ts(2026, 10, 13, 15, 0))
        shown = [hm(s) for s in slots]
        self.assertEqual(len(slots), 3, shown)
        self.assertTrue("Tue 17:00" <= shown[0] < "Tue 18:00", shown)  # slid back to before it closes
        self.assertTrue(shown[1].startswith("Wed"), shown)

    def test_retomadas_at_the_next_opening_spread_per_lead(self):
        # Talles 11/10: "espalhar no expediente": the ones that fall at the next opening do not all go at 9h.
        opened = ts(2026, 10, 13, 15, 0)
        firsts = set()
        for i in range(30):
            numero = f"55480000002{i:02d}"
            leads.save(numero, {"nome": f"N {i}", "horario_google": WEEKDAYS_8_18})
            slots = retomada.slot_times(numero, opened)
            self.assertEqual(len(slots), 3)
            self.assertTrue(all(b - a >= 2 * 3600 for a, b in zip([opened] + slots, slots)))
            self.assertTrue(all(8 <= datetime.fromtimestamp(s, sdr.BUSINESS_TZ).hour < 18 for s in slots))
            firsts.add(hm(slots[1]))
        self.assertGreater(len(firsts), 5, firsts)  # Wednesday's ones are not all at the opening

    def test_default_hours_without_data(self):
        slots = retomada.slot_times("5548000000999", ts(2026, 10, 13, 9, 30))  # nothing on file: weekdays 9h–18h
        shown = [hm(s) for s in slots]
        self.assertEqual(len(slots), 3, shown)
        self.assertEqual(shown[0], "Tue 15:30")
        self.assertTrue(all(9 <= datetime.fromtimestamp(s, sdr.BUSINESS_TZ).hour < 18 for s in slots), shown)
        self.assertTrue(all(b - a >= 2 * 3600 for a, b in zip(slots, slots[1:])), shown)

    def test_opening_only_while_the_business_is_open(self):
        self.queue("5548000000777")  # no hours on file: weekdays 9h–18h
        tuesday_10 = datetime(2026, 10, 13, 10, 0, tzinfo=sdr.BUSINESS_TZ)
        self.assertEqual(prospeccao.next_queued(None, tuesday_10)[0], "5548000000777")
        self.assertIsNone(prospeccao.next_queued(None, tuesday_10.replace(hour=17, minute=30)))  # under 1 h to close
        self.assertIsNone(prospeccao.next_queued(None, tuesday_10.replace(hour=21)))
        self.assertIsNone(prospeccao.next_queued(None, datetime(2026, 10, 12, 10, 0, tzinfo=sdr.BUSINESS_TZ)))  # holiday
        self.assertIsNone(prospeccao.next_queued(None, datetime(2026, 10, 11, 10, 0, tzinfo=sdr.BUSINESS_TZ)))  # Sunday
        self.queue("5548000000778", WEEKDAYS_8_18.replace("domingo: Fechado", "domingo: 08:00 to 12:00"))
        self.assertEqual(prospeccao.next_queued(None, datetime(2026, 10, 11, 10, 0, tzinfo=sdr.BUSINESS_TZ))[0], "5548000000778")

    def test_queue_over_pauses_and_tells(self):
        prospeccao.kv_set("prospeccao_pausada", "0")
        with patch.object(prospeccao, "enabled", return_value=True):
            found = vigia.queue_findings(time.time())
        self.assertEqual([f["tipo"] for f in found], ["fila"])
        self.assertEqual(prospeccao.kv_get("prospeccao_pausada"), "1")
        self.assertIn("fila acabou", prospeccao.kv_get("pausa_motivo"))


if __name__ == "__main__":
    unittest.main()
