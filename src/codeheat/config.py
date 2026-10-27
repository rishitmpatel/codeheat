"""Configuration and time-window handling."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REL = re.compile(r"^\s*(\d+)\s*(day|week|month|year|hour)s?(?:\s+ago)?\s*$", re.I)


def parse_when(spec: str | None, now: datetime) -> datetime | None:
    """Parse ``2024-01-31``, ``2024-01-31T10:00:00``, ``6 months ago``, ``now``."""
    if spec is None:
        return None
    s = spec.strip()
    if not s:
        return None
    if s.lower() in ("now", "today"):
        return now
    m = _REL.match(s)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        if unit == "hour":
            return now - timedelta(hours=n)
        if unit == "day":
            return now - timedelta(days=n)
        if unit == "week":
            return now - timedelta(weeks=n)
        if unit == "month":
            return _sub_months(now, n)
        return _sub_months(now, 12 * n)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"cannot parse date {spec!r}; use YYYY-MM-DD or e.g. '6 months ago'"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _sub_months(dt: datetime, n: int) -> datetime:
    y, m = dt.year, dt.month - n
    while m <= 0:
        m += 12
        y -= 1
    day = min(dt.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return dt.replace(year=y, month=m, day=day)


@dataclass
class Config:
    repo: str = "."
    branch: str | None = None
    since: str = "12 months ago"
    until: str | None = None
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    default_excludes: bool = True
    use_ignore_file: bool = True
    # coupling
    min_shared: int = 5
    min_degree: float = 0.30
    max_commit_files: int = 50
    # knowledge
    inactive_months: float = 6.0
    include_bots: bool = False
    merge_names: bool = True
    dir_depth: int = 2
    # hotspots / complexity
    ccn_threshold: int = 15
    changed_only: bool = False
    max_file_size: int = 1_000_000
    ignore_bulk: int = 0  # >0: drop commits touching more files than this from ALL analyses
    # trends
    trend_points: int = 12
    trend_top: int = 5
    # presentation
    top: int = 15
    # engine
    jobs: int | None = None
    use_cache: bool = True
    cache_dir: str | None = None
    now: datetime | None = None  # injectable for tests

    def window(self) -> tuple[datetime, datetime]:
        now = self.now or datetime.now(timezone.utc)
        until = parse_when(self.until, now) or now
        since = parse_when(self.since, until if self.until else now)
        if since is None:
            since = _sub_months(until, 12)
        if since >= until:
            raise ValueError("--since must be earlier than --until")
        return since, until


def default_cache_dir() -> Path:
    import os
    import sys

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "codeheat" / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "codeheat"
    base = os.environ.get("XDG_CACHE_HOME")
    return Path(base) / "codeheat" if base else Path.home() / ".cache" / "codeheat"
