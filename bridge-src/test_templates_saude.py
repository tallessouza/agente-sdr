"""Template state in the central database, the farm of opening and retomada templates, and their health (Talles, 11/10/2026)."""
import asyncio
import json
import random
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import cloud
import handover
import prospeccao
import sdr
import template_health as th
import templates_db
from test_cloud import pool_in_db


def tpl(name, status="APPROVED", category="UTILITY", score=None, text=None, rid=None):
    return {"id": rid or str(abs(hash(name)) % 10**9), "name": name, "status": status, "category": category, "language": "pt_BR",
            "components": [{"type": "BODY", "text": text or "Oi, {{1}}! Consigo falar com o atendimento por aqui? Tenho uma dúvida."}],
            **({"quality_score": {"score": score}} if score else {})}


class TemplateDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db),
                        patch.object(templates_db, "OLD_META", Path(self.tmp.name) / "meta.json"),
                        patch.object(templates_db, "OLD_POOL", Path(self.tmp.name) / "pool.json"),
                        patch.object(templates_db, "OLD_RETOMADA", Path(self.tmp.name) / "retomada.json")]
        for p in self.patches:
            p.start()
        app.db().close()
        prospeccao.connect().close()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_old_json_state_is_imported_once_then_never_read(self):
        Path(self.tmp.name, "meta.json").write_text(json.dumps({
            "templates": {"vencedor_001": {"scheme": "vencedor", "params": ["saudacao_min"], "estado": "pronto", "contado": "utility"}},
            "usados": ["Oi, {{1}}! Tem alguém por aí? Tenho uma dúvida."], "placar": {"vencedor": {"enviados": 3, "utility": 1, "marketing": 2}},
            "submetidos": {"2026-10-11": 4}}), encoding="utf-8")
        Path(self.tmp.name, "pool.json").write_text(json.dumps([{"name": "vencedor_001", "language": "pt_BR", "category": "UTILITY",
                                                                 "text": "Oi, {{1}}! Tem alguém por aí?", "params": ["saudacao_min"], "saude": "GREEN"}]), encoding="utf-8")
        meta = th.load_meta()
        self.assertEqual(meta["templates"]["vencedor_001"]["params"], ["saudacao_min"])
        self.assertEqual(meta["placar"]["vencedor"], {"enviados": 3, "utility": 1, "marketing": 2})
        self.assertEqual(meta["submetidos"], {"2026-10-11": 4})
        self.assertEqual([t["name"] for t in cloud.approved_templates()], ["vencedor_001"])
        Path(self.tmp.name, "meta.json").write_text("{}", encoding="utf-8")  # changing the old file changes nothing now
        self.assertEqual(th.load_meta()["placar"]["vencedor"]["utility"], 1)

    def test_health_changes_are_recorded_and_deleted_templates_leave_the_pool(self):
        meta = th.load_meta()
        meta["templates"]["vencedor_001"] = {"scheme": "vencedor", "params": ["saudacao_min"], "estado": "pronto"}
        th.save_meta(meta)
        sync = lambda ts: templates_db.sync_from_meta(ts, lambda n: th.tipo_of(n, meta), th.health, th.body_of)
        self.assertEqual(len(sync([tpl("vencedor_001", score="GREEN"), tpl("hello_world")])), 1)  # hello_world is not ours
        self.assertEqual(sync([tpl("vencedor_001", score="GREEN")]), [])  # nothing changed, nothing recorded
        changes = sync([tpl("vencedor_001", score="YELLOW")])
        self.assertEqual(changes[0]["agora"]["saude"], "YELLOW")
        templates_db.set_pool("abertura", ["vencedor_001"])
        sync([])  # deleted at Meta
        self.assertEqual(cloud.approved_templates(), [])
        with templates_db.connect() as c:
            self.assertEqual([r[0] for r in c.execute("SELECT saude FROM tpl_saude ORDER BY id")], ["GREEN", "YELLOW"])

    def test_draw_prefers_healthy_templates(self):
        rng = random.Random(7)
        options = [{"name": "verde", "saude": "GREEN"}, {"name": "amarelo", "saude": "YELLOW"}]
        draws = [th.pick_weighted(options, rng)["name"] for _ in range(2000)]
        self.assertGreater(draws.count("verde"), 2.5 * draws.count("amarelo"))
        pool_in_db([{"name": "verde", "category": "UTILITY", "text": "Oi, {{1}}! Tudo bem?", "params": ["saudacao_min"], "saude": "GREEN"},
                    {"name": "amarelo", "category": "UTILITY", "text": "Olá, {{1}}! Tudo bem?", "params": ["saudacao_min"], "saude": "YELLOW"}])
        picked = [cloud.pick_template({"saudacao_min": "bom dia"}, random.Random(i))[1]["name"] for i in range(300)]
        self.assertGreater(picked.count("verde"), picked.count("amarelo"))

    def test_retomada_farm_fills_each_family_as_marketing_within_the_daily_cap(self):
        meta = th.load_meta()
        templates = [tpl(name, category="MARKETING", score="GREEN", text=text) for name, (_f, text, _e) in th.RETOMADAS.items()]
        templates_db.sync_from_meta(templates, lambda n: th.tipo_of(n, meta), th.health, th.body_of)
        posted = []

        async def graph(method, path, body=None):
            posted.append(body)
            return {"id": "1"}

        with patch.object(th, "graph", new=graph):
            submitted = asyncio.run(th.ensure_retomadas(templates, meta))
        # Utility first (the retomadas' own 80/20, Talles 11/10): none approved yet, target 4 a family, at most 6 a day.
        self.assertEqual(len(submitted), th.RETOMADA_DAILY_MAX)
        self.assertEqual(posted[0]["category"], "UTILITY")
        for b in posted:
            text = b["components"][0]["text"]
            self.assertTrue(b["name"].startswith("retomada_") and th.familia_of(b["name"]) in th.RETOMADA_SKELETONS)
            self.assertFalse(text.startswith("{{") or text.endswith("}}"))
            self.assertNotRegex(text, r"\}\}\s*\{\{")
            self.assertEqual(sorted(re.findall(r"\{\{(\d)\}\}", text)), ["1", "2", "3"])
            utility = b["category"] == "UTILITY"
            self.assertEqual(th.is_utility_variant(b["name"]), utility)
            self.assertTrue(text.endswith(".") if utility else text.endswith("?"))  # utility: no sales close
            if utility:
                self.assertNotIn("20 minutos", text)
            self.assertEqual(len(b["components"][0]["example"]["body_text"][0]), 3)
        self.assertEqual(len({b["components"][0]["text"] for b in posted}), len(posted))  # never the same text twice
        with patch.object(th, "graph", new=graph):
            self.assertEqual(asyncio.run(th.ensure_retomadas(templates, meta)), [])  # the day's cap is spent
        self.assertEqual({t["name"] for t in th.retomada_pool()}, set(th.RETOMADAS))  # only approved ones are usable

    def test_health_report_counts_sends_failures_and_replies(self):
        meta = th.load_meta()
        meta["templates"]["vencedor_001"] = {"scheme": "vencedor", "params": ["saudacao_min"], "estado": "pronto"}
        th.save_meta(meta)
        templates_db.sync_from_meta([tpl("vencedor_001", score="GREEN")], lambda n: th.tipo_of(n, meta), th.health, th.body_of)
        now = time.time()
        prospeccao.enqueue([{"telefone_e164": "+5548999990001", "nome": "A"}, {"telefone_e164": "+5548999990002", "nome": "B"}])
        prospeccao.update("5548999990001", conversation=501, status="respondeu", respondeu_em=now + 60)
        prospeccao.update("5548999990002", conversation=502, status="enviado")
        templates_db.record_send("vencedor_001", 501, "2026-10-11", now)
        templates_db.record_send("vencedor_001", 502, "2026-10-11", now)
        templates_db.record_failure("vencedor_001", "2026-10-11")
        row = next(r for r in templates_db.health_report() if r["name"] == "vencedor_001")
        self.assertEqual((row["enviados"], row["falhas"], row["respostas"], row["saude"]), (2, 1, 1, "GREEN"))


if __name__ == "__main__":
    unittest.main()
