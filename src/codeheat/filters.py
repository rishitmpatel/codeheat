"""gitignore-style path filtering, default excludes and .codeheatignore."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

DEFAULT_EXCLUDES = """
# --- vendored / third-party / tooling ---
node_modules/
bower_components/
vendor/
vendored/
third_party/
third-party/
thirdparty/
Pods/
site-packages/
__pycache__/
.git/
.github/
.hg/
.svn/
.idea/
.vscode/
.tox/
.nox/
.venv/
*.egg-info/
# --- build output ---
dist/
build/
coverage/
htmlcov/
.next/
.nuxt/
# --- lockfiles ---
package-lock.json
npm-shrinkwrap.json
yarn.lock
pnpm-lock.yaml
bun.lockb
poetry.lock
pdm.lock
uv.lock
Pipfile.lock
Cargo.lock
go.sum
composer.lock
Gemfile.lock
Podfile.lock
mix.lock
pubspec.lock
flake.lock
packages.lock.json
gradle.lockfile
*.lock
# --- minified / bundled / maps ---
*.min.js
*.min.mjs
*.min.css
*-min.js
*.bundle.js
*.map
# --- generated code ---
*_pb2.py
*_pb2_grpc.py
*_pb2.pyi
*.pb.go
*.pb.cc
*.pb.h
*_generated.*
*.generated.*
*.gen.go
*_gen.go
*.g.dart
*.freezed.dart
*.designer.cs
*.Designer.cs
*.snap
__snapshots__/
*.pbxproj
# --- binaries, media, data blobs ---
*.png
*.jpg
*.jpeg
*.gif
*.ico
*.icns
*.bmp
*.webp
*.svg
*.pdf
*.zip
*.gz
*.tgz
*.bz2
*.xz
*.7z
*.tar
*.jar
*.war
*.class
*.pyc
*.pyo
*.so
*.dll
*.dylib
*.exe
*.o
*.a
*.bin
*.woff
*.woff2
*.ttf
*.eot
*.otf
*.mp3
*.mp4
*.mov
*.wav
*.ogg
*.webm
*.sqlite
*.sqlite3
*.db
*.psd
*.docx
*.xlsx
*.pptx
*.pickle
*.pkl
*.npy
*.parquet
*.csv
*.tsv
*.po
*.pot
*.mo
# --- changelog-style files that change with every release / PR ---
CHANGELOG*
CHANGES*
HISTORY*
NEWS*
RELEASES*
AUTHORS*
CONTRIBUTORS*
"""


def _glob_to_regex(glob: str) -> str:
    out = []
    i, n = 0, len(glob)
    while i < n:
        c = glob[i]
        if c == "*":
            if glob[i : i + 2] == "**":
                i += 2
                if glob[i : i + 1] == "/":
                    i += 1
                    out.append("(?:.*/)?")
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = glob.find("]", i + 2)
            if j == -1:
                out.append(re.escape(c))
            else:
                body = glob[i + 1 : j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j
        elif c == "\\" and i + 1 < n:
            i += 1
            out.append(re.escape(glob[i]))
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


class _Rule:
    __slots__ = ("rx", "negate", "dir_only")

    def __init__(self, line: str, ci: bool = False):
        self.negate = line.startswith("!")
        if self.negate:
            line = line[1:]
        self.dir_only = line.endswith("/")
        line = line.rstrip("/")
        anchored = "/" in line
        line = line.lstrip("/")
        body = _glob_to_regex(line)
        self.rx = re.compile(("" if anchored else "(?:.*/)?") + body + r"\Z", re.I if ci else 0)

    def matches(self, path: str, is_dir: bool) -> bool:
        if self.dir_only and not is_dir:
            return False
        return self.rx.match(path) is not None


def parse_rules(lines, ci: bool = False) -> list[_Rule]:
    rules = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        line = line.rstrip() if not line.endswith("\\ ") else line
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rules.append(_Rule(line.strip(), ci))
    return rules


class PathFilter:
    """Decides whether a repo-relative path is analysed.

    Semantics follow .gitignore: last matching rule wins, negation with ``!``,
    a path is ignored when any parent directory is ignored.
    """

    def __init__(
        self,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        default_excludes: bool = True,
        ignore_file: Path | None = None,
    ):
        rules: list[_Rule] = []
        if default_excludes:
            rules += parse_rules(DEFAULT_EXCLUDES.splitlines(), ci=True)
        if ignore_file is not None and ignore_file.is_file():
            try:
                rules += parse_rules(ignore_file.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                pass
        rules += parse_rules(exclude or [])
        self._rules = rules
        self._include = parse_rules(include or [])
        self._dir_cache: dict[str, bool] = {}
        self._path_cache: dict[str, bool] = {}

    def _state(self, path: str, is_dir: bool) -> bool:
        ignored = False
        for r in self._rules:
            if r.matches(path, is_dir):
                ignored = not r.negate
        return ignored

    def _dir_ignored(self, d: str) -> bool:
        if not d:
            return False
        hit = self._dir_cache.get(d)
        if hit is None:
            parent = d.rpartition("/")[0]
            hit = self._dir_ignored(parent) or self._state(d, True)
            self._dir_cache[d] = hit
        return hit

    def _included(self, path: str) -> bool:
        if not self._include:
            return True
        parts = path.split("/")
        cands = ["/".join(parts[: i + 1]) for i in range(len(parts))]
        for k, cand in enumerate(cands):
            is_dir = k < len(cands) - 1
            for r in self._include:
                if r.matches(cand, is_dir) and not r.negate:
                    return True
        return False

    def accepts(self, path: str) -> bool:
        hit = self._path_cache.get(path)
        if hit is None:
            hit = (
                self._included(path)
                and not self._dir_ignored(path.rpartition("/")[0])
                and not self._state(path, False)
            )
            self._path_cache[path] = hit
        return hit


@lru_cache(maxsize=None)
def top_component(path: str) -> str:
    """Architectural 'module' of a path, used to flag cross-directory coupling.

    First directory component; for conventional source roots (``src/``,
    ``lib/``, ``packages/`` ...) the first two components.
    """
    parts = path.split("/")
    if len(parts) == 1:
        return "."
    if parts[0] in ("src", "lib", "libs", "packages", "pkg", "apps", "app", "source", "modules", "crates", "internal", "cmd") and len(parts) > 2:
        return parts[0] + "/" + parts[1]
    return parts[0]
