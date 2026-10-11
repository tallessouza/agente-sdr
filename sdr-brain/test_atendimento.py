"""Oferta "atendimento" (prospecção ativa): sem preço e sem link na conversa; nada das regras do Instalador."""
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDR_BRAIN_TOKEN", "test")
os.environ.setdefault("SDR_BRAIN_DB", os.path.join(tempfile.gettempdir(), "sdr-brain-atendimento.db"))
import oferta  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OFERTAS = {k: v for k, v in json.loads((ROOT / "hermes-sdr" / "ofertas.json").read_text(encoding="utf-8")).items() if k in oferta.OFFERS}
A = {"oferta": "atendimento", "ofertas": OFERTAS}


class AtendimentoTests(unittest.TestCase):
    def test_offer_is_known_and_has_facts(self):
        self.assertIn("atendimento", oferta.OFFERS)
        self.assertEqual(oferta.current_offer(A), "atendimento")
        self.assertTrue(any("conversa de 20 minutos" in line for line in oferta.facts(A)))

    def test_any_price_or_link_is_flagged(self):
        issues = oferta.check(["Fica R$ 2.997 a implantação."], A, [])
        self.assertTrue(any("preço na conversa do Atendente" in i for i in issues))
        issues = oferta.check(["Dá uma olhada aqui https://instalador.talles.dev/oferta/whatsapp"], A, [])
        self.assertTrue(any("link na conversa do Atendente" in i for i in issues))

    def test_honest_reveal_and_call_pass(self):
        parts = ["Obrigado por responder! Sou o agente do Talles e preciso ser honesto: não tenho dúvida nenhuma, foi um teste de tempo de resposta. Vocês responderam em 2 horas.",
                 "Não é crítica: a essa hora ninguém tem obrigação de estar olhando o WhatsApp. É justamente isso que eu resolvo.",
                 "Numa semana normal, quantas mensagens chegam assim, depois do horário?"]
        self.assertEqual(oferta.check(parts, A, []), [])
        self.assertEqual(oferta.check(["Depende do volume de vocês, por isso o Talles monta a proposta numa conversa de 20 minutos. Fica melhor terça às 10h ou quarta às 15h?"], A, []), [])
        # since 09/10 22h there is no special condition in this offer
        self.assertTrue(oferta.check(["E tem uma condição especial de implantação para os 5 primeiros negócios que fecharem."], A, []))
        self.assertTrue(oferta.check(["Tem uma condição especial pra você fechar hoje."], A, []))
        self.assertTrue(oferta.check(["Tem uma condição especial pra você."], {"oferta": "instalador", "ofertas": OFERTAS}, []))

    def test_installer_rules_do_not_apply(self):
        # "atende seus clientes no WhatsApp" is the product here.
        self.assertEqual(oferta.check(["O atendente responde seus clientes no WhatsApp a qualquer hora, sem você estar online."], A, []), [])
        self.assertFalse(oferta.price_without_link(["A instalação fica pronta rápido."], A))


class AtendimentoSequenceTests(unittest.TestCase):
    def test_four_touches_only_for_atendimento(self):
        import app
        self.assertEqual([s for s, _ in app.stages_for("atendimento", False)], ["2h", "d1", "d3", "d6"])
        # the other offers keep their sequence
        self.assertEqual(app.due_stage(1800, False, "instalador"), "30min")
        self.assertEqual(app.due_stage(1800, False), "30min")

    def test_hours_are_read_from_the_dossier(self):
        import horario
        h = horario.parse_hours("seg a sex 8h30–19h, sáb 8h–12h, dom fechado")
        self.assertEqual(h[0], [(8.5, 19.0)]); self.assertEqual(h[4], [(8.5, 19.0)]); self.assertEqual(h[5], [(8.0, 12.0)]); self.assertEqual(h[6], [])
        h = horario.parse_hours("seg a sex 8h–12h e 13h30–18h, sáb 8h–12h, dom fechado")
        self.assertEqual(h[2], [(8.0, 12.0), (13.5, 18.0)])
        h = horario.parse_hours("seg fechado, ter a sex 8h30–19h, sáb 8h–12h, dom fechado")
        self.assertEqual((h[0], h[1]), ([], [(8.5, 19.0)]))
        h = horario.parse_hours("seg e ter 8h30–19h, qua 8h–19h, qui e sex 8h30–19h, sáb e dom fechado")
        self.assertEqual((h[1], h[2], h[3], h[6]), ([(8.5, 19.0)], [(8.0, 19.0)], [(8.5, 19.0)], []))
        self.assertEqual(horario.parse_hours("seg a sex 9h–18h, sáb 9h–0h, dom fechado")[5], [(9.0, 24.0)])
        self.assertEqual(horario.parse_hours("aberto 24h todos os dias")[3], [(0.0, 24.0)])
        self.assertIsNone(horario.parse_hours("")); self.assertIsNone(horario.parse_hours("horário não informado"))

    def test_four_touches_six_hours_apart_inside_open_hours_and_the_window(self):
        import horario
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        ts = lambda *a: datetime(*a, tzinfo=tz).timestamp()
        hours = {d: [(0.0, 24.0)] for d in range(7)}
        # Open all day: 6 h apart would push the 4th out of the 23 h window, so they tighten evenly.
        times = horario.touch_times(ts(2026, 10, 13, 9, 0), ts(2026, 10, 14, 8, 0), hours, tz)
        self.assertEqual(len(times), 4)
        gaps = [b - a for a, b in zip([ts(2026, 10, 13, 9, 0)] + times, times)]
        self.assertTrue(all(abs(g - gaps[0]) < 1 for g in gaps) and gaps[0] <= 6 * 3600)
        self.assertLessEqual(times[-1], ts(2026, 10, 14, 8, 0))
        # Business hours 8h-18h, lead wrote Tuesday 9h: the 4 go out in open time only, 2 h or more apart.
        office = horario.parse_hours("seg a sex 8h–18h, sáb e dom fechado")
        times = horario.touch_times(ts(2026, 10, 13, 9, 5), ts(2026, 10, 14, 8, 5), office, tz)
        self.assertEqual(len(times), 4)
        for t in times:
            self.assertTrue(8 <= datetime.fromtimestamp(t, tz).hour < 18)
        self.assertTrue(all(b - a >= 2 * 3600 - 60 for a, b in zip(times, times[1:])))
        # Saturday night reply, business closed until Monday: daytime fallback on Sunday, still 4 touches.
        shop = horario.parse_hours("seg a sex 8h–18h, sáb 8h–12h, dom fechado")
        times = horario.touch_times(ts(2026, 10, 10, 20, 25), ts(2026, 10, 11, 19, 25), shop, tz)
        self.assertEqual(len(times), 4)
        for t in times:
            local = datetime.fromtimestamp(t, tz)
            self.assertEqual(local.day, 11); self.assertTrue(9 <= local.hour < 20)

    def test_objection_touch_is_the_next_morning_inside_the_window(self):
        import app
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        ts = lambda *a: datetime(*a, tzinfo=tz).timestamp()
        # Conversation 122: "não faz sentido" Saturday 20:12; business open daily 8h-18h -> Sunday 9h.
        state = {"lead": {"origem": {"negocio": {"horario_resumo": "seg a dom 8h–18h"}}}}
        when = app.objection_touch_time(state, ts(2026, 10, 10, 20, 13), ts(2026, 10, 10, 20, 12))
        self.assertEqual(datetime.fromtimestamp(when, tz).strftime("%d %H:%M"), "11 09:00")
        # Closed on Sunday: daytime fallback, still inside the 23 h window.
        closed = {"lead": {"origem": {"negocio": {"horario_resumo": "seg a sex 8h–18h, sáb 8h–12h, dom fechado"}}}}
        when = app.objection_touch_time(closed, ts(2026, 10, 10, 20, 13), ts(2026, 10, 10, 20, 12))
        local = datetime.fromtimestamp(when, tz)
        self.assertEqual(local.day, 11); self.assertTrue(9 <= local.hour < 20)
        self.assertLessEqual(when, ts(2026, 10, 10, 20, 12) + app.ATENDIMENTO_WINDOW_SECONDS)

    def test_touches_go_in_order_and_stop_when_the_window_closes(self):
        import app
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        anchor = datetime(2026, 10, 13, 9, 0, tzinfo=tz).timestamp()
        state = {"jid": "5548999990000@cloud", "lead": {"origem": {"negocio": {"horario_resumo": "aberto 24h todos os dias"}}}}
        times = app.atendimento_touch_times(state, anchor, anchor)
        done: set[str] = set()
        # Everything is past due (brain down): still the FIRST undecided one, never a jump to d6.
        self.assertEqual(app.atendimento_due_stage(state, anchor, anchor, times[3] + 60, lambda s: s in done), "2h")
        done |= {"2h", "d1"}
        self.assertEqual(app.atendimento_due_stage(state, anchor, anchor, times[3] + 60, lambda s: s in done), "d3")
        # Window closed (10/10: legacy conversations got a d6 at once): nothing at all.
        self.assertIsNone(app.atendimento_due_stage(state, anchor, anchor, anchor + app.ATENDIMENTO_WINDOW_SECONDS + 1))
        self.assertTrue(app.official(state))
        self.assertFalse(app.official({"jid": "554899990000@s.whatsapp.net"}))

    def test_due_stage_follows_the_touch_times(self):
        import app
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        anchor = datetime(2026, 10, 13, 9, 0, tzinfo=tz).timestamp()
        state = {"lead": {"origem": {"negocio": {"horario_resumo": "aberto 24h todos os dias"}}}}
        times = app.atendimento_touch_times(state, anchor, anchor)
        self.assertIsNone(app.atendimento_due_stage(state, anchor, anchor, times[0] - 60))
        self.assertEqual(app.atendimento_due_stage(state, anchor, anchor, times[0] + 60), "2h")
        self.assertEqual(app.atendimento_due_stage(state, anchor, anchor, times[3] + 60), "2h")  # in order, first undecided
        self.assertEqual(app.atendimento_due_stage(state, anchor, anchor, times[3] + 60, lambda s: s != "d6"), "d6")


class TouchSpacingTests(unittest.TestCase):
    def test_noris_case_never_four_touches_in_one_hour(self):
        # 10/10: answered Saturday 18:54, open "seg a sáb 8h–20h, dom fechado" -> got 4 touches 15 min apart.
        import horario
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        anchor = datetime(2026, 10, 10, 18, 54, tzinfo=tz).timestamp()
        times = horario.touch_times(anchor, anchor + 23.5 * 3600, horario.parse_hours("seg a sáb 8h–20h, dom fechado"), tz)
        self.assertEqual(len(times), 4)
        self.assertTrue(all(b - a >= horario.MIN_GAP - 1 for a, b in zip([anchor] + times, times)))
        self.assertLessEqual(times[-1], anchor + 23.5 * 3600)

    def test_window_too_short_drops_touches_instead_of_squeezing_them(self):
        import horario
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        from datetime import datetime
        hours = {d: [(0.0, 24.0)] for d in range(7)}
        anchor = datetime(2026, 10, 13, 9, 0, tzinfo=tz).timestamp()
        times = horario.touch_times(anchor, anchor + 5 * 3600, hours, tz)
        self.assertEqual(len(times), 2)
        self.assertTrue(all(b - a >= horario.MIN_GAP - 1 for a, b in zip(times, times[1:])))

    def test_six_hours_unless_the_six_hour_mark_is_closed(self):
        # Talles, 10/10 23h40: "intervalo de 2h só se o toque daqui a 6h der fora do expediente da empresa".
        import horario
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        anchor = datetime(2026, 10, 12, 14, 0, tzinfo=tz).timestamp()  # Monday 14h, open every day
        times = horario.touch_times(anchor, anchor + 23.5 * 3600, horario.parse_hours("aberto 24h todos os dias"), tz)
        # 20h is closed for sending -> 16h; 22h closed -> 18h; 0h and 20h closed -> next opening 9h; 15h is past
        # the window (13h20) -> 11h.
        self.assertEqual([datetime.fromtimestamp(t, tz).strftime("%a %H:%M") for t in times], ["Mon 16:00", "Mon 18:00", "Tue 09:00", "Tue 11:00"])
        # Night reply: the first goes at the opening and the second still gets its 6 h, since the 4 fit.
        anchor = datetime(2026, 10, 12, 20, 30, tzinfo=tz).timestamp()
        times = horario.touch_times(anchor, anchor + 23.5 * 3600, horario.parse_hours("seg a sex 8h–20h, sáb e dom fechado"), tz)
        self.assertEqual([datetime.fromtimestamp(t, tz).strftime("%H:%M") for t in times], ["09:00", "15:00", "17:00", "19:00"])
        # Morning lead: 6 h would cost a touch, so the 4 win and go 2 h apart.
        anchor = datetime(2026, 10, 13, 9, 0, tzinfo=tz).timestamp()
        times = horario.touch_times(anchor, anchor + 23.5 * 3600, horario.parse_hours("seg a sex 8h–20h, sáb e dom fechado"), tz)
        self.assertEqual([datetime.fromtimestamp(t, tz).strftime("%H:%M") for t in times], ["11:00", "13:00", "15:00", "17:00"])

    def test_window_ends_thirty_minutes_early(self):
        import app
        self.assertEqual(app.ATENDIMENTO_WINDOW_SECONDS, 23 * 3600 + 30 * 60)

    def test_robots_keep_getting_touches_and_real_outcomes_stop_them(self):
        import app
        self.assertTrue(app.is_robot({"resposta_automatica": "sim"}))
        self.assertFalse(app.outcome_stops_touches({"resposta_automatica": "sim", "desfecho": "desqualificado"}))
        self.assertFalse(app.outcome_stops_touches({"atende_com_ia": "sim", "desfecho": "avaliar_dono"}))
        self.assertTrue(app.outcome_stops_touches({"desfecho": "desqualificado"}))
        self.assertTrue(app.outcome_stops_touches({"resposta_automatica": "sim", "desfecho": "call_marcada"}))
        self.assertFalse(app.outcome_stops_touches({}))

    def test_no_touch_within_two_hours_of_the_last_one(self):
        import app
        app.record_decision(4242, "2h", 1000.0, 50_000.0, True, "teste")
        self.assertTrue(app.touch_too_soon(4242, 50_000.0 + 3600))
        self.assertFalse(app.touch_too_soon(4242, 50_000.0 + 2 * 3600 + 1))
        app.record_decision(4243, "2h", 1000.0, 50_000.0, False, "não disparou")
        self.assertFalse(app.touch_too_soon(4243, 50_000.0 + 60))


if __name__ == "__main__":
    unittest.main()
