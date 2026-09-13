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
  `simulate/analysis/simulated_export/`, and
  `simulate/analysis/analysis.ipynb`.
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
   - `artifacts/` for participant flow, real-data exports, monitor snapshots, performance
     results, and other primary evidence;
   - `logs/` for concise command logs;
   - `simulate/analysis/` for the simulated export and its analysis;
   - `simulate/design/` for an optional design-simulation campaign.
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
- `simulate/analysis/simulated_export/`: simulated-participant export;
- `simulate/analysis/analysis.ipynb`: executed analysis of that export;
- `simulate/design/simulation.ipynb` and `simulate/design/run.json`: optional
  design simulation;
- `logs/*.log`: concise logs that explain commands and failures.

Use `record-participant-video` for screenshot and video production. Keep videos
at most 3 minutes and 1280×720. Audit notebooks may be up to 10 MB, but avoid
unnecessary inline output so the rendered audit remains quick to load.

Rendering gives screenshots, participant video, monitor snapshot, performance
test, design simulation, and analysis their own top-level sections, so each of
those artifacts is reviewed on its own rather than inside one combined evidence
panel.

### Design simulation

The optional `simulate/design/simulation.ipynb` contains a **Power analysis**
section and, for adaptive experiments, may contain an **Adaptive procedure**
section. Follow `power-analysis/SKILL.md`, then mark `simulation_notebook`,
`simulation_run`, and `simulation_results` present.

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

### Simulated export

Run from the experiment root:

```bash
psynet audit simulate
```

The command writes the only copy to
`audit/simulate/analysis/simulated_export/` and marks `simulate_export`
present.

### Performance evidence

For review-ready performance evidence, prefer a sustained test (typically
`--n-bots 40 --duration-minutes 5`). Use the audit-scoped command so PsyNet
writes the canonical path. From the experiment root:

```bash
psynet audit performance-test \
  --n-bots 40 \
  --duration-minutes 5 \
  --time-factor 1.0
```

The command writes `<experiment>/audit/artifacts/performance.json`
and marks `performance_result` present. Judge the run by median and p95
`/timeline` and `/response` times, not by how many bots finished. Zero
finished bots is expected when the window is shorter than the experiment. If
those percentiles are high, profile SQL with `psynet test local --sql-profile`
before changing the scientific policy. Use top-level
`psynet performance-test local --json-output <path>` for a non-audit file.

Shorter smoke runs are fine for a first pass or infrastructure testing; use
top-level `psynet performance-test local` so they do not become packet evidence.
When the experiment is nearing finalizing, prefer a sustained run (and a
window on the order of the estimated duration if you want completions). Skip
an expensive re-run when a suitable `artifacts/performance.json` already
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

The canonical analysis is `simulate/analysis/analysis.ipynb`. It should:

- read exported data directly;
- show data loading and cleaning;
- display useful summary tables or plots. Prefer Plotly with
  `pio.renderers.default = "plotly_mimetype"` for offline interactive figures
  and `pio.templates.default = "plotly_white"` for consistent presentation;
  inline SVG/PNG is also supported. Call `fig.show()`, `plt.show()`, or the
  appropriate equivalent so figures are stored in the executed notebook;
- write equations with normal MathJax delimiters: `$...$` or `\(...\)` inline,
  and `$$...$$` or `\[...\]` on their own line for display mathematics. MathJax
  is packaged with the rendered audit and works offline. Write a literal
  currency symbol as `\$` when another dollar sign occurs later in the block;
- distinguish technical validation from scientific conclusions.

## Figure layout for rendered audits

The audit renders notebooks inside a column roughly 700-900 px wide, narrower
than a JupyterLab window. That width is deliberate: code and prose stay
readable, and a wider page would not help because Python lines are short.
Figures that look fine while authoring routinely collide once rendered: facet
titles overlap each other, in-plot annotations land on the data, and long
legends wrap into the title.

Fix crowding by changing the layout, not by dropping data. A reviewer needs to
see every condition that was simulated or measured, so hiding series to make a
figure tidy is the wrong trade: it silently narrows the question the figure can
answer. Two encodings in one panel (colour for one factor, `line_dash` for
another) usually fit comfortably once the labels are short and the legend has
its own column.

Follow these rules.

- **Use `plotly_white` by default.** Set
  `pio.templates.default = "plotly_white"` beside the MIME renderer so figures
  have a consistent, print-friendly background.
- **Keep all the series.** Prefer one panel showing every condition over
  several panels that each show a subset. Split a figure only when it genuinely
  covers separate analyses, never to reduce line count.
- **Facet by row, not by column.** `facet_col` divides the already narrow
  width, and three columns leave about 250 px per panel, which is where facet
  titles start overlapping. `facet_row` keeps the full width for every panel
  and spends vertical space instead, which the page has plenty of. Use it when
  the panels have different y ranges or would otherwise be an unreadable
  tangle; otherwise encode the extra factor with colour or `line_dash` in one
  panel.
- **When faceting by row**, scale the height with the number of panels
  (`height=260 * n_rows + 140`), strip the `variable=` prefix Plotly Express
  puts in facet titles, and leave right margin for the rotated row labels:

  ```python
  fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
  fig.update_layout(height=260 * n_rows + 140, margin=dict(l=70, r=90, t=90, b=60))
  ```

  Row labels sit on the right edge, so pair `facet_row` with the horizontal
  legend above the plot rather than a right-hand legend column.
- **Shorten every label.** Map database-style ids
  (`well_specified_2pl`) to display labels (`Matching 2PL`) before plotting,
  and strip the `variable=` prefix Plotly Express adds to facet titles.
  Relabel the encoding columns too, not just the axes: anything missing from
  `labels` shows up as a raw column name in the hover text.
- **Put explanations in Markdown, not in the plot.** A `display(Markdown(...))`
  caption above the figure has unlimited room; an `annotation_text` inside the
  axes does not, and will sit on top of a line.
- **Give the legend its own space.** A horizontal legend above the plot works
  while it fits on one row. Two encodings produce one entry per combination,
  which wraps and pushes into the title, so those figures need a right-hand
  legend column and a matching right margin.
- **Set an explicit height.** A figure without one falls back to the 20 rem
  container, which squashes it; 420 px or more is a safe floor. The audit holds
  a figure to its authored height when the window is resized, so the height you
  choose is the height reviewers see.
- **Set explicit tick values** for a handful of design points, rather than
  letting Plotly choose ticks that repeat or crowd.
- **Use translucent confidence ribbons for dense curves.** Repeated error bars
  become a picket fence at single-unit resolution. Draw upper and lower bounds
  as a low-opacity filled polygon behind each line and put exact bounds in the
  line's hover text. Keep error bars for sparse, unrelated design points.

Use this reference layout, adjusting the numbers rather than inventing a new
scheme per figure:

```python
AUDIT_FIGURE_LAYOUT = dict(
    height=420,
    margin=dict(l=70, r=30, t=90, b=60),
    title=dict(x=0, xanchor="left"),
    legend=dict(
        orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title_text=""
    ),
)
# Many series, or two encodings: move the legend into its own column.
AUDIT_FIGURE_LAYOUT_SIDE_LEGEND = dict(
    AUDIT_FIGURE_LAYOUT,
    margin=dict(l=70, r=210, t=70, b=60),
    legend=dict(
        orientation="v", yanchor="top", y=1, xanchor="left", x=1.02, title_text=""
    ),
)

SCENARIO_LABELS = {"well_specified_2pl": "Matching 2PL", "three_pl_guessing": "3PL guessing"}
results["scenario"] = results["response_scenario"].map(SCENARIO_LABELS)
# Hover text shows the raw column name unless it is relabelled here too.
AXIS_LABELS = {"rmse": "Ability RMSE", "scenario": "Scenario", "policy": "Policy"}

display(Markdown("""## Operational performance

Solid lines are adaptive selection, dashed lines are random. Error bars are
Monte Carlo 95% intervals; the dashed red line is the RMSE requirement of
0.45."""))

# Every simulated condition stays in the panel: colour separates the response
# scenario, line_dash separates the selection policy.
fig = px.line(
    results, x="max_trials", y="rmse", color="scenario", line_dash="policy",
    error_y="rmse_mc95_half_width", markers=True,
    labels=dict(AXIS_LABELS, max_trials="Maximum CAT items"),
    title="Operational ability recovery",
)
fig.add_hline(y=0.45, line_dash="dash", line_color="firebrick")
fig.update_xaxes(tickvals=sorted(results["max_trials"].unique()))
fig.update_layout(**AUDIT_FIGURE_LAYOUT_SIDE_LEGEND)
fig.show()
```

Use `AUDIT_FIGURE_LAYOUT` for the simpler case of a single encoding with a few
short labels, where a legend row above the plot reads better than a side
column.

### Metric controls

Use Plotly `updatemenus` buttons, not page-level or ipywidget tabs, when one
diagnostic figure needs several y metrics. Tabs outside Plotly are not preserved
by the static notebook renderer. Keep the primary decision metric in a
permanently visible figure and put secondary views (for example correlation,
model SEM, bias, and coverage) behind the buttons. Also render a summary table
so printed and screenshotted audits retain the values.

Keep the metric data long-form. Build one trace per scenario/policy for the
initial metric, then have each button restyle those traces' `y`, error, and
hover arrays. Do not add a hidden duplicate trace for every metric: Plotly
serializes all hidden traces into the notebook, which can make the MIME bundle
large enough to exhaust the bounded audit preview.

### Check the rendered figures for overlapping text

Judging a figure in the authoring window is not enough, and neither is one
glance at a screenshot. Render the audit (`psynet audit render`, then
`psynet audit serve`), open it, and inspect every figure at the real column
width, in every metric-button state, and after resizing the browser window.
Resizing matters because it forces Plotly to redraw at a new size, which is when
a figure that was laid out generously can suddenly crowd itself.

Overlapping text is the failure to watch for: facet titles running into the
legend, y-axis titles from stacked panels colliding, tick labels merging, the
modebar sitting on top of the metric buttons. It is easy to miss by eye when the
labels are small, so check it directly in the browser console (or from
Playwright) rather than trusting a visual scan:

```javascript
Array.from(document.querySelectorAll(".notebook-plotly-target")).flatMap((figure) => {
  const labels = Array.from(figure.querySelectorAll("text"))
    .filter((node) => node.textContent.trim() && node.getBoundingClientRect().width > 0);
  return labels.flatMap((a, i) =>
    labels.slice(i + 1)
      .filter((b) => {
        const [boxA, boxB] = [a.getBoundingClientRect(), b.getBoundingClientRect()];
        return Math.min(boxA.right, boxB.right) - Math.max(boxA.left, boxB.left) > 1 &&
          Math.min(boxA.bottom, boxB.bottom) - Math.max(boxA.top, boxB.top) > 1;
      })
      .map((b) => [a.textContent.trim(), b.textContent.trim()]),
  );
});
```

An empty result is the standard to hold each figure to. Anything reported is a
layout bug to fix by shortening labels, adding margin, moving the legend, or
increasing the figure height, not something to leave for the reviewer.

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

Notebook HTML and SVG in the rendered audit can include executable script.
Treat the audit as trusted author content: do not bind `psynet audit serve`
beyond localhost unless every viewer is trusted with that notebook content.
Markdown reports still do not interpret raw HTML.

When a requirement depends on an external service, collect evidence that the
real integration worked end to end. Mocks and simulated payloads support
development but do not prove the real integration unless the task explicitly
defines simulation as acceptable. If safe access is unavailable, record a
blocker that says exactly what remains unverified.
