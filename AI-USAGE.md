# AI usage

## What I used

**Claude (chat).** Reading the brief and both FAQ rounds with me, and a first exploratory
look at the data. I uploaded the challenge dataset zip to that chat for the exploration.
I am declaring that plainly because FAQ round 1, section 2.2 says not to upload the dataset
to a third-party service, and I would rather state what I did than leave it in my history
unexplained. It went nowhere else: no hosted notebook, no bucket, no public repository, and
the data is in `.gitignore` from the first commit.

**Claude Code.** Pair-programming in this repository, for about a day. It wrote first drafts
of the loader, the rankers, the pipeline, the API, the tests, the Docker setup and the
documentation, and it ran the scripts, the tests and the container while I read the output.
Its commits are marked with a `Co-Authored-By` trailer, so the history shows exactly which
work it touched.

## What I decided

The choices in `DECISIONS.md` are mine, and Claude Code asked before anything that would
change which gateways get picked:

- Part 2 area: software development, not machine learning.
- What "needs a visit" means: silence plus behaviour unusual for that gateway.
- The score: 0–100 risk points, 50 for silence and 50 for anomalies, and a "low evidence"
  line at 10 points.
- Silence counts only for gateways in service that have reported before, from their install
  date onward.
- Repeat visits: suppressed per fault episode rather than a fixed cooldown.
- Rejected: the meter-read signal (the file stops at 2026-01-26) and the engineer review
  (one person, one day).
- Fleet-wide silence is reported as a warning but does not change the picks. I want to see
  that case before I let it move visits.

I also read every file I am handing in, reviewed the tests, and rewrote the documents.

## One thing it got wrong that I caught

**The claim that 30 silent gateways were invisible to the baseline.**

My prep notes said 30 gateways had no telemetry at all in the week before 2026-02-02, so
`baseline_3sigma.py` could never pick them. Claude Code accepted that, built it into the
argument for the silence signal, and even wrote it into the docstring of
`tests/test_regression_silent_gateway.py`.

It is false. When I ran `scripts/compare_to_baseline.py`, the line "our picks of fully dark
gateways (impossible for the baseline)" came out as **0**, in every week. If silence were
really the blind spot in the way we had written it, that number should have been large. The
breakdown in `scripts/decision_numbers.py` shows why: in every scored week, every gateway
with no rows at all is either not yet installed or already decommissioned. Zero of them are
in service.

The real blind spot is *partial* silence: 14 to 17 in-service gateways a week lose at least
84 of their 168 hours, and the baseline scores them only on the hours they did report. That
is still a good reason to rank on silence, but it is a different and smaller claim, and the
first version would not have survived a reviewer running the script.

I corrected `DECISIONS.md`, the test docstring, and my own mental model. The lesson I took:
an argument that sounds right needs a number attached, and the number needs a script in the
repository so anyone can re-run it. That is why `scripts/decision_numbers.py` exists.

## Other mistakes it made that were caught

The running log is `notes/ai-mistakes.md`. The ones that mattered:

- **A bug in the episode rule.** Its first version treated a low-evidence filler pick as the
  start of a fault, so a gateway that went dark the week after such a pick was never picked.
  The end-to-end test caught it; the fix is kept as `tests/test_regression_filler_pick.py`.
- **Output files were readable only by me** (mode 0600), because atomic writes went through
  `tempfile.mkstemp`. Spotted in `ls -la` after a Docker run.
- **The README promised "Python 3.11 or newer"**, but the pinned pyarrow has no wheels for
  3.13 and none of the pins have 3.14 wheels, which is what `python3` is on my machine.
- **Column units guessed from one gateway.** It called `avg_uptime` centiseconds from a
  single gateway, then seconds from a single fleet-wide median. A per-gateway check showed
  the unit depends on firmware.
- **Five error-handling gaps** found in a full review of the repository, including a
  half-copied parquet file being reported as a settings problem instead of a data problem.
  Each one now has a test in `tests/test_error_handling.py`.
