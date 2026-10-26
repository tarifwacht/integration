"""Quarter-hour time slots in UTC.

All German offsets are whole hours, so flooring in UTC gives the same slot
boundaries as local time, also on DST changeover days (92 or 100 slots).

Copied from Einspeisewacht (commit e4fd5fc), developed independently since.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

QUARTER = timedelta(minutes=15)
_QUARTER_SECONDS = 900


def slot_start(moment: datetime) -> datetime:
    """Return the UTC start of the quarter hour containing `moment`."""
    if moment.tzinfo is None:
        raise ValueError("naive datetime")
    seconds = int(moment.timestamp()) // _QUARTER_SECONDS * _QUARTER_SECONDS
    return datetime.fromtimestamp(seconds, UTC)


def split_interval(
    start: datetime, end: datetime, energy: float
) -> list[tuple[datetime, float]]:
    """Distribute `energy` linearly over the quarter hours between start and end.

    Returns (slot start in UTC, energy) pairs in chronological order. An empty or
    negative interval puts everything into the slot of `end`.
    """
    if end <= start:
        return [(slot_start(end), energy)]
    total = (end - start).total_seconds()
    pieces: list[tuple[datetime, float]] = []
    cursor = start
    slot = slot_start(start)
    while cursor < end:
        slot_end = slot + QUARTER
        piece_end = min(slot_end, end)
        share = (piece_end - cursor).total_seconds() / total
        pieces.append((slot, energy * share))
        cursor = piece_end
        slot = slot_end
    return pieces
