"""When the attendant's 4 follow-up touches go out (Talles, 10/10/2026).

"Uns 4 fups de 6 em 6h respeitando o horário de funcionamento, respeitando a janela de 24h; os 4 têm que
acontecer; se tiver horário de silêncio, diminui a distância entre eles com um intervalo de 2h."

And (10/10, 23h40): "intervalo de 2h só se o toque daqui a 6h der fora do expediente da empresa".

And, asked which wins when both cannot hold (4 touches 6 h apart need 24 h; the window is 23 h 30): "os 4 valem mais".

Each touch goes 6 h after the previous one (the first, 6 h after the agent's last message); 2 h after when the 6 h
mark is outside the business's hours or would leave no room for the touches still to come; at the next opening
when 2 h is closed too. Only in the business's hours, only between 9h and 20h (when touches go out at all) and
before the end of the window (30 min before the 24 h close). A business closed for the whole window uses the
daytime hours (9h–20h) the same way.
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


def open_intervals(start: float, end: float, hours: dict[int, list[tuple[float, float]]], tz: Any) -> list[tuple[float, float]]:
    """Open [a, b) spans of the business between two timestamps."""
    out: list[tuple[float, float]] = []
    day = datetime.fromtimestamp(start, tz).replace(hour=0, minute=0, second=0, microsecond=0)
    while day.timestamp() < end:
        for open_h, close_h in hours.get(day.weekday(), []):
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
                n: int = TOUCHES, ideal_gap: float = IDEAL_GAP) -> list[float]:
    """n touch moments in open hours between anchor and window_end: ideal_gap apart, closer when needed, never under MIN_GAP."""
    last_ok = window_end - END_MARGIN  # the bridge loop still has time to send the last one
    if last_ok <= anchor:
        return []
    tried: list[list[float]] = []
    # The business's hours first, then the daytime fallback when they cannot hold the n touches.
    for spec in ([hours] if hours else []) + [FALLBACK]:
        plan = _plan(anchor, last_ok, open_intervals(anchor, last_ok, _clip(spec), tz), n, ideal_gap)
        if len(plan) >= n:
            return plan
        tried.append(plan)
    return max(tried, key=len)


def _plan(anchor: float, last_ok: float, spans: list[tuple[float, float]], n: int, ideal_gap: float) -> list[float]:
    """Each touch at 6 h, else 2 h, else the next opening: the first of these that still leaves room for the rest
    (the 4 touches win over the 6 h, Talles 10/10)."""
    def is_open(t: float) -> bool:
        return any(a <= t < b for a, b in spans)

    def next_open(t: float) -> float | None:
        return next((max(a, t) for a, b in spans if b > t), None)

    def options(previous: float) -> list[float]:
        out = [previous + g for g in (ideal_gap, MIN_GAP) if previous + g <= last_ok and is_open(previous + g)]
        fallback = next_open(previous + MIN_GAP)
        if fallback is not None and fallback <= last_ok:
            out.append(fallback)
        return out

    def most_after(previous: float, k: int) -> int:
        """How many of k touches still fit after `previous` at the tightest pace (2 h, else next opening)."""
        count = 0
        while count < k:
            nxt = options(previous)
            if not nxt:
                break
            previous = min(nxt)
            count += 1
        return count

    plan: list[float] = []
    previous = anchor
    while len(plan) < n:
        choices = options(previous)
        if not choices:
            break
        left = n - len(plan) - 1
        best = max(most_after(c, left) for c in choices)
        previous = next(c for c in choices if most_after(c, left) == best)
        plan.append(previous)
    return plan


def _clip(hours: dict[int, list[tuple[float, float]]]) -> dict[int, list[tuple[float, float]]]:
    """Business hours limited to when touches may go out at all (SEND_START to SEND_END)."""
    return {d: [(max(a, SEND_START), min(b, SEND_END)) for a, b in ranges if min(b, SEND_END) > max(a, SEND_START)]
            for d, ranges in hours.items()}


