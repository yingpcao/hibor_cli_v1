# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A trimmed, self-contained fork of `../hibor-web`: a Playwright crawler for 慧博投研资讯 (hibor.com.cn)
driven as an agent-facing CLI. Two crawl targets only — `stock` (慧搜 by name/code) and `industry`
(行业 report list) — plus the WeKnora push. No job list in config, no `classify` archiving,
no scheduling. User-facing docs, the exit-code table and the command reference live in `README.md`;
don't duplicate them here.

It ships as a **system-level command**: `pyproject.toml` (hatchling, `[project.scripts] hibor =
"hibor_cli.cli:main"`) → `uv tool install --from git+https://github.com/yingpcao/hibor_cli_v1.git
hibor-cli` (or `--from <this dir>` while developing) → `hibor` on PATH, so an agent can call it from
any cwd. That is why config is found by *search* (`--config` > `HIBOR_CONFIG` > `./config.yaml` >
`~/.hibor/config.yaml`) instead of relative to the package, and why `init`/`spec` must work with no
config at all (`spec.CONFIGLESS_COMMANDS`). `hibor spec` is the machine-readable contract; the
distributable agent skill lives in `skills/hibor-reports/` (westock-data's shape: `SKILL.md` +
`references/` + `scripts/setup.{ps1,sh,cjs}`).

**This directory is git-ignored content that must never be committed**: `config.yaml` (live WeKnora
key), `state/` (Chrome profile = the login, plus the dedup DB), `output/` (report excerpts). The
public repo therefore carries `config.example.yaml` only; check `git status` before any publish.

Verification status (2026-10-04, after the packaging pass): suite green (274 tests) and the pieces that
touch the outside world were checked against the real thing, not just fixtures.
- Noise gate: `stock list 紫金 --scope abstract --days 30` returns 50 hits, gates keep 7 / filter 43;
  `stock list 三七互娱 --days 90` (title scope) keeps all three `公司调研→财报点评→半年报点评` company
  reports and filters nothing — the no-regression proof for the default mode; the same name in abstract
  mode filters all 5 传媒周报 mentions.
- System CLI: after `uv tool install`, run from arbitrary cwds in **both** `cmd` and PowerShell —
  `hibor --version`, `hibor spec` (11 commands, `config_path` resolved from `~/.hibor`), `hibor status`
  (sees the existing corpus), `hibor doctor`, and a live `hibor stock list 紫金 --scope abstract
  --days 7 --max 5` (2 kept / 9 filtered, reasons on stderr).
- Encoding: stdout bytes are valid UTF-8 JSON everywhere (cmd redirect and Git Bash pipes both parse).
  PowerShell 5.1 alone decodes child output as GBK, so the last byte of a Chinese character pairs with the
  following `"` and eats it — `ConvertFrom-Json` then fails on *any* Chinese CLI, `westock` included. The fix
  is caller-side (`[Console]::OutputEncoding=[Text.Encoding]::UTF8` before parsing), documented in
  `CONVENTIONS`, the skill and the README; do not "fix" it by writing GBK or `\uXXXX` from the CLI.
- Skill: `setup.ps1 -Skill` (and `setup.sh`/`setup.cjs --skill`) installs and registers into
  `~/.claude/skills`, `~/.codex/skills`, `~/.pi/agent/skills`; the project copy under
  `C:\HiborAgent\.qoder\skills\hibor-reports` is picked up by Qoder's skill list.
- `push` from PATH: `--kb __probe__` returned the live KB list in its error text, and `--kb RP-小金属
  --stock 紫金 --dry-run` listed the 2 files it would upload. Still untested: a real (non-dry) `push`,
  because it writes to a shared knowledge base. And note that
  `doctor` reported `logged_in: false` for this profile while the crawl still worked: list pages and the
  excerpt are reachable without an active login, so treat exit 3 from `doctor` as "quota/full-text may be
  limited", not "nothing will work".

## Commands

```powershell
PYTHONIOENCODING=utf-8 .venv\Scripts\python.exe -m pytest -q --cov=hibor_cli --cov-report=term-missing   # ~4s, no network, no browser
PYTHONIOENCODING=utf-8 .venv\Scripts\python.exe -m hibor_cli status --failed
PYTHONIOENCODING=utf-8 .venv\Scripts\python.exe -m hibor_cli doctor            # opens real Chrome, needs a live login
PYTHONIOENCODING=utf-8 .venv\Scripts\python.exe -m hibor_cli stock list 紫金矿业 --days 30 --max 12
```

Once installed (`uv tool install <this dir>`), the same commands are `hibor status --failed`,
`hibor doctor`, `hibor stock list …` from any cwd. `pytest.ini` has no coverage settings — pass the flags
above. `tests/test_spec.py` compares `spec.py` against argparse's real `--help`, and
`tests/test_skill.py` checks that every command and flag named in `skills/hibor-reports/` is real, so
the contract and the skill package can't quietly go stale when a flag changes.

The venv is uv-managed and has **no pip**: install with
`uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt`. To re-fetch one report,
delete its row in `state/reports.db` (table `report_items`, PK `(id, grp)`).

## Architecture

`cli.py` (argparse → `Outcome` → JSON envelope + exit code) → `crawl.fetch_target` / `list_target` →
`iter_stock` or `iter_industry` picked by `Target.kind` → `relevance.list_verdict` → per item
`detail.fetch_content_html` → `to_markdown` → `relevance.body_verdict` → `save_markdown`, with
`store.Store` recording status. `weknora.py` is the offline follow-up that pushes a saved folder to a KB.

- `targets.Target` (frozen dataclass, validated in `__post_init__`) is the whole description of work;
  `Target.folder` is both output folder and dedupe scope: `个股_<name>` / `行业_<name>`, **never
  scope-suffixed**, so the same report found under two scopes is one file and one DB row. Adding a
  third target kind means a `KINDS` entry, a `Target` field, a generator with the shared signature
  `(ctx, page, target, start, end, sleep, on_page)`, and one line in `crawl._walk` — there is no
  registry dict like hibor-web's `sources.SOURCES`, on purpose.
- `relevance.py` is always on for `stock` (no opt-in flag any more) and exists because 慧搜 is a
  **tokenized** match. Four gates keyed on `Target.name` alone (no stock-code lookup): title gate
  (only when `scope == "title"`), company/industry split from `ReportMeta.subject` (`601899(紫金矿业)`
  = company, always kept; `(锡行业)`/empty = industry), **noise gate** on the 栏目 breadcrumb + title,
  body gate on the `.abstruct-info` excerpt. A code search (name `601899`) matches `is_company` via the
  subject's code column. Dropped items are stored as `filtered` (counts as handled) and do **not**
  consume `max_reports`. The noise gate only ever sees `industry` items, so a company's own
  《半年报点评》 survives; it drops 例行壳子 (晨会/早间资讯/行业数据/高频数据/日报周报, plus title
  patterns like 每日…导航 and 周度观点) unconditionally, and 定期研报/定期策略/「…点评」leaves only when
  the title does **not** name the stock — which is why `scope == "title"` results are unchanged except
  for the shells. `Target.keep_noise` (`--keep-noise`) skips the gate for triage. Under wide scopes the
  body gate is nearly a no-op — the match already happened inside the excerpt — it stays as the
  backstop for "matched in the body, not repeated in this excerpt".
- `detail.py` owns the layout: one flat folder per target, and `report_filename` = 慧博's own title with
  the leading `<券商>-` segment moved to the end (`<标的>-<代码>-<主题>-<研报日>_<券商>.md`) — no publish-date
  prefix and no id in the name, since dates/id/source belong to the frontmatter. Two *different* reports
  sharing a title (brokers reuse them) is the only case that appends `_<id8>`; `save_markdown` detects it
  by looking for the existing file's `source:` line, so re-running one report still overwrites in place.
  Also here: `folders_in` (what `push` may sweep) and `reports_in` (md files, minus `NOT_REPORTS`).
  Note that `push` dedupes by file *name*, so renaming existing files makes them re-upload.
- `session.py` launches system Chrome (`channel="chrome"`) with a persistent profile whose path comes
  from `Settings.profile_dir` (config `profile_dir`, overridable per run with `HIBOR_PROFILE_DIR`); the
  `hibor init` template writes a `chrome-profile` next to the config file, and `--profile-dir` is how you
  point the installed CLI at a profile that is already logged in. The profile is
  the session — never export cookies to another client. Only one process can hold it, hence
  `profile_in_use` → `ProfileBusyError` (exit 6) before any browser starts.
- `config.py` rejects unknown top-level keys, so a hibor-web `config.yaml` (with `jobs:`) fails loudly
  instead of silently doing nothing. `Settings` carries `state_dir`/`profile_dir`/`config_path`; there is
  no `jobs`. `resolve_config_path()` implements the search order and raises a `ConfigError` that names
  `hibor init` as the fix; `write_config()` is what `init` runs and refuses to overwrite without `--force`.
  Relative paths resolve against the config file's directory, which is what makes `~/.hibor/config.yaml`
  a self-contained workspace.
- `spec.py` holds the agent-facing contract as data: `EXIT_CODES` (error code → exit number),
  `INTERNAL_ONLY_CODES` (`empty_content` is per-report, never a process exit), `CONFIGLESS_COMMANDS`
  (`init`/`spec`, which `main` must therefore not gate on a config), `ENVELOPE`, `CONFIG`, `COMMANDS`
  (one entry per command, flags byte-for-byte identical to `--help`), `RELEVANCE_GATES`, `CONVENTIONS`.
  `hibor spec` prints it plus `version` and the resolved `config_path` (or `config_error`).
- `push` names folders via `--stock/--industry` (or sweeps `output/` when neither is given); the
  API key is env-only in this fork and `config.yaml` ships `api_key: ""`.
- Everything Playwright-facing takes injectable collaborators (`session_factory(profile_dir, headless)`,
  `fetch`, `sleep`, `now`), and tests use `tests/fakes.py` rather than a browser. Only
  `tests/fixtures/search_sa.html` is a real captured response; `industry_list.html` and
  `detail_content.html` are hand-trimmed from observed structure, so green tests do not prove the live
  markup still matches.
- Library code never `print`s; it emits through `events.Emitter`, which resolves `sys.stdout/stderr` at
  write time. stdout is JSON only, progress is stderr, and `main` reconfigures both to UTF-8 because the
  console here is GBK.

Site facts (from recon, not obvious from code):
- 慧搜 results come from `POST /newweb/HuiSou/sa` (HTML fragment, 10/page, `ys` = page, `hidTotal` =
  count), called through `ctx.request` so it rides the browser's cookies and Referer; the crawler visits
  the real `HuiSou/s` page first. `sjfw` accepts **presets only** (`-1/-3/-7` days, `1/3/6/12/24`
  months), so `pick_window` asks for the smallest preset covering the range (the one-day margin means the
  answer is usually a step wider than asked) and filters dates locally; `px=sj` = newest first. Scope
  `cxzd`: `bt` 标题 / `zy` 摘要 / `qw` 全文. Dates there are day-only. Each `.result-dataitem` has two
  `.result-data1` span rows read **positionally**: 栏目 / `601899(紫金矿业)` or `(锡行业)` / 机构 / 作者,
  then 日期 / — / 大小 / 页数 / 分享者. Column 2 is `ReportMeta.subject`, the only place the site names
  the subject stock.
- 栏目 (`ReportMeta.column`) is a `→`-joined breadcrumb and the noise gate's main signal. Segments seen
  live on 2026-10-04: `晨会早刊→晨会纪要`, `晨会早刊→早间资讯`, `港美研究→港股→晨会早刊`,
  `行业分析→行业数据→数据周报`, `期货研究→期货日报|期货周报`, `行业分析→定期研报→行业周报|月报|
  双周报|季报|半年报`, `投资策略→定期策略→策略周报`, `行业分析→行业评论→行业点评|专题报告|行业调研`,
  `行业分析→行业策略→深度策略`, `公司调研→财报点评→半年报点评`, `公司调研→公司评论→事件点评|公司快报`,
  `公司调研→公司研究→深度研究|公司分析`. Note `行业评论`/`公司评论` are **parents** of both 点评 and
  专题报告, so the gate only treats a segment *ending in* 点评/简评/快评 as a comment. Change these
  tables against a real `stock list --scope abstract` capture, not from imagination.
- The 行业 page is a POST form (`#f1_hy1`, `#f1_hy2`, `#f1_ybbt`) and the pager is another POST, so the
  crawler drives the form and clicks "下一页"; there is **no server-side date filter** (it filters
  `分享时间` and stops at the first page older than the start). `parse_industries` reads `#f1_hy1`
  options plus the `hangYe2 = eval('(...)')` blob for sub-industries. Timestamps here are second-precision.
- Detail text lands in `.abstruct-info` (an excerpt, not the PDF) after an async fill; image-only PDFs
  leave it empty → `EmptyContentError`. Watermark lines and the empty links they leave are stripped in
  `to_markdown`.
- Behind the safedog WAF, a throttled logged-in automated session gets HTTP 200 with a completely empty
  document while anonymous `curl` still gets full pages. Detected in three places, always surfaced as
  `blocked` (exit 4): `doctor`, the missing `#f1_hy1` in `iter_industry`, the missing `#hidTotal` in
  `parse_results`. Delays in `config.yaml` are deliberate — don't lower them, don't retry in a loop when
  blocked, don't strip the `safedog-flow-item` cookie.

Error model (`models.py`): `HiborError.code` is the CLI's exit-code key. `SessionError` subclasses abort
the run (`LoginRequiredError` → 3, `BlockedError` → 4, also raised after `max_consecutive_failures`);
`fetch_target` re-raises with `.partial` (a `FetchResult` of what was already done) and `cli.main` puts
`partial.to_dict()` into the envelope `data`, so non-zero exits still report completed work. Per-report
failures are stored as `failed` and retried; `EmptyContentError` and relevance drops are terminal.
WeKnora transport maps to 2 (bad request) / 3 (401/403) / 4 (unreachable, 5xx) / 5 (some files unparsed).
