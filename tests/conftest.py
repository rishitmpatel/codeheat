from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from codeheat.config import Config


class Repo:
    """Scripted synthetic git repository."""

    def __init__(self, path: Path):
        self.path = path
        path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "tag.gpgsign", "false")
        self.git("config", "core.hooksPath", "/dev/null")

    def git(self, *args: str, env: dict | None = None) -> str:
        e = {**os.environ, **(env or {})}
        for k in ("GIT_DIR", "GIT_WORK_TREE"):
            e.pop(k, None)
        r = subprocess.run(["git", *args], cwd=self.path, env=e, capture_output=True, text=True)
        assert r.returncode == 0, f"git {args} failed: {r.stderr}"
        return r.stdout

    def commit(
        self,
        files: dict[str, str | None] | None = None,
        author: str = "Alice <alice@example.com>",
        date: str = "2025-03-01T12:00:00",
        msg: str = "change",
        mv: list[tuple[str, str]] | None = None,
    ) -> str:
        for old, new in mv or []:
            (self.path / new).parent.mkdir(parents=True, exist_ok=True)
            self.git("mv", old, new)
        for rel, content in (files or {}).items():
            p = self.path / rel
            if content is None:
                if p.exists():
                    p.unlink()
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        self.git("add", "-A")
        name, email = author[:-1].split(" <")
        d = date + "+00:00" if len(date) == 19 else date
        env = {
            "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": d,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": d,
        }
        self.git("commit", "-q", "--allow-empty", "-m", msg, env=env)
        return self.git("rev-parse", "HEAD").strip()

    def merge(self, branch: str, date: str = "2025-03-01T12:00:00") -> None:
        d = date + "+00:00"
        env = {"GIT_AUTHOR_DATE": d, "GIT_COMMITTER_DATE": d, "GIT_AUTHOR_NAME": "M", "GIT_AUTHOR_EMAIL": "m@x.com", "GIT_COMMITTER_NAME": "M", "GIT_COMMITTER_EMAIL": "m@x.com"}
        self.git("merge", "--no-ff", "-q", "-m", "merge", branch, env=env)


@pytest.fixture
def repo(tmp_path) -> Repo:
    return Repo(tmp_path / "repo")


@pytest.fixture
def cfg(tmp_path):
    def make(repo: Repo, **kw) -> Config:
        base = dict(repo=str(repo.path), since="2025-01-01", until="2025-12-31", cache_dir=str(tmp_path / "cache"), jobs=1, trend_points=4)
        base.update(kw)
        return Config(**base)
    return make


def py_func(name: str, branches: int, extra_lines: int = 0) -> str:
    """A python function with CCN == branches + 1."""
    body = "".join(f"    if x == {i}:\n        return {i}\n" for i in range(branches))
    body += "".join(f"    y{i} = {i}\n" for i in range(extra_lines))
    return f"def {name}(x):\n{body}    return -1\n"
