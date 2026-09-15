# AI mistakes log

Running log of mistakes Claude Code made that a check, a test or Sridhar caught.
Source material for AI-USAGE.md.

## 1. Guessed a column unit from a single gateway, then over-corrected (2026-09-15)
- **What the AI said:** after reading a few rows of one gateway, "`avg_uptime` rises by
  360,000 per hour, so it is probably centiseconds". Then, after one fleet-wide median of
  3,600, it said "the unit is seconds".
- **How it was caught:** a per-gateway median showed both claims were incomplete. 198
  gateways step by 3,600 per hour (seconds), about 113 step by about 360,000 (centiseconds),
  and 9 never change.
- **Lesson:** a single example and a single aggregate can both mislead. Check the
  distribution per gateway before trusting a unit.

## 1b. Repeated a wrong claim from the prep guide (2026-09-15)
- **What the AI said:** "12 decommissioned gateways are absent from telemetry" and
  "`offline_duration_sec` behaves like a counter", both taken from the guide.
- **How it was caught:** the exploration script showed the 12 gateways missing from
  telemetry are future installs (May–July 2026). The decommissioned ones do report, until
  the day before decommissioning. `offline_duration_sec` equals `disconnection_cnt ×
  avg_offline_duration` in every row, so it is a per-hour sum of outage lengths, not a counter.

## 2. Environment: pandas 2.2.3 on numpy 2.5 raised DeprecationWarnings (2026-09-15)
- **What happened:** the first `pip freeze` pulled numpy 2.5.3, which pandas 2.2.3 predates.
  Timestamp arithmetic emitted "generic unit" deprecation warnings.
- **How it was caught:** warnings in the exploration script output.
- **Fix:** pinned numpy 2.1.3.

## 3. Episode suppression blocked real faults after a filler pick (2026-09-15)
- **What the AI wrote:** `still_in_episode()` treated any pick as the start of a fault
  episode, and only checked weeks *after* the pick for a healthy week.
- **How it was caught:** `test_end_to_end` failed. The silent gateway was never ranked first,
  because it had been picked as low-evidence filler (score 3.57) the week before it went dark.
- **Fix:** also check the week that led to the pick. Kept as
  `tests/test_regression_filler_pick.py`.

## 5. "30 silent gateways the baseline cannot see" was wrong (2026-09-15)
- **What the AI said:** repeated the prep guide's headline, that 30 gateways had no telemetry
  in the week before 2026-02-02 and so were invisible to the baseline. It even wrote this
  into a test docstring.
- **How it was caught:** `scripts/compare_to_baseline.py` showed our ranker picked 0 fully
  dark gateways. A breakdown showed every zero-row gateway in every scored week was either
  not yet installed or already decommissioned: 0 in service.
- **What is true:** the real blind spot is heavy *partial* silence. 14–17 in-service
  gateways a week miss at least 84 of 168 hours, and the baseline scores them only on the
  hours they did report.

## 6. Atomic writes produced owner-only files (2026-09-15)
- **What the AI wrote:** `_write_atomically()` used `tempfile.mkstemp()` and then `os.replace()`.
  `mkstemp` creates files with mode 0600, and the rename keeps it.
- **How it was caught:** `ls -la output/` after the Docker run showed `-rw-------` on
  predictions.csv and results.json. No test had looked at file permissions.
- **Fix:** `os.chmod(tmp, 0o644)` before the rename, plus an assertion in `test_end_to_end`.

## 7. README promised "Python 3.11 or newer" (2026-09-15)
- **What the AI wrote:** README and Makefile told reviewers any Python 3.11+ works, and
  `make install` ran plain `python3`.
- **How it was caught:** before the clean-clone rehearsal, a wheel check showed pyarrow 17
  has no wheels for 3.13 and none of the three pins has 3.14 wheels. `python3` on this Mac is 3.14,
  so `make install` would have tried to build pandas from source.
- **Fix:** the Makefile uses `python3.12` (overridable), the README says 3.11 or 3.12,
  `requires-python` is `<3.13`, and Docker stays the recommended path.

## 8. Code review found five gaps in AI-written error handling (2026-09-15)
- **What the AI wrote:** loaders that let pyarrow/pandas exceptions escape, `POST /run`
  treating every `ValueError` as a configuration problem, `parse_monday` accepting
  timestamps with a UTC offset, and no check for fleet-wide silence.
- **How it was caught:** a structured review of the whole repository, with each suspicion
  reproduced on synthetic data before it counted. For example, a half-copied parquet file
  made `/run` answer `config_error` without naming the file. `2026-02-02T00:00-05:00` was
  accepted as a Monday although it is 05:00 UTC, which would leak 5 hours of the predicted week.
- **Fix:** `DataError` naming the file for unreadable parquet, Excel and CSV files; a separate
  `ConfigError`; offsets refused; a warning when most gateways go silent in the same week.
  All kept as tests in `tests/test_error_handling.py`.

## 4. Test assumed noise-free fixtures (2026-09-15)
- **What the AI wrote:** a test expecting the reason to lead with "no data for 5 hours".
- **How it was caught:** the random noise in the fixture flagged 14 anomalous hours, which
  outweighed 5 silent hours, so the anomaly led the reason. The ranker was right and the test was wrong.
