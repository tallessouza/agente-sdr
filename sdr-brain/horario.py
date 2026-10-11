"""When the attendant's 4 follow-up touches go out (Talles, 10/10/2026).

"Uns 4 fups de 6 em 6h respeitando o horário de funcionamento, respeitando a janela de 24h; os 4 têm que
acontecer; se tiver horário de silêncio, diminui a distância entre eles com um intervalo de 2h."

And (10/10, 23h40): "intervalo de 2h só se o toque daqui a 6h der fora do expediente da empresa".

And (11/10): "colocando os disparos de 6 em 6 via texto nos que couber dentro da janela e via novo disparo de
template nos que precisar fazer, deslocando para 2 horas para cair dentro do horário de atendimento".

Each touch goes 6 h after the previous one (the first, 6 h after the agent's last message); 2 h after when the 6 h
mark is outside the business's hours; at the next opening when 2 h is closed too. Only in the business's hours and
between 9h and 20h (when touches go out at all); a business with no opening in the next days uses 9h–20h. The 4
always happen: inside the 23 h 30 window as text, after it as a retomada template (touch_channel).
"""
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any

DAYS = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "dom": 6}
FALLBACK = {d: [(9.0, 20.0)] for d in range(7)}
TOUCHES = 4
IDEAL_GAP = 6 * 3600
END_MARGIN = 10 * 60  # time left after the last touch, before the window closes
# Never closer than this (10/10: the Nóris answered Saturday 18h54, closed Sunday, and got 4 touches 15 min apart).
MIN_GAP = 2 * 3600
SEND_START, SEND_END = 9.0, 20.0  # touches only go out in this local time (SDR_BUSINESS_*_HOUR of brain and bridge)
HORIZON = 7 * 86400  # how far ahead a touch may be planned (a business open only on Fridays still gets its own hours)

_DAY = r"(?:seg|ter|qua|qui|sex|sab|dom)"
_RANGE = r"\d{1,2}h\d{0,2}\s*-\s*\d{1,2}h\d{0,2}"
_SEGMENT = re.compile(rf"(?P<days>{_DAY}(?:\s+(?:a|e)\s+{_DAY})*|todos os dias)\s*(?P<what>fechado|{_RANGE}(?:\s+e\s+{_RANGE})*)")


def _fold(text: Any) -> str:
    # Dashes first: removing the accents would also remove the en dash of "8h30–19h".
    text = str(text or "").replace("–", "-").replace("—", "-")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _days(spec: str) -> list[int]:
    if spec.strip() == "todos os dias":
        return list(range(7))
    names = re.findall(_DAY, spec)
    days: list[int] = []
    for i, name in enumerate(names):
        days.append(DAYS[name])
        if i + 1 < len(names) and re.search(rf"{name}\s+a\s+{names[i + 1]}", spec):
            a, b = DAYS[name], DAYS[names[i + 1]]
            days += list(range(a + 1, b)) if a < b else [d % 7 for d in range(a + 1, b + 7)]
    return days


def parse_hours(text: Any) -> dict[int, list[tuple[float, float]]] | None:
    """'seg a sex 8h30–19h, sáb 8h–12h, dom fechado' -> {0: [(8.5, 19.0)], ..., 5: [(8.0, 12.0)], 6: []}; None if unreadable."""
    folded = _fold(text)
    if not folded:
        return None
    if re.search(r"aberto 24 ?h", folded):
        return {d: [(0.0, 24.0)] for d in range(7)}
    hours: dict[int, list[tuple[float, float]]] = {}
    for match in _SEGMENT.finditer(folded):
        days = _days(match.group("days"))
        ranges = []
        for h1, m1, h2, m2 in re.findall(r"(\d{1,2})h(\d{2})?\s*-\s*(\d{1,2})h(\d{2})?", match.group("what")):
            start = int(h1) + (int(m1) / 60 if m1 else 0)
            end = int(h2) + (int(m2) / 60 if m2 else 0)
            end = 24.0 if end == 0 else end  # "9h–0h" closes at midnight
            if end > start:
                ranges.append((start, end))
        for d in days:
            hours.setdefault(d, []).extend(ranges)
    return hours if any(hours.values()) else None


def open_intervals(start: float, end: float, hours: dict[int, list[tuple[float, float]]], tz: Any,
                   holidays: Any = ()) -> list[tuple[float, float]]:
    """Open [a, b) spans of the business between two timestamps; a holiday (YYYY-MM-DD) counts as closed."""
    out: list[tuple[float, float]] = []
    day = datetime.fromtimestamp(start, tz).replace(hour=0, minute=0, second=0, microsecond=0)
    while day.timestamp() < end:
        for open_h, close_h in ([] if day.strftime("%Y-%m-%d") in holidays else hours.get(day.weekday(), [])):
            a = max((day + timedelta(hours=open_h)).timestamp(), start)
            b = min((day + timedelta(hours=close_h)).timestamp(), end)
            if b > a:
                out.append((a, b))
        day = datetime(day.year, day.month, day.day, tzinfo=tz) + timedelta(days=1)
    return out


def _walk(intervals: list[tuple[float, float]], offset: float) -> float:
    """The moment `offset` seconds of open time into the intervals."""
    for a, b in intervals:
        if offset <= b - a:
            return a + offset
        offset -= b - a
    return intervals[-1][1]


def touch_times(anchor: float, window_end: float, hours: dict[int, list[tuple[float, float]]] | None, tz: Any,
                n: int = TOUCHES, ideal_gap: float = IDEAL_GAP, holidays: Any = ()) -> list[float]:
    """n touch moments in open hours between anchor and window_end: ideal_gap apart, closer when needed, never under MIN_GAP."""
    """n touch moments: each 6 h after the previous one, 2 h after when the 6 h mark falls outside the business's
    hours, at the next opening when that is closed too. `window_end` no longer limits the plan: what falls inside
    the window goes as text, what falls after it goes as a template (Talles 11/10, see touch_channel)."""
    horizon = anchor + HORIZON
    for spec in ([hours] if hours else []) + [FALLBACK]:
        spans = open_intervals(anchor, horizon, _clip(spec), tz, holidays)
        plan = _plan(anchor, horizon, spans, n, ideal_gap)
        if len(plan) >= n:
            return plan
    return plan


CADENCE_TOUCHES = 3
CADENCE_AFTER_OPENING = 3600  # one hour after the business opens


def cadence_times(after: float, hours: dict[int, list[tuple[float, float]]] | None, tz: Any, holidays: Any = (),
                  n: int = CADENCE_TOUCHES) -> list[float]:
    """The daily cadence after the 4 touches (Talles 11/10: "cadência diária dos próximos dias durante a semana"): one
    touch per working day (Monday to Friday, not a holiday) after `after`, an hour after the business opens (9h–20h);
    a weekday the business is closed is skipped. Up to 14 days ahead."""
    spec = _clip(hours or FALLBACK)
    out: list[float] = []
    day = datetime.fromtimestamp(after, tz).replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(14):
        day = datetime(day.year, day.month, day.day, tzinfo=tz) + timedelta(days=1)
        if day.weekday() >= 5 or day.strftime("%Y-%m-%d") in holidays:
            continue
        spans = spec.get(day.weekday(), [])
        if not spans:
            continue
        open_h, close_h = spans[0]
        when = min((day + timedelta(hours=open_h)).timestamp() + CADENCE_AFTER_OPENING, (day + timedelta(hours=close_h)).timestamp() - 1800)
        if when > after:
            out.append(when)
        if len(out) >= n:
            break
    return out


def touch_channel(when: float, window_end: float) -> str:
    """'texto' when the touch falls inside the 24 h window (minus the margin), 'template' after it."""
    return "texto" if when <= window_end - END_MARGIN else "template"


def _plan(anchor: float, horizon: float, spans: list[tuple[float, float]], n: int, ideal_gap: float) -> list[float]:
    def is_open(t: float) -> bool:
        return any(a <= t < b for a, b in spans)

    def next_open(t: float) -> float | None:
        return next((max(a, t) for a, b in spans if b > t), None)

    plan: list[float] = []
    previous = anchor
    while len(plan) < n:
        when = next((previous + g for g in (ideal_gap, MIN_GAP) if is_open(previous + g)), None)
        if when is None:
            when = next_open(previous + MIN_GAP)
        if when is None or when > horizon:
            break
        plan.append(when)
        previous = when
    return plan


def _clip(hours: dict[int, list[tuple[float, float]]]) -> dict[int, list[tuple[float, float]]]:
    """Business hours limited to when touches may go out at all (SEND_START to SEND_END)."""
    return {d: [(max(a, SEND_START), min(b, SEND_END)) for a, b in ranges if min(b, SEND_END) > max(a, SEND_START)]
            for d, ranges in hours.items()}


