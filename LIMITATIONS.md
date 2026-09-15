# What it cannot do

Ranked from most to least likely to cost money.

1. **It cannot prove it is cheaper than the baseline.** There is no ground truth in the
   bundle. The two lists share only 29 of 120 picks, so they cannot both be right, but I cannot say
   which one saves more. Everything in DECISIONS.md is reasoning plus data checks, not a measured cost.

2. **Silence cannot tell *why* a gateway went quiet.** A failing gateway, a dead SIM, a
   power cut at the site and a gap in LPDG's own monitoring all look the same. There is no
   region-wide gap (0 of 540 region-days below half their usual rows), but a problem shared by one building or
   one mobile cell would still send a technician to each gateway in it. A gap across most of the fleet is flagged as a
   warning (run summary and `GET /health`), but it does not change the picks.

3. **The weights and the "low evidence" line are judgement, not fitted.** Silence dominates:
   in most weeks 11–14 of the 15 picks are driven by it. The line of 10 points is only
   just above normal gaps (19–22% of gateway-weeks miss 34 or more hours), and the 15th pick in
   the last weeks sits at 10.4–10.7.

4. **A fault that survives a visit is never flagged again in the window.** Episode
   suppression assumes the visit fixed it. By week 8, 62 gateways are held back this way,
   including chronically silent ones a visit may not fix.

5. **New gateways get no anomaly signal in their first weeks.** "Normal" is measured on
   days 8–28 before Monday. A gateway installed in the last 8 days has no reference rows, so
   only silence can flag it.

6. **Meter reads, field visits and the engineer review are loaded but not used for ranking.**
   Meter reads stop at 2026-01-26, visits are a biased sample, and the review is one opinion on
   one day.

7. **`POST /run` rebuilds everything and blocks its caller** for about 4 s (about 5 s in Docker). This is fine for one run a
   week; with several years of telemetry it would need to be incremental.

8. **A flat reference means any rise counts.** If a metric never moved in days 8–28 (std 0),
   any rise in the last week counts as unusual. This catches a first-ever reboot, but also
   flags a single harmless blip. The baseline does the opposite and ignores such metrics.

# What two more weeks would fix

In order. Each item says what it buys, what it needs, and how I would know it worked.

1. **Check silence against meter reads (3 days).** For August to January, test whether a
   gateway silent 84+ hours in week *k* reads fewer meters in week *k+1* than one that was not.
   - *Buys:* evidence that silence costs €600, plus data-based weights and a better low-evidence line.
   - *Needs:* only data already in the bundle.
   - *Worked if:* picks show a clearly larger read-rate drop than non-picks, measured on
     later weeks than the ones used to set the weights.

2. **Re-flag long faults (1 day).** Let a suppressed gateway back in after 3 weeks
   still broken, with a reason like "still silent 3 weeks after the visit".
   - *Buys:* stops a visit that did not fix the gateway from hiding it for the whole window.
   - *Trade-off:* one extra €380 visit against €600 for every further week it stays broken.
   - *Worked if:* a test with a 6-week fault picks it in week 1 and again in week 4.

3. **Group silence by site (2 days).** When several gateways at the same site type and
   region go quiet in the same hours, rank the group once and say so in the reason.
   - *Buys:* fewer technicians sent to the same underlying problem.
   - *Worked if:* the week's picks contain fewer gateways that went silent at the same hour.

4. **Incremental `/run` with a job ID (2–3 days).** Cache each week's signals by the months
   they depend on, and return `202` with `GET /runs/{id}` for status.
   - *Buys:* runs stay fast as the data grows, and callers are not blocked.

**Not fixable in two weeks:** measuring the real cost. That needs visit outcomes from
*these* picks fed back into the pipeline, which only time and the field team can provide.
