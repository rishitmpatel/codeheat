"""Helpers shared by report writers."""

from __future__ import annotations

BLOCKS = "▁▂▃▄▅▆▇█"


def spark(values: list[float | None]) -> str:
    nums = [v for v in values if v is not None]
    if not nums:
        return ""
    lo, hi = min(nums), max(nums)
    hi = max(hi, lo + 0.2 * max(abs(hi), 1))  # tiny changes must not look like cliffs
    out = []
    for v in values:
        if v is None:
            out.append(" ")
        else:
            out.append(BLOCKS[min(7, int((v - lo) / (hi - lo) * 7.999))])
    return "".join(out)


def human_date(iso: str | None) -> str:
    return iso[:10] if iso else "-"


def short_path(path: str, width: int) -> str:
    if len(path) <= width:
        return path
    keep = width - 1
    return "…" + path[-keep:]
