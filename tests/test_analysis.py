"""End-to-end metric tests over scripted synthetic repositories."""

from __future__ import annotations

import json

import pytest

from codeheat.analyze import analyze
from conftest import py_func

ALICE = "Alice <alice@example.com>"
BOB = "Bob <bob@example.com>"
CAROL = "Carol <carol@example.com>"


def files_by_path(rep):
    return {f["path"]: f for f in rep["files"]}


def test_hotspot_metrics_exact(repo, cfg):
    repo.commit({"a.py": py_func("f", 3)}, ALICE, "2025-02-01T10:00:00")  # 8 lines
    repo.commit({"a.py": py_func("f", 3) + py_func("g", 1)}, BOB, "2025-02-02T10:00:00")  # +4 lines
    repo.commit({"a.py": py_func("f", 4) + py_func("g", 1)}, ALICE, "2025-02-03T10:00:00")  # +2 -0
    repo.commit({"b.py": py_func("h", 0)}, ALICE, "2025-02-04T10:00:00")
    rep = analyze(cfg(repo))
    assert rep["summary"]["commits"] == 4
    a = files_by_path(rep)["a.py"]
    assert (a["commits"], a["authors"]) == (3, 2)
    assert (a["added"], a["deleted"]) == (8 + 4 + 2, 0)
    assert a["loc"] == 14
    # f has 4 branches -> CCN 5; g has 1 branch -> CCN 2
    assert (a["ccn"], a["ccn_max"], a["functions"]) == (7, 5, 2)
    assert a["complexity_kind"] == "ccn"
    assert a["commit_pct"] == 0.75
    b = files_by_path(rep)["b.py"]
    assert (b["commits"], b["ccn"]) == (1, 1)
    # the more-changed, more-complex file ranks first
    assert a["rank"] == 1 and a["score"] > b["score"] > 0
    assert 0 < a["freq_norm"] <= 1 and 0 < a["cx_norm"] <= 1
    assert a["score"] == pytest.approx(a["freq_norm"] * a["cx_norm"], abs=1e-3)
    assert a["top_functions"][0]["name"] == "f" and a["top_functions"][0]["ccn"] == 5


def test_window_filters_commits(repo, cfg):
    repo.commit({"a.py": py_func("f", 1)}, ALICE, "2024-06-01T10:00:00")
    repo.commit({"a.py": py_func("f", 2)}, ALICE, "2025-02-01T10:00:00")
    repo.commit({"a.py": py_func("f", 3)}, ALICE, "2026-02-01T10:00:00")
    rep = analyze(cfg(repo))
    assert rep["summary"]["commits"] == 1
    assert files_by_path(rep)["a.py"]["commits"] == 1
    rep = analyze(cfg(repo, since="2024-01-01", until="2026-12-31"))
    assert rep["summary"]["commits"] == 3


def test_merge_commits_are_not_counted(repo, cfg):
    repo.commit({"a.py": py_func("f", 1)}, ALICE, "2025-02-01T10:00:00")
    repo.git("checkout", "-q", "-b", "feat")
    repo.commit({"b.py": py_func("g", 1)}, BOB, "2025-02-02T10:00:00")
    repo.git("checkout", "-q", "main")
    repo.commit({"a.py": py_func("f", 2)}, ALICE, "2025-02-03T10:00:00")
    repo.merge("feat", "2025-02-04T10:00:00")
    rep = analyze(cfg(repo))
    assert rep["summary"]["commits"] == 3
    rep_feat = analyze(cfg(repo, branch="feat"))
    assert rep_feat["summary"]["commits"] == 2 and rep_feat["repo"]["branch"] == "feat"


def test_renames_are_followed(repo, cfg):
    repo.commit({"old_name.py": py_func("f", 2)}, ALICE, "2025-02-01T10:00:00")
    repo.commit({"old_name.py": py_func("f", 3)}, BOB, "2025-02-02T10:00:00")
    repo.commit({}, ALICE, "2025-02-03T10:00:00", mv=[("old_name.py", "pkg/new_name.py")])  # pure move
    repo.commit({"pkg/new_name.py": py_func("f", 4)}, ALICE, "2025-02-04T10:00:00")
    repo.commit({}, BOB, "2025-02-05T10:00:00", mv=[("pkg/new_name.py", "pkg/final.py")])
    repo.commit({"pkg/final.py": py_func("f", 5)}, ALICE, "2025-02-06T10:00:00")
    rep = analyze(cfg(repo))
    fs = files_by_path(rep)
    assert set(fs) == {"pkg/final.py"}
    f = fs["pkg/final.py"]
    # 4 content commits; the two pure moves are not behavioural changes
    assert f["commits"] == 4 and f["authors"] == 2
    assert rep["summary"]["commits"] == 6
    # lines added: 6 (create f/2) + 2 (->3) + 2 (->4) + 2 (->5)
    assert f["added"] == 6 + 2 + 2 + 2
    # trend follows the file back through its old names
    pts = rep["trends"][0]["points"]
    assert pts[0]["ccn"] is None  # sampled before the file existed
    assert [p["ccn"] for p in pts if p["ccn"] is not None][-1] == 6


def test_recreated_path_does_not_inherit_old_history(repo, cfg):
    repo.commit({"x.py": py_func("f", 1)}, ALICE, "2025-02-01T10:00:00")
    repo.commit({}, ALICE, "2025-02-02T10:00:00", mv=[("x.py", "y.py")])
    repo.commit({"x.py": py_func("g", 2)}, BOB, "2025-02-03T10:00:00")  # new, unrelated x.py
    repo.commit({"y.py": py_func("f", 2)}, ALICE, "2025-02-04T10:00:00")
    rep = analyze(cfg(repo))
    fs = files_by_path(rep)
    assert fs["x.py"]["commits"] == 1 and fs["x.py"]["authors"] == 1 and fs["x.py"]["main_author"] == "Bob"
    assert fs["y.py"]["commits"] == 2 and fs["y.py"]["main_author"] == "Alice"


def _coupled_repo(repo, big_noise=True):
    """x.py and y.py: 6 shared commits. x alone twice, y alone 4 more. z never with them."""
    d = 1
    def day():
        nonlocal d
        d += 1
        return f"2025-03-{d:02d}T10:00:00"
    for i in range(6):
        repo.commit({"x.py": py_func("f", i), "y.py": py_func("g", i)}, ALICE, day())
    for i in range(2):
        repo.commit({"x.py": py_func("f", 10 + i)}, ALICE, day())
    for i in range(4):
        repo.commit({"y.py": py_func("g", 10 + i)}, BOB, day())
    for i in range(3):
        repo.commit({"z.py": py_func("h", i)}, BOB, day())
    if big_noise:  # touches 60 files incl. x and y: must be ignored for coupling
        repo.commit({f"gen/f{i}.py": f"v = {i}\n" for i in range(58)} | {"x.py": py_func("f", 20), "y.py": py_func("g", 20)}, ALICE, day())


def test_coupling_exact_and_bulk_commits_ignored(repo, cfg):
    _coupled_repo(repo)
    rep = analyze(cfg(repo))
    cp = rep["coupling"]
    assert cp["commits_skipped_large"] == 1
    assert len(cp["pairs"]) == 1
    p = cp["pairs"][0]
    assert (p["a"], p["b"]) == ("x.py", "y.py")
    assert p["shared"] == 6  # the 7th shared commit is the 60-file bulk commit
    assert (p["revs_a"], p["revs_b"]) == (8, 10)  # bulk commit excluded from revisions too
    assert p["degree"] == pytest.approx(6 / 8)  # shared / min(revs)
    assert p["jaccard"] == pytest.approx(6 / 12)
    assert p["kind"] == "same-module" and not p["surprising"]
    # With the bulk commit allowed it would count
    rep2 = analyze(cfg(repo, max_commit_files=100))
    assert rep2["coupling"]["pairs"][0]["shared"] == 7


def test_coupling_thresholds(repo, cfg):
    _coupled_repo(repo, big_noise=False)
    assert analyze(cfg(repo, min_shared=7))["coupling"]["pairs"] == []
    assert analyze(cfg(repo, min_degree=0.8))["coupling"]["pairs"] == []
    assert len(analyze(cfg(repo, min_shared=6, min_degree=0.6))["coupling"]["pairs"]) == 1


def test_cross_module_coupling_is_surprising_but_tests_are_not(repo, cfg):
    for i in range(6):
        repo.commit(
            {
                "api/routes.py": py_func("r", i),
                "db/models.py": py_func("m", i),
                "tests/test_api.py": py_func("t", i),
            },
            ALICE, f"2025-03-{i+1:02d}T10:00:00",
        )
    rep = analyze(cfg(repo))
    kinds = {(p["a"], p["b"]): p for p in rep["coupling"]["pairs"]}
    assert kinds[("api/routes.py", "db/models.py")]["surprising"] is True
    assert kinds[("api/routes.py", "db/models.py")]["kind"] == "cross-module"
    assert kinds[("api/routes.py", "tests/test_api.py")]["kind"] == "test-source"
    assert kinds[("api/routes.py", "tests/test_api.py")]["surprising"] is False
    assert rep["coupling"]["surprising_pairs"] == 1
    assert any(f["category"] == "coupling" and "api/routes.py" in f["title"] for f in rep["findings"])


def test_knowledge_shares_bus_factor_and_inactivity(repo, cfg):
    # 90 lines by Alice, 10 by Bob in big.py; then Carol & Bob keep the repo alive
    repo.commit({"big.py": "".join(f"a{i} = {i}\n" for i in range(90))}, ALICE, "2025-01-10T10:00:00")
    repo.commit({"big.py": "".join(f"a{i} = {i}\n" for i in range(90)) + "".join(f"b{i} = {i}\n" for i in range(10))}, BOB, "2025-01-11T10:00:00")
    # three-way file 40/35/25
    repo.commit({"tri.py": "".join(f"a{i} = 1\n" for i in range(40))}, ALICE, "2025-01-12T10:00:00")
    repo.commit({"tri.py": "".join(f"a{i} = 1\n" for i in range(40)) + "".join(f"b{i} = 1\n" for i in range(35))}, BOB, "2025-01-13T10:00:00")
    repo.commit({"tri.py": "".join(f"a{i} = 1\n" for i in range(40)) + "".join(f"b{i} = 1\n" for i in range(35)) + "".join(f"c{i} = 1\n" for i in range(25))}, CAROL, "2025-01-14T10:00:00")
    # Bob stays active until Nov, Carol until Dec; Alice's last commit is January
    repo.commit({"other.py": "x = 1\n"}, BOB, "2025-11-01T10:00:00")
    repo.commit({"other.py": "x = 2\n"}, CAROL, "2025-12-15T10:00:00")
    rep = analyze(cfg(repo))
    fs = files_by_path(rep)
    big = fs["big.py"]
    assert big["main_author"] == "Alice"
    assert big["main_share_lines"] == pytest.approx(0.9)
    assert big["main_share_commits"] == pytest.approx(0.5)
    assert big["bus_factor"] == 1 and big["authors"] == 2
    assert big["owners"][0] == [big["main_author_id"], 0.9]
    assert big["main_author_inactive"] is True  # Alice silent > 6 months before 2025-12-31
    tri = fs["tri.py"]
    assert (tri["main_author"], tri["main_share_lines"], tri["bus_factor"], tri["authors"]) == ("Alice", 0.4, 2, 3)
    assert fs["other.py"]["main_author_inactive"] is False
    assert rep["summary"]["inactive_main_author_files"] == 2
    authors = {a["name"]: a for a in rep["authors"]}
    assert authors["Alice"]["inactive"] and not authors["Carol"]["inactive"]
    # configurable
    rep2 = analyze(cfg(repo, inactive_months=12))
    assert rep2["summary"]["inactive_main_author_files"] == 0
    # directory level (root)
    root = next(d for d in rep["directories"] if d["path"] == ".")
    assert root["commits"] == 7 and root["authors"] == 3
    assert any(f["category"] == "knowledge" for f in rep["findings"])


def test_mailmap_and_case_insensitive_email_merge(repo, cfg):
    (repo.path / ".mailmap").write_text("Alice Real <alice@example.com> <alice.old@corp.example>\n")
    repo.commit({"a.py": py_func("f", 1)}, "Alice Old <alice.old@corp.example>", "2025-02-01T10:00:00")
    repo.commit({"a.py": py_func("f", 2)}, "Alice Real <alice@example.com>", "2025-02-02T10:00:00")
    repo.commit({"a.py": py_func("f", 3)}, "Bobby <Bob@Example.com>", "2025-02-03T10:00:00")
    repo.commit({"a.py": py_func("f", 4)}, "Robert B <bob@example.com>", "2025-02-04T10:00:00")
    rep = analyze(cfg(repo))
    a = files_by_path(rep)["a.py"]
    assert a["authors"] == 2  # Alice (mailmap) + Bob (case-insensitive e-mail)
    assert len(rep["authors"]) == 2
    assert {x["commits"] for x in rep["authors"]} == {2}
    assert "Alice Real" in {x["name"] for x in rep["authors"]}


def test_bots_excluded_from_knowledge(repo, cfg):
    repo.commit({"a.py": "".join(f"x{i} = 1\n" for i in range(50))}, "dependabot[bot] <bot@users.noreply.github.com>", "2025-02-01T10:00:00")
    repo.commit({"a.py": "".join(f"x{i} = 1\n" for i in range(50)) + "y = 1\n"}, ALICE, "2025-02-02T10:00:00")
    rep = analyze(cfg(repo))
    a = files_by_path(rep)["a.py"]
    assert a["main_author"] == "Alice" and a["authors"] == 1 and rep["summary"]["authors"] == 1
    rep = analyze(cfg(repo, include_bots=True))
    assert files_by_path(rep)["a.py"]["authors"] == 2


def test_default_excludes_include_and_codeheatignore(repo, cfg):
    repo.commit(
        {
            "src/app.py": py_func("f", 2),
            "vendor/lib.py": py_func("v", 2),
            "web/app.min.js": "var a=1;" * 10 + "\n",
            "package-lock.json": "{}\n",
            "legacy/old.py": py_func("o", 2),
            "tests/test_app.py": py_func("t", 1),
            ".codeheatignore": "legacy/\n",
        },
        ALICE, "2025-02-01T10:00:00",
    )
    rep = analyze(cfg(repo))
    assert set(files_by_path(rep)) == {"src/app.py", "tests/test_app.py"}
    rep = analyze(cfg(repo, use_ignore_file=False))
    assert "legacy/old.py" in files_by_path(rep)
    rep = analyze(cfg(repo, default_excludes=False, use_ignore_file=False))
    assert "vendor/lib.py" in files_by_path(rep)
    rep = analyze(cfg(repo, include=["src/"]))
    assert set(files_by_path(rep)) == {"src/app.py"}
    rep = analyze(cfg(repo, exclude=["tests/"]))
    assert "tests/test_app.py" not in files_by_path(rep)


def test_unsupported_language_uses_flagged_indentation_proxy(repo, cfg):
    sh = "if a; then\n    if b; then\n        if c; then\n            echo deep\n        fi\n    fi\nfi\n" * 3
    for i in range(3):
        repo.commit({"deploy.sh": sh + f"# {i}\n", "m.py": py_func("f", 5 + i)}, ALICE, f"2025-02-0{i+1}T10:00:00")
    rep = analyze(cfg(repo))
    d = files_by_path(rep)["deploy.sh"]
    assert d["complexity_kind"] == "indent_proxy" and d["ccn"] > 0 and d["functions"] == 0
    assert files_by_path(rep)["m.py"]["complexity_kind"] == "ccn"


def test_non_code_files_take_part_in_coupling_only(repo, cfg):
    for i in range(6):
        repo.commit({"a.py": py_func("f", i), "docs/guide.rst": f"v{i}\n"}, ALICE, f"2025-02-0{i+1}T10:00:00")
    rep = analyze(cfg(repo))
    assert set(files_by_path(rep)) == {"a.py"}
    p = rep["coupling"]["pairs"][0]
    assert {p["a"], p["b"]} == {"a.py", "docs/guide.rst"} and p["kind"] == "docs-source"


def test_trends_sampling(repo, cfg):
    for i in range(1, 9):
        repo.commit({"a.py": py_func("f", i)}, ALICE, f"2025-{i+1:02d}-15T10:00:00")
    rep = analyze(cfg(repo, since="2025-01-01", until="2025-10-01", trend_points=5))
    tr = rep["trends"][0]
    assert tr["path"] == "a.py" and len(tr["points"]) == 5
    vals = [p["ccn"] for p in tr["points"]]
    assert vals[0] is None  # nothing existed on 2025-01-01
    known = [v for v in vals if v is not None]
    assert known == sorted(known) and known[-1] == 9  # f with 8 branches -> CCN 9 at HEAD
    assert tr["change_pct"] == pytest.approx((9 - known[0]) / known[0], abs=1e-3)
    act = rep["activity"]
    assert [m["month"] for m in act][0] == "2025-01" and sum(m["commits"] for m in act) == 8
    assert act[1]["commits"] == 1


def test_changed_only_and_cache(repo, cfg, tmp_path):
    repo.commit({"old.py": py_func("f", 1), "new.py": py_func("g", 1)}, ALICE, "2024-01-01T10:00:00")
    repo.commit({"new.py": py_func("g", 2)}, ALICE, "2025-02-01T10:00:00")
    rep = analyze(cfg(repo))
    assert set(files_by_path(rep)) == {"old.py", "new.py"}  # old.py unchanged but mapped
    assert files_by_path(rep)["old.py"]["commits"] == 0 and files_by_path(rep)["old.py"]["rank"] is None
    assert rep["timings"]["blobs_computed"] == 2
    rep = analyze(cfg(repo))
    assert rep["timings"]["blobs_computed"] == 0 and rep["timings"]["blobs_cached"] == 2
    assert set(files_by_path(analyze(cfg(repo, changed_only=True)))) == {"new.py"}


def test_empty_window_and_errors(repo, cfg, tmp_path):
    repo.commit({"a.py": "x = 1\n"}, ALICE, "2020-01-01T10:00:00")
    rep = analyze(cfg(repo))
    assert rep["summary"]["commits"] == 0 and rep["findings"][0]["severity"] == "info"
    from codeheat.gitlog import GitError
    import dataclasses
    with pytest.raises(GitError):
        analyze(dataclasses.replace(cfg(repo), repo=str(tmp_path / "nope")))
    with pytest.raises(GitError):
        analyze(cfg(repo, branch="does-not-exist"))


def test_findings_text_for_top_hotspot(repo, cfg):
    big = "".join(py_func(f"f{i}", 35) for i in range(2))
    for i in range(5):
        repo.commit({"src/api/routes.py": big + f"# {i}\n", "small.py": py_func("s", 1) + f"# {i}\n"}, ALICE if i % 2 else BOB, f"2025-03-0{i+1}T10:00:00")
    repo.commit({"other.py": "x=1\n"}, BOB, "2025-03-09T10:00:00")
    rep = analyze(cfg(repo))
    top = rep["findings"][0]
    assert top["category"] == "hotspot" and top["priority"] == 1
    assert top["title"].startswith("src/api/routes.py: changed in 83% of all commits, complexity 72 (top 33%), 2 functions over CCN 30")
    assert "refactor candidate #1" in top["title"]


def test_json_roundtrip_and_schema_keys(repo, cfg):
    repo.commit({"a.py": py_func("f", 2)}, ALICE, "2025-02-01T10:00:00")
    rep = analyze(cfg(repo))
    again = json.loads(json.dumps(rep))
    for k in ("schema_version", "tool", "repo", "window", "settings", "summary", "findings", "files", "directories", "coupling", "authors", "trends", "activity", "timings"):
        assert k in again
    assert again["schema_version"] == 1
