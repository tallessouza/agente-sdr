import asyncio
from datetime import datetime
import json
from contextlib import closing
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

os.environ["SDR_BRAIN_TOKEN"] = "test"
os.environ["SDR_BRAIN_DB"] = os.path.join(tempfile.gettempdir(), "sdr-brain-acceptance.db")
try: os.unlink(os.environ["SDR_BRAIN_DB"])
except FileNotFoundError: pass
from fastapi.testclient import TestClient
import app


class FakeHTTP:
    def __init__(self, *args, **kwargs): self.posts = []
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def get(self, url, **kwargs):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"last_agent_ts": app.tracked.get(77, {}).get("last_agent_ts", 1), "last_lead_ts": 0, "lead": {"registros": {}}}
        return R()
    async def post(self, url, **kwargs):
        class R:
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"message": {"content": '{"decision":"aprovar"}'}}]}
        return R()


class Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app.app)

    def headers(self): return {"Authorization": "Bearer test"}

    def test_health_without_auth_and_auth_503_401_all_protected(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        for route, body in [("/review", {"draft_parts": []}), ("/events/exchange", {"conversation_id": 1}), ("/events/lead", {"conversation_id": 1}), ("/events/record", {"conversation_id": 1, "campo": "x", "valor": "y"})]:
            self.assertEqual(self.client.post(route, json=body).status_code, 401)
        old = os.environ.pop("SDR_BRAIN_TOKEN")
        try:
            for route, body in [("/review", {}), ("/events/exchange", {"conversation_id": 1}), ("/events/lead", {"conversation_id": 1}), ("/events/record", {"conversation_id": 1})]:
                self.assertEqual(self.client.post(route, json=body).status_code, 503)
        finally: os.environ["SDR_BRAIN_TOKEN"] = old

    def test_review_decisions_fallback_directives_and_parts(self):
        with patch.object(app, "ask_llm", side_effect=[{"decision": "aprovar"}, {"decision": "reescrever", "parts": ["nova"]}, {"decision": "bloquear", "motivo": "sigilo"}, None, {"decision": "reescrever", "parts": ["a", "b", "c", "d"]}]):
            self.assertEqual(self.client.post("/review", headers=self.headers(), json={"draft_parts": ["oi [[REGISTRO: dor = x]]"]}).json()["decision"], "aprovar")
            rewritten = self.client.post("/review", headers=self.headers(), json={"draft_parts": ["oi [[REGISTRO: dor = x]]"]}).json()
            self.assertIn("[[REGISTRO: dor = x]]", rewritten["parts"][0])
            self.assertEqual(self.client.post("/review", headers=self.headers(), json={}).json()["decision"], "bloquear")
            self.assertEqual(self.client.post("/review", headers=self.headers(), content=b"{").json()["motivo"], "review_unavailable")
            self.assertEqual(self.client.post("/review", headers=self.headers(), json={}).json()["motivo"], "review_unavailable")


    def test_review_timeout_fallback(self):
        class TimeoutHTTP:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def post(self, *args, **kwargs): raise TimeoutError("timeout")
        with patch.object(app.httpx, "AsyncClient", TimeoutHTTP):
            result = self.client.post("/review", headers=self.headers(), json={}).json()
            self.assertEqual(result, {"decision": "aprovar", "motivo": "review_unavailable"})

    def test_supervisor_guidance_and_escalation(self):
        app.CHATWOOT_ACCOUNT_ID = "1"; app.CHATWOOT_API_TOKEN = "x"
        with patch.object(app, "chatwoot_messages", new=AsyncMock(return_value=[{"content": "quero pessoa"}])), patch.object(app, "ask_llm", new=AsyncMock(return_value={"guidance": "pergunte", "escalate": True, "motivo": "pedido", "frase": "quero pessoa"})), patch.object(app, "bridge_post", new=AsyncMock()) as post:
            asyncio.run(app.supervisor({"conversation_id": 9}))
            self.assertEqual(post.await_count, 2)
            self.assertEqual(post.await_args_list[0].args[0], "/sdr/guidance")
            self.assertEqual(post.await_args_list[1].args[0], "/sdr/escalate")

    def fake_psycopg(self, rows_by_query):
        """psycopg stand-in: returns rows by the first table-ish marker in the SQL."""
        executed = []

        class Cursor:
            def execute(self, query, args):
                self.query = query
                executed.append((query, args))
            def fetchall(self):
                for marker, rows in rows_by_query.items():
                    if marker in self.query:
                        return rows
                return []
            def __enter__(self): return self
            def __exit__(self, *args): pass

        class Conn:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def cursor(self): return Cursor()

        return type("Psycopg", (), {"connect": staticmethod(lambda dsn: Conn())}), executed

    def test_enrichment_from_prefilled_handle_uses_quoted_sql(self):
        history = [("raiox", "2026-09-27 10:00", "raiox", "179", "https://instagram.com/p/1", "raiox")]
        fake, executed = self.fake_psycopg({"a.name": history})
        with patch.dict("sys.modules", {"psycopg": fake}), patch.dict(os.environ, {"OPENREPLY_DSN": "postgres://x"}), \
                patch.object(app, "bridge_post", new=AsyncMock()) as post, patch.object(app, "chatwoot_contact_name", new=AsyncMock(return_value="")), \
                patch.object(app.enrichment, "profile_lookup", new=AsyncMock(return_value={"bio": "mentora de social media", "ultimos_posts": []})):
            asyncio.run(app.enrich({"conversation_id": 4, "origin": {"instagram": "@Acme"}, "ts": 1790600400}))
        ficha = post.await_args.args[1]["profile"]
        self.assertEqual(ficha["origem_instagram"], {"status": "confirmado", "metodo": "texto_do_link"})
        self.assertEqual(ficha["instagram"], "@acme")
        self.assertEqual(ficha["campanha_instagram"]["palavra"], "raiox")
        self.assertEqual(ficha["perfil"]["bio"], "mentora de social media")
        self.assertIn('"DmLog"', executed[0][0])

    def test_window_match_by_name_and_ambiguity(self):
        e = app.enrichment
        two = [{"handle": "marina.escala", "igsid": "1", "sent": 0}, {"handle": "joao_lojas", "igsid": "2", "sent": 0}]
        no = lambda h: False
        self.assertEqual(e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Marina Duarte", candidates=two, in_campaign=no)["status"], "confirmado")
        self.assertEqual(e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Carla", candidates=two, in_campaign=no)["status"], "ambiguo")
        self.assertEqual(e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Carla", candidates=two[:1], in_campaign=no)["status"], "provavel")
        self.assertEqual(e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Carla", candidates=[], in_campaign=no)["status"], "direto")
        typed = e.resolve_identity(prefilled_handle="", typed_handle="loja.x", display_name="", candidates=[], in_campaign=lambda h: h == "loja.x")
        self.assertEqual((typed["status"], typed["method"]), ("confirmado", "lead_informou"))
        self.assertEqual(e.resolve_identity(prefilled_handle="", typed_handle="outra", display_name="", candidates=[], in_campaign=no)["status"], "informado")
        self.assertEqual(e.normalize_handle("@there"), "")
        self.assertTrue(e.name_matches_handle("Marina Duarte", "marina.escala"))
        self.assertFalse(e.name_matches_handle("Ana", "marina.escala"))

    def test_click_beats_dm_window(self):
        e = app.enrichment
        no = lambda h: False
        cands = [{"handle": "marina.escala", "igsid": "1", "sent": 0, "source": "clique"},
                 {"handle": "joao_lojas", "igsid": "2", "sent": 0, "source": "dm"},
                 {"handle": "ana.x", "igsid": "3", "sent": 0, "source": "dm"}]
        r = e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Carla", candidates=cands, in_campaign=no)
        self.assertEqual((r["username"], r["status"], r["method"]), ("marina.escala", "confirmado", "clique"))
        two_clicks = [dict(cands[0]), {"handle": "ana.x", "igsid": "3", "sent": 0, "source": "clique"}]
        self.assertEqual(e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Carla", candidates=two_clicks, in_campaign=no)["status"], "ambiguo")
        r = e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Ana Paula", candidates=two_clicks, in_campaign=no)
        self.assertEqual((r["username"], r["method"]), ("ana.x", "clique+nome"))

    def test_unconfirmed_identity_never_reaches_the_agent(self):
        window = [("marina.escala", "1", datetime(2026, 9, 28, 13, 0))]
        fake, _ = self.fake_psycopg({'"DmLog" d WHERE d.status': window})
        with patch.dict("sys.modules", {"psycopg": fake}), patch.dict(os.environ, {"OPENREPLY_DSN": "postgres://x"}), \
                patch.object(app, "bridge_post", new=AsyncMock()) as post, patch.object(app, "chatwoot_contact_name", new=AsyncMock(return_value="Carla")), \
                patch.object(app.enrichment, "profile_lookup", new=AsyncMock(return_value=None)):
            asyncio.run(app.enrich({"conversation_id": 5, "origin": None, "ts": 1790600400}))
        ficha = post.await_args.args[1]["profile"]
        self.assertEqual(ficha["origem_instagram"]["status"], "provavel")
        self.assertNotIn("instagram", ficha)
        self.assertNotIn("marina", json.dumps(ficha))

    def test_profile_sources_disabled_without_tokens(self):
        for var in ("META_GRAPH_TOKEN", "IG_BUSINESS_ID", "APIFY_TOKEN"):
            os.environ.pop(var, None)
        self.assertIsNone(asyncio.run(app.enrichment.business_discovery("empresa")))
        self.assertIsNone(asyncio.run(app.enrichment.apify_profile("empresa")))

    def run_followups(self, now, bridge_state):
        """Run one follow-up pass against a mocked bridge; return posted stages."""
        posted = []

        async def llm(_, **kwargs):
            return {"disparar": True, "texto": "Você falou que tudo para quando sai. Faz sentido olhar isso esta semana, ou o momento é outro?", "motivo": "dor"}

        async def post(path, payload):
            posted.append(payload["stage"])

        class Bridge(FakeHTTP):
            async def get(self, url, **kwargs):
                class R:
                    status_code = 200
                    def raise_for_status(self): pass
                    def json(self): return bridge_state
                return R()

        with patch.object(app, "ask_llm", new=llm), patch.object(app, "bridge_post", new=post), \
                patch.object(app, "chatwoot_messages", new=AsyncMock(return_value=[])), patch.object(app.httpx, "AsyncClient", Bridge):
            asyncio.run(app.followup_once(now=now))
        return posted

    def test_followup_decides_only_latest_stage_once_per_sequence(self):
        # 2026-09-28 10:00 Brasília (13:00 UTC)
        anchor = 1790600400.0
        app.tracked.clear()
        app.tracked[77] = {"jid": "j", "last_agent_ts": anchor}
        state = {"last_agent_ts": anchor, "last_lead_ts": anchor - 60, "lead": {"registros": {}}}
        self.assertEqual(self.run_followups(anchor + 200, state), [])
        self.assertEqual(self.run_followups(anchor + 400, state), ["5min"])
        self.assertEqual(self.run_followups(anchor + 500, state), [])  # same stage, once
        # downtime: at 2h10 only the latest reached checkpoint is decided
        self.assertEqual(self.run_followups(anchor + 7800, state), ["2h"])

    def test_touch_goes_through_the_reviewer(self):
        anchor = 1790600400.0
        state = {"last_agent_ts": anchor, "last_lead_ts": anchor - 60, "lead": {"registros": {}}, "context": {"capacidade": {"status": "ok"}}}
        for verdict, expected in (({"decision": "reescrever", "parts": ["Texto do revisor. Faz sentido, ou o momento é outro?"]}, "Texto do revisor. Faz sentido, ou o momento é outro?"),
                                  ({"decision": "bloquear", "motivo": "regra 1"}, None)):
            app.tracked.clear(); app.tracked[77] = {"jid": "j", "last_agent_ts": anchor}
            with closing(app.connection()) as conn:
                conn.execute("DELETE FROM decisions"); conn.execute("DELETE FROM sequences"); conn.commit()
            calls, sent = [], []

            async def llm(instruction, **kwargs):
                calls.append(instruction)
                if len(calls) == 1:
                    return {"disparar": True, "texto": "A gente corta seu gasto. Bora?", "motivo": "dor"}
                self.assertIn('"tipo": "toque"', instruction)
                self.assertIn('"capacidade"', instruction)
                return verdict

            async def post(path, payload): sent.append(payload["text"])

            class Bridge(FakeHTTP):
                async def get(self, url, **kwargs):
                    class R:
                        status_code = 200
                        def raise_for_status(self): pass
                        def json(self): return state
                    return R()

            with patch.object(app, "ask_llm", new=llm), patch.object(app, "bridge_post", new=post), \
                    patch.object(app, "chatwoot_messages", new=AsyncMock(return_value=[])), patch.object(app.httpx, "AsyncClient", Bridge):
                asyncio.run(app.followup_once(now=anchor + 400))
            self.assertEqual(sent, [expected] if expected else [])

    def test_contact_metrics_and_lean_agent_profile(self):
        perfil = {"seguidores": 900, "posts_total": 50, "bio": "make", "ultimos_posts": [
            {"legenda": "rotina de make", "tipo": "VIDEO", "link": "https://instagram.com/p/1", "curtidas": 10, "comentarios": 2},
            {"legenda": "coleção nova", "tipo": "IMAGE", "link": "https://instagram.com/p/2", "curtidas": 5, "comentarios": 1}]}
        attrs = app.crm.contact_attributes("carla", {"status": "confirmado", "method": "clique"}, perfil, "loja", None, {"campanha": "raiox", "palavra": "raiox"})
        self.assertEqual(attrs["ig_curtidas_recentes"], 15)
        self.assertEqual(attrs["ig_comentarios_recentes"], 3)
        self.assertEqual(attrs["ig_usuario"], "https://instagram.com/carla")
        self.assertIn("https://instagram.com/p/2", attrs["ig_ultimos_posts"])
        lean = app.enrichment.for_agent(perfil)
        self.assertEqual(lean["ultimos_posts"][0], {"legenda": "rotina de make", "tipo": "VIDEO"})

    def test_lead_reply_does_not_restart_the_clock(self):
        anchor = 1790600400.0
        app.tracked.clear()
        app.tracked[81] = {"jid": "j", "last_agent_ts": anchor}
        state = {"last_agent_ts": anchor, "last_lead_ts": anchor - 60, "lead": {"registros": {}}}
        self.assertEqual(self.run_followups(anchor + 400, state), ["5min"])
        # the lead answered at +20min and the agent replied at +21min
        state = {**state, "last_lead_ts": anchor + 1200, "last_agent_ts": anchor + 1260}
        # 30min checkpoint (anchor+30min) while they are still talking: skipped, not postponed
        self.assertEqual(self.run_followups(anchor + 1850, state), [])
        with closing(app.connection()) as conn:
            row = conn.execute("SELECT disparar, motivo FROM decisions WHERE conversation_id=81 AND stage='30min'").fetchone()
        self.assertEqual(row, (0, "conversa em andamento"))
        # no reset to 5min: the next touch is the 2h one, on the original clock
        self.assertEqual(self.run_followups(anchor + 3000, state), [])
        self.assertEqual(self.run_followups(anchor + 7300, state), ["2h"])

    def test_lead_spoke_last_waits_without_consuming_the_stage(self):
        anchor = 1790600400.0
        app.tracked.clear()
        app.tracked[82] = {"jid": "j", "last_agent_ts": anchor}
        state = {"last_agent_ts": anchor, "last_lead_ts": anchor - 60, "lead": {"registros": {}}}
        self.assertEqual(self.run_followups(anchor + 400, state), ["5min"])
        waiting = {**state, "last_lead_ts": anchor + 1700}  # agent still owes a reply
        self.assertEqual(self.run_followups(anchor + 1850, waiting), [])
        replied = {**state, "last_lead_ts": anchor + 1700, "last_agent_ts": anchor + 1720}
        # conversation still warm (quiet < 30 min) -> skipped
        self.assertEqual(self.run_followups(anchor + 1900, replied), [])

    def test_sequence_ends_and_new_silence_starts_a_new_one(self):
        anchor = 1790600400.0
        app.tracked.clear()
        app.tracked[83] = {"jid": "j", "last_agent_ts": anchor}
        state = {"last_agent_ts": anchor, "last_lead_ts": anchor - 60, "lead": {"registros": {}}}
        self.assertEqual(self.run_followups(anchor + 86500, state), ["d1"])  # last checkpoint
        self.assertEqual(app.sequence(83)[1] is not None, True)
        self.assertEqual(self.run_followups(anchor + 90000, state), [])  # ended, no new silence
        later = {**state, "last_lead_ts": anchor + 90000, "last_agent_ts": anchor + 90060}
        self.assertEqual(self.run_followups(anchor + 90060 + 400, later), ["5min"])

    def test_followup_skips_night_lead_last_paused_and_outcome(self):
        anchor = 1790600400.0
        night = 1790650800.0  # 2026-09-29 00:00 Brasília
        for cid, extra in ((84, {}), (85, {"last_lead_ts": anchor + 10}), (86, {"paused": True}), (87, {"lead": {"registros": {"desfecho": "perdido"}}})):
            app.tracked.clear()
            app.tracked[cid] = {"jid": "j", "last_agent_ts": anchor}
            state = {"last_agent_ts": anchor, "last_lead_ts": anchor - 60, "lead": {"registros": {}}, **extra}
            when = night if cid == 84 else anchor + 400
            self.assertEqual(self.run_followups(when, state), [], cid)

    def test_compact_transcript(self):
        rows = app.compact_transcript([
            {"message_type": 1, "content": "Quantas pessoas dependem de você?", "created_at": 1790600500},
            {"message_type": 0, "content": "quando eu viajo o financeiro para", "created_at": 1790600400},
            {"message_type": 1, "content": "nota interna", "private": True, "created_at": 1790600600},
            {"message_type": 2, "content": "Conversation resolved", "created_at": 1790600700},
            {"message_type": 0, "content": "", "attachments": [{"file_type": "image"}], "created_at": 1790600800},
        ])
        self.assertEqual([r["autor"] for r in rows], ["lead", "agente", "lead"])
        self.assertEqual(rows[0]["texto"], "quando eu viajo o financeiro para")
        self.assertEqual(rows[-1]["texto"], "[anexo]")

    def test_parse_json_object_tolerates_fences_and_prose(self):
        self.assertEqual(app.parse_json_object('```json\n{"decision":"aprovar"}\n```'), {"decision": "aprovar"})
        self.assertEqual(app.parse_json_object('Claro! {"disparar": false, "texto": "", "motivo": "x"} ok'), {"disparar": False, "texto": "", "motivo": "x"})
        self.assertIsNone(app.parse_json_object(""))
        self.assertIsNone(app.parse_json_object("[1,2]"))

    def test_unknown_conversation_is_forgotten(self):
        app.tracked.clear()
        app.tracked[99] = {"jid": "j", "last_agent_ts": 1790600400.0}
        class Gone(FakeHTTP):
            async def get(self, url, **kwargs):
                class R:
                    status_code = 404
                    def raise_for_status(self): raise AssertionError("not reached")
                    def json(self): return {}
                return R()
        with patch.object(app.httpx, "AsyncClient", Gone):
            asyncio.run(app.followup_once(now=1790600400.0 + 400))
        self.assertNotIn(99, app.tracked)

    def test_d4_only_after_price(self):
        self.assertEqual(app.due_stage(4 * 86400 + 10, post_price=False), "d1")
        self.assertEqual(app.due_stage(4 * 86400 + 10, post_price=True), "d4")
        self.assertIsNone(app.due_stage(100, post_price=True))

if __name__ == "__main__": unittest.main(verbosity=2)
