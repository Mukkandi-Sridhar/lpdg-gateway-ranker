# Decisions

Five choices, what else I could have done, and why I did not. Numbers come from
`scripts/explore_data.py` and `scripts/compare_to_baseline.py` on the delivered data.

---

## 1. Part 2 area: B — Software development

**Chose:** a REST API around the ranking, with real tests, a swappable ranker, deliberate
error handling and documentation.

**Alternatives:**
- **E, Machine learning.** Rejected because the bundle has no ground truth to beat the
  baseline on cost honestly. `field_visits.csv` only covers gateways someone already
  suspected, and 390 of its 642 visits found no fault. A model trained on it would learn
  who gets suspected, not who is broken, and I could not show otherwise in the time available.
- **A, Data engineering.** A close second, because this data really does fight back.
  Rejected because the software bullets match what I can build and defend live best: I
  have shipped FastAPI services, and "add something to the API" is the kind of change I can make with people watching.

**Cost:** my ranking is a hand-set rule, not a validated model. I state what it cannot
prove in LIMITATIONS.md instead of claiming it beats the baseline.

## 2. What "needs a visit" means: silence plus unusual behaviour, scored 0–100

**My definition:** a gateway needs a visit when it is in service and, in the 7 days before
Monday, it stopped delivering data, or behaved unusually compared with its own normal.
Also, it must not already have been visited for the same fault.

**Score:** 0–100 risk points = `50 × silence + 50 × anomaly`.
- *silence* = hours with no telemetry in the last 7 days ÷ 168
- *anomaly* = hours where disconnections, offline time or reboots were more than 3 standard
  deviations above the gateway's own mean ÷ 168, capped at 1. "Own mean" is measured on days
  8–28 before Monday.

A reason starts with `Low evidence – filling slot:` when the score is under 10. In the
delivered data no pick fell under 10, but the 15th pick in the last weeks sits at 10.4–10.7,
so ranks near 15 are close to what I would not dispatch.

**Why silence:** a gateway that stops reporting is the loudest sign that its meters are not
being read, which is the cost the brief describes. `baseline_3sigma.py` scores only rows
that exist, so silence is invisible to it. In every scored week, 14–17 in-service gateways
missed at least 84 of their 168 hours. Only 29 of our 120 picks are also baseline picks,
and in most weeks 11–14 of our 15 are driven by silence.

**Why days 8–28 for "normal":** the baseline measures normal over the full 28 days,
*including* the week it is judging. A fault that fills that whole week raises its own mean
and hides itself. `test_fault_filling_the_whole_week_is_not_hidden_by_its_own_normal`
covers this.

**Alternatives rejected:**
- **Baseline unchanged.** This is the intended path for this area, and I kept it available
  as `RANKER=baseline`. I did not make it the default because of the silence blind spot.
  Its re-picks are the other reason: it repeated 39 picks from the previous week, visits
  that the scorer credits nothing for.
- **Treat all silence as a fault.** Rejected: 24–42 gateways a week have no rows at all, and
  *every one* is not yet installed or already decommissioned. So silence only counts for
  gateways in service, from their install date, that have reported before.
- **Meter-read drop as a third signal.** Rejected: `meter_read_success.csv` ends at the week
  of 2026-01-26. For all 8 scored weeks it would be the same stale number.
- **Engineer review ("Schlecht") as a boost.** Rejected: it is one person's opinion on one
  day, usable only from 2026-02-16, and LPDG says it is not the answer key.

**What it costs / how it can be wrong:**
- Silence cannot tell a broken gateway from a dead SIM or a site power cut. Both may still need a visit, but not the same one.
- I checked for network-wide causes: in Jan–Mar, 0 of 540 region-days had fewer than
  half their usual rows, so silence looks gateway-level. Below region level I cannot check.
- A normal gateway misses about 13 hours a week (median), and 19–22% of in-service
  gateway-weeks miss 34 hours or more. So a score of 10 is only just above normal gaps.
- The 50/50 weights are a judgement, not fitted.

## 3. Repeat picks are suppressed per fault episode

**Chose:** once a gateway is picked, it is not picked again until a week from that pick
onward scores under 10, which counts as a healthy week. After that, a new fault can be picked.

**Why:** LPDG's scorer credits only the first visit in a run of faulty weeks. Another pick
in the same run costs €380 and a slot, and saves nothing. Our imaginary visits do not change
the telemetry, so a gateway still looks broken the week after we "visit" it. Without
suppression, the same gateways would fill the list every week.

**Alternatives rejected:**
- **Allow repeats** (the baseline): 39 wasted repeat picks over 8 weeks.
- **A fixed 1- or 2-week cooldown:** simpler, but after the cooldown it re-picks a gateway
  whose single fault is still running, which is exactly the visit the scorer does not credit.

**A bug this decision had, found by a test:** at first only weeks *after* the pick were
checked. A gateway picked as low-evidence filler, which went dark the following week, was
treated as "already visited" and never picked. Fixed by also checking the week that led to
the pick. Kept as `tests/test_regression_filler_pick.py`.

**What it costs:** if a real visit did *not* fix the gateway, we never flag it again inside
the window. By week 8, 62 gateways are held back this way. Some of those are chronically
silent gateways that a visit may not fix.

## 4. The API serves materialised results; POST /run rebuilds them from disk

**Chose:**
- `POST /run` re-reads `data/`, ranks every week, and writes `predictions.csv` and
  `output/results.json` atomically: temporary files, then rename.
- GET requests read `results.json`, and re-read it only when the file changes.
- One run at a time: a second call gets 409.
- A failed run leaves the old results served.
- Rankings extend past the 8 scored weeks to every Monday the telemetry fully covers, so a
  new month moves "this week's 15" forward while `predictions.csv` keeps its 8 weeks.

**Alternatives rejected:**
- **Compute on every request.** Always fresh, but every GET would read 1.4 million rows
  (about 4 s) for data that changes weekly.
- **Load data once at start-up.** Rejected because new months would need a restart,
  which the live session explicitly tests against.
- **Async `/run` with a job ID.** More moving parts for a run that takes about 4 seconds and
  happens once a week. It is the first thing I would add if runs got slow (LIMITATIONS.md).
- **A `week` parameter on `/run`.** A single-week run cannot see which gateways earlier
  weeks already picked, and the episode rule needs that history. Rebuilding everything in
  about 4 s is simpler and always consistent.

**What it costs:** answers are only as fresh as the last run; `GET /health` reports `stale` when
the telemetry months on disk differ from those in the last run. `/run` blocks its caller for about 4 s.

## 5. One cutoff, Monday 00:00 UTC, applied to every file through one function

**Chose:** `Dataset.before(monday)` cuts every file with the same rule, "strictly before
Monday 00:00 UTC":
- telemetry on `ts_utc`
- meter reads on `week_start`, so the predicted week's row is excluded
- field visits on `requested_on`, with the outcome hidden until `visited_on` has passed
- the engineer review on `reviewed_on`, so it appears only from 2026-02-16

Rankers receive already-cut data and cannot see the future. `test_before_applies_one_cutoff_to_every_file`
checks every file.

**Alternative rejected:** Europe/Berlin midnight. It is equally defensible, but it differs
by only 1–2 hours, and UTC is what `baseline_3sigma.py` uses. Mixing the two across files is
the bug LPDG says they look for, so there is one function and no second rule.

**What it costs:** up to 2 hours of Sunday-evening Berlin data are left out of each week.

---

## Data problems found and what I did

| Found | Evidence | What I did |
|---|---|---|
| Missing hours are absent rows, not blanks | 23.5% of the 1,866,240 gateway-hours have no row; no nulls in any column | Counted absent hours as silence, only when silence is meaningful (§2) |
| Exact duplicate rows | 6,547 rows, all identical copies (0 conflicting) | Dropped, and counted in the run summary; conflicting copies would be logged separately |
| Two ID formats | Telemetry and meter reads `0639EA…`; master, visits and review `06:39:EA:…` | Normalised everything to 12 uppercase hex at load |
| `gateway_master.csv` is Latin-1 | UTF-8 read fails on `Außenmast` | Read UTF-8, fall back to Latin-1 |
| 12 master gateways never report | They have `installed_on` dates from May to July 2026, after the data ends | Not eligible before their install date |
| Decommissioned gateways | 12, decommissioned 2025-09-22 to 2026-02-25; each reports until the day before | Not eligible from that date; the baseline picked one in the week it was removed |
| `offline_duration_sec` is not an hourly amount | Up to 726,642 in one hour; it equals `disconnection_cnt × avg_offline_duration` in every row | Treated as the total length of disconnections logged in that hour; the data dictionary's word "counter" is misleading |
| `avg_uptime` units differ by firmware | 198 gateways step 3,600 per hour, about 113 step 360,000, 9 never change; centiseconds only on firmware 3.x | Not used |
| `rx_nr_pkts` outliers | median 30, 99th percentile 60, max 140,852 | Not used |
| Meter reads end early | Last week is 2026-01-26 | Not used as a signal (§2) |
| Field visits are a biased sample | Only suspected gateways; 390 of 642 found nothing | Not used as labels |
