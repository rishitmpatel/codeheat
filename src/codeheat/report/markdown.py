"""Markdown summary (suitable for $GITHUB_STEP_SUMMARY)."""

from __future__ import annotations

from .common import human_date, spark

SEV_ICON = {"high": "\U0001f534", "medium": "\U0001f7e0", "low": "\U0001f535", "info": "⚪"}


def _esc(s: str) -> str:
    return s.replace("|", "\\|")


def render(rep: dict, top: int = 15, html_note: str | None = None) -> str:
    s, w = rep["summary"], rep["window"]
    L: list[str] = []
    L.append(f"## codeheat: {rep['repo']['name']} @ `{rep['repo']['branch']}`")
    L.append("")
    L.append(
        f"{human_date(w['since'])} → {human_date(w['until'])} · **{s['commits']:,}** commits · **{s['authors']}** authors · "
        f"**{s['code_files']}** source files ({s['code_files_changed']} changed) · {s['total_loc']:,} LOC"
    )
    if html_note:
        L += ["", html_note]
    L += ["", "### Findings", ""]
    for f in rep["findings"]:
        L.append(f"{f['priority']}. {SEV_ICON[f['severity']]} {f['title']}")
    hs = [f for f in rep["files"] if f["rank"]][:top]
    if hs:
        L += ["", f"### Top {len(hs)} hotspots", "", "| # | File | Commits | Authors | Churn | LOC | CCN | Max fn | Score |", "|--:|---|--:|--:|--:|--:|--:|--:|--:|"]
        for f in hs:
            px = "*" if f["complexity_kind"] == "indent_proxy" else ""
            L.append(
                f"| {f['rank']} | `{_esc(f['path'])}` | {f['commits']} | {f['authors']} | +{f['added']:,}/-{f['deleted']:,} | {f['loc']:,} | {f['ccn']}{px} | {f['ccn_max'] if not px else '-'} | {f['score']:.2f} |"
            )
        if any(f["complexity_kind"] == "indent_proxy" for f in hs):
            L += ["", "\\* indentation-based complexity proxy"]
    pairs = rep["coupling"]["pairs"][:10]
    if pairs:
        L += ["", "### Change coupling", "", "| File A | File B | Shared commits | Degree | Kind |", "|---|---|--:|--:|---|"]
        for p in pairs:
            L.append(f"| `{_esc(p['a'])}` | `{_esc(p['b'])}` | {p['shared']} | {p['degree']*100:.0f}% | {'**cross-module**' if p['surprising'] else p['kind']} |")
    risky = [f for f in rep["files"] if f["commits"] and (f["bus_factor"] == 1 or f["main_author_inactive"])]
    risky.sort(key=lambda f: (-f["score"], -f["commits"]))
    if risky:
        L += ["", "### Knowledge risks", "", "| File | Main author | Share (lines added) | Authors | Last seen |", "|---|---|--:|--:|---|"]
        for f in risky[:8]:
            L.append(
                f"| `{_esc(f['path'])}` | {_esc(f['main_author'] or '-')} | {(f['main_share_lines'] or 0)*100:.0f}% | {f['authors']} | {human_date(f['main_author_last_commit'])}{' (inactive)' if f['main_author_inactive'] else ''} |"
            )
    if rep["trends"]:
        L += ["", "### Complexity trend (top hotspots)", "", "| File | Trend | Change |", "|---|---|--:|"]
        for tr in rep["trends"]:
            ch = tr["change_pct"]
            L.append(f"| `{_esc(tr['path'])}` | `{spark([p['ccn'] for p in tr['points']])}` | {'-' if ch is None else f'{ch*100:+.0f}%'} |")
    L += ["", f"<sub>codeheat {rep['tool']['version']} · {rep['timings'].get('total', 0):.1f}s</sub>", ""]
    return "\n".join(L)
