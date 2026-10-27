"""Rich terminal report."""

from __future__ import annotations

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .common import human_date, short_path, spark

SEV_STYLE = {"high": "bold red", "medium": "bold yellow", "low": "cyan", "info": "dim"}
SEV_LABEL = {"high": "HIGH", "medium": "MED ", "low": "LOW ", "info": "INFO"}


def heat_style(x: float) -> str:
    if x >= 0.75:
        return "bold red"
    if x >= 0.5:
        return "dark_orange"
    if x >= 0.25:
        return "yellow"
    return "green"


def bar(x: float, width: int = 12) -> Text:
    x = max(0.0, min(1.0, x))
    full = x * width
    n = int(full)
    frac = full - n
    partial = "▏▎▍▌▋▊▉"[int(frac * 7)] if n < width and frac > 0.07 else ""
    t = Text("█" * n + partial, style=heat_style(x))
    t.append(" " * (width - n - len(partial)))
    return t


def render(rep: dict, console: Console | None = None, top: int = 15) -> None:
    c = console or Console()
    s = rep["summary"]
    w = rep["window"]
    c.print()
    head = Text()
    head.append("codeheat ", style="bold")
    head.append(f"{rep['repo']['name']}", style="bold cyan")
    head.append(f" @ {rep['repo']['branch']}  ")
    head.append(f"{human_date(w['since'])} → {human_date(w['until'])}", style="dim")
    c.print(head)
    c.print(
        Text(
            f"{s['commits']:,} commits · {s['authors']} authors · {s['code_files']} source files "
            f"({s['code_files_changed']} changed) · {s['total_loc']:,} LOC · {rep['timings'].get('total', 0):.1f}s",
            style="dim",
        )
    )
    if not s["commits"]:
        c.print(Panel("No commits in this window. Try a wider --since.", style="yellow"))
        return
    c.print()

    # --- hotspots ---------------------------------------------------------
    files = [f for f in rep["files"] if f["rank"]][:top]
    if files:
        t = Table(title="Hotspots — frequently changed AND complex", title_justify="left", box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
        wide = c.width >= 110
        cols = [("#", "right", 1), ("File", "left", 1), ("Commits", "right", 1), ("Auth", "right", wide), ("Churn +/-", "right", wide), ("LOC", "right", 1), ("CCN", "right", 1), ("Max fn", "right", 1), ("Score", "left", 1)]
        for col, just, show in cols:
            if show:
                t.add_column(col, justify=just, no_wrap=True, overflow="ellipsis")
        for f in files:
            proxy = f["complexity_kind"] == "indent_proxy"
            cells = [
                str(f["rank"]),
                short_path(f["path"], max(18, c.width - (92 if wide else 64))),
                str(f["commits"]),
                str(f["authors"]),
                f"+{f['added']:,}/-{f['deleted']:,}",
                f"{f['loc']:,}",
                f"{f['ccn']}{'*' if proxy else ''}",
                "-" if proxy else (f"[bold red]{f['ccn_max']}[/]" if f["ccn_max"] > 30 else f"[yellow]{f['ccn_max']}[/]" if f["ccn_max"] > 15 else str(f["ccn_max"])),
                Text.assemble(bar(f["score"], 10), f" {f['score']:.2f}"),
            ]
            t.add_row(*[cell for cell, (_n, _j, show) in zip(cells, cols) if show])
        c.print(t)
        if any(f["complexity_kind"] == "indent_proxy" for f in files):
            c.print(Text("* indentation-based proxy (language not supported by lizard)", style="dim"))
        # complex functions in top hotspots
        fn_rows = []
        for f in files[:5]:
            for fn in f["top_functions"][:3]:
                if fn["ccn"] > 10:
                    fn_rows.append((f["path"], fn))
        if fn_rows:
            ft = Table(title="Complex functions inside the top hotspots", title_justify="left", box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
            ft.add_column("File")
            ft.add_column("Function", overflow="ellipsis")
            ft.add_column("CCN", justify="right")
            ft.add_column("Lines", justify="right")
            for p, fn in sorted(fn_rows, key=lambda r: -r[1]["ccn"])[:10]:
                ft.add_row(short_path(p, 40), fn["name"], f"[bold red]{fn['ccn']}[/]" if fn["ccn"] > 30 else f"[yellow]{fn['ccn']}[/]", f"{fn['start']}–{fn['end']}")
            c.print(ft)
    else:
        c.print(Text("No hotspots: no source files with complexity changed in this window.", style="dim"))
    c.print()

    # --- coupling ---------------------------------------------------------
    cp = rep["coupling"]
    pairs = cp["pairs"]
    if pairs:
        ordered = [p for p in pairs if p["surprising"]][:5] + [p for p in pairs if not p["surprising"]]
        seen, rows = set(), []
        for p in sorted(ordered[:10], key=lambda p: (-p["strength"])):
            rows.append(p)
        t = Table(title=f"Change coupling — {cp['total_pairs']} pairs ({cp['surprising_pairs']} across modules)", title_justify="left", box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
        t.add_column("File A", overflow="ellipsis")
        t.add_column("File B", overflow="ellipsis")
        t.add_column("Shared", justify="right")
        t.add_column("Degree", justify="right")
        t.add_column("Kind")
        for p in rows[:10]:
            kind = Text("⚠ cross-module", style="bold yellow") if p["surprising"] else Text(p["kind"], style="dim")
            t.add_row(short_path(p["a"], 38), short_path(p["b"], 38), str(p["shared"]), f"{p['degree']*100:.0f}%", kind)
        c.print(t)
    else:
        c.print(Text(f"No file pairs changed together ≥{rep['settings']['min_shared']} times with ≥{rep['settings']['min_degree']*100:.0f}% coupling.", style="dim"))
    c.print()

    # --- knowledge --------------------------------------------------------
    risky = [f for f in rep["files"] if f["commits"] and (f["bus_factor"] == 1 or f["main_author_inactive"])]
    risky.sort(key=lambda f: (-(f["score"]), -f["commits"]))
    if risky:
        t = Table(title=f"Knowledge risks — {s['single_author_files']} single-owner files, {s['inactive_main_author_files']} with an inactive main author", title_justify="left", box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
        t.add_column("File", overflow="ellipsis")
        t.add_column("Main author", overflow="ellipsis")
        t.add_column("Share", justify="right")
        t.add_column("Authors", justify="right")
        t.add_column("Bus", justify="right")
        t.add_column("Main author last seen")
        for f in risky[:8]:
            last = human_date(f["main_author_last_commit"])
            t.add_row(
                short_path(f["path"], 40),
                f["main_author"] or "-",
                f"{(f['main_share_lines'] or 0)*100:.0f}%",
                str(f["authors"]),
                str(f["bus_factor"]),
                Text(last + (" ⚠ inactive" if f["main_author_inactive"] else ""), style="red" if f["main_author_inactive"] else ""),
            )
        c.print(t)
    dirs = [d for d in rep["directories"] if d["depth"] == 1][:6]
    if dirs:
        t = Table(title="Directory ownership", title_justify="left", box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
        t.add_column("Directory")
        t.add_column("Commits", justify="right")
        t.add_column("Authors", justify="right")
        t.add_column("Bus", justify="right")
        t.add_column("Main author (by lines added)", overflow="ellipsis")
        for d in dirs:
            t.add_row(d["path"], str(d["commits"]), str(d["authors"]), str(d["bus_factor"]), f"{d['main_author']} ({d['main_share_lines']*100:.0f}%)")
        c.print(t)
    c.print()

    # --- trends -----------------------------------------------------------
    if rep["trends"]:
        t = Table(title="Complexity trend of the top hotspots", title_justify="left", box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
        t.add_column("File", overflow="ellipsis")
        t.add_column("Over time")
        t.add_column("First", justify="right")
        t.add_column("Last", justify="right")
        t.add_column("Change", justify="right")
        for tr in rep["trends"]:
            vals = [p["ccn"] for p in tr["points"]]
            nums = [v for v in vals if v is not None]
            ch = tr["change_pct"]
            chs = "-" if ch is None else f"{ch*100:+.0f}%"
            style = "red" if (ch or 0) > 0.25 else "green" if (ch or 0) < -0.25 else ""
            t.add_row(short_path(tr["path"], 40), Text(spark(vals), style="orange3"), str(nums[0]) if nums else "-", str(nums[-1]) if nums else "-", Text(chs, style=style))
        c.print(t)
    act = rep["activity"]
    if act:
        c.print(Text.assemble(("Commits per month  ", "bold"), (spark([a["commits"] for a in act]), "orange3"), (f"   {act[0]['month']} → {act[-1]['month']}  (max {max(a['commits'] for a in act)}/month)", "dim")))
    c.print()

    # --- findings ---------------------------------------------------------
    body = []
    for f in rep["findings"]:
        line = Text()
        line.append(f"{f['priority']:>2}. ", style="bold")
        line.append(f"[{SEV_LABEL[f['severity']]}] ", style=SEV_STYLE[f["severity"]])
        line.append(f["title"])
        body.append(line)
    c.print(Panel(Group(*body), title="Findings, most important first", title_align="left", border_style="orange3", padding=(1, 2)))
