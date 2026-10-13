# Validation

Use this reference before claiming a PsyNet experiment is functionally complete
or before collecting final participant-flow evidence. It owns final check
commands, evidence path conventions, and PsyNet-specific validation pitfalls. For
day-to-day backend testing strategy, use
`develop-experiment-back-end/SKILL.md`. For participant-flow Playwright, use
`playwright-testing/SKILL.md`.

## Functional checks

Run functional checks from the experiment directory:

```bash
psynet test local
psynet audit simulate
```

Do not run ``python experiment.py`` as an import or syntax check.
See `develop-experiment-back-end/SKILL.md`.

`psynet test local` is the **logic** gate: bots walk the timeline and check
answers, but they never render a layout. Participant-flow Playwright is the
**layout** gate; see "Layout checks" in `playwright-testing/SKILL.md`.
Do not treat a green bot run as evidence that pages fit the window.

`psynet audit simulate` writes `audit/simulate/analysis/simulated_export/` and marks
`simulate_export` present. Both commands accept `--n-bots N` to override
`Exp.test_n_bots` for one run.

## Performance evidence

When the work needs performance evidence, run this sustained load test after
functional checks pass. If the experiment runs async jobs, first measure their
CPU use with `plan-server-resources/SKILL.md`. Do not rely on experiment defaults such as
`test_n_bots = 1`. Use the audit-scoped route so results land in the packet
immediately. From the experiment root:

```bash
psynet audit performance-test \
  --n-bots 40 \
  --duration-minutes 5 \
  --time-factor 1.0
```

That writes `audit/artifacts/performance.json` and marks `performance_result`
present. Judge the run by median and p95 `/timeline` and `/response` times, not
by how many bots finished. Zero finished bots is expected when the window is
shorter than the experiment. If those percentiles are high, profile SQL with
`psynet test local --sql-profile` before changing the scientific policy (see
the performance-testing tutorial). Use top-level
`psynet performance-test local --json-output <path>` for a custom non-audit
file.
If the experiment customizes `run_bot`, accept the `bot` argument and
`**kwargs`, and pass that same `bot` on to `super().run_bot(bot, **kwargs)`.
`psynet performance-test`, `psynet test local --parallel` and `psynet run-bot`
all call `exp.run_bot(bot, time_factor=...)` with a new `BotDriver`. In
`performance-test` and `test local --parallel` the bots run as threads in one
process and share one experiment instance, so store per-bot traits on `bot.var`
in `initialize_bot` (the `BotDriver` has no `var`), not in globals or on
`self`, and do not call `random.seed()`.

Short smoke runs are fine for a first pass or infrastructure testing; use
top-level `psynet performance-test local` so they do not become packet evidence.
When the experiment is nearing finalizing, prefer a sustained run (and a window
on the order of the estimated duration if you want completions). Skip
an expensive re-run when a suitable `audit/artifacts/performance.json` already
exists for the current implementation.

### Choosing how many participants to run at once

```bash
psynet performance-test local --n-bots auto --json-output performance.json
```

The printed summary tables are an overview. Take exact numbers from the JSON,
not by reading values off the tables' columns.

The capacity search uses short tests in which all bots arrive together. For
experiments with async jobs (audio analysis, REPP tapping, LLM calls) or
long holds, every bot hits each job and hold at once, so the search
underestimates how many participants the server can handle. In the JSON, compare each result's `startup_phase`
and `steady_state_phase`, and read the validation test (`"confirmation": true`
in the JSON), a long run at the recommended number of participants with
spread-out arrivals. When they
disagree, trust the long run with spread-out arrivals. That run starts on
the data the search left, so if it fails after the database grew a lot,
rerun on the server with `psynet performance-test ssh --reset-database`
before recommending a lower number. Only high-priority async jobs, which participants wait for,
count against `--max-queue-p95-s`; a low-priority backlog (`queue_waits.low`
in the JSON) is only reported, but if the summary warns that it grew during
a steady state, the workers can't keep up long-term. That check uses the
validation test if there is one, otherwise the largest passing test or the
first failing one. For CPU-heavy jobs,
also work out worker throughput: one worker process keeps up with about
(session length) ÷ (job CPU time × jobs per participant) participants, with
`cpu_avg` from `async_job_stats`. If the queue fails the next count, set
`worker_greenlets_per_process = 1` and raise `worker_processes`, about one
per spare CPU core. Report how you reached the recommended number of participants.

Each search test lasts one session but at most 5 minutes, so in a longer
experiment the search only loads its first few minutes, such as consent and
instructions. If the pages that load the server most come later, consider
an abridged version of the experiment for the search, for example a copy of
the experiment directory, that reaches those pages within its first 2
minutes. Shorten or skip the light pages, such as long instructions,
practice and questionnaires, but keep the heavy pages and their work
unchanged: trial pages, uploads, async jobs and holds. Then run a long test
of the full experiment at the number of participants the abridged search
recommends, with `--n-bots <recommended> --arrival-minutes <session minutes>`
and at least two sessions of `--duration-minutes`, and report both runs.

For chain experiments, also check how many participants got fewer trials
because every chain was busy (a line under TRIALS PER BOT, and
`busy_early_finishes` in the JSON). They are not failed, but more than one
bot and above 1% of bots started (`--max-busy-early-finish-rate`) fails the
test, and the search's recommended number of participants comes from it,
as for slow responses. Arrival patterns change the rate, so judge it from the
validation test. Besides recommending fewer participants, `wait_for_networks=True` or more
chains reduce it and may allow more participants at once.

## Interactive evidence

```bash
psynet debug local
```

Capture the generated ad page URL. Browser control is acceptable for quick
exploration, but repeatable screenshots, assertions, and participant recordings
should be Playwright-driven. Write the walk with `playwright-testing/SKILL.md`.
For canonical participant recordings, follow
`record-participant-video/SKILL.md`.

For grouped experiments, set explicit `max_wait_time` values on groupers and
barriers before recording participant flows; browser windows and headed
automation often enter sequentially, and default waits can be too short for
reliable evidence collection.

## Evidence notes

The experiment audit packet lives under `audit/` (see
`produce-experiment-audit`). Put review artifacts under `audit/artifacts/`,
simulated-data analysis under `audit/simulate/analysis/`, optional design
simulation under `audit/simulate/design/`, and command logs under
`audit/logs/`. Keep
`audit/audit.json` in sync with `psynet audit mark-present <artifact_id>` /
blockers as files land. Run those commands from the experiment root.

Record what you ran and what happened in those directories. If a command cannot
run because system services are unavailable, record that clearly rather than
pretending validation passed.
