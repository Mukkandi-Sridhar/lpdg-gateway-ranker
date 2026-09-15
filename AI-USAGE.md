# AI usage

<!-- TODO(Sridhar): rewrite this file in your own words before hand-in, and delete this line. -->

## Tools used

- **Claude (chat):** understanding the brief and both FAQ rounds, and a first exploratory look
  at the data. TODO(Sridhar): confirm and state plainly that you uploaded the challenge
  dataset zip to Claude chat for this exploration.
- **Claude Code:** pair-programming in this repository. It wrote first drafts of the loader,
  rankers, pipeline, API, tests, Docker files and documentation, and ran the scripts and tests. I reviewed,
  questioned and changed them. The ranking formula, the episode rule and the Part 2 area were
  my decisions, made when Claude Code asked.

## What I did myself

TODO(Sridhar): for example, chose the score formula and weights, decided silence only
counts for in-service gateways, chose episode-aware suppression over a fixed cooldown,
reviewed every file, rewrote DECISIONS.md and LIMITATIONS.md, recorded the video.

## One thing AI got wrong that I caught

TODO(Sridhar): pick ONE and describe it in your own words. The running log is in
`notes/ai-mistakes.md`. The strongest candidates are:

1. **"30 silent gateways the baseline cannot see" was false.** The AI repeated this claim
   from my prep notes and wrote it into a test docstring. Our own comparison script then
   showed we picked 0 fully dark gateways. A breakdown found every zero-row gateway was not
   yet installed or already decommissioned. The real blind spot is partial silence.
2. **Episode suppression blocked real faults.** The AI's first version treated a
   low-evidence filler pick as the start of a fault. The end-to-end test caught it, because
   a gateway that went dark the week after a filler pick was never ranked. Fixed, and kept
   as `tests/test_regression_filler_pick.py`.
3. **Output files were owner-only.** Atomic writes via `tempfile.mkstemp` left
   `predictions.csv` with mode 0600. I spotted it in `ls -la` after the Docker run.
4. **Units guessed from one gateway.** The AI called `avg_uptime` centiseconds from one gateway, then
   seconds from one fleet-wide median. A per-gateway check showed both: the unit depends on firmware.
