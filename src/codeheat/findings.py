"""Plain-language, prioritised findings."""

from __future__ import annotations

from .config import Config
from .coupling import is_test

SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
CAT_ORDER = {"hotspot": 0, "trend": 1, "coupling": 2, "knowledge": 3, "info": 4}


def _pct(x: float) -> str:
    v = x * 100
    return "<1%" if 0 < v < 1 else f"{v:.0f}%"


def _top_label(p: float | None) -> str:
    if p is None:
        return ""
    return f"top {p:.0f}%" if p >= 1.5 else "top 1%"


def make_findings(rep: dict, cfg: Config) -> list[dict]:
    out: list[dict] = []
    files = rep["files"]
    thr = cfg.ccn_threshold
    ranked = [f for f in files if f["rank"]]

    # --- hotspots ---------------------------------------------------------
    # Test files stay in the hotspot tables, but they are not refactor
    # candidates: long, flat test modules score high on summed CCN while
    # having no complex functions.
    candidates = [f for f in ranked if not is_test(f["path"])]
    for n, f in enumerate(candidates[:5], start=1):
        proxy = f["complexity_kind"] == "indent_proxy"
        cx = f"indentation complexity {f['ccn']}" if proxy else f"complexity {f['ccn']}"
        pct = f"{cx} ({_top_label(f['ccn_top_pct'])})"
        if f["functions_over_30"]:
            funcs = f"{f['functions_over_30']} function{'s' if f['functions_over_30'] != 1 else ''} over CCN 30"
        elif f["functions_over_threshold"]:
            funcs = f"{f['functions_over_threshold']} function{'s' if f['functions_over_threshold'] != 1 else ''} over CCN {thr}"
        elif proxy:
            funcs = "no per-function data (unsupported language)"
        else:
            funcs = f"no function over CCN {thr}"
        sev = "high" if f["score"] >= 0.5 else "medium" if f["score"] >= 0.25 else "low"
        out.append(
            {
                "category": "hotspot",
                "severity": sev,
                "title": f"{f['path']}: changed in {_pct(f['commit_pct'])} of all commits, {pct}, {funcs} — refactor candidate #{n}",
                "detail": (
                    f"{f['commits']} commits by {f['authors']} author{'s' if f['authors'] != 1 else ''}, "
                    f"{f['added']:,} lines added / {f['deleted']:,} deleted, {f['loc']:,} LOC. "
                    f"Hotspot score {f['score']:.2f}."
                ),
                "files": [f["path"]],
                "score": f["score"],
            }
        )

    # --- complexity growth --------------------------------------------------
    for tr in rep["trends"]:
        pts = [p["ccn"] for p in tr["points"] if p["ccn"] is not None]
        if len(pts) >= 3 and tr["change_pct"] is not None and tr["change_pct"] >= 0.25 and pts[-1] - pts[0] >= 20:
            out.append(
                {
                    "category": "trend",
                    "severity": "high" if tr["change_pct"] >= 0.5 else "medium",
                    "title": f"{tr['path']}: complexity grew {tr['change_pct']*100:+.0f}% ({pts[0]} → {pts[-1]}) over the window",
                    "detail": "A hotspot that keeps getting more complex compounds its cost on every change.",
                    "files": [tr["path"]],
                    "score": tr["change_pct"],
                }
            )
        elif len(pts) >= 3 and tr["change_pct"] is not None and tr["change_pct"] <= -0.25 and pts[0] - pts[-1] >= 20:
            out.append(
                {
                    "category": "trend",
                    "severity": "info",
                    "title": f"{tr['path']}: complexity fell {tr['change_pct']*100:.0f}% ({pts[0]} → {pts[-1]}) — refactoring is paying off",
                    "detail": "",
                    "files": [tr["path"]],
                    "score": 0,
                }
            )

    # --- coupling -----------------------------------------------------------
    pairs = rep["coupling"]["pairs"]
    surprising = [p for p in pairs if p["surprising"]]
    for p in surprising[:3]:
        out.append(
            {
                "category": "coupling",
                "severity": "high" if p["degree"] >= 0.7 and p["shared"] >= 10 else "medium",
                "title": (
                    f"{p['a']} and {p['b']} change together in {p['shared']} commits "
                    f"({p['degree']*100:.0f}% of the time) across modules ({p['module_a']} vs {p['module_b']})"
                ),
                "detail": "Hidden dependency: a change in one usually requires a change in the other, but nothing in the directory structure says so.",
                "files": [p["a"], p["b"]],
                "score": p["degree"],
            }
        )
    same = [p for p in pairs if p["kind"] == "same-module" and p["degree"] >= 0.8 and p["shared"] >= 2 * cfg.min_shared]
    if same:
        p = same[0]
        out.append(
            {
                "category": "coupling",
                "severity": "low",
                "title": f"{p['a']} and {p['b']} are almost always changed together ({p['shared']} commits, {p['degree']*100:.0f}%)",
                "detail": "Consider whether they should be one unit, or whether the shared concept deserves its own abstraction.",
                "files": [p["a"], p["b"]],
                "score": p["degree"],
            }
        )

    # --- knowledge ------------------------------------------------------------
    solo = [
        f for f in ranked[:10]
        if f["bus_factor"] == 1 and f["main_share_lines"] and f["main_share_lines"] >= 0.8 and f["commits"] >= 5
    ]
    by_author: dict[str, list[dict]] = {}
    for f in solo:
        by_author.setdefault(f["main_author"], []).append(f)
    for author, fl in by_author.items():
        inactive = fl[0]["main_author_inactive"]
        if len(fl) == 1:
            f = fl[0]
            title = (
                f"{f['path']} (hotspot #{f['rank']}): {f['main_share_lines']*100:.0f}% of added lines by {author}"
                + (f", who has not committed in {cfg.inactive_months:g}+ months" if inactive else " \u2014 single point of knowledge")
            )
        else:
            names = ", ".join(f"{f['path']} (#{f['rank']})" for f in fl[:4]) + (f" and {len(fl)-4} more" if len(fl) > 4 else "")
            title = (
                f"{len(fl)} of the top {min(10, len(ranked))} hotspots are >80% written by {author}"
                + (f", who has not committed in {cfg.inactive_months:g}+ months" if inactive else "")
                + f": {names}"
            )
        out.append(
            {
                "category": "knowledge",
                "severity": "high" if inactive else "medium",
                "title": title,
                "detail": "Bus factor 1 on files that change often. Pair on them, spread reviews, or document them.",
                "files": [f["path"] for f in fl],
                "score": max(f["score"] for f in fl),
            }
        )
    lost = [f for f in files if f["main_author_inactive"] and f["commits"]]
    if lost:
        top_lost = sorted(lost, key=lambda f: -(f["loc"]))[:3]
        share = len(lost) / max(1, sum(1 for f in files if f["commits"]))
        out.append(
            {
                "category": "knowledge",
                "severity": "high" if share >= 0.25 else "medium",
                "title": (
                    f"{len(lost)} changed file{'s' if len(lost) != 1 else ''} ({share*100:.0f}%) {'have' if len(lost) != 1 else 'has'} a main author with no commits in the last "
                    f"{cfg.inactive_months:g} months; largest: " + ", ".join(f["path"] for f in top_lost)
                ),
                "detail": "Knowledge-loss risk: the person who wrote most of this recently is no longer around to ask.",
                "files": [f["path"] for f in top_lost],
                "score": share,
            }
        )
    s = rep["summary"]
    if s.get("repo_bus_factor") == 1 and s["authors"] > 1 and (s["repo_main_author_share"] or 0) >= 0.6:
        out.append(
            {
                "category": "knowledge",
                "severity": "medium",
                "title": f"Repository bus factor is 1: {s['repo_main_author']} wrote {(s['repo_main_author_share'] or 0)*100:.0f}% of the added lines",
                "detail": "",
                "files": [],
                "score": s["repo_main_author_share"] or 0,
            }
        )

    # --- housekeeping ---------------------------------------------------------
    if rep["coupling"]["commits_skipped_large"]:
        out.append(
            {
                "category": "info",
                "severity": "info",
                "title": f"{rep['coupling']['commits_skipped_large']} commits touching more than {cfg.max_commit_files} files were ignored for coupling (bulk changes are noise)",
                "detail": "",
                "files": [],
                "score": 0,
            }
        )
    if rep["settings"].get("partial_clone"):
        out.append(
            {
                "category": "info",
                "severity": "info",
                "title": "Partial clone detected: added/deleted line counts were skipped (churn shows 0, ownership falls back to commit counts). Use a full clone for complete results.",
                "detail": "",
                "files": [],
                "score": 0,
            }
        )
    if not out:
        out.append(
            {
                "category": "info",
                "severity": "info",
                "title": "No notable findings in this window.",
                "detail": "",
                "files": [],
                "score": 0,
            }
        )
    out.sort(key=lambda r: (SEV_ORDER[r["severity"]], CAT_ORDER[r["category"]], -r["score"]))
    for i, r in enumerate(out, 1):
        r["priority"] = i
    return out
