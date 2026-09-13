---
name: produce-experiment-audit
description: Produce a standalone PsyNet experiment audit with audit.json, REPORT.md, evidence artifacts, validation, rendering, and honest blockers. Use when asked to prepare a portable experiment audit under the experiment's audit/ directory.
compatibility: Requires PsyNet with `psynet audit` CLI; ffprobe recommended for video artifact validation.
---

# Produce an experiment audit

A standalone audit is an `audit/` folder inside the experiment directory. Run
the CLI from the experiment root.

## Prerequisites

- Read `references/populating-an-audit.md`; it is the shared operational source
  of truth for audit contents, statuses, blockers, validation, and rendering.
- If participant screenshots or video are needed, use
  `record-participant-video`.
- For `artifacts/monitor.html`, follow the Monitor snapshot section in
  `references/populating-an-audit.md` (authenticated `/dashboard/monitoring`
  HTML from a running local or deployed server; mark `not_applicable` only when
  no server ever ran).
- If the experiment needs implementation changes, use
  `implement-experiment`.
- For a live handoff, use `prepare-experiment-tunnel` (and `public-tunnel`) when
  a temporary public preview is needed.

## Workflow

Two common pathways:

- **Agent-led implementation:** run `psynet audit init` early, keep `PLAN.md`
  current as work proceeds, and collect evidence during implementation.
- **Retrospective audit:** run `psynet audit init` after the experiment exists;
  `PLAN.md` is optional (remove or hide the plan section if not needed).

See `references/populating-an-audit.md` for the full pathway guidance.

1. From the experiment directory, run `psynet audit init`.
2. Produce evidence during implementation/validation into `audit/` paths as you
   go (see `references/populating-an-audit.md`). Prefer overwriting interim
   canonical files rather than regenerating later.
3. Keep evidence-generation scripts with the experiment source.
4. Close the packet: `psynet audit simulate` marks `simulate_export`, and
   `psynet audit performance-test` marks `performance_result` present;
   mark remaining artifacts, record blockers, then
   run `psynet audit validate` from the experiment root.
   A pass with blockers means the packet is coherent, not that the experiment is
   ready. Do not re-run expensive checks that already produced review-ready
   files.
5. Run `psynet audit render`.
6. Offer to open the audit for the human with `psynet audit serve --render`.
   If they agree, start the server, share the local URL, and leave it running.
   Do not ask them to remember or type that command. Use a separate tunnel
   helper when remote review is needed.
7. Hand over the rendered audit for review.

## Standalone layout

```text
experiment/
  experiment.py
  audit/
    audit.json
    PROMPT.md
    PLAN.md
    TIMELINE.md
    REPORT.md
    artifacts/
    logs/
    simulate/
      analysis/    # simulated export and analysis notebook
      design/      # optional design simulation
    site/          # generated; normally not committed
```

## Rules

- Do not duplicate the population procedure in this file or other skills; keep
  it in `references/populating-an-audit.md`.
- Do not present missing, blocked, skipped, or not-applicable artifacts as
  passing evidence.
- Keep custom or production credentials out of audit artifacts and logs.
- Stock ``deploy.toml`` excludes the whole ``audit/`` directory from deployment
  and debug staging. Existing experiments keep their current ``deploy.toml``;
  add ``audit`` to ``[exclude].paths`` if it is missing. Keep runtime helpers
  beside ``experiment.py``, not only under ``audit/``.
- Repository-specific wrapper skills may add conventions (for example extra
  metadata or review checklists); do not invent workshop layouts here.
