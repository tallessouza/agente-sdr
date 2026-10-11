"""When the attendant's 4 follow-up touches go out (Talles, 10/10/2026).

"Uns 4 fups de 6 em 6h respeitando o horário de funcionamento, respeitando a janela de 24h; os 4 têm que
acontecer; se tiver horário de silêncio, diminui a distância entre eles com um intervalo de 2h."

The touches spread over the business's OPEN time between the agent's last message and the end of the 24 h
window: 6 h apart when there is room, closer when closed hours eat the window, so all 4 always fit. A business
closed for the whole window falls back to daytime hours (9h–20h).
"""
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any

DAYS = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "dom": 6}
FALLBACK = {d: [(9.0, 20.0)] for d in range(7)}
TOUCHES = 4
IDEAL_GAP = 6 * 3600
MIN_TOUCH_OPEN_SECONDS = 15 * 60  # less open time than this per touch: use the daytime fallback

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
    """n touch moments in open hours between anchor and window_end: ideal_gap apart, closer when needed, never fewer."""
    if window_end <= anchor:
        return []
    intervals = open_intervals(anchor, window_end, hours or FALLBACK, tz)
    total = sum(b - a for a, b in intervals)
    if total < n * MIN_TOUCH_OPEN_SECONDS and hours:
        intervals = open_intervals(anchor, window_end, FALLBACK, tz)
        total = sum(b - a for a, b in intervals)
    if total < n * MIN_TOUCH_OPEN_SECONDS:
        intervals, total = [(anchor, window_end)], window_end - anchor
    gap = min(ideal_gap, total / n)
    return [_walk(intervals, gap * k) for k in range(1, n + 1)]
