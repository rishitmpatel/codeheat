"""Complexity-over-time sampling and monthly commit activity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .cache import BlobCache
from .complexity import analyse_source, cache_key, classify
from .gitlog import BlobReader, blob_sha_at, commit_at, prefetch_blobs, promisor_remote


def sample_times(since: datetime, until: datetime, n: int) -> list[datetime]:
    n = max(2, n)
    step = (until - since) / (n - 1)
    return [since + step * i for i in range(n)]


def _name_at(events: list[tuple[int, str, str]], before: str, ts: int) -> str | None:
    for ev_ts, path, status in events:  # newest first
        if ev_ts <= ts:
            return None if status == "D" else path
    return before


def complexity_trends(
    repo,
    ref_sha: str,
    since: datetime,
    until: datetime,
    points: int,
    files: list[str],
    names: dict[str, list[tuple[int, str, str]]],
    before: dict[str, str],
    cache: BlobCache,
) -> list[dict]:
    times = sample_times(since, until, points)
    commits = [commit_at(repo, ref_sha, t) for t in times]
    out = []
    if promisor_remote(repo):  # partial clone: fetch every needed historical blob in one go
        want = []
        for path in files:
            for t, c in zip(times, commits):
                nm = _name_at(names.get(path, []), before.get(path, path), int(t.timestamp())) if c else None
                sha = blob_sha_at(repo, c, nm) if nm else None
                if sha:
                    want.append(sha)
        prefetch_blobs(repo, sorted(set(want)))
    with BlobReader(repo) as rd:
        for path in files:
            kind = classify(path)
            if kind is None:
                continue
            pts = []
            for t, c in zip(times, commits):
                pt = {"t": t.date().isoformat(), "commit": c[:8] if c else None, "ccn": None, "loc": None, "nloc": None}
                if c:
                    nm = _name_at(names.get(path, []), before.get(path, path), int(t.timestamp()))
                    data = rd.read(f"{c}:{nm}") if nm else None
                    if data is not None:
                        key = cache_key(kind, nm, rd.last_sha or "")
                        m = cache.get_many([key]).get(key)
                        if not m:
                            m = analyse_source(nm, data.decode("utf-8", "replace"), kind)
                            if m and rd.last_sha:
                                cache.put_many({key: m})
                        if m:
                            pt.update(ccn=m["ccn"], loc=m["loc"], nloc=m["nloc"])
                pts.append(pt)
            vals = [p["ccn"] for p in pts if p["ccn"] is not None]
            change = None
            if len(vals) >= 2 and vals[0] > 0:
                change = round((vals[-1] - vals[0]) / vals[0], 4)
            out.append({"path": path, "points": pts, "change_pct": change, "proxy": kind == "proxy"})
    return out


def monthly_activity(commits, since: datetime, until: datetime, bot_ids: set[int]) -> list[dict]:
    months: list[str] = []
    y, m = since.year, since.month
    while (y, m) <= (until.year, until.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    counts = {k: 0 for k in months}
    people: dict[str, set[int]] = {k: set() for k in months}
    for c in commits:
        d = datetime.fromtimestamp(c.ts, timezone.utc)
        k = f"{d.year:04d}-{d.month:02d}"
        if k in counts:
            counts[k] += 1
            if c.person not in bot_ids:
                people[k].add(c.person)
    return [{"month": k, "commits": counts[k], "authors": len(people[k])} for k in months]
