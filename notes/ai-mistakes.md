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
