# Validation

Use this reference before claiming a PsyNet experiment is functionally complete
or before collecting final participant-flow evidence. It owns final check
commands, evidence path conventions, and PsyNet-specific validation pitfalls. For
day-to-day backend or frontend testing strategy, use
`develop-experiment-back-end/SKILL.md` and
`develop-experiment-front-end/SKILL.md`.

## Functional checks

Run functional checks from the experiment directory:

```bash
python experiment.py
psynet test local
psynet simulate --audit
```

`psynet simulate --audit` still writes `data/simulated_data/` and also zips it
to `audit/artifacts/simulated_data.zip`, then marks `simulation_export` present.

## Performance evidence

When the work needs performance evidence, run this sustained load test after
functional checks pass. Do not rely on experiment defaults such as
`test_n_bots = 1`. Prefer `--audit` so results land in the audit packet
immediately. From the experiment root:

```bash
psynet performance-test local \
  --n-bots 40 \
  --duration-minutes 5 \
  --time-factor 1.0 \
  --audit
```

That writes `audit/artifacts/performance.json` and marks `performance_result`
present. Use `--json-output` only for a custom non-audit path.
If the experiment customizes `run_bot`, preserve `bot=None` support and delegate
to `super().run_bot(...)` for framework-created bots; `psynet performance-test`
calls `exp.run_bot(time_factor=...)` without passing a bot object.

Short smoke runs are fine while iterating or infrastructure-testing; omit
`--audit` (or use `--json-output`) so they do not become the packet's evidence.
Prefer a sustained run when claiming production-like performance evidence. Skip
an expensive re-run when a suitable `audit/artifacts/performance.json` already
exists for the current implementation.

## Interactive evidence

```bash
psynet debug local
```

Capture the generated ad page URL. Browser control is acceptable for quick
exploration, but repeatable screenshots, assertions, and participant recordings
should be Playwright-driven. For canonical participant recordings, follow
`record-participant-video/SKILL.md`.

For grouped experiments, set explicit `max_wait_time` values on groupers and
barriers before recording participant flows; browser windows and headed
automation often enter sequentially, and default waits can be too short for
reliable evidence collection.

## Evidence notes

The experiment audit packet lives under `audit/` (see
`produce-experiment-audit`). Put review artifacts under `audit/artifacts/`,
analysis under `audit/analyses/`, and command logs under `audit/logs/`. Keep
`audit/audit.json` in sync with `psynet audit mark-present <artifact_id>` /
blockers as files land. Run those commands from the experiment root.

Record what you ran and what happened in those directories. If a command cannot
run because system services are unavailable, record that clearly rather than
pretending validation passed.
