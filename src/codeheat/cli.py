"""Command line interface."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import __version__
from .analyze import analyze
from .config import Config
from .gitlog import GitError

_GATE = re.compile(r"^\s*(hotspot|ccn)\s*(>=|>)\s*([0-9]*\.?[0-9]+)\s*$")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="codeheat",
        description="Behavioural code analysis of a git repository: hotspots, change coupling, knowledge risk and complexity trends.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("path", nargs="?", default=".", help="repository (or a directory inside it; only that subtree is analysed)")
    g = p.add_argument_group("window and scope")
    g.add_argument("--since", default="12 months ago", help="start of the analysis window (YYYY-MM-DD or '6 months ago')")
    g.add_argument("--until", default=None, help="end of the analysis window (default: now)")
    g.add_argument("--branch", default=None, help="branch/ref to analyse (default: HEAD)")
    g.add_argument("--include", action="append", default=[], metavar="GLOB", help="only analyse paths matching this gitignore-style glob (repeatable)")
    g.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="skip paths matching this glob (repeatable; also see .codeheatignore)")
    g.add_argument("--no-default-excludes", action="store_true", help="do not skip vendored/generated/lock/minified files")
    g.add_argument("--no-ignore-file", action="store_true", help="do not read .codeheatignore")
    g.add_argument("--changed-only", action="store_true", help="measure only files changed in the window (faster; map shows changed files only)")
    g.add_argument("--ignore-bulk", type=int, default=0, metavar="N", help="drop commits touching more than N files from every analysis (0 = keep)")
    g = p.add_argument_group("coupling")
    g.add_argument("--min-shared", type=int, default=5, help="minimum shared commits for a coupled pair")
    g.add_argument("--min-degree", type=float, default=0.30, help="minimum coupling degree (shared / min(revisions))")
    g.add_argument("--max-commit-files", type=int, default=50, help="ignore commits touching more files than this when computing coupling")
    g = p.add_argument_group("knowledge")
    g.add_argument("--inactive-months", type=float, default=6.0, help="a main author with no commit for this long counts as gone")
    g.add_argument("--include-bots", action="store_true", help="count bot accounts as authors")
    g.add_argument("--no-merge-names", action="store_true", help="do not merge identities that only share a display name")
    g = p.add_argument_group("complexity")
    g.add_argument("--ccn-threshold", type=int, default=15, help="a function above this CCN is flagged")
    g.add_argument("--trend-points", type=int, default=12, help="samples per complexity trend (0 disables trends)")
    g = p.add_argument_group("output")
    g.add_argument("--html", metavar="FILE", help="write a self-contained interactive HTML report")
    g.add_argument("--json", metavar="FILE", help="write the full analysis as JSON ('-' for stdout)")
    g.add_argument("--markdown", metavar="FILE", help="write a markdown summary ('-' for stdout)")
    g.add_argument("--top", type=int, default=15, help="rows in terminal tables")
    g.add_argument("-q", "--quiet", action="store_true", help="no terminal report")
    g.add_argument("--no-color", action="store_true")
    g = p.add_argument_group("CI gates (exit status 1 when violated)")
    g.add_argument("--fail-on", action="append", default=[], metavar="EXPR", help="'hotspot>0.9' (top hotspot score) or 'ccn>30' (max function CCN in files changed in the window); repeatable")
    g.add_argument("--max-ccn", type=int, default=None, metavar="N", help="shorthand for --fail-on ccn>N")
    g = p.add_argument_group("engine")
    g.add_argument("--jobs", "-j", type=int, default=None, help="worker processes for complexity analysis (default: CPU count)")
    g.add_argument("--no-cache", action="store_true", help="do not read/write the per-blob complexity cache")
    g.add_argument("--cache-dir", default=None, help="cache location (default: XDG/LOCALAPPDATA codeheat cache)")
    p.add_argument("--version", action="version", version=f"codeheat {__version__}")
    return p


def evaluate_gates(rep: dict, exprs: list[str]) -> list[str]:
    """Return human-readable violations."""
    bad: list[str] = []
    for e in exprs:
        m = _GATE.match(e)
        if not m:
            raise ValueError(f"bad --fail-on expression {e!r}; use 'hotspot>0.9' or 'ccn>30'")
        what, op, val = m.group(1), m.group(2), float(m.group(3))
        cmp = (lambda x: x > val) if op == ">" else (lambda x: x >= val)
        if what == "hotspot":
            for f in rep["files"]:
                if f["rank"] and cmp(f["score"]):
                    bad.append(f"hotspot score {f['score']:.2f} {op} {val:g}: {f['path']}")
        else:
            for f in rep["files"]:
                if f["commits"] and f["complexity_kind"] == "ccn" and cmp(f["ccn_max"]):
                    w = f.get("worst_function") or {}
                    bad.append(f"function CCN {f['ccn_max']} {op} {val:g}: {f['path']}:{w.get('start', '?')} {w.get('name', '')}".rstrip())
    return bad


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    gates = list(args.fail_on)
    if args.max_ccn is not None:
        gates.append(f"ccn>{args.max_ccn}")
    try:
        for g in gates:
            if not _GATE.match(g):
                raise ValueError(f"bad --fail-on expression {g!r}; use 'hotspot>0.9' or 'ccn>30'")
        cfg = Config(
            repo=args.path,
            branch=args.branch,
            since=args.since,
            until=args.until,
            include=args.include,
            exclude=args.exclude,
            default_excludes=not args.no_default_excludes,
            use_ignore_file=not args.no_ignore_file,
            min_shared=args.min_shared,
            min_degree=args.min_degree,
            max_commit_files=args.max_commit_files,
            inactive_months=args.inactive_months,
            include_bots=args.include_bots,
            merge_names=not args.no_merge_names,
            ccn_threshold=args.ccn_threshold,
            changed_only=args.changed_only,
            ignore_bulk=args.ignore_bulk,
            trend_points=args.trend_points,
            top=args.top,
            jobs=args.jobs,
            use_cache=not args.no_cache,
            cache_dir=args.cache_dir,
        )
        from rich.console import Console

        err = Console(stderr=True, no_color=args.no_color)
        stdout_taken = "-" in (args.json, args.markdown)
        status = err.status("[bold]analysing…") if err.is_terminal else None
        if status:
            status.start()
        try:
            rep = analyze(cfg, (lambda m: status.update(f"[bold]{m}…")) if status else None)
        finally:
            if status:
                status.stop()

        if not args.quiet and not stdout_taken:
            from .report import terminal

            terminal.render(rep, Console(no_color=args.no_color), top=args.top)
        if args.json:
            from .report import jsonout

            _emit(args.json, jsonout.dumps(rep))
        if args.markdown:
            from .report import markdown

            _emit(args.markdown, markdown.render(rep, args.top, f"Interactive HTML report: `{args.html}`" if args.html else None))
        if args.html:
            from .report import html

            _emit(args.html, html.render(rep))
            err.print(f"[dim]wrote {args.html}[/]")
        bad = evaluate_gates(rep, gates)
        if bad:
            err.print(f"[bold red]codeheat gate failed[/] ({len(bad)} violation{'s' if len(bad) != 1 else ''}):")
            for b in bad[:25]:
                err.print(f"  • {b}", highlight=False)
            return 1
        return 0
    except (GitError, ValueError) as exc:
        print(f"codeheat: error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


def _emit(dest: str, text: str) -> None:
    if dest == "-":
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
    else:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
