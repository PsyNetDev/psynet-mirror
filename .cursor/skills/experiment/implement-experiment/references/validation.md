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
`simulate_export` present.

## Performance evidence

When the work needs performance evidence, run this sustained load test after
functional checks pass. Do not rely on experiment defaults such as
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
If the experiment customizes `run_bot`, preserve `bot=None` support and delegate
to `super().run_bot(...)` for framework-created bots; `psynet performance-test`
calls `exp.run_bot(time_factor=...)` without passing a bot object.

Short smoke runs are fine for a first pass or infrastructure testing; use
top-level `psynet performance-test local` so they do not become packet evidence.
When the experiment is nearing finalizing, prefer a sustained run (and a window
on the order of the estimated duration if you want completions). Skip
an expensive re-run when a suitable `audit/artifacts/performance.json` already
exists for the current implementation.

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
