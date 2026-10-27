"""Orchestration: git history + complexity -> report dict (see docs/json-schema.md)."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import __version__
from .cache import BlobCache
from .complexity import Measurer, cache_key, classify
from .config import Config, default_cache_dir
from .coupling import compute_coupling
from .filters import PathFilter
from .findings import make_findings
from .gitlog import GitError, git, list_tree, promisor_remote, read_log, repo_toplevel, resolve_ref
from .history import build_history
from .scoring import bus_factor, normalise, top_percent
from .trends import complexity_trends, monthly_activity

SCHEMA_VERSION = 1


def _iso(ts: int | float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _contrib_summary(by_person: dict[int, list], people: list[dict], skip: set[int]):
    """by_person: id -> [lines_added, commits, last_ts]. Returns knowledge dict."""
    rows = [(pid, v) for pid, v in by_person.items() if pid not in skip]
    if not rows:
        return None
    tot_lines = sum(v[0] for _, v in rows)
    tot_commits = sum(v[1] for _, v in rows)
    # main author by lines added (ties: commits, then id); falls back to commits if no lines
    key = (lambda r: (r[1][0], r[1][1], -r[0])) if tot_lines else (lambda r: (r[1][1], -r[0]))
    pid, v = max(rows, key=key)
    use_lines = tot_lines > 0
    contrib = [r[1][0] if use_lines else r[1][1] for r in rows]
    tot = sum(contrib)
    shares = [
        [r[0], round(cv / tot, 3)]
        for r, cv in sorted(zip(rows, contrib), key=lambda x: -x[1])[:5]
    ] if tot else []
    return {
        "owners": shares,
        "main_id": pid,
        "authors": len(rows),
        "share_lines": round(v[0] / tot_lines, 4) if tot_lines else 0.0,
        "share_commits": round(v[1] / tot_commits, 4) if tot_commits else 0.0,
        "bus_factor": bus_factor(contrib),
        "main_last": v[2],
        "last": max(r[1][2] for r in rows),
    }


def analyze(cfg: Config, progress=None) -> dict:
    t_start = time.perf_counter()
    timings: dict[str, float] = {}

    def say(msg: str) -> None:
        if progress:
            progress(msg)

    def tick(name: str, t0: float) -> float:
        timings[name] = round(time.perf_counter() - t0, 3)
        return time.perf_counter()

    t = time.perf_counter()
    repo, subdir = repo_toplevel(cfg.repo)
    branch_name, ref_sha = resolve_ref(repo, cfg.branch)
    since, until = cfg.window()
    include = list(cfg.include)
    if subdir:
        include.append(subdir + "/")
    filt = PathFilter(
        include,
        cfg.exclude,
        cfg.default_excludes,
        (repo / ".codeheatignore") if cfg.use_ignore_file else None,
    )
    say("reading git history")
    partial = promisor_remote(repo) is not None
    if partial:
        say("partial clone detected: skipping line counts")
    raw = read_log(repo, ref_sha, since, until, numstat=not partial)
    hist = build_history(raw, filt, int(since.timestamp()), int(until.timestamp()), cfg.merge_names, cfg.ignore_bulk)
    commits = hist.commits
    people = hist.identities.people
    bots = {p["id"] for p in people if p["bot"]} if not cfg.include_bots else set()
    t = tick("git_log", t)

    # ---- files at the tip -------------------------------------------------
    tree = list_tree(repo, ref_sha)
    head_all = {e.path: e for e in tree if filt.accepts(e.path)}
    kinds = {p: classify(p) for p in head_all}
    code_paths = [p for p, k in kinds.items() if k]
    t = tick("ls_tree", t)

    # ---- per-file accumulators -------------------------------------------
    total_commits = len(commits)
    f_commits: Counter[str] = Counter()
    f_added: Counter[str] = Counter()
    f_deleted: Counter[str] = Counter()
    f_last: dict[str, int] = {}
    f_people: dict[str, dict[int, list]] = defaultdict(dict)
    d_commits: Counter[str] = Counter()
    d_people: dict[str, dict[int, list]] = defaultdict(dict)
    d_files: dict[str, set[str]] = defaultdict(set)
    person_last: dict[int, int] = {}
    commit_sets: list[set[str]] = []
    dir_cache: dict[str, list[str]] = {}

    def ancestors(path: str) -> list[str]:
        r = dir_cache.get(path)
        if r is None:
            parts = path.split("/")[:-1]
            r = [""] + ["/".join(parts[: i + 1]) for i in range(min(len(parts), cfg.dir_depth))]
            dir_cache[path] = r
        return r

    code_set = set(code_paths)
    for c in commits:
        person_last[c.person] = max(person_last.get(c.person, 0), c.ts)
        cs = set()
        touched_dirs: set[str] = set()
        for path, (a, d, _st) in c.files.items():
            if path not in head_all:
                continue
            cs.add(path)
            if path in code_set:
                f_commits[path] += 1
                f_added[path] += a
                f_deleted[path] += d
                if c.ts > f_last.get(path, 0):
                    f_last[path] = c.ts
                rec = f_people[path].setdefault(c.person, [0, 0, 0])
                rec[0] += a
                rec[1] += 1
                rec[2] = max(rec[2], c.ts)
                for dname in ancestors(path):
                    touched_dirs.add(dname)
                    dp = d_people[dname].setdefault(c.person, [0, 0, 0])
                    dp[0] += a
                    d_files[dname].add(path)
        for dname in touched_dirs:
            d_commits[dname] += 1
            d_people[dname][c.person][1] += 1
            d_people[dname][c.person][2] = max(d_people[dname][c.person][2], c.ts)
        commit_sets.append(cs)
    # nb: commits touching deleted files only still count in total_commits
    t = tick("accumulate", t)

    # ---- complexity -------------------------------------------------------
    say("measuring complexity")
    cache = BlobCache(Path(cfg.cache_dir) if cfg.cache_dir else default_cache_dir(), cfg.use_cache)
    measurer = Measurer(repo, cache, cfg.jobs, cfg.max_file_size)
    todo = [
        (p, head_all[p].sha, kinds[p], head_all[p].size)
        for p in code_paths
        if not cfg.changed_only or f_commits.get(p)
    ]
    measured = measurer.measure(todo)
    metrics: dict[str, dict] = {}
    for p, sha, kind, _sz in todo:
        m = measured.get(cache_key(kind, p, sha))
        if m:
            metrics[p] = m
    t = tick("complexity", t)

    # ---- hotspot scoring ---------------------------------------------------
    pool = [p for p in metrics if f_commits.get(p)]
    freq_n = dict(zip(pool, normalise([float(f_commits[p]) for p in pool])))
    cx_n: dict[str, float] = {}
    cx_sorted: dict[bool, list[float]] = {}
    for proxy in (False, True):
        grp = [p for p in pool if metrics[p]["proxy"] == proxy]
        cx_n.update(zip(grp, normalise([float(metrics[p]["ccn"]) for p in grp])))
        cx_sorted[proxy] = sorted(float(metrics[p]["ccn"]) for p in grp)
    score = {p: round(freq_n[p] * cx_n[p], 4) for p in pool}
    ranking = sorted((p for p in pool if score[p] > 0), key=lambda p: (-score[p], -(f_commits[p] * metrics[p]["ccn"]), p))
    rank_of = {p: i + 1 for i, p in enumerate(ranking)}
    pool_ccn_sorted = {k: v for k, v in cx_sorted.items()}

    # ---- knowledge --------------------------------------------------------
    inactive_cut = until.timestamp() - cfg.inactive_months * 30.4375 * 86400
    people_out = []
    person_commits: Counter[int] = Counter(c.person for c in commits)
    for pe in people:
        if pe["id"] in person_commits:
            people_out.append(
                {
                    "id": pe["id"],
                    "name": pe["name"],
                    "email": pe["email"],
                    "bot": pe["bot"],
                    "commits": person_commits[pe["id"]],
                    "last_commit": _iso(person_last.get(pe["id"])),
                    "inactive": person_last.get(pe["id"], 0) < inactive_cut,
                }
            )
    pname = {pe["id"]: pe["name"] for pe in people}

    files_out = []
    for p, m in metrics.items():
        n = f_commits.get(p, 0)
        know = _contrib_summary(f_people.get(p, {}), people, bots) if n else None
        rec = {
            "path": p,
            "language": PurePosixPath(p).suffix.lstrip(".").lower() or PurePosixPath(p).name.lower(),
            "commits": n,
            "commit_pct": round(n / total_commits, 4) if total_commits else 0.0,
            "authors": know["authors"] if know else 0,
            "added": f_added.get(p, 0),
            "deleted": f_deleted.get(p, 0),
            "churn": f_added.get(p, 0) + f_deleted.get(p, 0),
            "loc": m["loc"],
            "nloc": m["nloc"],
            "ccn": m["ccn"],
            "ccn_max": m["max"],
            "ccn_avg": m["avg"],
            "functions": m["nf"],
            "complexity_kind": "indent_proxy" if m["proxy"] else "ccn",
            "functions_over_threshold": sum(1 for f in m["fn"] if f[1] > cfg.ccn_threshold),
            "functions_over_30": sum(1 for f in m["fn"] if f[1] > 30),
            "freq_norm": round(freq_n.get(p, 0.0), 4),
            "cx_norm": round(cx_n.get(p, 0.0), 4),
            "score": score.get(p, 0.0),
            "rank": rank_of.get(p),
            "ccn_top_pct": round(top_percent(pool_ccn_sorted[m["proxy"]], float(m["ccn"])), 1) if p in score else None,
            "last_commit": _iso(f_last.get(p)),
            "main_author": pname[know["main_id"]] if know else None,
            "main_author_id": know["main_id"] if know else None,
            "owners": know["owners"] if know else [],
            "main_share_lines": know["share_lines"] if know else None,
            "main_share_commits": know["share_commits"] if know else None,
            "bus_factor": know["bus_factor"] if know else None,
            "main_author_last_commit": _iso(person_last.get(know["main_id"])) if know else None,
            "main_author_inactive": bool(know and person_last.get(know["main_id"], 0) < inactive_cut),
            "worst_function": (
                {"name": m["fn"][0][0], "ccn": m["fn"][0][1], "start": m["fn"][0][2], "end": m["fn"][0][3]}
                if m["fn"] and n
                else None
            ),
            "top_functions": [],
        }
        if rec["rank"] and rec["rank"] <= 100:
            rec["top_functions"] = [
                {"name": f[0], "ccn": f[1], "start": f[2], "end": f[3], "nloc": f[4]} for f in m["fn"][:8]
            ]
        files_out.append(rec)
    files_out.sort(key=lambda r: (r["rank"] or 10**9, -r["loc"], r["path"]))
    by_path = {r["path"]: r for r in files_out}

    # directories
    dirs_out = []
    for dname in sorted(d_people):
        know = _contrib_summary(d_people[dname], people, bots)
        if not know:
            continue
        fl = [by_path[f] for f in d_files[dname] if f in by_path]
        dirs_out.append(
            {
                "path": dname or ".",
                "depth": 0 if not dname else dname.count("/") + 1,
                "files_changed": len(fl),
                "files_total": sum(1 for q in by_path if not dname or q.startswith(dname + "/")),
                "commits": d_commits[dname],
                "authors": know["authors"],
                "loc": sum(r["loc"] for r in fl),
                "ccn": sum(r["ccn"] for r in fl),
                "max_score": max((r["score"] for r in fl), default=0.0),
                "main_author": pname[know["main_id"]],
                "main_author_id": know["main_id"],
                "owners": know["owners"],
                "main_share_lines": know["share_lines"],
                "main_share_commits": know["share_commits"],
                "bus_factor": know["bus_factor"],
                "main_author_last_commit": _iso(person_last.get(know["main_id"])),
                "main_author_inactive": person_last.get(know["main_id"], 0) < inactive_cut,
            }
        )
    dirs_out.sort(key=lambda r: (-r["commits"], r["path"]))
    t = tick("scoring_knowledge", t)

    # ---- coupling ---------------------------------------------------------
    coupling = compute_coupling(commit_sets, cfg.min_shared, cfg.min_degree, cfg.max_commit_files)
    t = tick("coupling", t)

    # ---- trends -----------------------------------------------------------
    say("sampling complexity trends")
    top_files = [r["path"] for r in files_out if r["rank"]][: cfg.trend_top]
    trends = complexity_trends(
        repo, ref_sha, since, until, cfg.trend_points, top_files, hist.names, hist.before, cache
    ) if top_files and cfg.trend_points >= 2 else []
    activity = monthly_activity(commits, since, until, bots)
    cache.close()
    t = tick("trends", t)

    # ---- summary & findings -----------------------------------------------
    human_ids = {c.person for c in commits} - bots
    head_date = None
    try:
        head_date = git(repo, "show", "-s", "--format=%ct", ref_sha).decode().strip()
        head_date = _iso(int(head_date))
    except (GitError, ValueError):
        pass
    summary = {
        "commits": total_commits,
        "authors": len(human_ids),
        "bots": len({c.person for c in commits} & bots),
        "files_changed": len({p for c in commits for p in c.files if p in head_all}),
        "code_files": len(metrics),
        "code_files_changed": sum(1 for r in files_out if r["commits"]),
        "total_loc": sum(r["loc"] for r in files_out),
        "total_ccn": sum(r["ccn"] for r in files_out if r["complexity_kind"] == "ccn"),
        "hotspots": sum(1 for r in files_out if r["score"] >= 0.25),
        "inactive_main_author_files": sum(1 for r in files_out if r["main_author_inactive"]),
        "single_author_files": sum(1 for r in files_out if r["commits"] and r["bus_factor"] == 1),
        "repo_bus_factor": (_contrib_summary(d_people.get("", {}), people, bots) or {}).get("bus_factor"),
        "repo_main_author": pname.get((_contrib_summary(d_people.get("", {}), people, bots) or {}).get("main_id")),
        "repo_main_author_share": (_contrib_summary(d_people.get("", {}), people, bots) or {}).get("share_lines"),
        "bulk_commits_ignored_for_coupling": coupling["commits_skipped_large"],
        "bulk_commits_dropped": hist.dropped_bulk,
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "codeheat", "version": __version__},
        "generated_at": _iso(datetime.now(timezone.utc).timestamp()),
        "repo": {
            "name": repo.name,
            "path": str(repo),
            "branch": branch_name,
            "head": ref_sha,
            "head_date": head_date,
        },
        "window": {"since": _iso(since.timestamp()), "until": _iso(until.timestamp())},
        "settings": {
            "include": cfg.include,
            "exclude": cfg.exclude,
            "default_excludes": cfg.default_excludes,
            "min_shared": cfg.min_shared,
            "min_degree": cfg.min_degree,
            "max_commit_files": cfg.max_commit_files,
            "inactive_months": cfg.inactive_months,
            "ccn_threshold": cfg.ccn_threshold,
            "include_bots": cfg.include_bots,
            "changed_only": cfg.changed_only,
            "ignore_bulk": cfg.ignore_bulk,
            "trend_points": cfg.trend_points,
            "partial_clone": partial,
        },
        "summary": summary,
        "findings": [],
        "files": files_out,
        "directories": dirs_out,
        "coupling": coupling,
        "authors": sorted(people_out, key=lambda a: -a["commits"]),
        "trends": trends,
        "activity": activity,
        "timings": {},
    }
    report["findings"] = make_findings(report, cfg)
    timings["total"] = round(time.perf_counter() - t_start, 3)
    timings["blobs_cached"] = measurer.stats["cached"]
    timings["blobs_computed"] = measurer.stats["computed"]
    report["timings"] = timings
    return report
