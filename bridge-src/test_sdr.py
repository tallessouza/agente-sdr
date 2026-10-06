import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import app
import handover
import sdr


class ParseReplyTests(unittest.TestCase):
    def test_directives_are_stripped_and_parsed(self):
        reply = ("Sou o agente do Talles.[[QUEBRA]]O que trava na sua operação quando você fica uma semana fora?"
                 "\n[[REGISTRO: dor = \"tudo para quando eu saio\"]]\n[[FOTO: entregas]]")
        parts, directives = sdr.parse_reply(reply)
        self.assertEqual(parts, ["Sou o agente do Talles.", "O que trava na sua operação quando você fica uma semana fora?"])
        self.assertIn({"type": "registro", "campo": "dor", "valor": "\"tudo para quando eu saio\""}, directives)
        self.assertIn({"type": "foto", "nome": "entregas"}, directives)
        self.assertNotIn("[[", "".join(parts))

    def test_escalation_directive(self):
        _parts, directives = sdr.parse_reply("Vou chamar ele agora. [[ESCALAR: indecisão | preciso pensar melhor]]")
        self.assertEqual(directives, [{"type": "escalar", "motivo": "indecisão", "frase": "preciso pensar melhor"}])

    def test_unknown_and_malformed_markers_never_reach_the_lead(self):
        parts, directives = sdr.parse_reply("Oi [[OUTRA: x]] tudo bem? [[REGISTRO: Campo Invalido = x]] [[quebrado")
        self.assertEqual(directives, [])
        self.assertEqual(parts, ["Oi  tudo bem?  quebrado"])

    def test_blank_lines_and_quebra_split_into_at_most_three_bubbles(self):
        parts, _ = sdr.parse_reply("a[[QUEBRA]]b[[QUEBRA]]c[[QUEBRA]]d")
        self.assertEqual(parts, ["a", "b", "c\n\nd"])
        parts, _ = sdr.parse_reply("Entendo totalmente.\n\nQuantas pessoas dependem de você?")
        self.assertEqual(parts, ["Entendo totalmente.", "Quantas pessoas dependem de você?"])
        parts, _ = sdr.parse_reply("linha 1\nlinha 2 do mesmo balão")
        self.assertEqual(parts, ["linha 1\nlinha 2 do mesmo balão"])


    def test_silence_sends_nothing_but_keeps_records(self):
        parts, directives = sdr.parse_reply("[[SILENCIO]] [[REGISTRO: desfecho = desqualificado]]")
        self.assertEqual(parts, [])
        self.assertEqual(directives, [{"type": "registro", "campo": "desfecho", "valor": "desqualificado"}])


class NoDashesTests(unittest.TestCase):
    def test_dashes_between_sentences_become_commas(self):
        cases = {
            "Entendo totalmente — e essa parte eu prefiro que você fale com o Talles.": "Entendo totalmente, e essa parte eu prefiro que você fale com o Talles.",
            "Resolver isso de ponta a ponta — de 3 a 5 fluxos, rodando em 21 dias — é a implantação: R$ 48.000.": "Resolver isso de ponta a ponta, de 3 a 5 fluxos, rodando em 21 dias, é a implantação: R$ 48.000.",
            "O Raio-X — 7 dias.": "O Raio-X, 7 dias.",
            "Fechado — Raio-X, 7 dias —, começando no dia 1.": "Fechado, Raio-X, 7 dias, começando no dia 1.",
            "Isso fica com ele —": "Isso fica com ele",
            "— primeiro ponto\n– segundo": "primeiro ponto\nsegundo",
            "o gargalo mapeado–o fluxo rodando": "o gargalo mapeado, o fluxo rodando",
            "Resposta rápida - sem enrolação.": "Resposta rápida, sem enrolação.",
            "dias 2-3 e o e-mail; R$ 12 a 18 mil": "dias 2-3 e o e-mail; R$ 12 a 18 mil",
        }
        for raw, expected in cases.items():
            self.assertEqual(sdr.no_dashes(raw), expected, raw)
        for dash in "\u2014\u2013\u2012\u2015":
            self.assertNotIn(dash, sdr.no_dashes(f"a {dash} b{dash}c {dash}"))


class NoColonsTests(unittest.TestCase):
    def test_colons_chaining_sentences_are_split(self):
        cases = {
            "O Raio-X custa R$ 12.000 e dura 7 dias: o Talles também abate na implantação.": "O Raio-X custa R$ 12.000 e dura 7 dias. O Talles também abate na implantação.",
            "Resolver isso de ponta a ponta é a implantação: R$ 48.000.": "Resolver isso de ponta a ponta é a implantação, R$ 48.000.",
            "São 4 vagas: 3 já foram.": "São 4 vagas, 3 já foram.",
            "Antes, três perguntas rápidas:": "Antes, três perguntas rápidas.",
            "Te respondo às 10:30, link https://wa.me/55": "Te respondo às 10:30, link https://wa.me/55",
        }
        for raw, expected in cases.items():
            self.assertEqual(sdr.no_colons(raw), expected, raw)
        self.assertEqual(sdr.plain_style("Fechado — Raio-X: 7 dias: começando no dia 1."), "Fechado, Raio-X, 7 dias. Começando no dia 1.")


class GuardrailTests(unittest.TestCase):
    def test_blocks_stack_names_accent_insensitive(self):
        self.assertEqual(sdr.leaked_terms(["Eu rodo no Hermes com Gêmini? não, gemini"]), ["hermes", "gemini"])
        self.assertEqual(sdr.leaked_terms(["arquivo em /opt/data/x"]), ["/opt/"])

    def test_offer_prerequisites_are_not_leaks(self):
        allowed = ["Sem Codex? Dá pra levar a Conta do Gemini junto na compra.",
                   "O Codex vem no plano pago do ChatGPT, Plus ou maior. Conta grátis não funciona.",
                   "Se você já assina o ChatGPT Plus, está resolvido."]
        self.assertEqual(sdr.leaked_terms(allowed), [])
        self.assertEqual(sdr.leaked_terms(["Eu rodo no Gemini da Google"]), ["gemini"])
        self.assertEqual(sdr.leaked_terms(["Sou um ChatGPT treinado"]), ["chatgpt"])

    def test_normal_sales_text_passes(self):
        text = ["Entendo totalmente. A implantação é R$ 48.000, 21 dias. A evolução do seu time aparece no dia 3, faz sentido?"]
        self.assertEqual(sdr.leaked_terms(text), [])


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patches = [
            patch.object(sdr, "DB_PATH", self.dir / "bridge.db"),
            patch.object(sdr, "CAPACITY_FILE", self.dir / "capacidade.json"),
            patch.object(sdr, "MEDIA_DIR", self.dir / "midia"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def write_capacity(self, **overrides):
        data = {"mes": "outubro/2026", "vagas_total": 4, "vagas_restantes": 3, "horas_comprometidas": 40,
                "horas_limite": 75, "proximo_mes": "novembro/2026", "atualizado_em": datetime.now().isoformat()}
        data.update(overrides)
        (self.dir / "capacidade.json").write_text(json.dumps(data))

    def test_capacity_unknown_when_missing(self):
        self.assertEqual(sdr.capacity(), {"status": "desconhecido"})

    def test_capacity_ok_and_full(self):
        self.write_capacity()
        self.assertTrue(sdr.capacity()["pode_oferecer_este_mes"])
        self.write_capacity(horas_comprometidas=76)
        self.assertFalse(sdr.capacity()["pode_oferecer_este_mes"])
        self.write_capacity(vagas_restantes=0)
        self.assertFalse(sdr.capacity()["pode_oferecer_este_mes"])

    def test_capacity_stale(self):
        self.write_capacity(atualizado_em=(datetime.now() - timedelta(days=9)).isoformat())
        self.assertEqual(sdr.capacity(), {"status": "desatualizado"})

    def test_only_described_media_is_offered_and_loadable(self):
        media = self.dir / "midia"
        media.mkdir()
        (media / "entregas.jpg").write_bytes(b"\xff\xd8jpg")
        (media / "sem-descricao.png").write_bytes(b"png")
        (media / "descricoes.json").write_text(json.dumps({"entregas.jpg": "painel de entregas"}))
        self.assertEqual(sdr.media_catalog(), [{"nome": "entregas", "descricao": "painel de entregas"}])
        self.assertIsNotNone(sdr.load_media("entregas"))
        self.assertIsNone(sdr.load_media("sem-descricao"))
        self.assertIsNone(sdr.load_media("../../etc/passwd"))

    def test_origin_from_prefilled_instagram_text(self):
        self.assertEqual(sdr.origin_from_text("Oi! Sou @loja.da_ana [R3]"), {"instagram": "@loja.da_ana", "peca": "R3", "canal": "instagram"})
        self.assertEqual(sdr.origin_from_text("Oi! Sou @there [R2]"), {"peca": "R2", "canal": "instagram"})
        self.assertIsNone(sdr.origin_from_text("bom dia, quanto custa?"))

    def test_offer_from_the_campaign_text(self):
        instalador = sdr.origin_from_text("Oi! Sou o @ana.studio e quero o meu Time de IA instalado")
        self.assertEqual(instalador, {"instagram": "@ana.studio", "canal": "instagram", "oferta": "instalador"})
        raiox = sdr.origin_from_text("E aí! Sou o @marina.escala e quero saber mais sobre o Raio-X")
        self.assertEqual(raiox["oferta"], "raiox")
        self.assertEqual(sdr.offer_from_text("quero o raiox"), "raiox")
        self.assertEqual(sdr.offer_from_text("quero meu TIME DE IA"), "instalador")
        self.assertIsNone(sdr.offer_from_text("meu time é bom, quanto custa?"))
        self.assertEqual(sdr.origin_from_text("quero o meu Time de IA instalado"), {"oferta": "instalador"})

    def test_offer_and_next_step_reach_the_context(self):
        sdr.remember_lead(11, "55@s.whatsapp.net", "Oi! Sou o @ana e quero o meu Time de IA instalado")
        payload = json.loads(sdr.trusted_context(11).split("\n")[1])
        self.assertEqual(payload["oferta"], "instalador")
        self.assertEqual(payload["lead"]["origem"]["oferta"], "instalador")
        with sdr.connect() as c:
            for field, value in (("tem_vps", "não"), ("proximo_passo", "contratar a VPS"), ("proximo_passo_em", "2026-10-08")):
                c.execute("INSERT INTO sdr_records VALUES (?,?,?,?)", (11, field, value, 1.0))
        lead = sdr.context_payload(11)["lead"]
        self.assertEqual(lead["registros"]["proximo_passo_em"], "2026-10-08")
        self.assertEqual(lead["proximo_passo"], {"texto": "contratar a VPS", "ate": "2026-10-08"})
        # What the agent records later wins over the campaign text.
        with sdr.connect() as c:
            c.execute("INSERT INTO sdr_records VALUES (?,?,?,?)", (11, "oferta", "raiox", 2.0))
        self.assertEqual(sdr.context_payload(11)["oferta"], "raiox")
        # No campaign and no record: the agent discovers it in the conversation.
        sdr.remember_lead(12, "56@s.whatsapp.net", "bom dia, quanto custa?")
        self.assertNotIn("oferta", sdr.context_payload(12))

    def test_offer_facts_file(self):
        with patch.object(sdr, "OFFERS_FILE", self.dir / "ofertas.json"):
            self.assertEqual(sdr.offers(), {"status": "desconhecido"})
        with patch.object(sdr, "OFFERS_FILE", Path(__file__).resolve().parent.parent / "hermes-sdr" / "ofertas.json"):
            facts = sdr.offers()
            self.assertEqual(facts["instalador"]["preco"], "R$ 47")
            self.assertEqual(facts["instalador"]["link_compra"], "https://instalador.talles.dev/antes")
            self.assertEqual(facts["raiox"]["preco"], "R$ 12.000")
            self.assertEqual(sdr.context_payload(13)["ofertas"], facts)

    def test_corrections_reach_the_next_turn(self):
        sdr.record_correction(8, ["Dados ficam comigo.", "A implantação é R$ 48.000."], ["Dados ficam comigo."], "review")
        sdr.record_correction(8, ["igual"], ["igual"], "review")  # unchanged: not stored
        payload = json.loads(sdr.trusted_context(8).split("\n")[1])
        self.assertEqual(payload["mensagens_corrigidas"], [{"voce_escreveu": "Dados ficam comigo.\n\nA implantação é R$ 48.000.", "o_lead_recebeu": "Dados ficam comigo."}])
        self.assertNotIn("mensagens_corrigidas", json.loads(sdr.trusted_context(9).split("\n")[1]))

    def test_origin_recorded_once_and_in_context(self):
        sdr.remember_lead(7, "55@s.whatsapp.net", "Oi! Sou @ana [R1]")
        sdr.remember_lead(7, "55@s.whatsapp.net", "Sou @outra [R9]")
        context = sdr.trusted_context(7, guidance=[(1, "traga a âncora agora")])
        payload = json.loads(context.split("\n")[1])
        self.assertEqual(payload["lead"]["origem"]["instagram"], "@ana")
        self.assertEqual(payload["orientacoes"], ["traga a âncora agora"])
        self.assertEqual(payload["capacidade"], {"status": "desconhecido"})


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db),
                        patch.object(sdr, "typing_seconds", return_value=0), patch.object(app, "send_presence", AsyncMock())]
        for p in self.patches:
            p.start()
        self.send = AsyncMock()
        self.chatwoot = AsyncMock()
        self.escalate = AsyncMock()
        self.record = AsyncMock()
        self.patches += [patch.object(app, "send_evolution", self.send), patch.object(app, "add_chatwoot_message", self.chatwoot),
                         patch.object(app, "escalate", self.escalate), patch.object(sdr, "record", self.record),
                         patch.object(sdr, "private_note", AsyncMock())]
        for p in self.patches[5:]:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    async def test_split_messages_records_and_escalation(self):
        reply = "Entendo.[[QUEBRA]]Vou chamar o Talles, pode ser?[[REGISTRO: desfecho = escalado]][[ESCALAR: pediu pessoa | quero falar com alguém]]"
        await app.deliver_agent_reply("5511@s.whatsapp.net", "src", 3, reply, "msg-1", "quero falar com alguém")
        self.assertEqual([c.args[1] for c in self.send.await_args_list], ["Entendo.", "Vou chamar o Talles, pode ser?"])
        self.assertEqual(self.send.await_args_list[0].kwargs["reply_to"], "msg-1")
        self.assertIsNone(self.send.await_args_list[1].kwargs["reply_to"])
        self.record.assert_awaited_once_with(3, "desfecho", "escalado")
        self.assertEqual(self.escalate.await_args.args[3]["motivo"], "pediu pessoa")

    async def test_guardrail_replaces_leaking_reply_and_escalates(self):
        await app.deliver_agent_reply("5511@s.whatsapp.net", "src", 3, "Eu sou o Hermes Agent da Nous Research.", None, "que IA é você?")
        self.assertEqual([c.args[1] for c in self.send.await_args_list], [sdr.FALLBACK_REPLY])
        self.assertIn("guardrail", self.escalate.await_args.args[3]["motivo"])

    async def test_campaign_offer_is_recorded_like_a_directive(self):
        with patch.object(app, "brain_event", AsyncMock()) as event:
            await app.record_offer_from_origin(5, {"instagram": "@ana", "oferta": "instalador"})
            await app.record_offer_from_origin(6, {"instagram": "@ana"})
            await app.record_offer_from_origin(7, None)
            await asyncio.sleep(0)
        self.record.assert_awaited_once_with(5, "oferta", "instalador")
        self.assertEqual(event.await_args.args[0], "/events/record")
        self.assertEqual({k: event.await_args.args[1][k] for k in ("conversation_id", "campo", "valor")},
                         {"conversation_id": 5, "campo": "oferta", "valor": "instalador"})

    def test_session_prefix_defaults_to_v13(self):
        import importlib, os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HERMES_SESSION_PREFIX", None)
            self.assertEqual(importlib.reload(app).HERMES_SESSION_PREFIX, "wa:v13:")

    async def test_owner_messages_are_not_leads(self):
        with patch.object(sdr, "OWNER_IDS", {"5564999425822", "556499425822", "148563086540988"}):
            self.assertTrue(sdr.is_owner("556499425822@s.whatsapp.net"))
            self.assertTrue(sdr.is_owner("148563086540988@lid"))
            self.assertTrue(sdr.is_owner("5564999425822@s.whatsapp.net"))
            self.assertFalse(sdr.is_owner("5511@s.whatsapp.net"))
        with patch.object(sdr, "OWNER_IDS", set()):
            self.assertFalse(sdr.is_owner("556499425822@s.whatsapp.net"))


if __name__ == "__main__":
    unittest.main()
