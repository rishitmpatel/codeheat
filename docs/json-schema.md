# codeheat JSON output (`--json out.json`)

`schema_version: 1`. Fields are only ever added within a schema version; a breaking change bumps the number.
Timestamps are ISO-8601 UTC (`2026-10-07T14:02:54Z`). Ratios (`*_pct`, `*_share*`, `degree`, `*_norm`, `score`) are floats in `[0, 1]`.
Paths are repo-relative, POSIX style, and use the **name at the tip of the analysed branch** (renames inside the window are followed).

```jsonc
{
  "schema_version": 1,
  "tool":   { "name": "codeheat", "version": "0.1.0" },
  "generated_at": "2026-10-27T07:20:00Z",
  "repo":   { "name": "flask", "path": "/abs/path", "branch": "main", "head": "<40-hex sha>", "head_date": "..." },
  "window": { "since": "...", "until": "..." },
  "settings": { ... },        // effective thresholds, see below
  "summary":  { ... },
  "findings": [ ... ],        // prioritised, plain language
  "files": [ ... ],           // every source file at the tip (see "File record")
  "directories": [ ... ],     // ownership per directory (depth <= 2) and the root
  "coupling": { ... },
  "authors": [ ... ],
  "trends": [ ... ],          // complexity over time for the top hotspots
  "activity": [ ... ],        // commits per month
  "timings": { ... }          // seconds per phase + cache statistics
}
```

## `settings`
`include`, `exclude` (user globs), `default_excludes` (bool), `min_shared`, `min_degree`, `max_commit_files`,
`inactive_months`, `ccn_threshold`, `include_bots`, `changed_only`, `ignore_bulk`, `trend_points`,
`partial_clone` (bool: true when the repo is a `--filter=blob:none` clone; line counts were then skipped).

## `summary`
| field | meaning |
|---|---|
| `commits` | non-merge commits in the window (the denominator of every `commit_pct`) |
| `authors`, `bots` | distinct people after identity normalisation; bots counted separately and excluded from knowledge metrics unless `--include-bots` |
| `files_changed` | distinct files (any type, existing at the tip, passing filters) touched in the window |
| `code_files`, `code_files_changed` | source files measured / of those, changed in the window |
| `total_loc`, `total_ccn` | sums over measured source files (`total_ccn` excludes indentation-proxy files) |
| `hotspots` | number of files with `score >= 0.25` |
| `inactive_main_author_files` | changed files whose main author has not committed for `inactive_months` |
| `single_author_files` | changed files with `bus_factor == 1` |
| `repo_bus_factor`, `repo_main_author`, `repo_main_author_share` | bus factor of the whole analysed tree |
| `bulk_commits_ignored_for_coupling` | commits touching more than `max_commit_files` files |
| `bulk_commits_dropped` | commits dropped from *all* analyses by `--ignore-bulk` |

## `findings[]`
`priority` (1 = most important), `severity` (`high` `medium` `low` `info`), `category`
(`hotspot` `trend` `coupling` `knowledge` `info`), `title` (one-sentence summary), `detail`, `files` (paths involved), `score` (category-specific sort key).

## File record (`files[]`)
Sorted by hotspot rank, then LOC. Files not changed in the window are present (they have `commits: 0`, `rank: null`, `score: 0`) unless `--changed-only`.

| field | meaning |
|---|---|
| `path`, `language` | extension without dot (or lower-cased file name) |
| `commits`, `commit_pct` | non-merge commits touching the file in the window, and share of all commits |
| `authors` | distinct (non-bot) people |
| `added`, `deleted`, `churn` | lines added / deleted / their sum, summed over the window |
| `loc`, `nloc` | physical lines at the tip; non-comment non-blank lines (lizard) |
| `ccn` | **complexity**: sum of cyclomatic complexity of all functions (lizard). For `complexity_kind: "indent_proxy"` it is `round(sum(indent levels) / 8)` |
| `ccn_max`, `ccn_avg`, `functions` | max / mean function CCN and function count (0 for proxy files) |
| `complexity_kind` | `"ccn"` or `"indent_proxy"` (language not parsed by lizard) |
| `functions_over_threshold`, `functions_over_30` | functions above `ccn_threshold` / above 30 |
| `freq_norm`, `cx_norm`, `score` | normalised change frequency, normalised complexity, and their product (see below) |
| `rank` | 1-based hotspot rank among files with `score > 0`, else `null` |
| `ccn_top_pct` | "top N%" of complexity among changed files of the same `complexity_kind` |
| `last_commit` | last commit touching the file in the window |
| `main_author`, `main_author_id` | author with most **lines added** in the window (ties: commits) |
| `main_share_lines`, `main_share_commits` | the main author's share by lines added / by commits |
| `owners` | `[[author_id, share_of_lines_added], ...]`, top 5 |
| `bus_factor` | smallest number of people covering >= 50% of lines added (commits if no lines were added) |
| `main_author_last_commit`, `main_author_inactive` | last commit by the main author anywhere in the window; inactive if older than `inactive_months` before `until` |
| `worst_function` | `{name, ccn, start, end}` of the most complex function (changed files only) |
| `top_functions` | up to 8 `{name, ccn, start, end, nloc}` (only for the top 100 hotspots) |

### Hotspot score
```
norm(x)  = 0.5 * percentile_rank(x) + 0.5 * ln(1 + x) / ln(1 + max)      (0 stays 0)
score    = norm(commits) * norm(ccn)
```
Computed over source files changed in the window. Percentile ranks (ties share the mean rank) make it robust to
outliers; the log half keeps magnitude. Indentation-proxy files are ranked for complexity only among each other.

## `directories[]`
`path` (`"."` = whole tree), `depth`, `files_changed`, `files_total`, `commits` (distinct commits touching the directory),
`authors`, `loc` and `ccn` (of changed files), `max_score`, `main_author(_id)`, `main_share_lines`, `main_share_commits`,
`bus_factor`, `owners`, `main_author_last_commit`, `main_author_inactive`.

## `coupling`
```jsonc
{ "pairs": [ { "a": "x.py", "b": "y.py", "shared": 6, "revs_a": 8, "revs_b": 10,
               "degree": 0.75,      // shared / min(revs_a, revs_b)
               "jaccard": 0.5,      // shared / (revs_a + revs_b - shared)
               "strength": 4.5,     // shared * degree; the sort key
               "module_a": "src/api", "module_b": "src/db",
               "kind": "cross-module",  // same-module | cross-module | test-source | test-test | docs-source | docs-docs | config-source
               "surprising": true }],   // kind == "cross-module"
  "total_pairs": 12, "surprising_pairs": 3,
  "commits_used": 480, "commits_skipped_large": 3 }
```
`pairs` holds the top 300 by `strength`. `revs_*` count only commits used for coupling (bulk commits excluded).
Modules are the first path component, or the first two below `src/ lib/ packages/ apps/ ...`.

## `authors[]`
`id` (the identity id used by `main_author_id` and `owners`), `name`, `email`, `bot`, `commits`, `last_commit`, `inactive`.
Identities are merged via `.mailmap` (git applies it to `%aN/%aE`), case-insensitive e-mail, GitHub no-reply numeric prefixes and identical multi-word names.

## `trends[]`
`{ "path", "proxy", "change_pct", "points": [ { "t": "2026-01-01", "commit": "<8 hex>", "ccn", "loc", "nloc" } ] }`.
`trend_points` evenly spaced instants from `since` to `until`; at each, the file (under its name at that time) is read from the
newest first-parent commit before the instant and measured. Values are `null` before the file existed.
`change_pct = (last - first) / first` over the non-null points.

## `activity[]`
`{ "month": "2026-01", "commits": 12, "authors": 4 }` for every month of the window (zero-filled).

## `timings`
Seconds per phase (`git_log`, `ls_tree`, `accumulate`, `complexity`, `scoring_knowledge`, `coupling`, `trends`, `total`) and
`blobs_cached` / `blobs_computed` for the per-blob complexity cache.
