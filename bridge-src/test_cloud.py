import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import app
import cloud
import handover
import prospeccao
import sdr


def event(**kw):
    base = {"event": "message_created", "id": 501, "message_type": "incoming", "private": False, "content": "Bom dia, pois não?",
            "inbox": {"id": 2}, "conversation": {"id": 900, "display_id": 77, "inbox_id": 2, "contact_inbox": {"source_id": "554899990000"}},
            "sender": {"phone_number": "+554899990000", "name": "Clínica X", "type": "contact"}, "attachments": []}
    base.update(kw)
    return base


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db),
                        patch.object(cloud, "CLOUD_INBOX_ID", 2)]
        for p in self.patches:
            p.start()
        app.db().close()
        app.hermes_pending.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_numbers_get_the_nine_back_and_map_to_evolution_jids(self):
        self.assertEqual(cloud.canonical_number("+55 48 9999-0000"), "5548999990000")
        self.assertEqual(cloud.canonical_number("5548999990000"), "5548999990000")
        self.assertEqual(cloud.canonical_number("554833330000"), "554833330000")  # landline stays
        self.assertEqual(cloud.jid_for("554899990000"), "5548999990000@cloud")
        self.assertEqual(cloud.evolution_jids("5548999990000"), ["554899990000@s.whatsapp.net", "5548999990000@s.whatsapp.net"])

    def test_template_rendering_fills_the_greeting_and_skips_missing_values(self):
        tpl = {"name": "teste_atendimento_01", "language": "pt_BR", "category": "UTILITY", "text": "Oi, {{1}}! Vocês atendem por aqui?", "params": ["saudacao_min"]}
        text, params = cloud.render_template(tpl, {"saudacao_min": "boa tarde"})
        self.assertEqual(text, "Oi, boa tarde! Vocês atendem por aqui?")
        self.assertEqual(params["processed_params"], {"1": "boa tarde"})
        self.assertIsNone(cloud.render_template(tpl, {}))
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump([tpl, {**tpl, "name": "pendente", "status": "PENDING"}], fh)
        with patch.object(cloud, "TEMPLATES_FILE", fh.name):
            names = {cloud.pick_template({"saudacao_min": "bom dia"})[1]["name"] for _ in range(10)}
        self.assertEqual(names, {"teste_atendimento_01"})

    def test_short_templates_carry_the_whole_test_question_in_the_variable(self):
        import random
        fields = cloud.test_fields("boa tarde", random.Random(1))
        a = {"name": "abordagem_a01", "language": "pt_BR", "category": "UTILITY", "text": "Olá, {{1}}. Obrigado pela atenção!", "params": ["abertura_teste"]}
        b = {"name": "abordagem_b01", "language": "pt_BR", "category": "UTILITY", "text": "Oi, tudo bem? {{1}}. Fico no aguardo.", "params": ["frase_teste"]}
        text_a, params_a = cloud.render_template(a, fields)
        text_b, _ = cloud.render_template(b, fields)
        self.assertEqual(text_a, f"Olá, boa tarde! {fields['frase_teste']}. Obrigado pela atenção!")
        self.assertEqual(params_a["processed_params"], {"1": f"boa tarde! {fields['frase_teste']}"})
        self.assertEqual(text_b, f"Oi, tudo bem? {fields['frase_teste']}. Fico no aguardo.")
        self.assertTrue(all(not p.endswith((".", "?", "!")) for p in cloud.TEST_PHRASES))

    def test_incoming_message_runs_the_agent_turn_once(self):
        with patch.object(app, "queue_hermes_turn") as queue:
            asyncio.run(app.cloud_inbox_event(event()))
            asyncio.run(app.cloud_inbox_event(event()))  # Chatwoot redelivery
        queue.assert_called_once()
        jid, content, _media, source_id, conversation_id, external_id, _ev = queue.call_args.args
        self.assertEqual((jid, content, source_id, conversation_id, external_id), ("5548999990000@cloud", "Bom dia, pois não?", "5548999990000", 77, "cw:501"))
        row = app.db().execute("SELECT jid, conversation_id FROM contacts").fetchone()
        self.assertEqual(row, ("5548999990000@cloud", 77))

    def test_reply_marks_the_prospect_as_answered(self):
        prospeccao.enqueue([{"telefone_e164": "+5548999990000", "nome": "Clínica X"}])
        prospeccao.update("5548999990000", status="enviado", jid="5548999990000@cloud", conversation=77, enviado_em=time.time() - 60)
        with patch.object(app, "queue_hermes_turn"):
            asyncio.run(app.cloud_inbox_event(event()))
        self.assertEqual(prospeccao.for_jid("5548999990000@cloud")["status"], "respondeu")

    def test_agent_messages_are_ignored_and_a_human_reply_pauses(self):
        with patch.object(app.handover, "pause", new=AsyncMock()) as pause:
            asyncio.run(app.cloud_inbox_event(event(id=600, message_type="outgoing", content_attributes={"bridge_agent": True})))
            pause.assert_not_called()
            asyncio.run(app.cloud_inbox_event(event(id=601, message_type="outgoing", content="Oi, aqui é o Talles")))
            pause.assert_awaited_once_with(77)

    def test_agent_text_goes_through_the_official_inbox_only(self):
        with patch.object(cloud, "post_message", new=AsyncMock()) as post, patch.object(app, "send_evolution", new=AsyncMock()) as evo, \
                patch.object(app, "add_chatwoot_message", new=AsyncMock()) as mirror:
            asyncio.run(app.agent_send_text("5548999990000@cloud", "5548999990000", 77, "Oi!"))
            post.assert_awaited_once_with(77, "Oi!")
            evo.assert_not_called(); mirror.assert_not_called()
            asyncio.run(app.agent_send_text("554899990000@s.whatsapp.net", "src", 12, "Oi!"))
            evo.assert_awaited_once(); mirror.assert_awaited_once()

    def test_followup_after_24h_is_cancelled_on_the_official_number(self):
        conn = app.db(); conn.execute("INSERT INTO contacts (jid, source_id, conversation_id, internal_id) VALUES (?,?,?,?)", ("5548999990000@cloud", "5548999990000", 77, 900)); conn.commit(); conn.close()
        now = time.time()
        fid = sdr.add_followup(77, now - 10, "Oi de novo", "teste", after_ts=now - 30 * 3600)
        with patch.object(app, "SDR_BRAIN_URL", "http://brain"), patch.object(sdr, "activity", return_value=(now - 30 * 3600, now - 29 * 3600)), \
                patch.object(app.handover, "paused", new=AsyncMock(return_value=False)), patch.object(cloud, "post_message", new=AsyncMock()) as post:
            asyncio.run(app.process_followups_once(now))
        post.assert_not_called()
        with sdr.connect() as c:
            self.assertEqual(c.execute("SELECT status, reason FROM sdr_followups WHERE id=?", (fid,)).fetchone(), ("cancelled", "janela_24h"))

    def test_failed_followup_is_never_retried_nor_queued(self):
        conn = app.db(); conn.execute("INSERT INTO contacts (jid, source_id, conversation_id, internal_id) VALUES (?,?,?,?)", ("554899990000@s.whatsapp.net", "src", 12, 12)); conn.commit(); conn.close()
        now = time.time()
        fid = sdr.add_followup(12, now - 10, "Vocês me responderam às 22h39", "teste", after_ts=now - 3600)
        boom = AsyncMock(side_effect=RuntimeError("store doesn't contain a device JID"))
        with patch.object(app, "SDR_BRAIN_URL", "http://brain"), patch.object(sdr, "activity", return_value=(now - 3600, now - 3500)), \
                patch.object(app.handover, "paused", new=AsyncMock(return_value=False)), patch.object(app, "send_presence", new=AsyncMock()), \
                patch.object(app, "SDR_BUSINESS_START_HOUR", 0), patch.object(app, "SDR_BUSINESS_END_HOUR", 24), \
                patch.object(app.sdr, "typing_seconds", return_value=0), patch.object(app, "send_evolution", new=boom):
            asyncio.run(app.process_followups_once(now))
            asyncio.run(app.process_followups_once(now + 30))
        self.assertEqual(boom.await_count, 1)
        self.assertEqual(boom.await_args.kwargs.get("retry"), True)
        with sdr.connect() as c:
            self.assertEqual(c.execute("SELECT status FROM sdr_followups WHERE id=?", (fid,)).fetchone()[0], "failed")
        self.assertEqual(app.db().execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)

    def test_prospect_sends_one_template_with_the_greeting(self):
        prospeccao.enqueue([{"telefone_e164": "+5548999990000", "nome": "Clínica X"}])
        tpl = [{"name": "teste_atendimento_01", "language": "pt_BR", "category": "UTILITY", "text": "Oi, {{1}}! Vocês atendem por aqui?", "params": ["saudacao_min"]}]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(tpl, fh)
        with patch.object(cloud, "TEMPLATES_FILE", fh.name), patch.object(cloud, "open_conversation", new=AsyncMock(return_value=("5548999990000", 77, 900))), \
                patch.object(cloud, "post_message", new=AsyncMock()) as post, patch.object(sdr, "add_label", new=AsyncMock()), \
                patch.object(sdr, "private_note", new=AsyncMock()), patch.object(app, "PROSPECT_CHANNEL", "cloud"):
            data = prospeccao.next_queued("5548999990000")[1]
            self.assertTrue(prospeccao.claim("5548999990000"))
            result = asyncio.run(app.prospect_cloud("5548999990000", data, time.time()))
        self.assertEqual(result, "enviado")
        text = post.await_args.args[1]
        self.assertRegex(text, r"^Oi, (bom dia|boa tarde|boa noite)! Vocês atendem por aqui\?$")
        self.assertEqual(post.await_args.kwargs["template"]["name"], "teste_atendimento_01")
        row = prospeccao.for_jid("5548999990000@cloud")
        self.assertEqual((row["status"], row["texto"]), ("enviado", text))

    def test_prospect_skips_a_number_already_talking_on_evolution(self):
        prospeccao.enqueue([{"telefone_e164": "+5548999990000", "nome": "Clínica X"}])
        conn = app.db(); conn.execute("INSERT INTO contacts (jid, source_id, conversation_id, internal_id) VALUES (?,?,?,?)", ("554899990000@s.whatsapp.net", "s", 5, 5)); conn.commit(); conn.close()
        with patch.object(cloud, "post_message", new=AsyncMock()) as post:
            result = asyncio.run(app.prospect_cloud("5548999990000", {}, time.time()))
        self.assertEqual(result, "ja_contato")
        post.assert_not_called()

    def test_conversation_failure_returns_the_number_to_the_queue(self):
        prospeccao.enqueue([{"telefone_e164": "+5548999990000", "nome": "Clínica X"}])
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump([{"name": "abordagem_a01", "language": "pt_BR", "category": "UTILITY", "text": "Olá, {{1}}. Obrigado!", "params": ["abertura_teste"]}], fh)
        with patch.object(cloud, "TEMPLATES_FILE", fh.name), patch.object(cloud, "open_conversation", new=AsyncMock(side_effect=RuntimeError("chatwoot down"))), \
                patch.object(cloud, "post_message", new=AsyncMock()) as post:
            result = asyncio.run(app.prospect_cloud("5548999990000", {}, time.time()))
        self.assertEqual(result, "erro")
        post.assert_not_called()
        self.assertEqual(prospeccao.next_queued("5548999990000")[0], "5548999990000")

    def test_owner_test_replays_a_dispatch_and_fim_cleans_it(self):
        prospeccao.enqueue([{"telefone_e164": "+5548988887777", "nome": "Odonto Real", "nicho": "clínica odontológica", "cidade": "São José"}])
        owner = "5564999425822@cloud"
        conn = app.db(); conn.execute("INSERT INTO contacts (jid, source_id, conversation_id, internal_id) VALUES (?,?,?,?)", (owner, "5564999425822", 68, 68)); conn.commit(); conn.close()
        with patch.object(sdr, "is_owner", return_value=True), patch.object(cloud, "post_message", new=AsyncMock()) as post, \
                patch.object(cloud, "resolve_conversation", new=AsyncMock()), patch.object(cloud, "open_conversation", new=AsyncMock(return_value=("5564999425822", 90, 990))), \
                patch.object(sdr, "add_label", new=AsyncMock()), patch.object(sdr, "private_note", new=AsyncMock()), patch.object(app, "queue_hermes_turn") as queue:
            asyncio.run(app.cloud_inbox_event(event(id=700, content="#teste", conversation={"id": 68, "display_id": 68, "inbox_id": 2})))
            row = prospeccao.for_jid(owner)
            self.assertEqual((row["status"], row["conversation"], json.loads(row["dados"])["nome"]), ("enviado", 90, "Odonto Real"))
            self.assertEqual(post.await_args_list[-1].args[0], 90)  # the test message went to the new conversation
            self.assertEqual(prospeccao.next_queued("5548988887777")[0], "5548988887777")  # the real business is untouched
            asyncio.run(app.cloud_inbox_event(event(id=701, content="Bom dia, pois não?", conversation={"id": 990, "display_id": 90, "inbox_id": 2})))
            queue.assert_called_once()
            self.assertEqual(prospeccao.for_jid(owner)["status"], "respondeu")
            asyncio.run(app.cloud_inbox_event(event(id=702, content="#fim", conversation={"id": 990, "display_id": 90, "inbox_id": 2})))
        self.assertIsNone(prospeccao.for_jid(owner))
        self.assertFalse(sdr.owner_test_run(owner))

    def test_category_rule_keeps_marketing_at_most_twenty_percent(self):
        import template_health as th
        util = [{"category": "UTILITY"}]; mkt = [{"category": "MARKETING"}]
        self.assertEqual(th.choose_category(util + mkt, 0, 0), "UTILITY")    # 1 of 1 would be 100% marketing
        self.assertEqual(th.choose_category(util + mkt, 4, 0), "MARKETING")  # 1 of 5 = 20%
        self.assertEqual(th.choose_category(util + mkt, 4, 1), "UTILITY")    # 2 of 6 > 20%
        self.assertEqual(th.choose_category(util, 4, 0), "UTILITY")          # no marketing in stock
        self.assertIsNone(th.choose_category(mkt, 0, 0))                     # no utility: no send at all
        self.assertIsNone(th.choose_category(mkt, 40, 0))
        self.assertIsNone(th.choose_category([], 10, 0))
        sends = {"UTILITY": 0, "MARKETING": 0}
        for _ in range(100):
            sends[th.choose_category(util + mkt, sends["UTILITY"], sends["MARKETING"])] += 1
        self.assertEqual(sends, {"UTILITY": 80, "MARKETING": 20})

    def test_marketing_kept_by_health_within_twenty_percent(self):
        import template_health as th
        body = [{"type": "BODY", "text": "Oi, {{1}}! Tem alguém por aí? Tenho uma dúvida."}]
        mk = lambda i, status, cat, score=None: {"id": str(i), "name": f"vencedor_{i:03d}", "status": status, "category": cat,
                                                 "language": "pt_BR", "components": body, **({"quality_score": {"score": score}} if score else {})}
        templates = [mk(i, "APPROVED", "UTILITY", "GREEN") for i in range(1, 9)] + [
            mk(20, "APPROVED", "MARKETING", "RED"), mk(21, "APPROVED", "MARKETING", "YELLOW"), mk(22, "APPROVED", "MARKETING", "GREEN"),
            mk(23, "APPROVED", "MARKETING"), mk(24, "PENDING", "MARKETING"), mk(25, "APPROVED", "UTILITY", "RED")]
        with patch.object(th, "META_FILE", Path(self.tmp.name) / "meta.json"):
            meta = th.load_meta()
            for t in templates:
                meta["templates"][t["name"]] = {"scheme": "vencedor", "params": ["saudacao_min"], "estado": "pronto"}
            self.assertNotIn("vencedor_025", {t["name"] for t in th.build_pool(templates, meta)})  # RED utility leaves the draw
            with patch.object(th, "graph", new=AsyncMock(return_value={"success": True})):
                deleted = asyncio.run(th.trim_marketing(templates, meta))
        # 8 utility allow 2 marketing: GREEN and UNKNOWN stay; RED, YELLOW and the pending one go.
        self.assertEqual(sorted(deleted), ["vencedor_020", "vencedor_021", "vencedor_024"])

    def test_health_builds_the_pool_and_submits_only_unseen_variants(self):
        import random
        import template_health as th
        body = lambda t: {"type": "BODY", "text": t}
        templates = [
            {"name": "abordagem_a01", "status": "APPROVED", "category": "UTILITY", "language": "pt_BR", "components": [body("Olá, {{1}}. Obrigado pela atenção!")]},
            {"name": "abordagem_b01", "status": "APPROVED", "category": "MARKETING", "language": "pt_BR", "components": [body("Oi, tudo bem? {{1}}. Fico no aguardo.")]},
            {"name": "abordagem_b02", "status": "PENDING", "category": "UTILITY", "language": "pt_BR", "components": [body("Oi, como vai? {{1}}. Valeu!")]},
            {"name": "hello_world", "status": "APPROVED", "category": "UTILITY", "language": "en_US", "components": [body("Hello World")]},
        ]
        with patch.object(th, "META_FILE", Path(self.tmp.name) / "meta.json"):
            meta = th.load_meta()
            pool = th.build_pool(templates, meta)
            self.assertEqual({(t["name"], t["category"], tuple(t["params"])) for t in pool},
                             {("abordagem_a01", "UTILITY", ("abertura_teste",)), ("abordagem_b01", "MARKETING", ("frase_teste",))})
            batch = th.new_variants(templates, meta, 30, random.Random(3))
        texts = [b["template"]["components"][0]["text"] for b in batch]
        self.assertEqual(len(batch), 30)
        self.assertEqual(len(set(texts)), 30)
        self.assertFalse({"Olá, {{1}}. Obrigado pela atenção!", "Oi, tudo bem? {{1}}. Fico no aguardo."} & set(texts))
        self.assertFalse({"abordagem_a01", "abordagem_b01", "abordagem_b02"} & {b["template"]["name"] for b in batch})
        self.assertTrue(all(not t.startswith("{{") and not t.endswith("}}") for t in texts))
        for b in batch:  # the example has one value per variable, as Meta requires
            self.assertEqual(len(b["template"]["components"][0]["example"]["body_text"][0]), len(b["info"]["params"]))

    def test_bait_waits_for_utility_then_is_edited_and_scored(self):
        import template_health as th
        with patch.object(th, "META_FILE", Path(self.tmp.name) / "meta.json"):
            meta = th.load_meta()
            meta["templates"]["isca_001"] = {"scheme": "isca", "params": ["saudacao_min"], "alvo": "Oi, {{1}}! Consigo falar com alguém agora? Tenho uma dúvida.", "estado": "isca"}
            approved = [{"id": "77", "name": "isca_001", "status": "APPROVED", "category": "UTILITY", "language": "pt_BR",
                         "components": [{"type": "BODY", "text": "Oi, {{1}}! Sua solicitação foi registrada."}]}]
            th.learn(approved, meta)
            self.assertEqual(meta["placar"], {})  # a bait approved as utility is not scored yet
            self.assertEqual(th.build_pool(approved, meta), [])  # and never sent with the bait text
            with patch.object(th, "graph", new=AsyncMock(return_value={"success": True})) as graph:
                self.assertEqual(asyncio.run(th.edit_baits(approved, meta)), [])  # off by default: never edited
                graph.assert_not_called()
                with patch.object(th, "BAIT_ENABLED", True):
                    edited = asyncio.run(th.edit_baits(approved, meta))
            self.assertEqual(edited, ["isca_001"])
            self.assertEqual(graph.await_args.args[:2], ("POST", "77"))
            self.assertEqual(graph.await_args.args[2]["components"][0]["text"], "Oi, {{1}}! Consigo falar com alguém agora? Tenho uma dúvida.")
            after = [{**approved[0], "components": [{"type": "BODY", "text": "Oi, {{1}}! Consigo falar com alguém agora? Tenho uma dúvida."}]}]
            th.learn(after, meta)
            self.assertEqual(meta["placar"]["isca"]["utility"], 1)
            self.assertEqual([t["name"] for t in th.build_pool(after, meta)], ["isca_001"])

    def test_bad_number_quality_pauses_the_queue(self):
        import template_health as th
        self.assertIsNone(th.number_alarm({"quality_rating": "GREEN", "status": "CONNECTED", "health_status": {"can_send_message": "AVAILABLE"}}))
        self.assertIsNone(th.number_alarm({"quality_rating": "YELLOW", "status": "CONNECTED"}))
        self.assertEqual(th.number_alarm({"quality_rating": "RED", "status": "CONNECTED"}), "qualidade do número RED")
        self.assertEqual(th.number_alarm({"quality_rating": "GREEN", "status": "FLAGGED"}), "número FLAGGED")
        self.assertIn("bloqueou", th.number_alarm({"status": "CONNECTED", "health_status": {"can_send_message": "BLOCKED"}}))
        prospeccao.kv_set("prospeccao_pausada", "0")
        with patch.object(th, "PHONE_ID", "1"), patch.object(th, "graph", new=AsyncMock(return_value={"quality_rating": "RED", "status": "CONNECTED"})):
            report = asyncio.run(th.guard_number())
        self.assertEqual(report["alarme"], "qualidade do número RED")
        self.assertEqual((prospeccao.kv_get("prospeccao_pausada"), prospeccao.kv_get("pausa_motivo")), ("1", "qualidade do número RED"))

    def test_every_marketing_template_is_cleaned_and_scored(self):
        import template_health as th
        body = [{"type": "BODY", "text": "Oi, {{1}}! Tem alguém por aí? Tenho uma dúvida."}]
        templates = [
            {"id": "1", "name": "vencedor_001", "status": "APPROVED", "category": "UTILITY", "language": "pt_BR", "components": body},
            {"id": "2", "name": "vencedor_002", "status": "APPROVED", "category": "MARKETING", "language": "pt_BR", "components": body},
            {"id": "3", "name": "frase_var_001", "status": "PENDING", "category": "MARKETING", "language": "pt_BR", "components": body},
            {"id": "4", "name": "frase_var_002", "status": "PENDING", "category": "UTILITY", "language": "pt_BR", "components": body},
        ]
        with patch.object(th, "META_FILE", Path(self.tmp.name) / "meta.json"):
            meta = th.load_meta()
            for t in templates:
                meta["templates"][t["name"]] = {"scheme": t["name"].rsplit("_", 1)[0], "params": ["saudacao_min"], "estado": "pronto"}
            th.learn(templates, meta)
            with patch.object(th, "graph", new=AsyncMock(return_value={"success": True})) as graph:
                deleted = asyncio.run(th.trim_marketing(templates, meta))
        self.assertEqual(sorted(deleted), ["frase_var_001", "vencedor_002"])
        self.assertEqual(graph.await_count, 2)
        self.assertEqual(meta["placar"]["frase_var"]["marketing"], 1)  # pending marketing still scored
        self.assertEqual(meta["placar"]["vencedor"], {"utility": 1, "marketing": 1})

    def test_bait_tactic_is_off_unless_enabled(self):
        import template_health as th
        self.assertNotIn("isca", th.SCHEMES)

    def test_scheme_weights_follow_utility_success(self):
        import template_health as th
        meta = {"placar": {"vencedor": {"utility": 8, "marketing": 2}, "frase_var": {"utility": 0, "marketing": 10}}, "templates": {}, "usados": []}
        weights = dict(zip(th.SCHEMES, th.scheme_weights(meta)))
        self.assertGreater(weights["vencedor"], weights["pergunta_var"])  # untried schemes sit in the middle
        self.assertGreater(weights["pergunta_var"], weights["frase_var"])
        self.assertGreater(weights["frase_var"], 0)

    def test_queue_pauses_itself_when_no_template_is_allowed(self):
        prospeccao.enqueue([{"telefone_e164": "+5548999990000", "nome": "Clínica X"}])
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump([{"name": "abordagem_b01", "language": "pt_BR", "category": "MARKETING", "text": "Oi, tudo bem? {{1}}. Fico no aguardo.", "params": ["frase_teste"]}], fh)
        with patch.object(cloud, "TEMPLATES_FILE", fh.name), patch.object(cloud, "open_conversation", new=AsyncMock()) as opened, \
                patch.object(cloud, "post_message", new=AsyncMock()) as post:
            self.assertTrue(prospeccao.claim("5548999990000"))
            result = asyncio.run(app.prospect_cloud("5548999990000", {}, time.time()))
        self.assertEqual(result, "sem_template")
        opened.assert_not_called(); post.assert_not_called()
        self.assertEqual(prospeccao.kv_get("prospeccao_pausada"), "1")
        self.assertEqual(prospeccao.next_queued("5548999990000")[0], "5548999990000")

    def test_stale_outbox_items_expire_unsent(self):
        conn = app.db()
        conn.execute("INSERT INTO outbox (kind,number,payload,next_attempt,created_at) VALUES ('text','5548',?,0,?)", (json.dumps({"content": "velha"}), time.time() - 3 * 3600))
        conn.execute("INSERT INTO outbox (kind,number,payload,next_attempt,created_at) VALUES ('text','5548',?,0,?)", (json.dumps({"content": "nova"}), time.time()))
        conn.commit(); conn.close()
        claimed = app._outbox_claim_due()
        self.assertEqual([item[3]["content"] for item in claimed], ["nova"])
        self.assertEqual(app.db().execute("SELECT status FROM outbox WHERE payload LIKE '%velha%'").fetchone()[0], "expired")


if __name__ == "__main__":
    unittest.main()
