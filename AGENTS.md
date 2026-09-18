# Agent instructions

On Windows, develop in WSL (Ubuntu) using Linux commands. Native Windows is not supported.

Start by following `psynet/resources/experiment_scripts/AGENTS.md`.

Then act on the following PsyNet developer instructions:

## Sandbox reminder

When running PsyNet commands from Cursor, disable sandboxing by setting
`required_permissions: ["all"]` on the shell command.

## Dallinger repo

### Summary

When developing PsyNet, keep a local checkout of Dallinger at `~/Dallinger`.
If a change is needed in Dallinger, make it there and submit a PR .

### Dallinger repo instructions

Cloud Agents push to a Dallinger fork at `DALLINGER_FORK_URL` using the PAT `DALLINGER_GH_TOKEN`.
If these environment variables are not present, tell the user to follow these user instructions:

#### User instructions

1. Create a fine-grained GitHub PAT via the GitHub website.
   - Scope it to the agent's fork of Dallinger only, with the following permissions:
      - Contents: Read and write
      - Pull requests: Read and write
   - Set an expiry of 1 year or less (required for interacting with Dallinger organization).
2. Save this token as a Cloud Agent secret named `DALLINGER_GH_TOKEN` via the Cursor website.
3. Create a Dallinger fork on the GitHub website (e.g., `https://github.com/<your-username>/Dallinger`).
4. Save the fork URL as a Cloud Agent secret named `DALLINGER_FORK_URL` via the Cursor website.

#### Cloud Agent instructions

Clone the fork at `DALLINGER_FORK_URL` to `~/Dallinger`.
If `~/Dallinger` already exists, remove it or reuse that checkout.

Authenticate GitHub CLI + git using the token (avoid printing the token):

- `printf "%s" "$DALLINGER_GH_TOKEN" | gh auth login --hostname github.com --git-protocol https --with-token`
- `gh auth setup-git`

Add the upstream remote:

- `cd ~/Dallinger`
- `git remote add upstream https://github.com/Dallinger/Dallinger.git`

Make sure it is up-to-date:

- `git fetch upstream master`
- `git merge upstream/master`

Create a feature branch:

- `git checkout -b <branch-name>`

Install it in editable mode: `uv pip install -e ~/Dallinger`.
If this fails with `pg_config executable not found`, install PostgreSQL
development headers (e.g. `libpq-dev`) and retry.

Make changes and commit locally.

Push: `git push -u origin <branch-name>`

Open a PR to upstream: `gh pr create --base master --head <your-username>:<branch-name>`

If your PsyNet PR depends on this new unmerged change to Dallinger,
specify your fork in `pyproject.toml` (use a literal URL; environment
variables are not expanded in `pyproject.toml`):

```toml
# In [project].dependencies
"dallinger[docker] @ git+https://github.com/<your-username>/Dallinger.git@<branch-name>",
```

Use the GitHub CLI to find and read Dallinger job logs.
Use the token `DALLINGER_GH_TOKEN` for all these commands (either via
`gh auth login --with-token` above or by setting `GH_TOKEN` in the command).

1. List recent runs:
   - `gh run list --repo "$DALLINGER_FORK_URL" --limit 10`
2. View logs for a specific run:
   - `gh run view <run-id> --repo "$DALLINGER_FORK_URL" --log-failed`
3. If the run is against upstream, use the canonical repo:
   - `gh run list --repo https://github.com/Dallinger/Dallinger --limit 10`
   - `gh run view <run-id> --repo https://github.com/Dallinger/Dallinger --log-failed`

Local agents use a similar approach, but `~/Dallinger` should be created already by the user,
and it may be a clone of the original repository, not a fork.

## CI status checks (GitLab)

When you need to check CI status for PsyNet, use the GitLab API with the
`GITLAB_TOKEN` environment variable (project access token). This token should
be provided automatically if you are working with the team's Cursor Cloud Agent
setup. If not, tell the user to create a token via
<https://gitlab.com/PsyNetDev/PsyNet/-/settings/access_tokens>
and add it as a secret in the Cloud Agent dashboard
(<https://cursor.com/dashboard?tab=cloud-agents>)

Fetch the latest pipeline with:

```http
GET https://gitlab.com/api/v4/projects/PsyNetDev%2FPsyNet/pipelines?per_page=1
```

Then list jobs for that pipeline and, if needed, fetch job logs via the trace
endpoint:

```http
GET https://gitlab.com/api/v4/projects/<project_id>/pipelines/<pipeline_id>/jobs
GET https://gitlab.com/api/v4/projects/<project_id>/jobs/<job_id>/trace
```

This is the preferred approach for agents when verifying CI status or logs.

## Playwright flakiness guardrails

When adding or updating Playwright E2E tests, follow these rules to reduce CI flakiness:

1. **Prefer stable signals over transient text**:
   - Avoid asserting countdown text or short-lived status labels (e.g. `3`, `2`, `1`, `Uploading...`).
   - Prefer durable prompts, control visibility/enabled state, URL changes, or trial events.

2. **Avoid overly strict DOM shape assumptions**:
   - Do not rely on exact element counts/styles unless they are guaranteed by the experiment contract.
   - Prefer `at least one`, role-based selectors, IDs, and semantic assertions.

3. **Use event evidence in stable ways**:
   - Avoid live polling of `psynet.trial.eventLog` with strict timing windows in E2E tests; this is prone to CI timing variance.
   - Prefer durable submit-time evidence: assert successful `POST /response` increments after key actions.
   - If event assertions are needed, read them from submitted `metadata.event_log` payloads at submit boundaries and check coarse presence/order only.

4. **Treat auto-advance pages as optional checkpoints**:
   - If a page can auto-advance quickly, verify it only if present.
   - If already advanced, continue by advancing to the next stable prompt instead of failing.

5. **Do not use force-click unless strictly necessary**:
   - Use normal `click()` with visibility/enabled checks first.
   - Use forced clicks only for known framework overlays or non-actionability edge cases.

6. **Keep media assertions resilient**:
   - For playback, detect either active PsyNet sounds or real DOM media playback.
   - For staged blobs, assert strongly only when lifecycle guarantees availability; otherwise use best-effort checks and rely on downstream UI/event evidence.

7. **Centralize shared navigation logic in harness helpers**:
   - Reuse `psynetHarness` helpers for gateway-page clearing, next-button waits, and prompt advancement.
   - Add new shared helpers when a robust pattern appears in multiple specs.

8. **When fixing flakes, update both test comments and docs**:
   - Keep per-test section comments aligned with what is actually asserted.
   - Document new anti-flakiness patterns in dev docs/AGENTS when they become standard practice.

9. **Prefer deterministic step-by-step flows when the timeline is fixed**:
   - If experiment steps are known in advance, encode the exact sequence of expected prompts/actions.
   - Avoid heuristic navigation (`try-next`, broad fallback selectors, generic loops) for deterministic demos.
   - Treat mismatches as test failures, not as recoverable branches.

10. **Separate page-type handling explicitly**:
    - Gateway/ad pages, consent pages, and timeline pages have different DOM/state behavior.
    - Use page-specific assertions/selectors for each type; do not assume timeline containers (e.g. `#main-body`) exist everywhere.

11. **Use fail-fast synchronization tied to the expected transition**:
    - After each action, wait for the exact intended effect (expected text, expected control state, expected URL/page transition).
    - Prefer short bounded waits on deterministic invariants over long generic polls.

12. **Assert playback/recording via the actual implementation path**:
    - For `AudioPrompt`, verify PsyNet sound-state/event transitions instead of DOM `<audio>` elements.
    - For `VideoPrompt`, verify `video#prompt` playback behavior.
    - Align assertions with how that step is implemented in experiment/template code.

## Automatic code review

Before finalizing a merge request, prompt the user to run an automatic code
review. Suggest the repo-local Cursor command `/branch-review`, which invokes
the `branch-review` skill at `.cursor/skills/branch-review/SKILL.md`. This
specific command name avoids ambiguity with generic Cursor-provided review
commands.

If the user runs `/branch-review`, address any actionable findings before
finalizing the merge request. If the user declines or the review is not run,
record that explicitly in the merge request description.

## Merge request descriptions

Use `.gitlab/merge_request_templates/Default.md` as the template.
Write for experiment authors, not only for maintainers: prefer plain language
over internal jargon, and include short code examples when the change affects
a public API or migration.

## CLI development

Use Click for new and refactored command-line interfaces, following the
project's existing command patterns.

## Simplification and refactoring

When a change seems to require adding substantial new code, pause to consider
whether package functionality or behavior can be simplified instead. Prefer
solutions that avoid unnecessary code growth, remove obsolete code, or reuse
existing abstractions, and call out promising refactoring opportunities to the
user when they are relevant.

## Testing

Non-trivial code changes should be tested.
Prefer red/green test-driven development, but avoid committing overly verbose tests in the final PR.
Implement sensible unit tests where appropriate.
Verify changes end-to-end by running `psynet test local` within a relevant demo.
Prefer concise tests that exercise real/public interfaces.
Avoid very long tests with extensive monkeypatching unless there is no practical
alternative; if monkeypatching is necessary, keep it minimal and focused on
observable behavior rather than internal implementation details.

## Code organization and documentation

- Prefer marking module-internal helper functions with a leading underscore. Keep public-looking names for functions that are intended to be imported or called from outside the module.
- When adding a feature that operates heavily within a module and that module lacks an explanatory module docstring, add one. The docstring should explain why the module exists, the important design constraints, and how maintainers should interact with it. When you add such a docstring, explicitly suggest that the user reviews it.
- When adding or changing documentation, use Sphinx-native cross references for internal documentation and API links. Prefer roles such as `:doc:`, `:ref:`, `:class:`, `:func:`, and `:meth:` over raw relative `.html` links so links remain valid across builders and directory moves. If a URL must be ignored by linkcheck, keep the ignore pattern as narrow as possible and document why.

## Error handling policy

Avoid silently suppressing broad exceptions (for example `except Exception: pass`).
If a broad exception must be caught for resilience, emit at least a warning-level log
with useful context unless the path is intentionally noisy best-effort cleanup.

## Database migrations

We assume PsyNet experiments are short-lived and their databases do not need
to persist across PsyNet version upgrades. As a result, avoid complicating
code to support database migrations or backward-compatible schema changes.

## Docstrings

Prefer including function docstrings. Short docstrings are fine; often a brief
descriptive summary line is sufficient.

## Finishing up changes

When you make changes to the PsyNet codebase:

1. **Add a changelog fragment**: Pull requests should include one or more fragment files in `changelog.d/` instead of editing `CHANGELOG.md` directly. Create a fragment with the helper command:

   ```bash
   psynet dev changelog new <category> "<short description>"
   ```

   `<category>` is one of `breaking`, `added`, `changed`, `deprecated`, `removed`, `fixed`, `updated`, or `documentation`. The helper writes a fragment `changelog.d/<YYYYMMDD>-<slug>.<category>.md` containing your description as a stub, which you then edit to the final entry (e.g. `Added support for X.`). Do not include author or reviewer metadata in changelog fragments. End each entry with a period. The date prefix keeps fragments roughly chronological and the slug makes them descriptive at a glance; same-day collisions are caught by the helper, in which case use a more specific description. Each entry should summarize the overall user-facing change rather than the incremental process of building it. Do not describe undoing, reverting, or revising content that was created earlier in the same merge request; describe only the final result that the merge request delivers.

   Do **not** commit a regenerated `CHANGELOG.md` from your MR — `CHANGELOG.md` is a generated artifact, rebuilt by the maintainer at release time. Committing fragments only avoids merge conflicts on `CHANGELOG.md` between MRs. Run `psynet dev changelog preview` locally from a PsyNet source checkout if you want to preview how the fragments will render; it prints the preview to stdout and leaves `CHANGELOG.md` unchanged. Maintainers cut a release from a PsyNet source checkout with `psynet dev changelog release <version> <date>`, which consumes fragments and inserts a versioned section. Alpha versions do not get changelog release sections. Stable releases consume matching beta/release-candidate sections plus any remaining fragments.

   If you push directly to `master` (bypassing an MR), CI won't check for a fragment — but please still create one with `psynet dev changelog new` so the change appears in the next release notes.

2. **Run pre-commit**: Before committing, run pre-commit to ensure code formatting is correct:

   ```bash
   export PATH="/home/ubuntu/.local/bin:$PATH"
   pre-commit run --all-files
   ```

   If pre-commit is not installed, install it first with `pip3 install pre-commit`.

3. **Commit and push**: Commit all changes including changelog fragments (but not a regenerated `CHANGELOG.md`) and any pre-commit formatting fixes.
