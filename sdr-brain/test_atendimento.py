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
        self.assertEqual([s for s, _ in app.stages_for("atendimento", False)], ["2h", "d1", "d3", "d6", "c1", "c2", "c3"])
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
        # Talles 11/10: 6 em 6; 2 h só quando as 6 h caem fora do expediente; o que passa da janela vai por template.
        import horario
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        ts = lambda *a: datetime(*a, tzinfo=tz).timestamp()
        fmt = lambda times: [datetime.fromtimestamp(t, tz).strftime("%a %H:%M") for t in times]
        hours = {d: [(0.0, 24.0)] for d in range(7)}
        anchor = ts(2026, 10, 13, 9, 0)
        times = horario.touch_times(anchor, anchor + 23.5 * 3600, hours, tz)
        # The 4 go inside the window (Talles 11/10): 6 h would leave the 4th for tomorrow, after the window, so the gaps shrink.
        self.assertEqual(fmt(times), ["Tue 13:30", "Tue 15:30", "Tue 17:30", "Tue 19:30"])
        self.assertEqual([horario.touch_channel(t, anchor + 23.5 * 3600) for t in times], ["texto"] * 4)
        office = horario.parse_hours("seg a sex 8h–18h, sáb e dom fechado")
        times = horario.touch_times(ts(2026, 10, 13, 9, 5), 0, office, tz)
        self.assertEqual(fmt(times), ["Tue 15:05", "Tue 17:05", "Wed 09:00", "Wed 15:00"])
        # Saturday night reply, closed on Sunday: the 4 still go by text inside the window, on Sunday 9h–20h (Talles 11/10).
        shop = horario.parse_hours("seg a sex 8h–18h, sáb 8h–12h, dom fechado")
        anchor = ts(2026, 10, 10, 20, 25)
        times = horario.touch_times(anchor, anchor + 23.5 * 3600, shop, tz)
        self.assertEqual(fmt(times), ["Sun 09:00", "Sun 15:00", "Sun 17:30", "Sun 19:30"])
        self.assertEqual({horario.touch_channel(t, anchor + 23.5 * 3600) for t in times}, {"texto"})
        # No opening in the next days at all: daytime hours.
        self.assertEqual(len(horario.touch_times(anchor, 0, {d: [] for d in range(7)}, tz)), 4)

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
        # Window closed: the touch still happens (as a template), the first undecided one.
        self.assertEqual(app.atendimento_due_stage(state, anchor, anchor, times[3] + 60), "2h")
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
        self.assertEqual([datetime.fromtimestamp(t, tz).strftime("%a %H:%M") for t in times], ["Sun 09:00", "Sun 14:00", "Sun 16:00", "Sun 18:00"])  # inside her window (Talles 11/10)
        self.assertTrue(all(b - a >= horario.MIN_GAP - 1 for a, b in zip([anchor] + times, times)))

    def test_six_hours_unless_the_six_hour_mark_is_closed(self):
        # Talles, 10/10 23h40: "intervalo de 2h só se o toque daqui a 6h der fora do expediente da empresa".
        import horario
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        week = horario.parse_hours("seg a sex 8h–20h, sáb e dom fechado")
        fmt = lambda times: [datetime.fromtimestamp(t, tz).strftime("%H:%M") for t in times]
        anchor = datetime(2026, 10, 12, 14, 0, tzinfo=tz).timestamp()
        self.assertEqual(fmt(horario.touch_times(anchor, 0, horario.parse_hours("aberto 24h todos os dias"), tz)), ["16:00", "18:00", "09:00", "15:00"])
        anchor = datetime(2026, 10, 12, 20, 30, tzinfo=tz).timestamp()
        self.assertEqual(fmt(horario.touch_times(anchor, 0, week, tz)), ["09:00", "15:00", "17:00", "19:00"])
        anchor = datetime(2026, 10, 13, 9, 0, tzinfo=tz).timestamp()
        self.assertEqual(fmt(horario.touch_times(anchor, 0, week, tz)), ["15:00", "17:00", "19:00", "09:00"])

    def test_holiday_is_closed_and_rare_hours_are_kept(self):
        # 12/10 is a national holiday (ofertas.json): Saturday-night reply -> Tuesday, not Monday.
        import horario
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        anchor = datetime(2026, 10, 10, 20, 25, tzinfo=tz).timestamp()
        shop = horario.parse_hours("seg a sex 8h–18h, sáb 8h–12h, dom fechado")
        times = horario.touch_times(anchor, 0, shop, tz, holidays={"2026-10-12"})
        self.assertEqual([datetime.fromtimestamp(t, tz).strftime("%a %H:%M") for t in times], ["Tue 09:00", "Tue 15:00", "Tue 17:00", "Wed 09:00"])
        # Open only on Fridays and Saturdays (#84): its own Friday, not a closed Sunday.
        rare = horario.parse_hours("seg a qui fechado, sex 10h–20h, sáb 10h–14h, dom fechado")
        first = horario.touch_times(anchor, 0, rare, tz)[0]
        self.assertEqual(datetime.fromtimestamp(first, tz).strftime("%a %H:%M"), "Fri 10:00")

    def test_window_ends_thirty_minutes_early(self):
        import app
        self.assertEqual(app.ATENDIMENTO_WINDOW_SECONDS, 23 * 3600 + 30 * 60)

    def test_robots_keep_getting_touches_and_real_outcomes_stop_them(self):
        import app
        self.assertTrue(app.is_robot({"resposta_automatica": "sim"}))
        self.assertFalse(app.outcome_stops_touches({"resposta_automatica": "sim", "desfecho": "avaliar_dono"}))
        self.assertTrue(app.outcome_stops_touches({"resposta_automatica": "sim", "desfecho": "desqualificado"}))  # a person said no
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


class RetomadaPlanTests(unittest.TestCase):
    def test_when_label_and_sentence_case(self):
        import app
        from datetime import datetime
        tz = app.BUSINESS_TZ
        sent = datetime(2026, 10, 10, 19, 40, tzinfo=tz).timestamp()
        self.assertEqual(app.when_label(sent, datetime(2026, 10, 11, 10, 0, tzinfo=tz).timestamp()), "ontem às 19h40")
        self.assertEqual(app.when_label(sent, datetime(2026, 10, 13, 10, 0, tzinfo=tz).timestamp()), "no sábado às 19h40")
        self.assertEqual(app.when_label(datetime(2026, 10, 13, 9, 0, tzinfo=tz).timestamp(), datetime(2026, 10, 13, 15, 0, tzinfo=tz).timestamp()), "hoje às 9h")
        t1 = "Oi, {{1}}! Aqui é o agente do Talles, uma inteligência artificial. {{2}} mandei uma mensagem"
        t2 = "Olá, {{1}}! Sou o agente do Talles, uma IA. Testei o WhatsApp de vocês {{2}} e a mensagem"
        self.assertEqual(app.fit_case("ontem às 19h40", t1, 2), "Ontem às 19h40")
        self.assertEqual(app.fit_case("ontem às 19h40", t2, 2), "ontem às 19h40")
        self.assertEqual(app.short_name("Clínica Odontológica Rident - Centro | Florianópolis"), "Clínica Odontológica Rident")

    def test_retomada_goes_in_the_business_hours(self):
        import app
        from datetime import datetime
        tz = app.BUSINESS_TZ
        sunday_night = datetime(2026, 10, 11, 21, 0, tzinfo=tz).timestamp()
        start, until = app.retomada_window({"horario_resumo": "seg a sex 8h–18h, sáb 8h–12h, dom fechado"}, sunday_night)
        self.assertEqual(datetime.fromtimestamp(start, tz).strftime("%a %H:%M"), "Mon 09:30")  # sending starts at 9h, +30 min
        self.assertEqual(datetime.fromtimestamp(until, tz).strftime("%H:%M"), "17:45")
        monday_ten = datetime(2026, 10, 12, 10, 0, tzinfo=tz).timestamp()
        start, _ = app.retomada_window({"horario_resumo": "seg a sex 8h–18h"}, monday_ten)
        self.assertEqual(start, monday_ten)  # open now: right away

    def test_rendered_retomada_has_no_open_slot(self):
        import app
        text = app.render_retomada("Oi, {{1}}! {{2}} mandei. {{3}} Topa?", ["pessoal da X", "Ontem às 19h", "Quem chama fecha com quem responde."])
        self.assertEqual(text, "Oi, pessoal da X! Ontem às 19h mandei. Quem chama fecha com quem responde. Topa?")



class CadenceTests(unittest.TestCase):
    def test_daily_cadence_on_working_days_after_the_four_touches(self):
        # Talles 11/10: after the 4 touches, one a working day on the next days (templates), in the business hours.
        import horario
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        fmt = lambda times: [datetime.fromtimestamp(t, tz).strftime("%a %d %H:%M") for t in times]
        office = horario.parse_hours("seg a sex 8h–18h, sáb 8h–12h, dom fechado")
        last = datetime(2026, 10, 9, 17, 0, tzinfo=tz).timestamp()  # Friday
        self.assertEqual(fmt(horario.cadence_times(last, office, tz, holidays={"2026-10-12"})), ["Tue 13 10:00", "Wed 14 10:00", "Thu 15 10:00"])
        late = horario.parse_hours("seg fechado, ter a sex 14h–20h, sáb e dom fechado")
        self.assertEqual(fmt(horario.cadence_times(last, late, tz)), ["Tue 13 15:00", "Wed 14 15:00", "Thu 15 15:00"])

    def test_sequence_has_seven_stages_and_the_cadence_layers(self):
        import app
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        anchor = datetime(2026, 10, 13, 9, 0, tzinfo=tz).timestamp()
        state = {"lead": {"origem": {"negocio": {"horario_resumo": "seg a sex 8h–18h, sáb e dom fechado"}}}}
        times = app.atendimento_touch_times(state, anchor, anchor)
        self.assertEqual(len(times), 7)
        self.assertTrue(all(b > a for a, b in zip(times, times[1:])))
        self.assertTrue(all(datetime.fromtimestamp(t, tz).weekday() < 5 for t in times[4:]))
        self.assertEqual([app.STAGE_LAYER[s] for s in ("c1", "c2", "c3")], ["autoridade", "fit", "adiamento"])


class FourInsideTheWindowTests(unittest.TestCase):
    def test_closed_sunday_still_gets_four_texts_inside_the_window(self):
        # Talles 11/10: whoever answered gets the 4 touches by text inside the 24 h window, 6 h apart, 2 h when needed;
        # the business closed on Sunday does not push them to Tuesday templates.
        import horario
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        office = horario.parse_hours("seg a sex 8h–18h, sáb 8h–12h, dom fechado")
        lead = datetime(2026, 10, 10, 18, 30, tzinfo=tz).timestamp()
        anchor = lead + 60
        window_end = lead + 23 * 3600 + 30 * 60
        times = horario.touch_times(anchor, window_end, office, tz, holidays={"2026-10-12"})
        fmt = [datetime.fromtimestamp(x, tz).strftime("%a %H:%M") for x in times]
        self.assertEqual(len(times), 4)
        self.assertTrue(all(horario.touch_channel(x, window_end) == "texto" for x in times), fmt)
        self.assertTrue(all(b - a >= 2 * 3600 for a, b in zip(times, times[1:])), fmt)
        self.assertEqual(fmt[0], "Sun 09:00")

    def test_open_business_keeps_six_hours_apart(self):
        import horario
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        office = horario.parse_hours("seg a sex 8h–18h, sáb e dom fechado")
        lead = datetime(2026, 10, 13, 8, 0, tzinfo=tz).timestamp()  # Tuesday morning
        times = horario.touch_times(lead + 60, lead + 23.5 * 3600, office, tz)
        fmt = [datetime.fromtimestamp(x, tz).strftime("%a %H:%M") for x in times]
        self.assertEqual(len(times), 4, fmt)
        self.assertTrue(all(b - a >= 2 * 3600 for a, b in zip(times, times[1:])), fmt)
        self.assertTrue(all(8 <= datetime.fromtimestamp(x, tz).hour < 18 for x in times), fmt)  # inside the business hours
        self.assertTrue(all(horario.touch_channel(x, lead + 23.5 * 3600) == "texto" for x in times), fmt)

if __name__ == "__main__":
    unittest.main()
