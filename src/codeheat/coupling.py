"""Change coupling: which files change together."""

from __future__ import annotations

import re
from collections import Counter
from itertools import combinations
from pathlib import PurePosixPath

from .complexity import classify
from .filters import top_component

_TEST_DIRS = {"test", "tests", "spec", "specs", "__tests__", "testing", "e2e", "integration", "it"}
_TEST_NAME = re.compile(r"(^test_|_test\.|\.test\.|\.spec\.|_spec\.|tests?\.[a-z]+$|^conftest\.)", re.I)
_DOC_EXT = {".md", ".rst", ".txt", ".adoc", ".mdx"}


def is_test(path: str) -> bool:
    p = PurePosixPath(path)
    return any(part.lower() in _TEST_DIRS for part in p.parts[:-1]) or bool(_TEST_NAME.search(p.name))


def is_doc(path: str) -> bool:
    p = PurePosixPath(path)
    return p.suffix.lower() in _DOC_EXT or (p.parts and p.parts[0].lower() in ("docs", "doc", "documentation"))


def pair_kind(a: str, b: str) -> str:
    for x, y in ((a, b), (b, a)):  # root-level manifests/config (pyproject.toml, CI files ...)
        if "/" not in x and classify(x) is None and "/" in y:
            return "config-source"
    ta, tb = is_test(a), is_test(b)
    if ta and tb:
        return "test-test"
    if ta != tb:
        return "test-source"
    da, db = is_doc(a), is_doc(b)
    if da or db:
        return "docs-source" if da != db else "docs-docs"
    return "cross-module" if top_component(a) != top_component(b) else "same-module"


def compute_coupling(
    commit_sets: list[set[str]],
    min_shared: int,
    min_degree: float,
    max_commit_files: int,
    limit: int = 300,
) -> dict:
    """commit_sets: for each commit, the files it touched (that still exist at HEAD)."""
    usable = [s for s in commit_sets if 0 < len(s) <= max_commit_files]
    skipped_big = sum(1 for s in commit_sets if len(s) > max_commit_files)
    revs: Counter[str] = Counter()
    for s in usable:
        revs.update(s)
    eligible = {f for f, n in revs.items() if n >= min_shared}
    pairs: Counter[tuple[str, str]] = Counter()
    for s in usable:
        fl = sorted(f for f in s if f in eligible)
        if len(fl) > 1:
            pairs.update(combinations(fl, 2))
    out = []
    for (a, b), shared in pairs.items():
        if shared < min_shared:
            continue
        ra, rb = revs[a], revs[b]
        degree = shared / min(ra, rb)
        if degree < min_degree:
            continue
        kind = pair_kind(a, b)
        out.append(
            {
                "a": a,
                "b": b,
                "shared": shared,
                "revs_a": ra,
                "revs_b": rb,
                "degree": round(degree, 4),
                "jaccard": round(shared / (ra + rb - shared), 4),
                "strength": round(shared * degree, 3),
                "module_a": top_component(a),
                "module_b": top_component(b),
                "kind": kind,
                "surprising": kind == "cross-module",
            }
        )
    out.sort(key=lambda r: (-r["strength"], -r["shared"], r["a"], r["b"]))
    return {
        "pairs": out[:limit],
        "total_pairs": len(out),
        "surprising_pairs": sum(1 for r in out if r["surprising"]),
        "commits_used": len(usable),
        "commits_skipped_large": skipped_big,
    }
