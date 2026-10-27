from __future__ import annotations

import json
import re

import pytest

from codeheat.cli import main
from conftest import py_func

ALICE = "Alice <alice@example.com>"
BOB = "Bob <bob@example.com>"


@pytest.fixture
def busy(repo):
    for i in range(7):
        repo.commit(
            {"core/engine.py": py_func("run", 3 + i) + py_func("go", 40), "api/routes.py": py_func("r", i), "tests/test_engine.py": py_func("t", i)},
            ALICE if i % 2 else BOB, f"2025-03-{i+1:02d}T10:00:00",
        )
    return repo


def args(repo, tmp_path, *extra):
    return [str(repo.path), "--since", "2025-01-01", "--until", "2025-12-31", "--cache-dir", str(tmp_path / "c"), "--jobs", "1", *extra]


def test_terminal_report(busy, tmp_path, capsys):
    assert main(args(busy, tmp_path, "--no-color")) == 0
    out = capsys.readouterr().out
    for needle in ("Hotspots", "core/engine.py", "Change coupling", "Knowledge risks", "Findings", "refactor candidate #1", "Complexity trend"):
        assert needle in out


def test_json_markdown_html_outputs(busy, tmp_path, capsys):
    j, m, h = tmp_path / "o.json", tmp_path / "o.md", tmp_path / "o.html"
    assert main(args(busy, tmp_path, "-q", "--json", str(j), "--markdown", str(m), "--html", str(h))) == 0
    rep = json.loads(j.read_text())
    assert rep["files"][0]["path"] == "core/engine.py"
    md = m.read_text()
    assert md.startswith("## codeheat:") and "| # | File |" in md and "core/engine.py" in md
    html = h.read_text()
    assert "<!doctype html>" in html and "core/engine.py" in html and "{{" not in html
    # fully self-contained: no external resources
    assert not re.search(r"""(src|href)\s*=\s*["']https?://""", html)
    assert "@import" not in html and "url(http" not in html
    assert len(html) < 400_000
    # embedded data parses
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert data["meta"]["repo"] == "repo" and data["files"][0]["p"] == "core/engine.py"


def test_json_to_stdout(busy, tmp_path, capsys):
    assert main(args(busy, tmp_path, "--json", "-")) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["commits"] == 7


def test_gates(busy, tmp_path, capsys):
    assert main(args(busy, tmp_path, "-q", "--max-ccn", "100")) == 0
    assert main(args(busy, tmp_path, "-q", "--max-ccn", "30")) == 1
    err = capsys.readouterr().err
    assert "core/engine.py" in err and "go" in err and "gate failed" in err
    assert main(args(busy, tmp_path, "-q", "--fail-on", "hotspot>0.5")) == 1
    assert main(args(busy, tmp_path, "-q", "--fail-on", "hotspot>0.99")) == 0
    assert main(args(busy, tmp_path, "-q", "--fail-on", "nonsense")) == 2


def test_errors(tmp_path, capsys):
    assert main([str(tmp_path)]) == 2
    assert "not inside a git repository" in capsys.readouterr().err
    assert main([".", "--since", "garbage"]) == 2


def test_subdirectory_argument_limits_scope(busy, tmp_path):
    out = tmp_path / "o.json"
    assert main([str(busy.path / "core"), "--since", "2025-01-01", "--until", "2025-12-31", "--cache-dir", str(tmp_path / "c"), "-q", "--json", str(out)]) == 0
    assert [f["path"] for f in json.loads(out.read_text())["files"]] == ["core/engine.py"]
