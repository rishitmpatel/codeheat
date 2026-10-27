"""Turn raw git commits into canonical, rename-aware change records."""

from __future__ import annotations

from dataclasses import dataclass, field

from .filters import PathFilter
from .gitlog import RawCommit
from .identity import Identities, ResolvedIdentities


@dataclass
class Commit:
    sha: str
    person: int
    ts: int
    #: canonical (HEAD-name) path -> (added, deleted, status)
    files: dict[str, tuple[int, int, str]] = field(default_factory=dict)


@dataclass
class History:
    commits: list[Commit]  # newest first
    identities: ResolvedIdentities
    #: canonical path -> [(ts, name-after-commit, status)] newest first
    names: dict[str, list[tuple[int, str, str]]]
    #: canonical path -> name before the oldest in-window change
    before: dict[str, str]
    dropped_bulk: int = 0


def build_history(
    raw: list[RawCommit],
    filt: PathFilter,
    since_ts: int,
    until_ts: int,
    merge_names: bool = True,
    ignore_bulk: int = 0,
) -> History:
    raw = [c for c in raw if since_ts <= c.ts <= until_ts]
    ids = Identities(merge_names)
    for c in raw:
        ids.observe(c.name, c.email)
    resolved = ids.resolve()

    alias: dict[str, str] = {}
    names: dict[str, list[tuple[int, str, str]]] = {}
    before: dict[str, str] = {}
    commits: list[Commit] = []
    dropped = 0
    # git log is newest-first, which is the order the rename map needs.
    for rc in raw:
        files: dict[str, tuple[int, int, str]] = {}
        for ch in rc.changes:
            canon = alias.get(ch.path, ch.path)
            if ch.status == "R" and ch.old_path:
                alias[ch.old_path] = canon
                before[canon] = ch.old_path
                if ch.added == 0 and ch.deleted == 0:
                    if filt.accepts(canon):  # pure move: keep the name, not a behavioural change
                        names.setdefault(canon, []).append((rc.ts, ch.path, "R"))
                    continue
            elif ch.status == "A":
                alias.pop(ch.path, None)
                before[canon] = ch.path
            else:
                before[canon] = ch.path
            if not filt.accepts(canon):
                continue
            prev = files.get(canon)
            if prev:
                files[canon] = (prev[0] + ch.added, prev[1] + ch.deleted, ch.status)
            else:
                files[canon] = (ch.added, ch.deleted, ch.status)
            names.setdefault(canon, []).append((rc.ts, ch.path, ch.status))
        if ignore_bulk and len(files) > ignore_bulk:
            dropped += 1
            for canon in files:  # undo name events of dropped commit
                names[canon].pop()
            continue
        commits.append(
            Commit(rc.sha, resolved.id_of(rc.name, rc.email), rc.ts, files)
        )
    return History(commits, resolved, names, before, dropped)
