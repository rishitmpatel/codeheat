"""Author identity normalisation.

``git log`` already applies ``.mailmap`` (``%aN``/``%aE``).  On top of that we
merge identities that share a case-insensitive e-mail (GitHub ``12345+user@users.noreply``
addresses are folded onto ``user@users.noreply``) and, optionally, identities that share the
same multi-word display name.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

_NOREPLY = re.compile(r"^\d+\+(.+@users\.noreply\.github\.com)$", re.I)
_BOT = re.compile(r"(\[bot\]|^(dependabot|renovate|github-actions|pre-commit-ci|greenkeeper|snyk-bot|codecov|allcontributors)\b|-bot\b|\bbot$)", re.I)


def norm_email(email: str) -> str:
    e = email.strip().lower()
    m = _NOREPLY.match(e)
    return m.group(1) if m else e


def is_bot(name: str, email: str) -> bool:
    return bool(_BOT.search(name) or _BOT.search(email.split("@")[0]) or "[bot]" in email.lower())


class Identities:
    def __init__(self, merge_names: bool = True):
        self.merge_names = merge_names
        self._counts: Counter[tuple[str, str]] = Counter()

    def observe(self, name: str, email: str) -> None:
        self._counts[(name, email)] += 1

    def resolve(self) -> "ResolvedIdentities":
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            while parent.setdefault(x, x) != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for (name, email), _ in self._counts.items():
            ek = "e:" + norm_email(email)
            find(ek)
            nm = " ".join(name.lower().split())
            if self.merge_names and len(nm.split()) >= 2:
                union(ek, "n:" + nm)
        groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for key in self._counts:
            groups[find("e:" + norm_email(key[1]))].append(key)
        mapping: dict[tuple[str, str], int] = {}
        people: list[dict] = []
        for _root, keys in sorted(groups.items(), key=lambda kv: -sum(self._counts[k] for k in kv[1])):
            names = Counter()
            emails = Counter()
            for k in keys:
                names[k[0]] += self._counts[k]
                emails[norm_email(k[1])] += self._counts[k]
            display = names.most_common(1)[0][0] or emails.most_common(1)[0][0]
            email = emails.most_common(1)[0][0]
            pid = len(people)
            people.append({"id": pid, "name": display, "email": email, "bot": is_bot(display, email), "aliases": sorted({k[0] for k in keys} | set(emails))})
            for k in keys:
                mapping[k] = pid
        return ResolvedIdentities(mapping, people)


class ResolvedIdentities:
    def __init__(self, mapping: dict[tuple[str, str], int], people: list[dict]):
        self.mapping = mapping
        self.people = people

    def id_of(self, name: str, email: str) -> int:
        return self.mapping[(name, email)]
