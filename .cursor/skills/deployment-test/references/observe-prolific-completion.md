# Observe until Prolific completion


After deployment, observe the ongoing experiment until it completed on Prolific
instead of stopping at launch success. Poll the dashboard participant table,
recruiter state, and logs until the Prolific participant is complete, failed,
returned, or otherwise reaches a terminal state. Record the participant status,
completion flag, failure fields, payment fields, and any recruiter-state changes
seen during the wait.

Also check the Prolific study state directly from the deployed app/container.
Do not print environment variables or config values, because they may include
the Prolific API token. Instead, call `prolific_service_from_config()` inside
the web container and print only the study status and submission status counts.
The experiment is not complete while the Prolific study status is still
`ACTIVE`, even if there are no currently `ACTIVE` submissions and even if all
visible PsyNet participant rows are terminal. The study as a whole must be in
state `COMPLETED`, not `ACTIVE`.

Use the study id from the deployment output, Prolific study URL, or participant
`hit_id`. If you need to read the `hit_id` from the database inside the
container, use raw SQL (e.g.
`SELECT DISTINCT hit_id FROM participant WHERE hit_id IS NOT NULL`) rather
than the Dallinger ORM: querying `Participant` via the ORM from a plain
container Python shell fails with
`No such polymorphic_identity 'psynet.participant.Participant'` because the
PsyNet models are not imported in that context. Then query Prolific like this:

```bash
ssh -i <ssh-key> <ssh-user>@<ssh-host> \
  "docker compose -f ~/dallinger/<app-name>/docker-compose.yml exec -T web python - <<'PY'
import json
from collections import Counter

from dallinger.prolific import prolific_service_from_config

study_id = '<prolific-study-id>'
service = prolific_service_from_config(strict=False)
study = service.get_study(study_id)
submissions = service.get_submissions(study_id)
counts = Counter(s.get('status') for s in submissions)
active = [s.get('id') for s in submissions if s.get('status') == 'ACTIVE']
print(json.dumps({
    'study_status': study.get('status'),
    'places_taken': study.get('places_taken'),
    'total_available_places': study.get('total_available_places'),
    'number_of_submissions': study.get('number_of_submissions'),
    'submission_status_counts': dict(sorted(counts.items())),
    'active_submission_count': len(active),
}, sort_keys=True, indent=2))
PY"
```

Do not declare completion from a single poll with `active_submission_count == 0`.
If the study is still `ACTIVE`, Prolific can still recruit replacement
participants after returns or time-outs. Continue observing until
`study_status == "COMPLETED"`. Treat all other study states as not completed
unless the user explicitly asks to stop watching.

Once the Prolific run reaches a terminal state, perform the post-completion
Dozzle log download and review described below. Compare these logs against the
initial deployment-time scan and call out errors that only appeared after
completion.

When several apps were deployed, observe them in parallel and apply this
whole completion/audit workflow to each app independently: each has its own
recruiter run, its own dashboard, and its own audit folder keyed by app name
(the Lucid app follows the adapted observation described in "Deploy The
Lucid Variant"). Do not stop observing one app because another completed
first.

After the study status is `COMPLETED`, record the deployment's audit trail in
a per-deployment folder under `<psynet-root>/deployment-tests/`.
Do **not** commit `analysis.md`, `local/`, or any other audit artifacts to the
deployment branch (or to `master`). The whole `deployment-tests/` tree is
gitignored in the PsyNet repository; deployment branches remain for
deploy-code provenance only. Instead, archive the finished audit folders in
the dedicated private repository (see "Archive the audit trail" below).

Each deployment gets one folder named after the study-completion date/time and
app name:

```text
deployment-tests/<YYYYMMDD-HHMMSS>-<app-name>/
  analysis.md                            # local-only Markdown analysis
  local/                                 # raw data, never committed
    logs.zip                             # full Dozzle logs download
    logs/                                # extracted per-container logs
    export/                              # psynet export output
    prolific-study-and-submissions.json  # raw Prolific data
```

Use local time for the timestamp unless the user requests UTC.

**Keep sensitive data out of chat summaries.** Prefer putting identifiers and
raw excerpts in `local/` artifacts and the local `analysis.md`. When quoting
in chat, avoid:

- Prolific worker/participant IDs (`worker_id` / `PROLIFIC_PID` values) or any
  other platform account identifiers.
- Participant personal data: names, demographics, free-text responses, or
  quoted answer content.
- Credentials, API tokens, or secret config values (including anything the
  user supplied for dashboard/Dozzle/SSH login).

Referring to participants by their PsyNet row id (`participant 16`) and to
submissions by Prolific submission/assignment id is fine for cross-referencing.
When log excerpts are quoted in chat, strip any worker IDs they contain. If in
doubt, describe the evidence and point to the `local/` artifact instead of
quoting it.

Collect the `local/` artifacts as follows:

1. **Full Dozzle logs**: save the downloaded ZIP as `local/logs.zip` and
   extract it to `local/logs/` (see the Dozzle section below).
2. **Database/data export**: run `psynet export ssh` from the experiment
   directory into `local/export/`:

```bash
cd <psynet-root>/tests/deployment/<experiment>  # the app's experiment dir
psynet export ssh --app <app-name> --server <ssh-host> --anonymize no \
  --path <psynet-root>/deployment-tests/<YYYYMMDD-HHMMSS>-<app-name>/local/export
```

   This saves the database dump (`regular/database.zip`), per-table CSVs
   (`regular/data/`), and the deployed source code (`source_code.zip`).

3. **Raw Prolific data**: save the full study object and all submissions as
   JSON (run the `prolific_service_from_config()` snippet above with
   `print(json.dumps({'study': study, 'submissions': submissions}, ...))`
   and redirect to `local/prolific-study-and-submissions.json`).

### Post-completion checklist

Work through all of these once `study_status == "COMPLETED"`:

1. Download the full Dozzle logs ZIP again and re-run the log review,
   comparing against the deployment-time scan; store it in `local/`.
2. Export the database and data with `psynet export ssh` into `local/export/`.
3. Save the raw Prolific study and submissions JSON into `local/`.
4. Review the previous comparable deployment's `analysis.md` (e.g. the
   `*-1` run when auditing `*-2`, or the previous RC's run for the same
   app) and check whether each issue found there is resolved, still
   present, or changed in the current deployment. Fetch it from the
   `psynet-deployment-tests` archive repository if it is not on disk.
5. Write `analysis.md` locally, referencing the `local/` artifacts. Do not
   `git add`, commit, or push anything under `deployment-tests/` in the
   PsyNet repository.
6. Offer to tear down the deployed app once the data is captured. Do not
   destroy it without explicit user confirmation:

```bash
cd <psynet-root>/tests/deployment/<experiment>  # the app's experiment dir
psynet destroy ssh --server <ssh-host> --app <app-name>
```

7. Archive the audit trail (see below) once the `analysis.md` verdict is
   settled.

### Archive the audit trail

Finished audit folders are archived in the dedicated **private** repository
<https://gitlab.com/computational-audition-lab/psynet-deployment-tests>
(`git@gitlab.com:computational-audition-lab/psynet-deployment-tests.git`).
It holds only artifacts; the deployment-test experiments themselves stay in
the PsyNet repository under `tests/deployment/`.

Its structure groups deployments by the base they were cut from:

```text
releases/<base-tag>/<YYYYMMDD-HHMMSS>-<app-name>/   # e.g. releases/v13.3.0rc0/...
master/<short-hash>/<YYYYMMDD-HHMMSS>-<app-name>/   # master-based deployments
practice/<...>/                                     # workflow shakedown runs
```

Each archived folder keeps the layout described above (`analysis.md` plus
`local/`). To archive, clone the repository (or pull an existing clone),
copy the finished per-deployment folder(s) into the matching
`releases/<base-tag>/` or `master/<short-hash>/` directory, and commit and
push with a message naming the base and app(s). Ask the user before pushing.
The repository must stay private: exports contain participant data. Large
raw archives (e.g. `data.zip`) may be pruned after the corresponding release
has shipped and the analysis conclusions are settled.

This report should be more detailed than the chat summary. Include:

- Deployment metadata: app name, experiment URL, dashboard URL, PsyNet commit,
  Dallinger commit, Prolific study id, and final Prolific study status.
- Final Prolific counts by submission status, including `APPROVED`, `RETURNED`,
  `TIMED-OUT`, `AWAITING REVIEW`, and any unexpected statuses.
- The total cost of the run as reported by the recruiting platform itself.
  Fetch it inside the app's web container: for Prolific apps use
  `ProlificService.get_total_cost(study_id)` (via
  `prolific_service_from_config()`); for Lucid apps use
  `LucidService.get_cost(survey_number)` (via `get_lucid_service()`). Report
  the amount with its currency and state which platform figure it is.
- Dashboard-vs-Prolific reconciliation: compare participant rows against
  Prolific submissions using assignment/submission id, worker id, status,
  completion flag, failure fields, payment fields, reward/bonus fields, and
  branch/failure logs. Highlight mismatches or explain why they are expected.
- Detailed log findings by container (`web`, `worker`, `clock`, `redis`,
  `pgbouncer`), including tracebacks, errors, warnings, repeated warning loops,
  unusual status transitions, and suspicious but non-fatal events.
- A concise timeline of important events: launch, study creation, recruitment,
  participant completions/returns/time-outs, approval attempts, bonus payments,
  study completion, and post-completion log download.
- A follow-up on the previous comparable deployment: list each issue from
  that run's `analysis.md` and state whether it is resolved, still present,
  or superseded in this deployment, with evidence. If this is the first
  deployment of its kind, say so.
- Interpretation and severity for each finding, distinguishing confirmed bugs,
  likely harmless noise, expected Prolific edge cases, and unresolved questions.

Reference the exact downloaded log directory and file names used for the
analysis so the evidence can be rechecked later from the local ZIP.

