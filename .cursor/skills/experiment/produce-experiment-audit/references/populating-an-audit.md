# Populate an experiment audit

Use this reference whenever populating a PsyNet experiment audit under the
experiment's `audit/` directory.

Let `AUDIT_ROOT` mean `audit/` relative to the experiment root (the directory
that contains `experiment.py`). Paths below are relative to `AUDIT_ROOT` unless
noted otherwise.

## Ownership

Implementation and validation skills **produce** audit artifacts as they run.
This reference owns paths, statuses, blockers, inventory, validate, and render.

Do **not** treat audit population as a second evidence campaign. If
`artifacts/performance.json` (or another required output) is already present
from implementation, mark it present and move on. Re-run an expensive check only
when the existing file is missing, invalid, or no longer represents the final
implementation.

## Path cheat-sheet

`psynet audit` uses `./audit/` from the experiment directory:

| Working directory | Typical command | Resolved packet |
|-------------------|-----------------|-----------------|
| Experiment root | `psynet audit validate` | `./audit` |

Run from the experiment root. Running from inside `audit/` is an error.

For `mark-present` / `render`, the same rule applies.

## Early audit-aware habit

Initialize the packet before meaningful runs. From the first useful command
onward, write outputs into the audit layout even when they are interim:

- Prefer canonical paths such as `artifacts/performance.json`,
  `artifacts/simulated_data.zip`, and `analyses/analysis.ipynb`.
- Overwrite the same path when a later run supersedes an interim result.
- Mark artifacts `present` when the file is the evidence you intend to hand
  off (including smoke runs used for infrastructure testing).
- Update `audit.json` as files land (`psynet audit mark-present ...`).

## Workflow pathways

Choose the pathway that matches how the experiment was built:

### Agent-led implementation

Use when an agent (or team) implements the experiment and collects evidence as
work proceeds.

1. From the experiment directory, run `psynet audit init` **before** meaningful
   implementation runs.
2. Fill `PLAN.md` as the implementation plan takes shape.
3. Produce evidence during implementation/validation into `audit/` paths as you
   go (see below). Prefer overwriting interim canonical files rather than
   regenerating later.
4. Close the packet with `mark-present`, `validate`, and `render`.

### Retrospective audit

Use when a human (or team) implemented the experiment first and is creating the
audit packet afterward to document and hand off what was built.

1. From the experiment directory, run `psynet audit init` once you are ready to
   package evidence.
2. `PLAN.md` is optional. You may:
   - leave the starter placeholder,
   - write a short retrospective plan,
   - remove the `plan` section from `audit.json`, or
   - hide it with `"display": false`.
3. Focus on `REPORT.md`, `TIMELINE.md`, evidence artifacts, and honest
   blockers for anything still missing.
4. Close the packet with `mark-present`, `validate`, and `render`.

`psynet audit validate` warns (non-fatal) when the core profile has no plan
section. That warning is expected for retrospective audits.

## Workflow

1. Initialize the packet before collecting evidence: from the experiment
   directory, run `psynet audit init`.
2. Fill the core section files:
   - `PLAN.md`: implementation plan (**recommended** for agent-led audits;
     optional for retrospective audits — see **Workflow pathways** above);
   - `REPORT.md`: implementation, validation, analysis, and limitations;
   - `TIMELINE.md`: notable implementation and evidence events. Use list items
     of the form `- T+HH:MM:SS [actor] description`. The actor must be one of
     `agent-start`, `agent`, `agent-stop`, `manual`, or `system`. Extra tags
     such as `[evidence]` go *after* the actor (`- T+00:05:12 [agent]
     [evidence] Ran simulate.`). `psynet audit validate` warns on lines that
     look like entries but were ignored.
   - `PROMPT.md`: original prompt or brief when useful.
   - `audit.json` `implementation.summary`: one-sentence subtitle for the
     rendered page. Leave the starter TODO only until you have a real summary;
     validate warns, and the page omits it until rewritten.
3. Collect reviewable outputs under:
   - `artifacts/` for participant flow, exports, monitor snapshots, performance
     results, and other primary evidence;
   - `analyses/` for notebooks and analysis outputs;
   - `logs/` for concise command logs.
4. Keep evidence-generation scripts with the implementation source. Evidence
   should be reproducible, not just a manually assembled folder.
5. After an artifact exists, run:

   ```bash
   psynet audit mark-present <artifact_id>
   ```

   Add a manifest entry first when the artifact is not already declared.
6. Record checks and blockers honestly in `audit.json`. A coherent packet may
   still have blockers; validate success means structure is OK, not that the
   experiment is ready.
7. Before handoff, run:

   ```bash
   psynet audit validate
   psynet audit render
   ```

## Evidence checklist

Choose evidence that matches the experiment. Common artifacts are:

- `artifacts/participant.mp4`: concise participant walkthrough;
- `artifacts/screenshots/*.png`: targeted participant-facing states;
- `artifacts/screenshots/manifest.json`: optional screenshot captions;
- `artifacts/performance.json`: sustained performance-test output;
- `artifacts/monitor.html`: static monitor snapshot;
- `artifacts/data.zip`: exported local or real-run data;
- `artifacts/simulated_data.zip`: simulated-participant export;
- `analyses/analysis.ipynb`: executed, self-contained analysis notebook;
- `logs/*.log`: concise logs that explain commands and failures.

Use `record-participant-video` for screenshot and video production. Keep videos
at most 3 minutes and 1280×720. Keep rendered notebooks small enough for typical
review tooling (normally under about 100 KB).

Rendering gives screenshots, participant video, monitor snapshot, performance
test, and analysis their own top-level sections, so each of those artifacts is
reviewed on its own rather than inside one combined evidence panel.

### Monitor snapshot

`artifacts/monitor.html` is a **static HTML snapshot of `/dashboard/monitoring`**
from a running experiment (local debug or deployed). In the dashboard nav this
is the **Monitor** tab (it opens on the Networks visualization). Capture that
page. Do not substitute **Basic data** (`/dashboard/data`).

Capture it while the server is up and at least one participant (or bot) has
progressed far enough that the network graph shows useful state:

1. Start or reuse `psynet debug local` (or a deployed app).
2. Read dashboard credentials from the launch info PsyNet writes under
   `~/psynet-data/launch-data/<deployment_id>/launch-info.json` (or the
   equivalent printed at launch). Do not invent credentials.
3. Open the authenticated Monitor page at `/dashboard/monitoring`.
4. Save the page HTML to `audit/artifacts/monitor.html` (for example
   Playwright `page.content()` after HTTP basic auth). Prefer capturing via the
   same participant-flow script that already talks to the running server.
5. Mark present: `psynet audit mark-present monitor_snapshot`.

`psynet audit render` rewrites `/static/...` links and copies Dallinger frontend
assets so the snapshot is viewable offline. You do not need to vendor those
assets by hand.

Mark `monitor_snapshot` **`not_applicable`** only when the work never had a
running PsyNet server/dashboard to snapshot (for example pure docs or
offline-only packaging). Local debug without a paid deployment is still a valid
source—do not mark N/A just because the app was not deployed remotely.

There is no dedicated `psynet audit` subcommand for N/A yet; set
`status: not_applicable` on the artifact in `audit.json`, remove its required
blocker (or replace it with an N/A note in `REPORT.md`), then re-validate.

### Simulation export packaging

`psynet simulate` writes `data/simulated_data/` (a directory). Prefer `--audit`
so PsyNet also zips that tree to the canonical audit path. From the experiment
root:

```bash
psynet simulate --audit
```

`--audit` writes `<experiment>/audit/artifacts/simulated_data.zip`
and marks `simulation_export` present. Use `--no-mark-present` to write the zip
without updating `audit.json`. Overwrite the same zip when a later simulation
supersedes an interim run.

### Performance evidence

For review-ready performance evidence, prefer a sustained test (typically
`--n-bots 40 --duration-minutes 5`). Prefer `--audit` so PsyNet writes the
canonical path. From the experiment root:

```bash
psynet performance-test local \
  --n-bots 40 \
  --duration-minutes 5 \
  --time-factor 1.0 \
  --audit
```

`--audit` writes `<experiment>/audit/artifacts/performance.json`
and marks `performance_result` present. Use `--json-output` only for a non-audit
path, and `--no-mark-present` only when you want the JSON in the packet without
updating `audit.json`.

Shorter smoke runs are fine while iterating or infrastructure-testing; omit
`--audit` (or use `--json-output`) so they do not become the packet's evidence.
Skip an expensive re-run when a suitable `artifacts/performance.json` already
exists for the current implementation.

## Manifest rules

For every review-relevant artifact, declare a stable lowercase snake-case id,
kind, relative path, title, description, whether it is required, status, and
creator.

Use statuses consistently:

- `present`: the declared file exists and is ready to inspect;
- `missing`: no completed artifact exists yet;
- `blocked`: a real attempt failed or cannot proceed;
- `not_applicable`: the experiment design does not need the artifact.

Every required non-present artifact needs a matching blocker. A useful blocker
states what was attempted, what prevented completion, and the next concrete
step. Never turn a skipped or failed check into passing evidence.

Declare screenshots either as individual artifacts or in the `captions` map of
the present `screenshots` manifest artifact. Rendering publishes safe image
paths referenced by that manifest and builds the screenshot carousel.

## Analysis and reporting

The canonical analysis is `analyses/analysis.ipynb` unless another format is
more appropriate. It should:

- read exported data directly;
- show data loading and cleaning;
- display useful summary tables or plots (prefer inline SVG; call
  `plt.show()` or equivalent so figures are stored in the executed notebook);
- distinguish technical validation from scientific conclusions.
- distinguish technical validation from scientific conclusions.

`REPORT.md` should state:

- what was implemented;
- which commands and procedures ran;
- where the important evidence lives;
- what export and analysis showed;
- which checks remain blocked, missing, or not applicable;
- how a reviewer can reproduce or extend the checks.

Do not claim an experiment is fully validated unless every required artifact
and check supports that claim.

## Local preview

When handing the audit to a human for review, offer to open it in a browser.
If they agree, from the experiment root run:

```bash
psynet audit serve --render
```

Share the local URL and leave the server running. Do not ask the human to
remember or type that command. Use `public-tunnel` when a remote URL is needed.

## Safety

Use only safe local credentials and redact secrets from logs and artifacts.
Never commit production tokens, custom service credentials, or participant
secrets.

When a requirement depends on an external service, collect evidence that the
real integration worked end to end. Mocks and simulated payloads support
development but do not prove the real integration unless the task explicitly
defines simulation as acceptable. If safe access is unavailable, record a
blocker that says exactly what remains unverified.
