"""Complexity measurement: lizard (multi-language CCN) with an indentation fallback.

* Languages lizard understands -> cyclomatic complexity per function.
* Other source-like files (shell, SQL dialects, Haskell, ...) -> an
  *indentation proxy*: sum of indentation levels over non-blank, non-comment
  lines divided by 8.  It is flagged ``proxy: true`` everywhere it is shown
  and is only ever ranked against other proxy files.
* Everything else (docs, config, data) has no complexity and takes no part in
  hotspot ranking.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import PurePosixPath

try:  # lizard is a hard dependency, but keep import errors readable
    import lizard
    import lizard_languages
    from lizard import analyze_file as _lz_analyze
except ImportError as exc:  # pragma: no cover
    raise SystemExit("codeheat requires the 'lizard' package: pip install lizard") from exc

from .cache import BlobCache
from .gitlog import BlobReader, prefetch_blobs

PROXY_EXTS = {
    ".sh", ".bash", ".zsh", ".fish", ".ksh", ".ps1", ".psm1", ".bat", ".cmd", ".awk", ".tcl",
    ".hs", ".lhs", ".ml", ".mli", ".fs", ".fsx", ".clj", ".cljs", ".cljc", ".ex", ".exs",
    ".jl", ".nim", ".cr", ".d", ".dart", ".groovy", ".gradle", ".cmake", ".mk", ".vim", ".el",
    ".lisp", ".scm", ".rkt", ".v", ".sv", ".vhd", ".vhdl", ".asm", ".s", ".pas", ".coffee",
    ".elm", ".purs", ".sass", ".scss", ".less", ".graphql", ".proto", ".thrift", ".tf",
}
PROXY_NAMES = {"makefile", "dockerfile", "rakefile", "gemfile", "justfile", "jenkinsfile", "vagrantfile", "cmakelists.txt"}
_COMMENT = re.compile(r"^\s*(#|//|--|;|/\*|\*|\*/|rem\b|'|%|\"\")", re.I)
SCHEMA = 3
TOP_FUNCS = 20


def classify(path: str) -> str | None:
    """'lizard', 'proxy' or None (not a source file)."""
    p = PurePosixPath(path)
    name = p.name.lower()
    if name.endswith(".d.ts"):
        return None  # type declarations only
    if lizard_languages.get_reader_for(p.name) is not None and p.suffix.lower() != ".sql":
        return "lizard"
    if p.suffix.lower() in PROXY_EXTS or name in PROXY_NAMES:
        return "proxy"
    if p.suffix.lower() == ".sql":
        return "proxy"
    return None


def count_lines(text: str) -> int:
    if not text:
        return 0
    n = text.count("\n")
    return n if text.endswith("\n") else n + 1


def _proxy(text: str) -> dict:
    levels = []
    for line in text.splitlines():
        if not line.strip() or _COMMENT.match(line):
            continue
        width = 0
        for ch in line:
            if ch == " ":
                width += 1
            elif ch == "\t":
                width += 4 - (width % 4)
            else:
                break
        levels.append(width)
    if not levels:
        return {"loc": count_lines(text), "nloc": 0, "ccn": 0, "max": 0, "avg": 0.0, "nf": 0, "proxy": True, "fn": []}
    counts: dict[int, int] = {}
    for w in levels:
        if w:
            counts[w] = counts.get(w, 0) + 1
    thresh = max(3, len(levels) // 100)
    unit = min((w for w, c in counts.items() if c >= thresh), default=4)
    unit = min(max(unit, 2), 8)
    total = sum(round(w / unit) for w in levels)
    return {
        "loc": count_lines(text),
        "nloc": len(levels),
        "ccn": round(total / 8),
        "max": 0,
        "avg": 0.0,
        "nf": 0,
        "proxy": True,
        "fn": [],
    }


def analyse_source(path: str, text: str, kind: str) -> dict | None:
    """Return metrics for one file's text, or None if it cannot be analysed (e.g. minified)."""
    loc = count_lines(text)
    if loc and len(text) / loc > 400:  # minified / data blob
        return None
    if kind == "proxy":
        return _proxy(text)
    try:
        info = _lz_analyze.analyze_source_code(PurePosixPath(path).name, text)
    except Exception:
        return _proxy(text) | {"proxy": True}
    funcs = info.function_list
    ccns = [f.cyclomatic_complexity for f in funcs]
    top = sorted(funcs, key=lambda f: (-f.cyclomatic_complexity, f.start_line))[:TOP_FUNCS]
    return {
        "loc": loc,
        "nloc": info.nloc,
        "ccn": sum(ccns),
        "max": max(ccns, default=0),
        "avg": round(sum(ccns) / len(ccns), 2) if ccns else 0.0,
        "nf": len(funcs),
        "proxy": False,
        "fn": [[f.name[:120], f.cyclomatic_complexity, f.start_line, f.end_line, f.nloc] for f in top],
    }


def _work(batch: list[tuple[str, str, str, bytes]]) -> list[tuple[str, dict | None]]:
    out = []
    for key, path, kind, data in batch:
        text = data.decode("utf-8", "replace")
        out.append((key, analyse_source(path, text, kind)))
    return out


def cache_key(kind: str, path: str, sha: str) -> str:
    ext = PurePosixPath(path).suffix.lower()
    return f"{SCHEMA}:{kind}:{lizard.version}:{ext}:{sha}"


class Measurer:
    """Measures many (path, blob) pairs with caching and a process pool."""

    def __init__(self, repo, cache: BlobCache, jobs: int | None = None, max_size: int = 1_000_000):
        self.repo = repo
        self.cache = cache
        self.jobs = jobs or os.cpu_count() or 1
        self.max_size = max_size
        self.stats = {"cached": 0, "computed": 0}

    def measure(self, items: list[tuple[str, str, str, int]]) -> dict[str, dict | None]:
        """items: (path, blob_sha, kind, size) -> {cache_key: metrics|None}"""
        keys = {}
        for path, sha, kind, size in items:
            if size > self.max_size:
                continue
            keys.setdefault(cache_key(kind, path, sha), (path, sha, kind))
        cached = self.cache.get_many(list(keys))
        result: dict[str, dict | None] = {k: (v or None) for k, v in cached.items()}
        todo = [(k, *keys[k]) for k in keys if k not in cached]
        self.stats["cached"] += len(cached)
        self.stats["computed"] += len(todo)
        if not todo:
            return result
        fresh: dict[str, dict | None] = {}
        self.stats["prefetched"] = self.stats.get("prefetched", 0) + prefetch_blobs(self.repo, [t[2] for t in todo])

        def batches():
            batch, size = [], 0
            with BlobReader(self.repo) as rd:
                for key, path, sha, kind in todo:
                    data = rd.read(sha)
                    if data is None:
                        fresh[key] = None
                        continue
                    batch.append((key, path, kind, data))
                    size += len(data)
                    if size > 400_000 or len(batch) >= 64:
                        yield batch
                        batch, size = [], 0
            if batch:
                yield batch

        if self.jobs <= 1 or len(todo) < 40:
            for b in batches():
                fresh.update(_work(b))
        else:
            with ProcessPoolExecutor(max_workers=self.jobs) as pool:
                futs = [pool.submit(_work, b) for b in batches()]
                for f in futs:
                    fresh.update(f.result())
        # store misses as {} so they are not recomputed
        self.cache.put_many({k: (v or {}) for k, v in fresh.items()})
        result.update({k: (v or None) for k, v in fresh.items()})
        return result
