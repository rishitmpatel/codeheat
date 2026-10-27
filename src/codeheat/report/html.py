"""Self-contained HTML report (inline CSS + JS, no network)."""

from __future__ import annotations

import json
from importlib import resources


def _asset(name: str) -> str:
    return resources.files("codeheat.report").joinpath("assets", name).read_text(encoding="utf-8")


def build_payload(rep: dict) -> dict:
    authors = rep["authors"]
    # colour order: by how much code each author owns (main author, by LOC)
    owned: dict[int, int] = {}
    for f in rep["files"]:
        if f["main_author_id"] is not None:
            owned[f["main_author_id"]] = owned.get(f["main_author_id"], 0) + f["loc"]
    order = sorted(authors, key=lambda a: (-owned.get(a["id"], 0), -a["commits"]))
    idx = {a["id"]: i for i, a in enumerate(order)}
    files = []
    for f in rep["files"]:
        files.append(
            {
                "p": f["path"],
                "l": f["loc"],
                "n": f["commits"],
                "a": f["authors"],
                "ad": f["added"],
                "de": f["deleted"],
                "c": f["ccn"],
                "m": f["ccn_max"],
                "fn": f["functions"],
                "ov": f["functions_over_threshold"],
                "px": 1 if f["complexity_kind"] == "indent_proxy" else 0,
                "s": f["score"],
                "r": f["rank"],
                "t": f["ccn_top_pct"],
                "fq": f["freq_norm"],
                "cx": f["cx_norm"],
                "ma": idx.get(f["main_author_id"]),
                "ms": f["main_share_lines"],
                "mc": f["main_share_commits"],
                "bf": f["bus_factor"],
                "gone": 1 if f["main_author_inactive"] else 0,
                "ml": f["main_author_last_commit"],
                "lc": f["last_commit"],
                "ow": [[idx.get(o[0]), o[1]] for o in f["owners"]],
                "tf": [[x["name"], x["ccn"], x["start"], x["end"]] for x in f["top_functions"][:6]],
            }
        )
    dirs = []
    for d in rep["directories"]:
        dirs.append(
            {
                "p": d["path"],
                "d": d["depth"],
                "n": d["commits"],
                "a": d["authors"],
                "l": d["loc"],
                "bf": d["bus_factor"],
                "ma": idx.get(d["main_author_id"]),
                "ms": d["main_share_lines"],
                "gone": 1 if d["main_author_inactive"] else 0,
                "ow": [[idx.get(o[0]), o[1]] for o in d["owners"]],
                "fc": d["files_changed"],
                "ft": d["files_total"],
                "mx": d["max_score"],
            }
        )
    return {
        "meta": {
            "repo": rep["repo"]["name"],
            "branch": rep["repo"]["branch"],
            "head": rep["repo"]["head"][:8],
            "since": rep["window"]["since"][:10],
            "until": rep["window"]["until"][:10],
            "generated": rep["generated_at"][:10],
            "version": rep["tool"]["version"],
            "ccn_threshold": rep["settings"]["ccn_threshold"],
            "inactive_months": rep["settings"]["inactive_months"],
            "min_shared": rep["settings"]["min_shared"],
            "min_degree": rep["settings"]["min_degree"],
            "max_commit_files": rep["settings"]["max_commit_files"],
            "summary": rep["summary"],
            "seconds": rep["timings"].get("total"),
        },
        "authors": [
            {"n": a["name"], "c": a["commits"], "last": a["last_commit"], "gone": 1 if a["inactive"] else 0, "bot": 1 if a["bot"] else 0, "own": owned.get(a["id"], 0)}
            for a in order
        ],
        "findings": [
            {"k": x["category"], "s": x["severity"], "t": x["title"], "d": x["detail"], "f": x["files"], "i": x["priority"]}
            for x in rep["findings"]
        ],
        "files": files,
        "dirs": dirs,
        "coupling": {
            "pairs": rep["coupling"]["pairs"][:120],
            "total": rep["coupling"]["total_pairs"],
            "surprising": rep["coupling"]["surprising_pairs"],
            "skipped": rep["coupling"]["commits_skipped_large"],
        },
        "trends": [
            {"p": t["path"], "ch": t["change_pct"], "px": t["proxy"], "pts": [[q["t"], q["ccn"], q["loc"]] for q in t["points"]]}
            for t in rep["trends"]
        ],
        "activity": rep["activity"],
    }


def render(rep: dict) -> str:
    payload = json.dumps(build_payload(rep), separators=(",", ":"), ensure_ascii=False)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    title = f"codeheat \u00b7 {rep['repo']['name']}"
    page = _asset("report.html")
    return (
        page.replace("{{TITLE}}", title.replace("&", "&amp;").replace("<", "&lt;"))
        .replace("/*{{CSS}}*/", _asset("report.css"))
        .replace("/*{{JS}}*/", _asset("report.js"))
        .replace("{{DATA}}", payload)
    )
