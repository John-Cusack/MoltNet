# Nest Economy Implementation — Blockers

Date: 2026-09-11
Executor: GLM 5.3 Flash (per plan)

## Blocker: root-suite gate `uv run pytest tests/ -q` cannot complete green in this environment

Two pre-existing, independent defects. Neither involves any whitelisted file;
both reproduce on the untouched tree. The whitelist forbids editing the
implicated files, so per the failure protocol they are recorded here
unmodified.

### 1. Unbounded live-LLM integration test (collection position #103)

- `tests/test_colony_run.py::test_colony_3_bots_20_cycles` runs a real
  3-bot x 20-cycle colony through the live Gateway (`await run_colony()`).
- Its comment says "marked as integration, skipped by default", but the skip
  is not wired up: `pytest.mark.integration` is unregistered and nothing
  deselects it (PytestUnknownMarkWarning at collection).
- `@pytest.mark.timeout(600)` is inert — pytest-timeout is not installed
  (PytestUnknownMarkWarning at collection), so the test runs unbounded.
- Live process evidence during the hang: pytest in `epoll_wait` (wchan
  `ep_poll`), two `CLOSE-WAIT` sockets to 127.0.0.1:8080 (Recv-Q 1) — the
  Gateway closed the connections mid-request and the test's HTTP client has
  no read timeout. ~24s CPU accumulated over ~2h elapsed.
- Position proof: pytest collection order has exactly 102 tests before it
  (14 test_analyzer + 14 test_backends + 38 test_bot_lifecycle + 17
  test_brain + 19 test_colony_integration); both interrupted runs stopped at
  the identical 102-test buffered-output boundary
  (`..........................ss...[13%] / .........s...`).
- Run history: baseline attempt 1 (pre-edit tree) stalled 900s at that point
  (tool deadline); a later verification run stalled ~2h at the same point and
  was killed by the operator during diagnosis (stdout was block-buffered, so
  no output beyond the 102-test boundary was captured).

### 2. Deterministic env-pollution failure: `test_search_repos_enriched_disabled`

When the integration test is deselected
(`uv run pytest tests/ -q -m "not integration"`):

```
FAILED tests/test_library_search.py::TestMoltGitClientEnhancements::test_search_repos_enriched_disabled - assert not True
    client = MoltGitClient(base_url="", bot_name="bot-test")
>   assert not client.is_enabled
E   assert not True
E    +  where True = <clawdbot.moltgit_client.MoltGitClient object>.is_enabled
1 failed, 525 passed, 4 skipped, 1 deselected, 2 warnings in 32.74s
```

Causal chain (all pre-existing, none on the whitelist):

1. `tests/test_colony_run.py:34` — `os.environ.setdefault("MOLTGIT_URL",
   "http://localhost:9103")` at module import; pytest imports the module
   during collection, so the variable is set for the whole pytest process.
2. `tests/test_library_search.py:365` — expects
   `MoltGitClient(base_url="")` to be disabled (graceful-degradation path).
3. `clawdbot/moltgit_client.py:108` — `self.base_url = (base_url or
   os.environ.get("MOLTGIT_URL", "")).rstrip("/")` — empty string is falsy,
   so `or` falls through to the polluted env and the client enables itself.

Reproduced identically with `MOLTGIT_URL` unset in the launching shell
(`env -u MOLTGIT_URL ...`: same single failure), because the pollution
happens inside the pytest process. This failure exists on the untouched tree
as well; the baselines never reached it only because the suite hung at test
#103 first.

## Resolution evidence (runtime-only selections, zero files modified)

```
uv run pytest tests/ -q -m "not integration"
  -> 1 failed, 525 passed, 4 skipped, 1 deselected, 2 warnings in 32.74s

env -u MOLTGIT_URL uv run pytest tests/ -q -m "not integration"
  -> identical failure (leak is in-process)

uv run pytest tests/ -q -m "not integration" \
  --deselect tests/test_library_search.py::TestMoltGitClientEnhancements::test_search_repos_enriched_disabled
  -> 525 passed, 4 skipped, 2 deselected, 2 warnings in 32.10s
```

Every runnable pre-existing test passes; the two runtime deselections are
exactly the two pre-existing defects above. Suggested fixes (out of scope
for this plan's whitelist): register + deselect the `integration` marker (or
install pytest-timeout), and change `moltgit_client.py:108` to
`base_url if base_url is not None else os.environ.get(...)`.

All other gates (colonyos suite, substrate contracts, unpluggability, forensics
coverage, bot-side nest tests, scoped ruff) are green — see
`.agents/plans/nest-economy-report.md`.
