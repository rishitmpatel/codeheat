from datetime import datetime, timezone

import pytest

from codeheat.complexity import analyse_source, classify
from codeheat.config import parse_when
from codeheat.filters import PathFilter, top_component
from codeheat.gitlog import parse_log
from codeheat.identity import Identities, norm_email
from codeheat.report.common import spark
from codeheat.scoring import bus_factor, normalise, pct_ranks


def test_pct_ranks_ties_share_mean_rank():
    assert pct_ranks([1, 2, 2, 4]) == [0.25, 0.625, 0.625, 1.0]


def test_normalise_zero_stays_zero_and_is_bounded():
    n = normalise([0, 1, 10, 1000])
    assert n[0] == 0 and all(0 <= x <= 1 for x in n) and n[-1] == pytest.approx(1.0)
    assert n == sorted(n)
    # outlier robustness: the 10 is not flattened to ~0 by the 1000
    assert n[2] > 0.5 * n[3] * 0.6


def test_bus_factor():
    assert bus_factor([90, 10]) == 1
    assert bus_factor([50, 50]) == 1  # 50% is enough
    assert bus_factor([40, 35, 25]) == 2
    assert bus_factor([30, 30, 20, 20]) == 2
    assert bus_factor([0, 0]) == 0


def test_parse_when():
    now = datetime(2025, 3, 31, tzinfo=timezone.utc)
    assert parse_when("2024-01-02", now) == datetime(2024, 1, 2, tzinfo=timezone.utc)
    assert parse_when("12 months ago", now) == datetime(2024, 3, 31, tzinfo=timezone.utc)
    assert parse_when("1 month ago", now) == datetime(2025, 2, 28, tzinfo=timezone.utc)
    assert parse_when("2 weeks ago", now) == datetime(2025, 3, 17, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        parse_when("whenever", now)


def test_filters_defaults_and_globs(tmp_path):
    f = PathFilter()
    for bad in ["node_modules/x/index.js", "a/vendor/b.go", "package-lock.json", "web/app.min.js", "api/x_pb2.py", "poetry.lock", "img/logo.png", "CHANGELOG.md", "sub/dist/out.js"]:
        assert not f.accepts(bad), bad
    for ok in ["src/app.py", "lib/vendorish/a.py", "README.md", "docs/index.rst"]:
        assert f.accepts(ok), ok
    ig = tmp_path / ".codeheatignore"
    ig.write_text("# c\nlegacy/\n*.gen.py\n!legacy/keep.py\n/only_root.py\n")
    f = PathFilter(ignore_file=ig)
    assert not f.accepts("legacy/a.py") and not f.accepts("x/y.gen.py") and not f.accepts("only_root.py")
    assert f.accepts("sub/only_root.py")
    f = PathFilter(include=["src/**"], exclude=["src/skip/"])
    assert f.accepts("src/a/b.py") and not f.accepts("src/skip/x.py") and not f.accepts("tests/t.py")
    assert PathFilter(default_excludes=False).accepts("node_modules/x.js")


def test_top_component():
    assert top_component("setup.py") == "."
    assert top_component("api/routes.py") == "api"
    assert top_component("src/flask/app.py") == "src/flask"
    assert top_component("src/x.py") == "src"


def test_parse_log_handles_odd_paths_and_renames():
    sep = b"\x1e"
    head = b"%s\x1fAl Ice\x1fa@x.com\x1f1700000000\x1f"
    data = (
        sep + head % b"a" * 1 + b"\x00\n:100644 100644 aaa bbb M\x00dir with space/\xc3\xa9.py\x00"
        b":100644 100644 aaa bbb R087\x00old.py\x00new name.py\x00"
        b":000000 100644 000 bbb A\x00bin.png\x00"
        b"3\t1\tdir with space/\xc3\xa9.py\x00" b"5\t0\t\x00old.py\x00new name.py\x00" b"-\t-\tbin.png\x00"
        + sep + head % b"b" + b"\x00\n"
    )
    cs = parse_log(data)
    assert [c.sha for c in cs] == ["a", "b"]
    c = cs[0]
    assert c.name == "Al Ice" and c.ts == 1700000000
    assert [(x.status, x.path, x.old_path, x.added, x.deleted) for x in c.changes] == [
        ("M", "dir with space/é.py", None, 3, 1),
        ("R", "new name.py", "old.py", 5, 0),
        ("A", "bin.png", None, 0, 0),
    ]
    assert cs[1].changes == []


def test_identity_merging():
    ids = Identities()
    ids.observe("Alice A", "Alice@X.com")
    ids.observe("alice a", "alice@x.com")
    ids.observe("Alice A", "alice@home.org")  # same full name -> same person
    ids.observe("Bob", "bob@x.com")
    ids.observe("Bob", "bob@y.com")  # single-word names are NOT merged
    ids.observe("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")
    r = ids.resolve()
    assert r.id_of("Alice A", "Alice@X.com") == r.id_of("Alice A", "alice@home.org") == r.id_of("alice a", "alice@x.com")
    assert r.id_of("Bob", "bob@x.com") != r.id_of("Bob", "bob@y.com")
    assert [p for p in r.people if p["bot"]][0]["name"] == "dependabot[bot]"
    assert norm_email("123+user@users.noreply.github.com") == "user@users.noreply.github.com"


def test_lizard_ccn_and_proxy_fallback():
    m = analyse_source("a.py", "def f(x):\n    if x:\n        return 1\n    return 2\n", "lizard")
    assert (m["ccn"], m["max"], m["nf"], m["proxy"]) == (2, 2, 1, False)
    js = analyse_source("a.js", "function g(a){ if(a&&a>1){return 1} for(;;){break} return 0 }", "lizard")
    assert js["max"] == 4
    sh = analyse_source("run.sh", "if true; then\n    echo a\n    if true; then\n        echo b\n    fi\nfi\n", "proxy")
    assert sh["proxy"] is True and sh["ccn"] >= 0
    assert classify("x.py") == "lizard" and classify("run.sh") == "proxy" and classify("README.md") is None
    assert analyse_source("a.js", "x" * 5000, "lizard") is None  # minified blob


def test_spark_does_not_exaggerate_small_changes():
    s = spark([100, 101, 102])
    assert max(s) <= "\u2585"  # a 2% drift must not reach the top block
    assert spark([None, 1, 5]) .startswith(" ")


def test_parse_log_without_numstat_for_partial_clones():
    head = b"\x1e%s\x1fA\x1fa@x.com\x1f1700000000\x1f"
    data = head % b"a" + b"\x00\n:100644 100644 aaa bbb M\x00x.py\x00:100644 100644 aaa bbb R090\x00o.py\x00n.py\x00"
    (c,) = parse_log(data, numstat=False)
    assert [(x.status, x.path, x.old_path, x.added, x.deleted) for x in c.changes] == [("M", "x.py", None, 0, 0), ("R", "n.py", "o.py", 0, 0)]
