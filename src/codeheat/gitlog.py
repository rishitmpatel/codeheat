"""Single-pass git history extraction.

One ``git log --raw --numstat -z -M`` invocation yields, for every non-merge
commit: author identity (mailmap-aware via ``%aN``/``%aE``), author timestamp,
and for each touched file its status (A/M/D/R/T), rename source and the
added/deleted line counts.  Parsing is NUL based so any path is handled.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(repo: str | Path, *args: str, check: bool = True, input: bytes | None = None) -> bytes:
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=off", "-c", "log.showSignature=false", *args],
        cwd=str(repo),
        input=input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise GitError(proc.stderr.decode("utf-8", "replace").strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def repo_toplevel(path: str | Path) -> tuple[Path, str]:
    """Return (toplevel, relative-subdir-or-empty)."""
    p = Path(path).resolve()
    if not p.exists():
        raise GitError(f"path does not exist: {path}")
    try:
        top = git(p if p.is_dir() else p.parent, "rev-parse", "--show-toplevel").decode().strip()
    except GitError as exc:
        raise GitError(f"{path} is not inside a git repository") from exc
    top_p = Path(top).resolve()
    try:
        rel = p.relative_to(top_p).as_posix()
    except ValueError:
        rel = ""
    return top_p, ("" if rel == "." else rel)


def resolve_ref(repo: Path, branch: str | None) -> tuple[str, str]:
    ref = branch or "HEAD"
    out = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False).decode().strip()
    if not out:
        raise GitError(f"cannot resolve branch/ref {ref!r} (is the repository empty?)")
    name = ref
    if ref == "HEAD":
        cur = git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False).decode().strip()
        name = cur or "HEAD (detached)"
    return name, out


@dataclass
class Change:
    status: str  # A M D R T
    path: str
    old_path: str | None
    added: int
    deleted: int


@dataclass
class RawCommit:
    sha: str
    name: str
    email: str
    ts: int
    changes: list[Change] = field(default_factory=list)


LOG_FORMAT = "%x1e%H%x1f%aN%x1f%aE%x1f%at%x1f"


def read_log(repo: Path, ref_sha: str, since: datetime, until: datetime, numstat: bool = True) -> list[RawCommit]:
    """Commits newest-first, merges excluded.  ``numstat=False`` (partial clones)
    yields changes with 0/0 line counts, which avoids fetching every blob."""
    out = git(
        repo,
        "log",
        ref_sha,
        "--no-merges",
        "-M",
        "-l2000",
        "--raw",
        *(["--numstat"] if numstat else []),
        "-z",
        "--no-color",
        f"--since={since.isoformat()}",
        f"--until={until.isoformat()}",
        f"--format={LOG_FORMAT}",
    )
    return parse_log(out, numstat)


def _int(b: bytes) -> int:
    return 0 if b == b"-" else int(b)


def parse_log(data: bytes, numstat: bool = True) -> list[RawCommit]:
    commits: list[RawCommit] = []
    for chunk in data.split(b"\x1e"):
        if not chunk.strip(b"\0\n "):
            continue
        toks = chunk.split(b"\0")
        head = toks[0].split(b"\x1f")
        if len(head) < 4:
            continue
        c = RawCommit(
            sha=head[0].decode(),
            name=head[1].decode("utf-8", "replace"),
            email=head[2].decode("utf-8", "replace"),
            ts=int(head[3]),
        )
        i = 1
        raws: list[tuple[str, str | None, str, bool]] = []  # status, old, path, is_submodule
        while i < len(toks):
            t = toks[i].lstrip(b"\n")
            if not t.startswith(b":"):
                break
            f = t.split(b" ")
            status = f[4].decode()[:1] if len(f) >= 5 else "M"
            submodule = f[1] == b"160000" or f[0] == b":160000"
            if status in ("R", "C"):
                old, new = toks[i + 1].decode("utf-8", "replace"), toks[i + 2].decode("utf-8", "replace")
                raws.append((status, old, new, submodule))
                i += 3
            else:
                raws.append((status, None, toks[i + 1].decode("utf-8", "replace"), submodule))
                i += 2
        # numstat entries follow in the same order
        for status, old, path, submodule in raws:
            added = deleted = 0
            if numstat:
                if i >= len(toks):
                    break
                t = toks[i].lstrip(b"\n")
                parts = t.split(b"\t", 2)
                if len(parts) < 3:
                    i += 1
                    continue
                a, d, rest = parts
                i += 3 if rest == b"" else 1
                try:
                    added, deleted = _int(a), _int(d)
                except ValueError:
                    added = deleted = 0
            if submodule:
                continue
            if status == "T":
                status = "M"
            c.changes.append(Change(status, path, old if status in ("R", "C") else None, added, deleted))
        commits.append(c)
    return commits


@dataclass
class TreeEntry:
    path: str
    sha: str
    size: int


def list_tree(repo: Path, sha: str) -> list[TreeEntry]:
    out = git(repo, "ls-tree", "-r", "-z", "-l", sha)
    res = []
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        mode, typ, osha, size = meta.decode().split(None, 3)
        if typ != "blob" or mode == "120000":
            continue
        res.append(TreeEntry(path.decode("utf-8", "replace"), osha, int(size) if size.strip() != "-" else 0))
    return res


class BlobReader:
    """Streaming ``git cat-file --batch`` wrapper."""

    def __init__(self, repo: Path):
        self.last_sha: str | None = None
        self.p = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=str(repo),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def read(self, spec: str) -> bytes | None:
        assert self.p.stdin and self.p.stdout
        self.p.stdin.write(spec.encode("utf-8") + b"\n")
        self.p.stdin.flush()
        header = self.p.stdout.readline().split()
        self.last_sha = None
        if len(header) < 3 or header[1] != b"blob":
            return None
        self.last_sha = header[0].decode()
        size = int(header[2])
        data = self.p.stdout.read(size)
        self.p.stdout.read(1)
        return data

    def close(self) -> None:
        # Forked pool workers may inherit our stdin pipe, so closing it would not
        # deliver EOF; all reads are complete here, so just stop the process.
        try:
            self.p.kill()
            self.p.wait(timeout=5)
        except Exception:
            pass
        for stream in (self.p.stdin, self.p.stdout):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def commit_at(repo: Path, ref_sha: str, when: datetime) -> str | None:
    out = git(repo, "rev-list", "-n1", "--first-parent", f"--before={when.isoformat()}", ref_sha, check=False)
    s = out.decode().strip()
    return s or None


def promisor_remote(repo: Path) -> str | None:
    """Name of the promisor remote if this is a partial clone, else None."""
    out = git(repo, "config", "--get-regexp", r"^(remote\..*\.promisor|extensions\.partialclone)$", check=False).decode()
    for line in out.splitlines():
        key, _, val = line.partition(" ")
        if key == "extensions.partialclone" and val.strip() not in ("", "true"):
            return val.strip()
        if key.endswith(".promisor") and val.strip() == "true":
            return key[len("remote."): -len(".promisor")]
    return None


def prefetch_blobs(repo: Path, shas: list[str]) -> int:
    """In a ``--filter=blob:none`` clone, fetch the missing blobs in a few batched
    requests (git would otherwise fetch them one round-trip at a time).
    Returns the number of blobs fetched."""
    if not shas:
        return 0
    remote = promisor_remote(repo)
    if not remote:
        return 0
    out = git(repo, "rev-list", "--objects", "--no-walk", "--missing=print", "--stdin", input="\n".join(shas).encode() + b"\n", check=False)
    missing = [ln[1:] for ln in out.decode().splitlines() if ln.startswith("?")]
    for i in range(0, len(missing), 4000):
        part = missing[i : i + 4000]
        git(
            repo, "fetch", remote, "--no-tags", "--no-write-fetch-head", "--recurse-submodules=no",
            "--filter=blob:none", "--stdin", input="\n".join(part).encode() + b"\n", check=False,
        )
    return len(missing)


def blob_sha_at(repo: Path, commit: str, path: str) -> str | None:
    out = git(repo, "ls-tree", commit, "--", path, check=False).decode().split()
    return out[2] if len(out) >= 3 and out[1] == "blob" else None
