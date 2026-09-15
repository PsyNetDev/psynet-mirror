# CHANGELOG

## [13.3.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v13.3.0) Release - 2026-07-07

### Added

- Refactored timeline to use named branches for end logic. `Timeline.elts` is now a dict of named branches (`main`, `successful_end`, `unsuccessful_end`, `rejected_consent`). `elt_id` now starts with the branch name (e.g. `["main", 3]`). `EndPage` classes are now redirect elements instead of `PageMaker` wrappers. `participant.fail()` automatically redirects to the `unsuccessful_end` branch unless the participant is already in an end logic branch or already completed.
- Added `psynet dev experiments update` as the source-checkout command for updating bundled demo and test experiment files, including a `--skip-constraints` option for faster non-constraints updates.
- Added an ASV performance benchmark suite (demo experiment performance tests
  and serialize/deserialize micro-benchmarks). A CI job publishes rendered
  graphs to GitLab Pages alongside the docs, and an `asv_regression` job fails a
  merge request when `asv continuous` finds a significant regression between its
  merge base and branch tip.
- Added a two-participant Playwright test for the chatrooms demo that verifies live message relay and persisted chat history.
- Added support for agent-assisted PsyNet releases via a repo-local release skill and a `psynet dev release announce` command.
- Added a `chatroom_simple` demo showing a minimal real-time chatroom built with the high-level `ChatRoom` component and a synchronised trial maker.
- Added a `Trial.sync_group` property that returns the `SyncGroup` matching the trial maker's `sync_group_type`, giving a multi-group-safe alternative to `participant.sync_group`.

### Changed

- Refactored chain network growth to use live readiness queries instead of the cached `ready_to_spawn` flag, added non-blocking polling for within-chain growth, and normalized graph-chain topology into SQL vertex/edge tables.
- Temporarily allowed the ASV regression CI job to fail while benchmark reliability is improved.
- Changed ASV CI so merge requests run only benchmarks under `benchmarks/fast/` as the regression gate, while default-branch CI runs the full benchmark suite with `asv continuous` before publishing results.
- Updated demo regeneration so post-release alpha versions keep demo and test experiment dependencies pointed at the `master` branch.
- Fixed `/review` skill to diff against `origin/master` instead of stale local `master`, preventing inflated diffs that include changes already on master.
- Sync barriers now use a database-backed registry with per-barrier processing and serialized release callables to improve multi-process coordination.
- Changed performance test summaries to include median response times alongside requests per second.
- Updated CI so full ASV benchmark regressions are reported without blocking master pipelines, and made Heroku CLI installation fail fast when unavailable.
- Added regression coverage for nested transaction session reuse and commit behavior.
- Made SerializedCallable keyword-only for participant/experiment arguments to prevent positional misuse.
- Moved the multi-room chatrooms demo from `demos/experiments/chatrooms` to `demos/features/websocket_chatroom`.
- Updated the rock-paper-scissors demo and the chatroom and synchronization tutorials to derive a chatroom `room_id` from the new `Trial.sync_group` property instead of `participant.sync_group`, which is unsafe when a participant belongs to multiple sync groups.
- Reworked `psynet dev release announce`: the experimenter-facing changes summary is now written by the release manager and passed via `--summary-file` instead of being selected from the CHANGELOG by keyword patterns (which missed recruiter changes and included maintainer tooling), long summaries are split across Slack blocks (fixing `invalid_blocks` errors), announcements are posted to a testing channel for review before the real broadcast, and messages got a visual refresh (link buttons, emoji category headers, vertical spacing between category sections, and a logo footer).

### Deprecated

- Deprecated Asset.set_keys in favor of ensure_keys_and_paths.

### Removed

- Removed support for Prolific screen-out payments because Prolific no longer supports the screen-out API route.

### Fixed

- Two substantial performance optimizations for graph-based experiments.
- Fixed a Playwright audio demo flake by centralizing PsyNet page-loaded synchronization before timeline consent clicks.
- Fixed `AsyncCodeBlock` raising `RuntimeError: Participant already has an async code block process pending, this shouldn't happen.` when a participant re-entered an `AsyncCodeBlock` while a previously finished or failed process was still attached. `AsyncCodeBlock.initiate` now logs a warning and clears the stale reference instead of crashing, so participants no longer get stuck (e.g. inside the Prolific failed-participant `wait_for_assignment_return` loop).
- Fixed graph demo `generate_grid` returning `blocks` instead of `groups` for the `participant_groups` key in the network structure, and added `choose_participant_group` support to `GraphChainTrialMaker`.
- Fixed PsyNet custom SQL table polymorphic discriminator columns to use flexible string lengths, avoiding truncation errors for fully qualified polymorphic identities longer than 50 characters. (author: [Peter Harrison])
- Fixed PsyNet's `jsonpickle` usage to pass the `keys` option explicitly, avoiding deprecation warnings that could fail tests when warnings are treated as errors.
- Exported request parameters as plain JSON-like dict/list values to avoid jsonpickle `py/object` payloads in database exports.
- Fixed CI Docker constraints generation, Chrome installation, and browser startup when local Chrome binaries are available.
- Fixed serialized callables to receive participant and experiment context when invoked through PsyNet's context helper.
- Allow `psynet export ssh` to omit `--app` by selecting the running app on the server.
- Prevent deposited assets from changing storage identity when re-linked, and ensure undeposited assets adopt current parent metadata, including finalize_assets behavior.
- Added early app-exists checks for `psynet deploy ssh` and `psynet debug ssh`.
- Prevented `Trial.check_if_can_mark_as_finalized()` from finalizing incomplete trials by requiring `trial.complete` before finalization checks proceed.
- Fill missing parent/link metadata for deposited assets so external asset export paths remain unique.
- Fixed `--stagger` value not being passed in SSH test and performance-test commands.
- Stabilized S3 storage tests by using local mocking for the boto3 backend and unique prefixes for AWS CLI integration checks.
- Refactored Selenium Chrome-driver setup into `psynet.testing.chrome_driver`, preserved retry-based launch resilience, restored CI chromedriver pinning to avoid Selenium Manager network hangs, and emitted startup diagnostics to stdout for CI triage.
- Fixed translation test mock translations to preserve variable placeholders.
- Fixed `get_translator()` failing when called from a top-level script without a package context.
- Loaded the generated runtime server configuration before exporting local debug data.
- Raised a clearer error for experiment directory import-name collisions.
- Fixed the end-page "Finish" button showing an untranslated English label in non-English locales; the visible label is now translatable while the recorded answer value stays "Finish".
- Fixed Prolific return-for-bonus checks so transient return-status lookup failures no longer fail the participant flow.
- Fixed waited async code blocks so participants who re-enter the same pending async code block process wait for the existing process instead of starting a duplicate.
- Fixed Prolific unread message notifications so recruiter checks no longer crash when combining multiple notification lines.
- Recorded returned Prolific assignment status in the return-for-bonus flow.
- Fixed Prolific unread-message checks when message field names differ from the documented response shape.
- Skipped scheduled experiment status recording until experiment launch has finished.
- Stabilized the create-and-rate gap demo test by balancing trial assignment and asserting durable chain growth outcomes.
- Mocked S3 access in the static audio preparation test.

### Documentation

- Documented contributor guidance for using Click in command-line interfaces, seeking simplifications before adding substantial code, writing changelog fragments without author attributions that summarize only the final merge-request result, and understanding the ASV performance-testing setup.
- Integrated the ISMIR 2025 PsyNet tutorial: added the tutorial chapters under `docs/getting_started/`, added the companion `demos/features/pages` and `demos/features/timeline` demos, added the tutorial pipeline demos under `demos/pipelines/`, and included `psynet-step` in the demos extra so the `step_tag` pipeline runs in CI.
- Fixed stale demo paths in the documentation.
- Added a developer docs build command with live preview support.
- Removed the version number from the documentation title and simplified the alpha version switcher label.
- Added a repo-local refactor Cursor skill for maintainability-focused PR review guidance.
- Removed changelog reminder from AGENTS.
- Documented the standard merge request description format for PsyNet agent work.
- Clarified how Prolific base payments, bonuses, and partial payments are handled.
- Documented that agents should prompt users to run `/branch-review` before finalizing merge requests.
- Added a repo-local Cursor skill for debugging deployed PsyNet test experiments via the dashboard and Dozzle logs.
- Filled gaps in the API reference, documenting `AsyncCodeBlock` and other timeline constructs, the end-logic classes, and `AudioForcedChoiceTest`, and fixed several broken cross-references.
- Deployment-test skill (renamed from `debug-deployment-test-experiments` to `deployment-test`): test deployments now use a fresh branch per deployment based on the latest release tag, refresh experiment scripts via `psynet update-scripts`, and keep log ZIPs and raw logs out of git. `tests/manual_recruiter_testing` is now included in `list_experiment_dirs()` so release tooling keeps its template scripts up to date, while remaining excluded from CI test runs.
- Release skill: minor releases now default to a release-candidate flow, release commits stage explicit paths to avoid sweeping in unrelated local files, the publish steps verify that the tag's documentation is deployed and reachable from the docs version dropdown, GitLab release titles omit the tag's `v` prefix, release candidates are now tag-only on GitLab (no release entry), since GitLab lacks a pre-release flag, the docs version switcher labels prereleases in the same style as the alpha entry (e.g. `13.3.0 rc0`), and release candidates are numbered starting from `rc1`.

## [13.2.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v13.2.0) Release - 2026-05-26

### Added

- Added documentation builds for release-candidate / alpha tags, published at `/rc/<tag>/`, with the new RC visible in the version switcher from every deployed subdir.
- Added ``demos/experiments/chatrooms`` demo: real-time multi-room chat using
  Dallinger's WebSocket relay, with server-side message persistence, occupancy
  broadcasts, and a REST endpoint for chat history.
- Enabled chatroom to Rock, Paper, Scissors demo results page.
- Added `ChatRoom` element for modular pages.
- Added optional websocket support for timeline elements.
- Added developer documentation plus a repo-local `/review` Cursor workflow backed by the `branch-review` skill for reviewing branches against `master`.
- Added SQLAlchemy profiling utilities with aggregation, CLI flags, and pytest assertions (e.g. `psynet test local --sql-profile`) plus execution callsite tracking.
- Added checks to catch cases where Assets are created in the wrong place.
- Added Playwright (JS) end-to-end tests for audio, graphics, imitation_chain_video, and static_audio demos, plus the video feature demo.
- Added a dedicated `playwright_e2e` GitLab CI job to run Playwright demo tests and publish JUnit, Playwright HTML report, and backend logs as artifacts.
- Improved 'basic data' functionality:
  - Basic data is now included by default in PsyNet exports.
  - Added support for CSV-format basic data export.
  - Added basic data export examples to the demos.
- Added regression test to ensure Jinja gettext extraction is captured.
- Added demo/docs example for random sync group role assignment after sorting participants.
- Added WaitPage time stats (median/95th/max) to performance test results.
- Added AsyncProcess duration stats (avg/median/p95/max by trial maker) to performance test results.
- Added async process queue delay tracking (`time_enqueued`, `queue_delay` on `AsyncProcess`) with Q Share metric highlighting bottlenecks.
- Added trial count stats (min/median/max) for succeeded bots in performance test results.
- Added scaling slowdown comparison (vs baseline) in cross-test performance summary.
- Added requests/sec throughput metric to performance test results.
- Added bot initialization time distribution (median/p95/max) to per-test detail reporting.
- Added detection and reporting of bots that started but never created DB participant records.
- Added RQ worker count display in async process times section for context on queue delays.

### Changed

- Migrated Python linting and formatting from black/isort/flake8 to Ruff, including pre-commit and contributor documentation updates.
- `GraphChainTrialMaker` now accepts vertex-based blocks and participant groups via the `network_structure` argument.
- Reformatted CHANGELOG and configured CHANGELOG linter.
- Removed deprecated `initial_recruitment_size` attribute from all demo and test experiment classes. This attribute should now be set via `config.txt` or `experiment.config` instead.
- Renamed version-checking helpers in `psynet/version.py` for clearer intent.
- Updated IDE recommendations in documentation to recommend VSCode/Cursor as the default IDE instead of PyCharm. PyCharm is now mentioned as an alternative with warnings about debugging issues. Removed detailed PyCharm setup instructions that may become outdated, and removed PyCharm debugger references from Dockerfiles.
- Refactored timeline page JavaScript into standalone `psynet.js` with template-driven JSON bootstrap data, preserving initialization order for prompt/control scripts and Lucid termination hooks.
- Updated GitLab CI configuration to auto-cancel redundant pipelines when new commits are pushed to a branch that already has a running pipeline.
- Expanded Playwright demo coverage to perform real UI interactions (controls, recording, playback, event-log assertions) across audio, graphics, imitation_chain_video, static_audio, and video_feature demos.
- Added Playwright failure diagnostics and artifacts (screenshots, traces, videos, JUnit/HTML reports) and stabilized visual snapshots for the audio demo.
- Updated S3 test code to use proper mocking and hence avoid conflicts between testing processes.
- Replaced the moto-backed S3 emulator with a minimal filesystem-backed mock for targeted S3 artifact-storage tests, while moving broader backup coverage back to a local-storage test path and removing the `moto` dependency from the test environment.
- Switched docs deployment to the PyData Sphinx theme for the current alpha docs and future release docs, and updated versioned publishing to build each docs version from its own git ref.
- Updated `docs/scripts/generate_version_switcher.py` to always read the alpha version from `origin/<default_branch>` instead of falling back to the local checkout.
- Improved performance-test summary table: replaced Completed/Bot Errors columns with Succeeded/Errored/Terminated, and response time columns with median/95th/max.
- Separated bot duration tracking by outcome (succeeded/failed/incomplete) in performance test results.
- Redirected bot output to dedicated logfile, keeping console output minimal during performance tests.
- Improved performance test output: tabulate-based tables, AsyncProcess duration stats, ANSI-colored headers/success rates, and reorganized per-test detail reporting.
- Refactored performance test code from `experiment.py` into standalone `psynet/perf_test.py` module with `PerformanceTester` class.
- Updated `@playwright/test` from 1.58.2 to 1.60.0 (Chromium 148.0.7778.96).
- Switched audio-tooling demo dependencies from private GitLab git URLs to public PyPI releases: `repp` + `reppextension` are now installed via `repp-tapping==1.4.0` (which bundles `reppextension` as a deprecated compatibility shim) and `sing4me` via `sing4me==2.0.0`. The `[demos]` extra declares both directly and the Dockerfile no longer needs the private-deps install step.
- Refactored the docs `pages:` GitLab CI job: extracted the inline shell into `docs/scripts/build_pages.sh` (the CI job is now a thin wrapper) and tidied `docs/scripts/generate_version_switcher.py`. The branch pipeline now also rebuilds the latest active prerelease into `public/rc/<tag>/` and prunes stale `public/rc/` subdirs once their base ships stable, so the site only ever advertises a currently-pending release candidate.
- Marked the highest stable release as `"preferred": true` in the version switcher, so pydata-sphinx-theme preselects it as the canonical version and renders a "switch to vX.Y" banner on alpha, rc, and older stable subdirs.
- Introduced a changelog-fragments workflow under `changelog.d/` to eliminate `CHANGELOG.md` merge conflicts between MRs. Each change now ships as a small markdown fragment, and `CHANGELOG.md` is generated from those fragments at release time. Highlights:
  - Added the source-checkout-only `psynet dev changelog` command group, with `preview` to render fragments without changing files, `new <category> "<description>"` to create a date-prefixed fragment, and `release <version> <date>` to fold fragments into a versioned `CHANGELOG.md` section.
  - Wired GitLab's merge-request changelog check through the installed `psynet dev changelog check-mr` command so CI validates fragments through the same source-checkout command path as maintainers.
  - Supported categories follow Keep a Changelog ordering: `breaking`, `added`, `changed`, `deprecated`, `removed`, `fixed`, `updated`, `documentation`. Empty sections are skipped in the rendered output.
  - Removed the in-progress `## Unreleased` section from `CHANGELOG.md` so future MRs don't conflict on it.
  - Tightened the GitLab `changelog_check` CI job to enforce two rules on normal MRs: (1) the diff must touch a date-prefixed fragment file, and (2) `CHANGELOG.md` must not be edited directly. Release branches are exempt because they regenerate `CHANGELOG.md` from fragments.
  - Documented the workflow, contributor expectations (commit only fragments, never a regenerated `CHANGELOG.md`), and the date-prefixed fragment convention in `AGENTS.md` and `changelog.d/README.md`.

### Removed

- Removed unused participant scope aliases (`participant.globals`, `participant.locals`) and stopped flattening module-local variables into `Participant.to_dict()` exports; these removed APIs now raise explicit runtime errors with replacement guidance to use `participant.var` or `participant.module_state.var`.
- Removed redundant `ModuleState.var` override in favor of the shared SQL mixin `var` property.
- Removed redundant `logging.basicConfig(level=logging.INFO)` and root logger initialization from demo/test experiment scripts where they were unused.
- Removed unused `remove_unused_translations_po` helper from translation utilities.
- Removed unused `assert_all_variables_defined` helper from translation checks.
- Removed unused `import_module` helper from utils.
- Removed unused `get_package_locales_directory` helper from utils.
- Removed unused `pretty_log_dict` and `query_yes_no` helpers from utils.
- Removed unused `DisableLogger` helper from utils.
- Removed unused `LANGUAGES_WITHOUT_CAPITALIZATION` constant from translation checks.
- Removed unused `format_hash` and `hash_object` helpers from utils.
- Removed `strip_url_parameters` and custom `cache` helpers from utils in favor of standard library usage.
- Removed unreachable code after error raises in asset/serialization helpers.
- Removed the PgBadger CI job and related reporting scripts.
- Removed `dict_to_js_vars` as it is no longer used anywhere in code.
- Removed the unused `bump-my-version` dev dependency and the corresponding `.bumpversion.toml` config; the release process edits the three version files manually.

### Fixed

- Fixed flaky Selenium test failures caused by transient Chrome startup crashes (`SessionNotCreatedException`) by adding retry logic to the bot WebDriver initialization.
- Stabilised flaky Playwright demo tests `audio.spec.js` and `imitation_chain_video.spec.js`.
- Stabilised flaky Playwright `video_feature.spec.js` demo by waiting for the initial auto-recording cycle to finish before clicking "Record from start".
- Corrected pybabel Jinja keyword config so gettext and pgettext extraction works on Babel 2.18+.
- Installed demo dependencies via the `demos` extra and Dallinger constraints extras (Docker/CI), avoiding RequestsDependencyWarning from unpinned transitive packages.
- Disallow PsyNet requirements pinned to master in deployment prechecks, and clarify version-check failures with explicit ValueError messages.
- Replaced third-party `cached_property` package with Python's built-in `functools.cached_property`, fixing a `ModuleNotFoundError` on Python 3.13 after Dallinger removed the package from its dependencies.
- Fixed `changelog_check` CI job failing on merge requests (SIGPIPE when piping to grep).
- Added CI test to verify translations are up-to-date on release branches without calling translation APIs; duplicate translation warnings are printed but don't fail the test.
- Included `tests/isolated/translation/` directory in CI test runs.
- Fixed `CI` environment variable not being passed to Docker container in CI, causing `@local_only` tests to run incorrectly.
- Fixed `@local_only` and `@ci_only` pytest decorators by changing condition from `os.environ.get("CI")` to `os.environ.get("CI") is not None` to ensure a boolean result.
- Fixed `test_translator_with_file_path` to use `{NAME}` instead of `■0■` since `ChatGptTranslator` has `use_codebook=False`.
- Fixed `test_warnings` to filter out external service warnings (e.g., Heroku CLI terms of service notices and Node launch warnings).
- Standardized "Abort Experiment" to "Abort experiment" in templates for consistent capitalization and removed obsolete translation entries from PO files.
- Removed prompt text from prompt metadata to avoid large export file sizes.
- Suppressed forkpty DeprecationWarning in pytest configuration.
- Exported datetimes in database exports as readable strings to avoid jsonpickle formatting.
- Fixed performance-test summary crashes for short runs by handling missing response metrics and zero-success-rate denominators gracefully.
- Fixed performance-test local startup and teardown by launching via `psynet debug local`, loading runtime server credentials, and improving subprocess shutdown behavior.
- Fixed performance-test server logs not capturing full output by draining pexpect process in background thread.
- Fixed variable shadowing of builtin `error` in `dashboard_errors` method.
- Restricted wait-page time and trial count stats to succeeded bots only in performance test results.
- Renamed the experiment status payload key to `launch_time` to avoid overwriting row timestamps.
- Added automatic check during Docker deployment to detect missing or outdated Dockerfile format. Dockerfiles are now mandatory for all Docker deployments, and error messages guide users to run `psynet update-scripts` with appropriate warnings.
- Fixed chain trial makers to keep block state consistent when advancing blocks after depletion, consolidating block-state updates.
- Added validation to ensure `ChainTrialMaker` start nodes are instances of `node_class`, preventing silent fallback to base-class behavior when subclasses are expected.
- Fixed Playwright harness experiment lifecycle and teardown to reduce stale-process/port conflicts, while keeping legacy mode optional via environment flag.
- Fixed SliderControl to re-register minimal-interaction gating on `trialPrepare`, so pages that call `psynet.trial.restart()` can re-enable submit/next correctly after slider interaction.
- Added richer Playwright next-button timeout diagnostics (prompt text, event tail, control state) to speed up CI failure triage.
- Fixed `generate_text_file` to write the provided text argument instead of a hardcoded default.
- Fixed `join` to accept list/tuple inputs so `join(pages)` works when assembling timeline components such as `AsyncCodeBlock`.
- Fixed malformed Sphinx cross-reference in `SliderCopyTrial` docstring with extra backticks and wrong module path (should be `dense` not `main`).
- Fixed incorrect Sphinx cross-reference in `MediaImitationChainTrial` docstring missing the `record` module in the path.
- Fixed incorrect Sphinx cross-references in `AudioImitationChainTrial` and `CameraImitationChainTrial` docstrings pointing to non-existent `audio_imitation_chain` and `video_imitation_chain` modules.
- Fixed incorrect type hint `mode: bool` in `deployment_info.init` that should be `mode: str` since mode values are strings like "debug", "sandbox", "live".
- Fixed incorrect property name `self.job` in `WorkerAsyncProcess.cancel` that should be `self.redis_job`, which would cause an `AttributeError` when trying to cancel an async process.
- Fixed resource type mismatch in `Notifier` where `"memory"` was used instead of `"ram"`, causing worker process info to be missing from RAM usage notifications.
- Fixed indentation bug in `GroupBarrier.choose_who_to_release` where only the last participant was added to release list instead of all participants when group is below minimum size.
- Fixed incorrect octave ratio in `StretchedTimbre` docstring: should be 2.1 rather than 2.0, not 2.0 rather than 1.9.
- Fixed missing f-string prefix in `LucidService.remove_default_qualifications_from_survey` error message, causing literal `{response.status_code}` instead of actual values.
- Fixed incorrect Sphinx cross-references in `MediaImitationChainNode` and `CameraImitationChainNode` docstrings pointing to wrong module paths.
- Fixed incorrect `super().encode()` call in `NumpySerializer.default` for `np.bool_` types; should return `bool(obj)` like other numpy types.
- Fixed `Participant.fail` passing wrong argument to fail routines where `experiment=self` should have been `experiment=exp`.
- Fixed quote escaping issue in `SVGLogo.html` where nested double quotes in `onclick` handler produced invalid HTML.
- Fixed incorrect use of `os.path.remove` instead of `os.remove` in `RecordTrial.async_post_trial`.
- Fixed Unicode typo in `UnityPage` docstring where `Ín` used an accented character instead of ASCII `In`.
- Fixed Unicode typo in `HouseholdIncomePerYear` demography page where `ĺess_than_10000` used a special character instead of ASCII `less_than_10000`.
- Fixed missing `@classmethod` decorator on `_PythonList.serialize` and `_PythonDict.serialize` methods in `psynet/field.py`.
- Fixed `get_package_name` to read metadata from the provided path.
- Fixed bug in `VocabTrial.show_feedback` where `self.show_feedback` (the method) was checked instead of `self.trial_maker.show_feedback` (the boolean attribute), causing feedback to be shown even when disabled.
- Fixed `Trial.cue` asset registration to deposit assets before generating keys, preventing missing `deployment_id` errors.
- Fixed bug in `translation_contains_same_variables` where only the first variable check (Jinja pattern) was evaluated due to an early return inside the loop, causing f-string, format string, and HTML tag checks to be skipped.
- Fixed potential `UnboundLocalError` in `_experiment_variables` when cursor creation fails.
- Fixed `linspace` to handle single-length requests without division by zero.
- Fixed `dict_to_js_vars` to serialize quotes safely and handle empty inputs.
- Fixed `format_timedelta` to return meaningful output for zero and negative durations.
- Fixed `get_fitting_font_size` to return the last size that fits within bounds rather than the first size that overflows.
- Fixed `get_package_source_directory` to handle setuptools `where` lists in pyproject files.
- Fixed `get_locales_dir_from_path` to resolve locales relative to the provided path rather than the current working directory.
- Fixed `get_package_source_directory` to resolve paths relative to the provided package root.
- Fixed `check_translations` to resolve the package namespace from the provided path.
- Fixed translation validation to report missing entries before variable-mismatch checks.
- Fixed `S3Storage.list` to honor `top` and `extension` filters.
- Fixed `pretty_format_seconds` to avoid rounding to 60 seconds instead of rolling into the next minute.
- Hardened Playwright demo tests against flaky timeline transitions by replacing brittle exact-count/transient-text assertions with event/baseline waits and tolerant auto-advance handling across audio, graphics, static_audio, imitation_chain_video, and video_feature specs.
- Replaced bare `assert response.ok` in Lucid API calls with informative error messages that include the HTTP status code, URL, and response body.
- Fixed Playwright browser download timeout in CI by copying the browser cache from the official Playwright Docker image at build time (cdn.playwright.dev is unreachable from CI runners).

### Documentation

- Expanded Windows/WSL installation guidance with quick-start steps, WSL notes, and audio troubleshooting based on Haoyu Hu's guide.
- Clarified AGENTS setup for Dallinger auth and local environment bootstrapping.
- Added Playwright anti-flakiness guardrails to `AGENTS.md` so future E2E tests use stable selectors/events and auto-advance-safe assertions.
- Clarified Dallinger fork workflow steps around auth, upstream sync, and pg_config failures.
- Clarified system dependency checks and PostgreSQL password guidance in experiment scripts AGENTS.md.
- Streamlined API documentation structure and reduced Sphinx warnings.
- Simplified documentation navigation and reference links.
- Documented GitLab CI status checks and token guidance for agents in AGENTS.md.

## [13.1.1](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v13.1.1) Release - 2026-02-18

### Fixed

- Fixed browser "Leave page?" popup appearing at the end of experiments when redirecting participants to the recruiter. Added `skip_beforeunload` attribute to Page classes and set it to `True` on `ExecuteFrontEndJS` (author: Frank Höger)
- Removed stale `deploy/prolific` toctree entry from docs that pointed to a page that no longer exists (author: Frank Höger)

## [13.1.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v13.1.0) Release - 2026-02-17

### Added

- Added automatic SSH known_hosts management during deployment. The remote server's host key is now added to `~/.ssh/known_hosts` before any SSH connections are made, so users no longer need to manually SSH to the server first (author: Frank Höger, reviewer: Peter Harrison)
- Added ``make_next_definition`` method to streamline the implementation of chain experiments.
  We have done this in a back-compatible manner and left existing dependencies unchanged for now.
  We have added a demo of the new approach called `chain_trial_maker`.
  More documentation will be added soon when we incorporate the ISMIR 2025 tutorial into
  the main PsyNet documentation (author: Peter Harrison, reviewer: Frank Höger)
- Added `AGENTS.md` to help Cursor know how to run experiments locally (author: Peter Harrison, reviewer: Frank Höger)
- Added `psynet locales` command to list supported translation locales (author: Frank Höger, reviewer: Peter Harrison)
- Added check for empty translations in `check_translations` (author: Frank Höger, reviewer: Peter Harrison)
- Added default ``.vscode/extensions.json`` and ``.vscode/settings.json`` to experiment scripts,
  to aid with configuring VSCode (author: Peter Harrison, reviewer: Frank Höger)
- Added 'getting started' section to documentation (author: Peter Harrison, reviewer: Frank Höger)

### Changed

- Updated for the removal of the sqlalchemy-postgres-copy package in Dallinger 12.0.0 (author: Frank Höger, reviewer: Peter Harrison)
- Updated bot `sign_up` method to extract participant identifier (unique_id/participant_id) from URL to comply with Dallinger v12.x.0 bot validation requirements (author: Lucas Gautheron, reviewer: Peter Harrison)
- Made LabRecruiter `external_submission_url` configurable via experiment config key `lab_recruiter_external_submission_url` (author: Frank Höger, reviewer: Peter Harrison)
- Renamed `CapRecruiter` to `LabRecruiter`, incl. all variations thereof (author: Frank Höger, reviewer: Peter Harrison)
- Renamed `incoming_vertex_ids` to `dependent_vertex_ids` in graph networks (author: Lucas Gautheron, reviewer: Peter Harrison)
- Optimized experiment Dockerfiles for greater build speed. The resulting Dockerfiles no longer use a PsyNet base image.
  To update existing experiment scripts, update PsyNet, then run `psynet update-scripts` in the experiment directory (author: Peter Harrison, reviewer: Frank Höger)
- Removed `deploy_docker` CI job that pushed PsyNet Docker images to the GitLab registry. The `pages` job now installs PsyNet from source instead of using a pre-built Docker image. This is part of the broader deprecation of the Docker installation route (author: Frank Höger, reviewer: Peter Harrison)
- Improved Lucid termination logging: intent is logged before the API call, and RID is included in all messages (author: Frank Höger)

### Deprecated

- Deprecated Docker installation route in favor of the standard virtual environment method (author: Peter Harrison, reviewer: Frank Höger)

### Fixed

- Fixed TODO scan to skip virtual environments and tolerate non-UTF-8 files (author: Cursor, reviewer: Peter)
- Fixed `psynet.debugger()` crashing with `RuntimeError: debugpy.listen() has already been called on this process` when hitting the breakpoint more than once per session. `debugpy.listen()` is now only called on the first invocation (author: Frank Höger, reviewers: Peter Harrison, Frank Höger)
- Fixed debugger `launch.json` path mapping using `${env:PWD}` which resolved to the wrong directory in multi-root workspaces, causing Cursor to open a nonexistent file instead of the experiment's `experiment.py`. Changed to `${fileDirname}` across all demos, tests, and the experiment template (author: Frank Höger, reviewer: Peter Harrison)
- Fixed version check message being printed twice (author: Frank Höger)
- Fixed bug where `psynet export` never downloaded source code due to incorrect `--no-source` flag definition (`flag_value` instead of `is_flag`), causing the default value to be the string `'False'` instead of boolean `False` (author: Frank Höger, reviewer: Peter Harrison)
- Fixed missing source code download in non-legacy export path (author: Frank Höger, reviewer: Peter Harrison)
- Fixed `lab_recruiter_external_submission_url` config parameter being required; it is now optional with an empty string default (author: Frank Höger)
- Fixed erroneous participant termination ("user-tried-to-leave") when Unity pages reload during Lucid recruitment. Added `is_unity_page` attribute to Page classes to skip the beforeunload detection for Unity pages (author: Frank Höger)
- Removed unused method `generate_asset_key` (author: Peter Harrison, reviewer: Frank Höger)
- Improved error messages in `psynet translate` (author: Frank Höger, reviewer: Peter Harrison)
- Suppress yaspin color warnings in non-TTY environments to fix test failures in CI with `pytest -Werror` (author: Frank Höger, reviewer: Peter Harrison)
- Make `get_requirement` use `pip freeze` rather than `metadata.version` to ensure that commit hashes are available (author: Peter Harrison, reviewer: Frank Höger)
- Improve string-matching robustness in `get_requirement` (previously substrings would match, e.g. 'net' would retrieve the 'psynet' package) (author: Peter Harrison, reviewer: Frank Höger)
- Added missing `.dallinger` mapping to `docker/run` (author: Peter Harrison, reviewer: Frank Höger)
- md5 hashing now correctly ignores files whose names begin with `.` (e.g. `.DS_Store`) (author: Peter Harrison, reviewer: Frank Höger)
- Fixed bug in command-line argument validation that prevented users from accessing the one-app-per-server deployment route (author: Peter Harrison, reviewer: Frank Höger)
- Fixed bug in the propagation of the `--update` argument to the Dallinger CLI (author: Peter Harrison, reviewer: Frank Höger)
- Fixed bug in version consistency check when using a development version of PsyNet (author: Peter Harrison, reviewer: Frank Höger)
- Fixed bug that was causing `get_hardware_status` to fail (author: Peter Harrison, reviewer: Frank Höger)
- Fixed GitLab CI test failures by moving `pytest-timeout` from optional dev dependencies to main dependencies (author: Frank Höger, reviewer: Peter Harrison)
- Fixed bug in `grow_network` route (author: Lucas Gautheron, reviewer: Peter Harrison)
- Fixed bug where networks were not growing properly in graph experiments (author: Lucas Gautheron, reviewer: Peter Harrison)
- Improved performance in graph-based experiments (author: Lucas Gautheron, reviewer: Peter Harrison)
- Fixed redundant `Trial.check_if_can_mark_as_finalized` logic (author: Lucas Gautheron, reviewer: Peter Harrison)
- Fixed bug where `check_ready_to_spawn` was being called when not available (author: Peter Harrison, reviewer: Frank Höger)
- Fixed bug where in certain cases `Trial.cue` produced a sqlalchemy.orm.exc.DetachedInstanceError (author: Peter Harrison, reviewer: Frank Höger)
- Fixed bug in `update_demos.py` where `post_update_psynet_requirement` failed to update the md5sum in constraints.txt due to a mismatched regex pattern (author: Frank Höger)
- **Lucid**
  - Fixed misleading error message "No LucidRID for Lucid RID" in `get_participant` which was actually querying the Participant table; changed to warning that explains this can happen during early termination (e.g., mobile detection, wrong browser) (author: Frank Höger)
  - Fixed Lucid participants who completed the experiment being incorrectly marked as "returned" with `failed_reason=user-tried-to-leave`. This was caused by a race condition where the redirect to Lucid triggered the beforeunload event, which then called `/terminate_participant` and overwrote the completion status. The endpoint now skips termination for participants with `progress=1` (author: Frank Höger)
  - Fixed `/terminate_participant` endpoint failing with AssertionError when participant record doesn't exist in database (e.g., due to race conditions during mobile phone detection). The endpoint now extracts the assignment_id from request parameters to still call Lucid's termination API (author: Frank Höger, reviewer: Peter Harrison)
  - Fixed Lucid participants who reject consent getting stuck in "working" status. `RejectedConsentLogic` now properly terminates the participant on Lucid's side and auto-redirects them back to Lucid after 2 seconds (author: Frank Höger, reviewer: Peter Harrison)
  - Fixed Lucid recruiter `get_status` crashing with `AttributeError: 'DataFrame' object has no attribute 'client_status'` when submissions list is empty (author: Frank Höger)
  - Fixed Lucid completion handling for 403 responses: these are now expected (likely already completed via browser redirect) and marked locally, rather than logged as errors (author: Frank Höger)
  - Fixed Lucid termination handling for 403 and 400 responses: 403 (already terminated via redirect or rejected early) and 400 (RID never activated on Lucid) are now expected and marked locally, rather than logged as errors (author: Frank Höger)

### Updated

- Updated Dallinger to version 12.1.2. SSH deployments now require the `server_pem` configuration variable to be set with a path to an SSH key file. SSH agent-based authentication is no longer supported for deployments. PEM files should be stored in `~/.ssh/` directory (author: Frank Höger, reviewer: Peter Harrison)

### Documentation

- Updated translation files (`.po` files) for all supported languages using `psynet translate` to ensure consistency and completeness (author: Frank Höger, reviewer: Peter Harrison)
- Added SQLAlchemy profiling tutorial (author: Cursor, reviewer: Peter Harrison)
- Added docstrings for SQL profiling CLI helpers (author: Cursor, reviewer: Peter Harrison)

## [13.0.5](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v13.0.5) Release - 2026-02-12

### Fixed

- Fixed `psynet.debugger()` crashing with `RuntimeError: debugpy.listen() has already been called on this process` when hitting the breakpoint more than once per session. `debugpy.listen()` is now only called on the first invocation (author: Frank Höger, reviewer: Peter Harrison)
- Fixed debugger `launch.json` path mapping using `${env:PWD}` which resolved to the wrong directory in multi-root workspaces, causing Cursor to open a nonexistent file instead of the experiment's `experiment.py`. Changed to `${fileDirname}` across all demos, tests, and the experiment template (author: Frank Höger, reviewer: Peter Harrison)

### Updated

- Updated Dallinger to version 11.5.7 (author: Frank Höger)
  Read about the changes at <https://github.com/Dallinger/Dallinger/releases/tag/v11.5.7>

## [13.0.4](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v13.0.4) Release - 2026-02-05

### Fixed

- Fixed bug where `psynet export` never downloaded source code due to incorrect `--no-source` flag definition (`flag_value` instead of `is_flag`), causing the default value to be the string `'False'` instead of boolean `False` (author: Frank Höger, reviewer: Peter Harrison)
- Fixed missing source code download in non-legacy export path (author: Frank Höger, reviewer: Peter Harrison)
- Fixed bug in the propagation of the `--update` argument to the Dallinger CLI (author: Peter Harrison, reviewer: Frank Höger)
- Pin pip<26 in Dockerfile (author: Frank Höger)
- Fixed CI test failures on version tags by treating them like release branches (skip null translator) (author: Frank Höger)
- Fixed Unity WebGL pages failing with "Request cannot be constructed from a URL that includes credentials" when the page URL contained embedded credentials (e.g. when navigating from the dashboard in debug mode). The Unity template now constructs asset URLs with an origin stripped of credentials so that `fetch()` for `.wasm` and `.data` files succeeds (author: Frank Höger)

## [13.0.3](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v13.0.3) Release - 2026-01-29

### Fixed

- Fixed browser "Leave page?" popup appearing at the end of Lucid experiments when redirecting to the recruiter. Added `skip_beforeunload` attribute to Page classes and set it to `True` on `ExecuteFrontEndJS`  (author: Frank Höger, reviewer: Peter Harrison)

## [13.0.2](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v13.0.2) Release - 2026-01-27

### Fixed

- Fixed erroneous participant termination ("user-tried-to-leave") when Unity pages reload during Lucid recruitment. Added `is_unity_page` attribute to Page classes to skip the beforeunload detection for Unity pages (author: Frank Höger, reviewer: Peter Harrison)

## [13.0.1](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v13.0.1) Release - 2026-01-05

### Changed

- Disabled automatic backups (author: Frank Höger, reviewer: Peter Harrison)

### Fixed

- Fixed GitLab CI test failures by moving `pytest-timeout` from optional dev dependencies to main dependencies (author: Frank Höger, reviewer: Peter Harrison)
- Fixed documentation for `prolific_is_custom_screening` default value (`False` not `True`) (author: Frank Höger, reviewer: Peter Harrison)
- Fixed translation extraction hanging indefinitely when virtual environment directories are present in the experiment directory. The `_get_py_entries_from_dir()` function now skips hidden directories (starting with `.`) and common virtual environment directory names (`.venv`, `venv`, `.env`, `env`, etc.) to avoid processing thousands of Python library files (author: Frank Höger, reviewer: Peter Harrison)
- Added missing `config_options` parameter in `psynet deploy ssh` command (author: Frank Höger, reviewer: Peter Harrison)
- Fixed bug in Lucid (CINT) qualifications code (author: Elif Celen, reviewer: Frank Höger)

### Documentation

- Add `gettext` package to installation section (author: Frank Höger, reviewer: Peter Harrison)

## [13.0.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v13.0.0) Release - 2025-10-23

### Breaking changes

- In Prolific recruitement the base payment is now subtracted from the bonus (see 'Partial payments in Prolific recruitment' in section 'Added' below)
- Implementations of `test_serial_run_bots` in custom experiments might need to be changed as a result of the new  `BotDriver` class (see section 'Changed' below)
- Replaced `Exp.test_real_time` and `--real-time` with `Exp.test_time_factor` and `--time-factor`

### Added

- Added support for Python 3.13 (author: Frank Höger, reviewer: Peter Harrison)
- Added demo of multiple audio files in one page (author: Peter Harrison, reviewer: Frank Höger)
- Added `MonitorInformation` class to automatically collect information about the monitors (screen resolution, color depth, model number etc.); refactored `next_button` macro (author: Pol van Rijn, reviewer: Peter Harrison)
- Added opt-in functionality to leave comments on every PsyNet page (`leave_comments_on_every_page`) (useful for lab or field experiments for experimenters to leave notes) (author: Pol van Rijn, reviewer: Peter Harrison)
- Added `psynet deploy local` subcommand (author: Pol van Rijn, reviewer: Peter Harrison)
- Show audio input device on the monitor (author: Pol van Rijn, reviewer: Peter Harrison)
- Support text presentation in `VocabTest` for backward compatibility and rare and foreign scripts (author: Pol van Rijn, reviewer: Peter Harrison)
- Forward participants on the Ad page to the timeline if they already exist (author: Pol van Rijn, reviewer: Peter Harrison)
- Check if the `page_uuid` is valid and if not tell participants to reload the page (author: Pol van Rijn, reviewer: Peter Harrison)
- Added support for automatic data backups, which are now enabled by default. These backups are stored, along with other experiment metadata, in a customisable 'artifact storage repository'. By default PsyNet uses a 'local' storage repository located at `~/psynet-data/artifacts` on the experiment server, but this can be optionally changed to an S3 bucket (authors: Pol van Rijn, Peter Harrison; reviewer: Peter Harrison)
- Added support for automatic experiment notifications via Slack (authors: Pol van Rijn, Peter Harrison; reviewer: Peter Harrison)
- Added a 'Deployments' dashboard which allows the experimenter to review all studies logged in the artifact storage repository (authors: Pol van Rijn, Peter Harrison; reviewer: Peter Harrison)
- Added a 'basic data' route which can be used to serve the basic data required for scientific analyses (authors: Pol van Rijn, Peter Harrison; reviewer: Peter Harrison)
- Added rating scale prompts (`RatingPrompt`, `MultiRatingPrompt`) (author: Peter Harrison, reviewer: Frank Höger)
- Partial payments in Prolific recruitment (authors: Frank Höger, Peter Harrison; reviewer: Peter Harrison)
  - Added a `screen-out` route to make use of Dallinger's screen out functionality allowing for partial payments to participants who did not complete the whole study, e.g. participants who failed prescreening
  - Added a `partial_payment` test experiment
  - Added an experiment for manually testing Prolific recruiter deployments
- Added reporting of HTTP request time analytics when running tests (author: Peter Harrison, reviewer: Frank Höger)
- Added new `join_criterion` argument to `Grouper` allowing users to customize whether a group is `SyncGroup` is eligible to be joined (author: Peter Harrison, reviewer: Frank Höger)
- Added 'Audio Similarity' demo experiment (author: Peter Harrison, reviewer: Frank Höger)
- It is now possible to write `expected_trials_per_participant="n_nodes"` and `max_trials_per_participant="n_nodes"`
  in StaticTrialMakers. In such cases, `n_nodes` will be taken as referring to the number of start nodes with which the trial maker was initialized. This is particularly helpful for stimulus sets generated programmatically by listing files in directories. Analogous functionality is available in ChainTrialMakers using the term `n_start_nodes` (author: Peter Harrison, reviewer: Frank Höger)
- Added adblocker note to 'Are you ready to continue?' message (author: Peter Harrison, reviewer: Frank Höger)
- Added `psynet.debugger()` for creating breakpoints in VSCode/Cursor (see [docs](https://psynetdev.gitlab.io/PsyNet/experiment_development/development_workflow.html#breakpoints)) (author: Peter Harrison, reviewer: Frank Höger)
- Added debugger and GitHub Actions configuration files to experiment scripts (author: Peter Harrison, reviewer: Frank Höger)
- Added `get_timeline` method as an alternative way to specify the experiment timeline (see audio demo for an example). This allows users to put the timeline logic at the beginning of the experiment.py file, enhancing readability (author: Peter Harrison, reviewer: Frank Höger)
- Added timeout funtionality for some scheduled tasks (author: Peter Harrison)
- Added automatic timeout functionality to the CI tests to help debug stuck tasks (author: Peter Harrison)
- Modules and trial makers now accept callables for the `assets` argument, which is helpful for experiments using local file assets (author: Peter Harrison, reviewer: Frank Höger)
- Added shell completion for `psynet` commands (author: Frank Höger, reviewer: Peter Harrison)

### Changed

- Simplified the logging output when running `psynet debug local` (author: Peter Harrison, reviewer: Frank Höger)
- Include _logs.jsonl_ instead of _server.log_ when exporting with `psynet export ssh` (author: Frank Höger, reviewer: Peter Harrison)
- Allow users to specify a custom path format for storing export data in the `psynet-data` directory (author: Pol van Rijn, reviewer: Peter Harrison)
- Reordered dashboard tabs (authors: Pol van Rijn, Peter Harrison; reviewer: Peter Harrison)
- Automated tests now use a new `BotDriver` class which simulates participant actions using HTTP requests.
  This makes the simulation more realistic (i.e. more likely to catch bugs) and removes deadlocks
  in parallel testing. However, some implementations of `test_serial_run_bots` have needed to be changed
  as a result, and this could apply also to experiments with custom implementations of this method (author: Peter Harrison, reviewer: Frank Höger)
- Added `pre_deploy_constant`, a mechanism for specifying constants that are computed once in the pre-deploy phase (i.e. on the experimenter's local machine), with this value then propagating to the deployed web app (author: Peter Harrison, reviewer: Frank Höger)
- `AudioPrompt` has had the default play control label renamed from 'Play from start' to just 'Play' (author: Peter Harrison, reviewer: Frank Höger)
- Improved the landing page that users are shown when they navigate to the experiment's base URL (author: Peter Harrison, reviewer: Frank Höger)
- Updated `audio_stimulus_set_from_dir` functionality to support lazy evaluation and hence work better for large stimulus sets. See updated documentation for details (author: Peter Harrison, reviewer: Frank Höger)
- CI now requires merge requests to provide corresponding entries in CHANGELOG.md (author: Peter Harrison, reviewer: Frank Höger)
- `check_dallinger_version` now defaults to `false`, meaning that PsyNet will be less aggressive about version changes in Dallinger (author: Peter Harrison)
- Improved error message for `check_dallinger_version` (author: Peter Harrison)
- Address recent Dallinger changes to `Experiment` initialization (author: Peter Harrison, reviewer: Frank Höger)
- Renamed the 'Help' button to 'Comment' and removed previous help page text (author: Frank Höger, reviewer: Peter Harrison)
- Replaced `max_exp_dir_size_in_mb` experiment variable with `EXP_MAX_SIZE_MB` environment variable (author: Frank Höger, reviewer: Peter Harrison)
- `dallinger_recommended_version` now only specifies the minor Dallinger version (author: Frank Höger, reviewer: Peter Harrison)

### Fixed

- Pin dominate to version 2.9.1; monkey patch `dominate.dom_tag.get_event_loop` (author: Frank Höger, reviewer: Peter Harrison)
- Separate creators and raters in GAP experiments (author: Pol van Rijn, reviewer: Frank Höger)
- Fixed downloading assets via copying when exporting a local experiment (if the experiment is already down, you cannot download the assets from the URL) (author: Pol van Rijn, reviewer: Peter Harrison)
- Fixed a bug where `check_dallinger_version` would freeze forever in automated tests if the versions were mismatched (author: Peter Harrison, reviewer: Frank Höger)
- Updated database transaction code to use `dallinger.db.sessions_scope` and thereby avoid unintended long-lived database sessions that can lead to performance issues including deadlocks (author: Peter Harrison, reviewer: Frank Höger)
- Fixed bug where `cache` argument was ignored in `asset()` calls (author: Peter Harrison, reviewer: Frank Höger)
- Added missing `time_estimate` parameter passed from `Consent`s when creating respective `ConsentPage`s (author: Frank Höger, reviewer: Peter Harrison)
- Fixed bug in `run_pre_checks` when executing `psynet deploy ssh` (author: Frank Höger, reviewer: Peter Harrison)
- Renamed `_local` method to `_run_local` in _command_line.py_ to avoid accidental name clashes (author: Frank Höger, reviewer: Peter Harrison)
- Made the `SurveyJSControl`'s style more consistent with PsyNet (author: Peter Harrison, reviewer: Frank Höger)
- Made `current_trial` accessor more robust (avoids `current_trial is None` problems by retrying the database query) (author: Peter Harrison, reviewer: Frank Höger)
- Fixed bug in junit.xml merging in CI (author: Peter Harrison, reviewer: Frank Höger)
- CI now does not terminate early on test failure (author: Peter Harrison, reviewer: Frank Höger)
- Fixed stochastic bug in vocabulary test (author: Peter Harrison, reviewer: Frank Höger)
- Temporary files like `.deploy` and `source_code.zip` are now cleaned up after `psynet` commands (author: Peter Harrison, reviewer: Frank Höger)
- Fixed a problem with the ad HTML template, which prevented users from trialling experiments in GitHub Codespaces (author: Peter Harrison, reviewer: Frank Höger)
- Fixed bugs in `psynet simulate`. (author: Peter Harrison, reviewer: Frank Höger)
- Fixed a few bugs that were causing `MediaSliderControl` to fail to initialize properly in some cases (author: Peter Harrison, reviewer: Frank Höger)
- Improved Chrome driver management in pytest_psynet.py (author: Peter Harrison, reviewer: Frank Höger)
- Fixed layout jumping bug in `SurveyJSControl` (author: Peter Harrison, reviewer: Frank Höger)
- Removed `Trial.contents` setter/getter which was causing problems with upcoming Dallinger dashboard changes (author: Peter Harrison, reviewer: Frank Höger)
- Fixed bug in `in_deployment_package` helper function (author: Peter Harrison, reviewer: Frank Höger)
- Fixed bug in pgbadger workflow in CI (author: Peter Harrison, reviewer: Frank Höger)
- Fixed bug in JSSynth stopAllAudio that was in some cases preventing the JSSynth from playing at all (author: Peter Harrison, reviewer: Raja Marjieh)
- Fixed bug in `get_authenticated_session` that occasionally caused tests to fail with 'Connection reset by peer' errors (author: Peter Harrison, reviewer: Frank Höger)
- Fixed logic when deploying from archive by making sure `Experiment.pre_deploy` gets called omitting database generation and asset uploading while still creating the source code zip file (author: Frank Höger, reviewer: Peter Harrison)
- Deleted _static/assets_ directory to exclude assets from the source code zip file (author: Frank Höger, reviewer: Peter Harrison)

### Updated

- Updated Dallinger to version 11.5.5 (author: Frank Höger, reviewer: Peter Harrison)
  Read about the changes at
  - <https://github.com/Dallinger/Dallinger/releases/tag/v11.4.0>
  - <https://github.com/Dallinger/Dallinger/releases/tag/v11.5.0>
  - <https://github.com/Dallinger/Dallinger/releases/tag/v11.5.1>
  - <https://github.com/Dallinger/Dallinger/releases/tag/v11.5.2>
  - <https://github.com/Dallinger/Dallinger/releases/tag/v11.5.3>
  - <https://github.com/Dallinger/Dallinger/releases/tag/v11.5.4>
  - <https://github.com/Dallinger/Dallinger/releases/tag/v11.5.5>

### Removed

- Removed 'mock' dependency (author: Frank Höger, reviewer: Peter Harrison)
- Removed references to eligibility requirements for Prolific recruitments (author: Frank Höger, reviewer: Peter Harrison)

### Documentation

- Added documentation for new Dallinger config variable 'server_pem' (author: Frank Höger)
- Improved documentation for `choose_participant_group` (author: Peter Harrison)
- Updated mentions about supported Ubuntu versions (author: Frank Höger, reviewer: Peter Harrison)
- Added missing Dallinger and PsyNet configuration variables (author: Frank Höger, reviewer: Peter Harrison)
- Fixed outdated unicode datatypes for configuration variables by replacing them with `bool`, `int`, and `str` types (author: Frank Höger, reviewer: Peter Harrison)
- Fixed some warning messages and typos (author: Frank Höger, reviewer: Peter Harrison)
- Added a subsection for partial payments in Prolific recruitment (author: Frank Höger, reviewer: Peter Harrison)
- Updated Prolific deployment documentation to reflect the new changes to Prolific payment processes (author: Peter Harrison, reviewer: Frank Höger)

## [12.1.1](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v12.1.1) Release - 2025-07-15

### Fixed

- Fixed demos' constraints.txt files to reference the latest release version instead of the master branch (author: Frank Höger)

## [12.1.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v12.1.0) Release - 2025-06-25

### Added

- Added `AsyncCodeBlock`, a version of `CodeBlock` where the code is run asynchronously (authors: Peter Harrison and Frank Höger)
- Expose Lucid reach estimation to command line (author: Pol van Rijn, reviewer: Frank Höger)
- Added new option to `AudioPrompt` controls, accepting either a boolean or an iterable, to support custom selection and naming of controls (author: joshfrank95, reviewer: Peter Harrison)
- Allow participants to select multiple native languages in `NativeLanguage` questionnaire (author: joshfrank95, reviewer: Peter Harrison)
- Added controls to `JSSynth` (author: Peter Harrison, reviewer: joshfrank95)
- Added a CI test that flags warnings (author: Peter Harrison, reviewer: Frank Höger)

### Changed

- Set default logging level to 1 (`info`) rather than 0 (`debug`) (author: Peter Harrison, reviewer: Frank Höger)
- Only build the PsyNet documentation in CI when tagging a new release (author: Frank Höger, reviewer: Peter Harrison)

### Fixed

- The CI now no longer fails when translations are missing, except when on a release branch (author: Peter Harrison, reviewer: Pol van Rijn)
- Fixed garbage collection bug by removing `Exp.global_nodes` and `Exp.global_assets` (authors: Pol van Rijn and Peter Harrison)
- Fixed bug with stop button in audio controls (author: joshfrank95, reviewer: Peter Harrison)
- Removed dependency on Inter font which was loaded by CDN and therefore caused page layout jumping (author: Peter Harrison, reviewer: Pol van Rijn)
- Fixed and re-enabled the translation demo test (author: Frank Höger)
- Removed some unnecessary logging messages (author: Peter Harrison, reviewer: Frank Höger)
- Removed unnecessary sleep from `init_db` (author: Peter Harrison, reviewer: Frank Höger)
- Added `.venv` to the default experiment gitignore file to reflect common usage (author: Peter Harrison, reviewer: Frank Höger)
- Fixed bug when insufficient networks found after filtering blocks (author: Peter Harrison, reviewer: Frank Höger)
- Fixed some warnings messages in CI (author: Peter Harrison, reviewer: Frank Höger)
- Minor improvements to Docker launch workflow to address problems where local virtual environments caused failures (author: Peter Harrison, reviewer: Frank Höger)
- Fixed failing pgBadger CI tests by upgrading Python image to 3.13; upgraded pgBadger to version 13.1 (author: Frank Höger, reviewer: Peter Harrison)
- Automatically focus on `TextControl` and `NumberControl` (author: Frank Höger, reviewer: Peter Harrison)
- Update Dockertag automatically when running `psynet prepare` (author: Frank Höger, reviewer: Peter Harrison)
- Keep buttons disabled while still playing sounds in `BeepHeadphoneTest` and `HugginsHeadphoneTest` (author: Frank Höger, reviewer: Peter Harrison)

### Documentation

- Added tutorial for massive file uploads to Amazon S3 (authors: Pol van Rijn and Peter Harrison)
- Update feature contribution (author: Peter Harrison)
- Clarify that virtualenv and virtualenvwrapper are not required to use PsyNet (author: Peter Harrison, reviewer: Frank Höger)

## [12.0.3](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v12.0.3) Release - 2025-05-28

### Updated

- Updated Dallinger to version 11.3.1. This specific patch version (temporarily) disables `scheduled_job` `async_recruiter_status_check` as it is causing database deadlocks. Read about the changes in Dallinger at <https://github.com/Dallinger/Dallinger/releases/tag/v11.3.0> and <https://github.com/Dallinger/Dallinger/releases/tag/v11.3.1> (author: Frank Höger)

## [12.0.2](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v12.0.2) Release - 2025-05-14

### Fixed

- Updated Configuration patching code to reflect recent change in Dallinger's `Configuration.load` signature (author: Pol van Rijn, reviewer: Peter Harrison)

## [12.0.1](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v12.0.1) Release - 2025-04-30

### Fixed

- Fixed `Experiment.get_recruiter_status` for cases where `Experiment.recruiter.get_status()` returns a `RecruitmentStatus` instead of a `dict` (author: Frank Höger, reviewer: Peter Harrison)

### Updated

- Updated Dallinger to version 11.2.0. Read about changes in Dallinger: <https://github.com/Dallinger/Dallinger/releases/tag/v11.2.0> (author: Frank Höger)

## [12.0.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v12.0.0) Release - 2025-03-20

### Fixed

- Removed dash separator for release candidate and alpha versions (author: Frank Höger)
- Added `supports_delayed_publishing = True` to `BaseLucidRecruiter` (authors: Pol van Rijn, Frank Höger)
- Fixed `specified_using_version` for release candidates (author: Frank Höger)
- Fixed regex for requirements.txt when updating constraints (author: Frank Höger)

### Added

- Added `KeyboardPushButtonControl` for keyboard responses on `PushButtonControl`s (authors: Pol van Rijn, Peter Harrison)
- Added test to make sure that demos specify the correct version of Dallinger in constraints.txt (author: Peter Harrison, reviewer: Frank Höger)

### Changed

- Switched to alpha versions instead of development versions in the `master` branch (author: Frank Höger, reviewer: Peter Harrison)
- Changed the `psynet` requirement to use PsyNet's `master` branch and the `master` Docker image in the `master` branch when being on an alpha version (author: Frank Höger, reviewer: Peter Harrison)
- Updated logic for replacing the PsyNet Docker image tag when updating demo and test experiments (author: Frank Höger, reviewer: Peter Harrison)
- Set `SKIP_CHECK_PSYNET_VERSION_REQUIREMENT=1` before running `psynet check-constraints` in a local Docker environment (author: Frank Höger, reviewer: Peter Harrison)

## [12.0.0rc2](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v12.0.0rc2) Release candidate - 2025-02-27

### Fixed

- Previously, PsyNet would never translate anything if the experiment was not completely loaded (in order to access the config var `locale`). However, there is no need to wait for this if a user manually passes `locale` as an argument (authors: Pol van Rijn, Peter Harrison)
- Fixed a bug where `check_versions` failed when a release candidate version, e.g. `psynet==12.0.0rc1`, was specified in requirements.txt (author: Frank Höger, reviewer: Peter Harrison)

### Added

- Added 'Beep headphone test' to check if people can listen to audio but you don't care that much about the quality of the playback device (authors: Pol van Rijn, Peter Harrison)
- Added translations for 75 languages (authors: Pol van Rijn, Peter Harrison)

### Changed

- Consent verification (author: Peter Harrison, reviewer: Frank Höger):
  - PsyNet now only forces experiments to contain consent pages during deploying, not during debugging.
  - Demos no longer include `NoConsent` in their timelines.
  - Demos no longer include `SuccessfulEndPage` at the end of the timeline, since this no longer needs to be added explicitly.
- Changed default value of config variable `is_custom_screening` to `False` (author: Frank Höger, reviewer: Peter Harrison)

### Updated

- Updated Dallinger to version 11.1.1. Read about changes in Dallinger: <https://github.com/Dallinger/Dallinger/releases/tag/v11.1.1> (author: Frank Höger)

## [12.0.0rc1](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v12.0.0rc1) Release candidate - 2025-02-15

### Fixed

- Fixed bug that prevent the export command from being run (author: Frank Höger)

### Changed

- Removed hyphen from release candidate and development versions (author: Frank Höger)

## [12.0.0rc0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v12.0.0-rc0) Release candidate - 2025-02-12

### Added

- The new `psynet translate` command generates translations for the current directory (e.g. an experiment or a package). By default these translations are generated using OpenAI's ChatGPT but Google Translate is also supported. API tokens are needed in both case (authors: Pol van Rijn, Peter Harrison)
  - If you want to use a translator with context, you can write this instead:

  ```py
  _ = get_translator(context=True)
  InfoPage(_("welcome page", "Welcome to the experiment!"), time_estimate=5)
  ```

  - Changing locales during the experiment is no longer supported (support before was patchy anyway).
  - PsyNet will now throw an error if you try to debug an experiment with missing translations. You will need to generate these with `psynet translate`. It will require valid translations for all locales specified in `supported_locales`. If this is not set, it falls back to the experiment `locale`.
  - Various `ModularPage`, `TrialMaker`, etc classes no longer accept a `locale` argument or attribute.

  #### Other translation related changes

  - Translation documentation has been simplified and extended
  - The config variable `language` has been renamed to `locale`

- Added `asset` helper function for creating assets. This now can be used instead of the confusing variety of Asset subclasses, e.g. `ExperimentAsset`, `CachedAsset`, `CachedFunctionAsset`, etc. For example (author: Peter Harrison; reviewer: Frank Höger):

```py
asset("audio.wav")
asset("audio.wav", cache=True)
asset(synthesize_sine_wav, arguments: {"frequency": 440})
asset("https://s3.amazonaws.com/mybucket/audio.mp3")

### Breaking changes
- The `get_translator` interface has been simplified. It now returns a single translator, `gettext`, commonly abbreviated to `_`. Locale, and namespace (previously called 'module') are inferred automatically from the context. This means you can mark translations as simply as this:

```py
_ = get_translator()
InfoPage(_("Welcome to the experiment!"), time_estimate=5)
```

- Added documentation for the Dallinger `publish_experiment` config variable to indicate if the experiment should be also published when deploying. In the case of Prolific recruitment, if `False` a draft study will be created which later can be published via the Prolific web UI; in the case of Lucid recruitment, if `False` an awarded survey will be created which later can be published (set 'live') via the Lucid web UI. Default: `True` (author: Frank Höger, reviewer: Peter Harrison).
- Added a Dallinger config variable `disable_browser_autotranslate` to turn on or off autotranslate. In Dallinger the default is off, in psynet the default is on (i.e. block automatic translation) (author: Pol van Rijn, Peter Harrison)
- Added interactive option to disable Dallinger version check (authors: Peter Harrison; reviewer: Pol van Rijn)

### Changed

- Removed exact pinning of the Dallinger version by allowing (again) any greater minor version (author: Frank Höger, reviewer: Peter Harrison).
- Introduced `dallinger_recommended_version` variable and replaced environment variable `SKIP_CHECK_DALLINGER_VERSION` with config variable `check_dallinger_version` to allow for flexibility, e.g. when deploying `Dallinger` development branches. When set to `False` PsyNet bypasses the check for the version of Dallinger that is recommended for the current PsyNet release. Default: `True` (author: Frank Höger, reviewer: Peter Harrison).
- Moved `mock` package from optional-dependencies to dependencies in _pyproject.toml_ (author: Frank Höger).

### Removed

- Removed unneeded dependency `pybabel` which crashed CI (author: Pol van Rijn, reviewer: Frank Höger).
- Removed `--open-recruitment` config variable; removed `--open-recruitment` flag from deploy commands (author: Frank Höger, reviewer: Peter Harrison).

### Updated

- Updated Dallinger to version 11.1.0. Read about changes in Dallinger: <https://github.com/Dallinger/Dallinger/releases/tag/v11.1.0> (author: Frank Höger).
- Improved asset documentation (author: Peter Harrison, reviewer: Frank Höger).
- Updated demos to use the `asset` helper function (author: Peter Harrison, reviewer: Frank Höger).

## [11.9.1](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.9.1) Release - 2025-03-07

### Fixed

- Fixed Dallinger version in the constraints.txt files of demo and test experiments (author: Frank Höger).
- Moved mock package from optional-dependencies to dependencies in pyproject.toml (author: Frank Höger).

## [11.9.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.9.0) Release - 2025-01-16

### Fixed

- Fixed construction of download source URL in `_export_source_code` (author: Peter Harrison).
- Removed `client_ip_address` from anonymous data export (author: Frank Höger, reviewer: Peter Harrison).

### Added

- Added support for depositing folder assets to SSH deployments/debugging (author: Frank Höger, reviewer: Peter Harrison).
- Allow release candidate tags in requirements.txt files (author: Frank Höger, reviewer: Peter Harrison).
- It is now possible to provide functions directly to the timeline and they will be interpreted as code blocks (author: Peter Harrison, reviewer: Frank Höger).
- Added `--open-recruitment` flag for `psynet deploy ssh|heroku` deployments (author: Frank Höger, reviewer: Peter Harrison).

### Changed

- Improved deploy logic (author: Frank Höger, reviewer: Peter Harrison):
  - Renamed config variable `activate_recruiter_on_start` to `open_recruitment`
  - Allow config variable `open_recruitment=False` to be overridden by using the `--open-recruitment` flag. Specifically, following logic now applies with respect to recruiters:
    - `psynet deploy ssh` (Prolific): creates a draft study but will wait for you to launch it manually from the Prolific web GUI
    - `psynet deploy ssh` (MTurk): fails and tells you to add the `--open-recruitment` flag
    - `psynet deploy ssh` (Lucid): creates a draft Lucid survey
    - `psynet deploy ssh --open-recruitment` (Prolific): creates and publishes the Prolific study
    - `psynet deploy ssh --open-recruitment` (MTurk): creates and publishes the MTurk HIT
    - `psynet deploy ssh --open-recruitment` (Lucid): creates a live Lucid survey
- Renamed `server_option` to `option_server` in _dallinger.command_line.docker_ssh_ for Dallinger 11 compatibility (author: Frank Höger, reviewer: Peter Harrison).

### Removed

- Removed obsolete _deploy.sh_ files in demos/tests (author: Frank Höger, reviewer: Peter Harrison).

### Updated

- Updated Dallinger to version 11.0.1. Read about changes in Dallinger, e.g. the addition of new config variables `prolific_workspace` and `prolific_project` to support declaration of Prolific workspaces and project names: <https://github.com/Dallinger/Dallinger/releases/tag/v11.0.1> (author: Frank Höger, reviewer: Peter Harrison).

### Documentation changes

- Added new section for setting up a physical server (author: Peter Harrison).

## [11.8.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.8.0) Release 2024-11-05

### Fixed

- Add `PsyNetRecruiterMixin` to `GenericRecruiter` class definition (author: Frank Höger, reviewer: Peter Harrison).
- Remove erroneous `Node.check_on_create` (author: Peter Harrison, reviewer: Frank Höger).
- Fixed importing of `get_experiment` in lucid.py (author: Peter Harrison, reviewer: Frank Höger).
- Fixed bug whereby `GibbsTrial` was causing an export error if no answer had been submitted (author: Eline Van Geert, reviewer: Peter Harrison)
- Fixed rendering condition for markupsafe v3 (author: Frank Höger).
- Fixed bug in `get_folder_size_mb` (it was ignoring subdirectories) (author: Peter Harrison, reviewer: Frank Höger).

### Added

- Added config variable `prolific_is_custom_screening` with a default of `True` (author: Frank Höger, reviewer: Peter Harrison).
- Added `source_code.zip` as part of the exported data (both when exporting from the command line as from the dashboard). The ZIP-file includes a snapshot of the experiment of the moment it was deployed (author: Frank Höger, reviewer: Peter Harrison).

### Updated

- Updated Dallinger to version 10.3.0 (author: Frank Höger, reviewer: Peter Harrison).
- Updated 'update demos' logic to work with release candidates (author: Frank Höger).

### Documentation changes

- Added libpq to MacOS installation instructions (author: Peter Harrison).

## [11.7.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.7.0) Release 2024-09-23

### Fixed

- Fixed a bug where participants would receive payment even if they rejected the consent form (author: Peter Harrison, reviewer: Frank Höger).
- Refactored updating of experiment scripts to include **init**.py and added comment to test.py (author: Frank Höger, reviewer: Peter Harrison).
- Fixed bug where `db.drop_all` was not upgrading enum types properly (author: Peter Harrison, reviewer: Frank Höger).
- Added missing dependencies to demo experiments (author: Frank Höger, reviewer: Peter Harrison).
- Added missing `participant_group` argument to `GraphChainNode` constructor (author: Frank Höger, reviewer: Peter Harrison).
- Fixed `AccessDenied` error in `list_psynet_chrome_processes` (author: Frank Höger, reviewer: Peter Harrison).
- Fixed PsyNet logo layout issues on ad and consent pages (author: Frank Höger, reviewer: Peter Harrison).
- Better serialization for numpy data structures (author: Peter Harrison, reviewer: Frank Höger).
- Improved `Experiment.grow_networks` (author: Frank Höger, reviewer: Peter Harrison).
- Immediately terminate participants on Lucid when using mobile browser when this should not be allowed (authors: Pol van Rijn, reviewer: Frank Höger).
- Revamp of synchronous experiment support (author: Peter Harrison, reviewer: Frank Höger):
  - Fixed deadlock problems in synchronous experiment framework.
  - Fixed issue with synchronous experiment framework that made it hard to combine with chain experiments.
  - Fixed flakey staircase pitch discrimination demo test.
  - Fixed broken `accumulate_answers` test.
  - Fixed bug in progress fixing.
- Fixed type error in Lucid `incidence_rate` statistic caused by `numpy` version upgrade (author: Peter Harrison, reviewer: Frank Höger).
- Fixed bug where calling `participant.fail()` twice would produce an error (author: Peter Harrison, reviewer: Frank Höger).
- Fixed problem with out-of-date `click_coordinates` in graphics pages (author: Peter Harrison, reviewer: Frank Höger).

### Added

- Added new configuration variable `loglevel_worker` set to `1` (info) as default (author: Frank Höger, reviewer: Peter Harrison).
- Added class `DevProlificRecruiter` to improve on debugging capabilities (author: Frank Höger, reviewer: Peter Harrison).
- Added synchronous 'create and rate' demo experiment (author: Eline van Geert, reviewer: Peter Harrison).
- Added 'vertical processing' demo experiment (author: Peter Harrison, Frank Höger, reviewer: Peter Harrison).
- Added `/on-demand-asset` to logged requests (author: Frank Höger, reviewer: Peter Harrison).
- Added check for a maximum experiment directory size of 256 MB in `pre_checks` (author: Frank Höger, reviewer: Peter Harrison).
- Added `get_config` wrapper to get rid of `get_and_load_config` (author: Frank Höger, reviewer: Peter Harrison).
- Added a version of the static audio demo to the tests folder (author: Frank Höger, reviewer: Peter Harrison).
- Improved on error logs in source code export (author: Frank Höger, reviewer: Peter Harrison).
- Added experiment attribute `export_classes_to_skip` for specifying a list of classes to be excluded when exporting data. `ExperimentStatus` is now excluded by default (author: Frank Höger, reviewer: Peter Harrison).
- Added a note to the export part of the dashboard (author: Frank Höger, reviewer: Peter Harrison).
- CI now creates reports analyzing database usage and shows which tests have passed and which have failed (author: Silvio Tomatis, reviewer: Peter Harrison).
- Revamp of synchronous experiment support (author: Peter Harrison, reviewer: Frank Höger):
  - Added `initial_group_size`, `max_group_size`, `min_group_size`, and `join_existing_groups` to `SimpleGrouper`, making its functionality much more flexible.
  - Added `gibbs_within_sync` demo (aggregated GSP with synchronous decisions)
  - Added `sync_quorum` demo (imposing a quorum on part of the experiment timeline)
  - Added `test_rock_paper_scissors_parallel` (testing that the synchronous functionality scales well)
- Documented expected_trials_per_participant better (author: Peter Harrison).
- Added debugging text for staircase pitch discrimination demo experiment (author: Peter Harrison).

### Changed

- Renamed `FastFunctionAsset` to `OnDemandAsset` and route `fast-function-asset` to `on-demand-asset` (author: Frank Höger, reviewer: Peter Harrison).
- Renamed some Lucid specific variables (author: Frank Höger, reviewer: Peter Harrison).
- Refactored `recruiter.py` so that all recruiters receive a `PsyNetRecruiterMixin` (author: Peter Harrison, reviewer: Frank Höger).
- Refactored the `EndPage` logic to be written in Python rather than in Jinja (author: Peter Harrison, reviewer: Frank Höger).

### Disabled

- Skipped the "demo translation" test as it makes the CI fail for unknown reasons (author: Frank Höger, reviewer: Peter Harrison).

### Removed

- Removed DeprecationWarning for `max_trials_per_participant` (author: Frank Höger, reviewer: Peter Harrison).

### Updated

- Updated Dallinger to version 10.2.1 (author: Frank Höger, reviewer: Peter Harrison).
- Updated jQuery to version 3.7.1 (author: Frank Höger, reviewer: Peter Harrison).

### Documentation changes

- Updated deployment, and development sections (author: Peter Harrison).
- Updated synchronization tutorial (author: Peter Harrison).
- Render documentation for staircase paradigms (author: Peter Harrison).

## [11.6.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.6.0) Release 2024-07-03

- Fixed units for median request time taken in dashboard `Resources` tab visualization (author: Frank Höger, reviewer: Peter Harrison).
- Respect comments in requirements.txt when specifying package versions (author: Frank Höger, reviewer: Peter Harrison).
- Fix bug saving `ExperimentStatus` (author: Frank Höger, reviewer: Peter Harrison).
- Fixed issue in `BaseLucidRecruiter.run_checks` where the `participant` variable wasn't initialized (author: Frank Höger, reviewer: Peter Harrison).
- Fixed bug where progress bars did not increment properly when PageMakers returned unexpected amounts of credit.
This most commonly affected trial makers with feedback pages (author: Peter Harrison, reviewer: Frank Höger).
- Fixed bug where sounds played from audio files (e.g. .wav) were stopping early on devices with high latency (e.g. Bluetooth headsets) (author: Peter Harrison, reviewer: Frank Höger).
- Fix occasional psutil.AccessDenied error when running psynet debug (author: Peter Harrison, reviewer: Frank Höger).

### Added

- Added callback to `debug` and `deploy` commands leveraging Dallinger's `verify_id` method to check for a valid app name, e.g. no underscore in app name (author: Frank Höger, reviewer: Peter Harrison).
- Added check to ensure a config.txt file exists when experiment.py is present (author: Frank Höger, reviewer: Peter Harrison).
- Added a check that raises an error if `base_payment` is set to a value greater than `30` (author: Frank Höger, reviewer: Peter Harrison).
- Added `bump-my-version` as a new optional dependency allowing for automated version bumping, incl. pre-release/development version specifiers (author: Frank Höger, reviewer: Peter Harrison).
- Added test for participant failing logic (author: Peter Harrison, reviewer: Frank Höger).
- Added support for staircase psychophysical procedures via GeometricStaircaseTrialMaker and associated utility classes. See staircase_pitch_discrimination demo for example usage (author: Peter Harrison, reviewer: Frank Höger).
- Added warning that fade_out parameter in audio trials should be avoided as it currently has unreliable behavior (author: Peter Harrison, reviewer: Frank Höger).
- Added convenience property Node.trial (author: Peter Harrison, reviewer: Frank Höger).
- Added convenience properties ChainNode.chain and ChainTrial.chain (author: Peter Harrison, reviewer: Frank Höger).

### Changed

- Removed Experiment.fail_participant and moved its logic into Participant.fail (author: Peter Harrison, reviewer: Frank Höger).
- Moved `finalize_assets outside Trial.__init__`, making it easier for users to override `Trial.__init__` (author: Peter Harrison, reviewer: Frank Höger).

### Updated

- Updated `Dallinger` to `v10.1.2`. This fixes a crucial issue in relation to Prolific recruitment. See the complete release notes at <https://github.com/Dallinger/Dallinger/releases/tag/v10.1.2>.
- Various documentation updates (author: Peter Harrison).

## [11.5.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.5.0) Release 2024-06-07

### Fixed

- Fixed a couple of image rendering bugs that manifested when using SVG files with `GraphicPrompt`/`GraphicControl` (author: Peter Harrison, reviewer: Frank Höger).
- Fixed various issues and improvements/additions for Lucid recruitment (authors: Pol van Rijn, Frank Höger; reviewer: Peter Harrison):
  - Added `initial_response_within_s` setting; if a participant does not proceed to the consent within a certain time (default 180 seconds), the participant is terminated via the backend-end.
  - Added a Lucid tab in the dashboard displaying various data and statistics, e.g.
    - Lucid respondents activity, incl. a detailed breakdown of their status
    - Lucid marketplace codes of respondents
    - Lucid metrics (e.g. conversion rate, dropoff rate, incidence rate, termination LOI, completion LOI)
    - Various historams, incl. comparisions Lucid vs. PsyNet
  - Added new `psynet lucid` commands: `compensate`, `cost`, `locale`, `qualifications`, `status`, `studies`, `submissions`
  - Cleanup integration of external libraries (bootstrap, bootstrap-select, d3)
- Fixed race condition in `nextPage` which manifested on graphics pages when double-clicking on a response (author: Peter Harrison, reviewer: Frank Höger).
- The `nodes` argument in `StaticTrialMaker` can now be a callable. This is helpful for referring to local files that are not part of the experiment directory, which we don't want the remote server to try to access (author: Peter Harrison, reviewer: Frank Höger).
- Fixed bug in `render_error` (variables sometimes accessed before assignment) (author: Peter Harrison, reviewer: Frank Höger).

### Added

- Added `require_requirements_txt` decorator for `psynet generate-constraints` and `psynet check-constraints` commands (author: Frank Höger, reviewer: Peter Harrison).

### Changed

- Restructured demo directories (author: Frank Höger, reviewer: Peter Harrison):
  - Moved demos into respective new subdirectories `demos/experiments` and `demos/features`.
    **Note: if you are using a local editable version of PsyNet, we recommend deleting it and creating a fresh clone so that the old directories are purged properly.**
  - Moved demos that are only used for testing into `tests /experiments`.
  - Moved a part of the tests into respective new subdirectories `tests/isolated/demos`, `tests/isolated/experiments` and `tests/isolated/features`.
  - Renamed and updated `list_demo_dirs` to `list_experiment_dirs` functions to reflect the new directory structure.

### Updated

- Updated bootstrap to v5.3.3 (author: Frank Höger, reviewer: Peter Harrison).

### Documentation changes

- Updated SSH server deploy docs (author: Peter Harrison).
- Added troubleshooting section related to Heroku CLI not responding (author: Shota Shiiku, reviewer: Frank Höger)

## [11.4.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.4.0) Release 2024-05-25

### Fixed

- Avoid throwing an `NotImplementedError` if accidentally multiple trials are made; only propagate the answer of the first trial and fail other remaining trials (author: Pol van Rijn, reviewer: Peter Harrison).
- Fixed bug where progress bar would behave strangely when timeline constructs ended up delivering an unexpected amount of time reward. This bug was most salient in trial makers when `expected_trials_per_participant` was specified inaccurately (author: Peter Harrison, reviewer: Frank Höger).
- Removed `require_exp_directory` decorator for `psynet check-constraints` and `psynet generate-constraints` which was causing Docker builds to fail (author: Frank Höger, reviewer: Peter Harrison).

### Changed

- `participant.time_credit` is now represented as a float rather than as an object of class `TimeCreditStore` (author: Peter Harrison, reviewer: Frank Höger).
- Renamed `fix_time` to `with_fixed_time_credit`. As a reminder, this function ensures that a given portion of
  the timeline always delivers a specified amount of time credit once completed, irrespective of how many
  pages/trials the participant consumes in that region (author: Peter Harrison, reviewer: Frank Höger).

## [11.3.1](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.3.1) Release 2024-05-17

### Fixed

- Fixed failing authentication in dashboard export tab (author: Frank Höger, reviewer: Peter Harrison).
- Fixed `require_exp_directory` decorator which was making Docker deployments fail (author: Frank Höger, reviewer: Peter Harrison).

### Updated

- Updated 'black' code formatter; ran checks (author: Frank Höger)

## [11.3.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.3.0) Release 2024-05-09

### Added

- Added `psynet.timeline.sequence`, a utility function for administering a selection of test elements in
  a customizable order for different participants (author: Peter Harrison, reviewer: Frank Höger).
- Added new attribute `network.participants` to access all participants in a network (author: Peter Harrison, reviewer: Frank Höger).
- Automatically register recruiters when importing `psynet` (author: Frank Höger, reviewer: Peter Harrison).
- Retrieve the user's home path on the remote SSH server dynamically via SSH instead of having it hard-coded (author: Frank Höger, reviewer: Peter Harrison).
- Minor updates/fixes to graph.py (author: Peter Harrison, reviewer: Raja Marjieh).
- Check if the current working directory is an experiment directory before continuing running PsyNet commands (author: Frank Höger, reviewer: Peter Harrison).
- Added logic to export a deployed experiment's source code (author: Frank Höger, reviewer: Peter Harrison).
- Check if any TODOs are still present in experiment files; if 'yes' experiment deployment will be stopped. This check can be skipped by setting environment variable `SKIP_TODO_CHECK=1` (author: Frank Höger, reviewer: Peter Harrison).

### Fixed

- Fixed bug in `psynet.timeline.randomize`; it now works properly for more complex elements such as trial makers (author: Peter Harrison, reviewer: Frank Höger).
- Fixed md5sum in demos' constraints.txt files generated by demos/update_demos.py (author: Frank Höger).
- Retrieve user's home path on the remote SSH server dynamically via SSH

### Changed

- `recode_wav` no longer uses Parselmouth but instead uses soundfile (author: Peter Harrison, reviewer: Frank Höger).
- Changed default for `max_trials_per_participant` to `NoArgumentProvided` and throw a deprecation warning when it is left unchanged. To preserve old behavior, we still interpret `NoArgumentProvided` as if it were `None` (author: Frank Höger, reviewer: Peter Harrison).

### Deprecated

- `max_trials_per_participant` not being set explicitly (author: Frank Höger, reviewer: Peter Harrison).

### Documentation changes

- Updated AWS server setup (author: Peter Harrison).

## [11.2.2](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.2.2) Release 2024-03-28

### Fixed

- Re-add `babel` and `pandas` dependencies (author: Frank Höger).
- Fix the demos/update_demos.py script to take into account dependency changes in pyproject.toml since the last release (author: Frank Höger).

## [11.2.1](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.2.1) Release 2024-03-27

### Fixed

- Streamlined PsyNet's dependencies to reduce the installation of unnecessary packages (author: Peter Harrison, reviewer: Frank Höger).
- Fixed broken API documentation in previous v11.1.0 release.

## [11.2.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.2.0) Release 2024-03-27

### Fixed

- Fixed bug whereby `parent_trial` relationship was not updating properly (author: Peter Harrison).
- `SKIP_CHECK_DALLINGER_VERSION` is now propagated properly to Docker containers (author: Peter Harrison).

### Added

- Track loading times in new `Request` table (author: Pol van Rijn, reviewer: Peter Harrison).
- Track experiment status over time (author: Pol van Rijn, reviewer: Peter Harrison).
- Show change of experiment status over time in the dashboard (author: Pol van Rijn, reviewer: Peter Harrison).

### Changed

- `psynet destroy ssh` can now receive app arguments to destroy multiple apps at once; by default it's not asking to expire HITs, but it's now an optional parameter (author: Pol van Rijn, reviewer: Peter Harrison).

### Improved

- Made `network.degree` more efficient (author: Peter Harrison, reviewer: Frank Höger).

### Documentation changes

- Updated Prolific documentation (author: Peter Harrison).
- Added section `Connecting to the database via SSH` (author: Peter Harrison).

## [11.1.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.1.0) Release 2024-03-05

### Fixed

- Improved efficiency of `find_networks` (loading `network.head` in a subquery as part of the initial networks retrieval) (author: Peter Harrison).
- Fixed Chrome and ChromeDriver download link in Dockerfile (author: Frank Höger, reviewer: Peter Harrison).
- PsyNet now throws an error if an experiment still uses the old trial maker method `compute_bonus` (author: Peter Harrison, reviewer: Frank Höger).
- Fixed bug in version check (previously it would fail when requirements.txt files included `.git` extensions) (author: Peter Harrison, reviewer: Frank Höger).

### Added

- Added a `batch_zipped` parameter to `MediaGibbsNode`. If `batch_zipped` is True, the batch file including the media for the Gibbs slider will be saved as a compressed .zip folder including the .batch file. This zipped batch can be beneficial when media to load are heavy files, as only the smaller .zip folder needs to be downloaded on the participant's computer. The .zip folder is then unpacked only there, avoiding the need for downloading the heavy uncompressed batch file. For heavy media files, the zipped batch option will thus decrease page loading times for the MediaGibbs trials. (author: Eline Van Geert, reviewer: Peter Harrison)
- Added an svg Gibbs demo using a zipped batch file: svg_gibbs_zipped (author: Eline Van Geert, reviewer: Peter Harrison)
- Added an `unzip` property to media definition in `MediaGibbsTrial` (author: Eline Van Geert, reviewer: Peter Harrison)
- Added new config variable `big_base_payment` which defaults to `False` (author: Frank Höger, reviewer: Peter Harrison).
- Added assertion which stops startup of an experiment if `base_payment > 20` and `big_base_payment = true` is NOT set (author: Frank Höger, reviewer: Peter Harrison).
- Added assertion logging a warning message if `base_payment > 10` (author: Frank Höger, reviewer: Peter Harrison).
- Added cap-recruiter section to experiment config template (author: Frank Höger, reviewer: Peter Harrison).
- Added `with_for_update` option to various queries to make sure that appropriate locks are made on queries. This should reduce the number of deadlock errors we observe (author: Peter Harrison).
- Added missing library licenses (author: Peter Harrison).

### Changed

- Changed `preloadBatch` to also work with a zipped batch file (author: Eline Van Geert, reviewer: Peter Harrison)
- Changed default `fix_time_credit` in `conditional`, `switch`, and `GroupBarrier` constructs to `False`. This means that (unlike before) the time credit will vary according to which branch the participant takes, which we think is more expected behavior. Default `fix_time_credit` remains `True` for `while_loop`, providing a protection against situations where the participant spends infinite time in a loop and gets infinite credit. We may address this behavior differently in the future. (author: Peter Harrison, reviewer: Frank Höger)
- `grow_networks` now happens in a periodic background process to avoid deadlock errors and improve robustness (author: Peter Harrison).
- Barrier logic now happens in a periodic background process to avoid deadlock errors and improve robustness (author: Peter Harrison).
- SQLAlchemy performance improvements (author: Peter Harrison):
  - Substantial improvements in database usage efficiency, which should manifest in faster page response times. Efficiency of asset usage is now much improved: it is now practical to start an experiment with e.g. 100,000 assets.
  - PsyNet has now moved on from its 'commit all the time' strategy. Now the strategy is instead to have just one commit at the end of a given HTTP response or at the end of a given asynchronous process.
  - If a participant waits more than 60 s for PsyNet to prepare their next trial then their session will be terminated
  under the assumption that some error has occurred. This timeout is customizable via the attribute `TrialMaker.max_time_waiting_for_trial`.
  - `AsyncProcesses` no longer start immediately, but instead start when the database transaction is committed.
  - `awaiting_async_process` has been removed.
  - Eliminated nested pytest calls, which were preventing some important error messages (particularly those in asynchronous processes) from being logged.

### Updated

- Updated `Dallinger` to `v10.0.1`. See the complete release notes at <https://github.com/Dallinger/Dallinger/releases/tag/v10.0.1>.
- Updated pyproject.toml (added `dallinger[docker]`, `pytest`)
- Updated PsyNet to support Python 3.12 (author: Frank Höger, reviewer: Peter Harrison).
- Updated GitLab CI to use Python 3.12.2 image (author: Frank Höger, reviewer: Peter Harrison).

### Documentation changes

- Installation (general, developer, Docker, virtual environment) (author: Peter Harrison).
- Fix warnings when building documentation (author: Frank Höger, reviewer: Peter Harrison).
- Fix broken internal links (author: Frank Höger, reviewer: Peter Harrison).

## [11.0.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v11.0.0) Release 2024-01-05

### Breaking changes

- Renamed various variables. To update your experiment, do a find-and-replace search for these variables in your experiment code.

Config variables:

- min_accumulated_bonus_for_abort -> min_accumulated_reward_for_abort
`show_bonus` -> `show_reward`

Experiment variables:

- `dynamically_update_progress_bar_and_bonus` -> `dynamically_update_progress_bar_and_reward`
- `show_bonus` -> `show_reward`

Trial methods:

- `compute_bonus` -> `compute_performance_reward`

Experiment methods:

- `estimated_bonus_in_dollars` -> `estimated_reward_in_dollars`
- `estimated_max_bonus` -> `estimated_max_reward`
- `get_progress_and_bonus` -> `get_progress_and_reward`

Participant methods:

- `calculate_bonus` -> `calculate_reward`
- `get_bonus` -> `get_time_reward`
- `inc_performance_bonus` -> `inc_performance_reward`

- Removed `prolific_reward_cents` to instead use `base_payment` for Prolific reward (author: Frank Höger, reviewer: Peter Harrison).
- Removed `prolific_maximum_allowed_minutes` from docs (author: Frank Höger, reviewer: Peter Harrison).

### Fixed

- Replaced occurrences of 'from flask import Markup' with 'from markupsafe import Markup' (author: Frank Höger).
- Fixed wheel build target in pyproject.toml (author: Frank Höger).
- Fixed bug registering `pageUpdated` event (author: Peter Harrison).
- Prevent autocomplete on number input fields (author: Frank Höger, reviewer: Peter Harrison).
- Fixed bug in custom prompts demo and tutorial (author: Peter Harrison).
- Fixed bug with experiment label property (it was causing an error message on psynet export (author: Peter Harrison, reviewer: Pol van Rijn).
- Fixed pre-deploy checks for Heroku-incompatible storage backends (author: Peter Harrison, reviewer: Frank Höger).
- Fixed bug in `check_ssh_cache` that was causing `CachedAsset` to fail (author: Peter Harrison, reviewer: Frank Höger).
- `Unserialize` no longer fails when an SQL object cannot be found in the database, but instead returns `None`. This should make PsyNet more robust to cases where the `export` command is run partly through an experiment (author: Peter Harrison, reviewer: Frank Höger).
- Fixed bug where Gibbs networks would skip a dimension on rare event of node duplication (author: Peter Harrison, reviewer: Eline Van Geert).
- Fixed displayed text in language selection prompt (author: Yoko Urano, reviewer: Pol van Rijn).
- Fixed a bug where the PsyNet/Dallinger version consistency check was using an incorrect regex (author: Peter Harrison, reviewer: Pol van Rijn).
- PsyNet Docker images are now built using the Python dependencies specified in Dallinger's requirements.txt, which stops packages from accidentally being upgraded to incompatible versions (author: Peter Harrison, reviewer: Pol van Rijn).
- Updated Unity demo with new WebGL files to fix an issue where the `page_uuid`s sometimes did not match due to a race condition (authors: Ofer Tchernichovski, Nori Jacoby).
- Fixed order of function when when updating demos (author: Frank Höger).
- Fixed bug where trial makers weren't waiting for asynchronous file deposits (author: Peter Harrison, reviewer: Frank Höger).
- Fixed various minor bugs.

### Added

- Added 'Gibbs image' demo (author: Eline Van Geert, reviewer: Peter Harrison).
- Added `on_first_launch` hook for `TrialMaker`s (author: Pol van Rijn, reviewer: Peter Harrison).
- Added/updated logging info when the `fail()` method is called on node, trial, network, and participant (author: Frank Höger, reviewer: Peter Harrison).
- Added optional `height` argument to `VideoPrompt` (author: Frank Höger, reviewer: Peter Harrison).
- Run the pre-commit tests as part of GitLab CI pipeline (author: Frank Höger, reviewer: Peter Harrison).
- Add `--real-time` option for running bots (author: Peter Harrison).
- Added ability to specify extra files in `TrialMaker`s (author: Pol van Rijn, reviewer: Peter Harrison).
- It is now possible to run multiple bots in parallel through a PsyNet test. Example command: `psynet test local --n-bots 10 --parallel`. (authors: Eline Van Geert and Peter Harrison, reviewer: Peter Harrison)
- `psynet test` now supports remote deployments. Push your app to the remote server by running `psynet debug ssh --app test` as usual, then test it by running e.g. `psynet test ssh --app test --n-bots 10 --parallel`. (author: Peter Harrison, reviewer: Eline Van Geert)
- Added additional static audio demo (author: Elif Celen, reviewers: Peter Harrison, Frank Höger).
- Added JS function `psynet.stageResponse` as a mechanism for staging responses in custom controls (author: Peter Harrison).
- Provide a decorator `@expose_to_api` which will register an arbitrary static function under `/api/<name>` (author: Pol van Rijn, reviewer: Peter Harrison).

### Changed

- The polymorphic identity column used to distinguish different types of object within a given database table now uses a fully qualified module name to avoid problems (author: Peter Harrison, reviewer: Frank Höger).
that happened when two classes from different modules used the same name.
- Changed `VideoPrompt`'s default value for `mirrored` to `False`, and specify `mirrored=True` in all demos currently using `VideoPrompt` (author: Frank Höger, reviewer: Peter Harrison).
- Revise deprecation statement about `AntiphaseHeadphoneTest` (author: Peter Harrison).
- Better error messages for when a `wait_while` times out (author: Peter Harrison, reviewer: Pol van Rijn).
- Deprecate `DebugStorage`, all usages can be replaced with `LocalStorage` (author: Peter Harrison, reviewer: Frank Höger).
- PsyNet demos now source PsyNet from PyPi instead of GitLab, making dependency installation much faster. Adapted 'update demo' logic to reflect those changes (author: Frank Höger, reviewer: Peter Harrison).

### Updated

- Updated `Dallinger` to `v9.12.0`. See the complete release notes at <https://github.com/Dallinger/Dallinger/releases/tag/v9.12.0>.
- Updated/fixed logic for updating demos (author: Frank Höger)
- Make `page` accessible within Page Jinja templates (author: Peter Harrison).
- Auto-update PsyNet Docker image version; updated demos (author: Frank Höger, reviewer: Peter Harrison).

### Removed

- Removed old references to setup.py (author: Frank Höger).
- Removed old `LOCAL_S3` code (author: Peter Harrison).

### Documentation changes

- Fixed documentation for `choose_participant_group`.
- Added section for creating new experiments.
- Added documentation for `start_nodes`.
- Updated instructions about Python versions.
- Updated timeline, troubleshooting, and tutorials chapters.
- Updated installation instructions (incl. those for demos).
- Updated section on SSH deployment.
- Updated documentation for `ModularPage`.
- Updated documentation for demos.
- Updated section on writing custom frontends.
- Updated chapter on making a release.
- Replaced occurrences of `pip` with `pip3`.

## [10.4.1](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v10.4.1) Release 2023-12-18

### Updated

- Updated `Dallinger` to `v9.11.0`. See the complete release notes at <https://github.com/Dallinger/Dallinger/releases/tag/v9.11.0>.

## [10.4.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v10.4.0) Release 2023-09-24

### Fixed

- Fixed bug where preloading images was failing (author: Peter Harrison, reviewer: Frank Höger).
- Removed debug info in macro for `VideoSliderControl` (author: Eline Van Geert, reviewer: Peter Harrison).
- Fixed `show_footer=False`, which wasn't previously working (author: Peter Harrison, reviewer: Eline van Geert).
- Fixed bug for duplicate next button in `SurveyJSControl` (author: Peter Harrison).
- Fixed issues with `jsPsych` page formatting (author: Peter Harrison, reviewer: Eline van Geert).
- Fixed Heroku deployment from archive, which was previously failing early with a 'Checking the wrong experiment' error (author: Peter Harrison, reviewer: Frank Höger).
- Added a check to prevent cases where PsyNet tests import multiple different experiments in the same session, as this could cause difficult state contamination errors (author: Peter Harrison, reviewer: Frank Höger).
- Migrated most PsyNet tests into the `isolated` directory to further protect against contamination issues (author: Peter Harrison, reviewer: Frank Höger).
- Minor fix for dashboard's `GenericTrialNode` display (author: Peter Harrison).
- Allow name-based PsyNet requirements like `psynet==10.0.0` in `requirements.txt` (author: Frank Höger, reviewer: Peter Harrison).
- Added `verify_psynet_requirement`and `check_versions` checks to `run_pre_checks_sandbox` (author: Frank Höger, reviewer: Peter Harrison).

### Added

- It is now possible to add custom buttons to modular pages via the ``buttons`` argument (author: Peter Harrison, reviewer: Frank Höger).
- Added new modular page argument: `show_start_button` (author: Peter Harrison, reviewer: Frank Höger).
- Added new modular page argument: `show_next_button` (author: Peter Harrison, reviewer: Frank Höger).
- Better error message when `asset_storage` is not set (author: Peter Harrison).
- Added support for custom CSS themes (see `custom_themes` demo) (author: Peter Harrison, reviewer: Frank Höger).
- Added `psynet test` for running an experiment's regression tests (author: Peter Harrison, reviewer: Frank Höger).
- Added `psynet simulate` for generating simulated data from an experiment (author: Peter Harrison, reviewer: Frank Höger).
- Added function `check_versions` which throws an error when deploying or debugging remotely if the version of PsyNet specified in `requirements.txt` differs from the version installed locally (author: Frank Höger, reviewer: Peter Harrison).
- Added `validate` argument to `Page` constructor, which streamlines the experience of setting custom validation functions (author: Peter Harrison, reviewer: Frank Höger).
- Added better checks in `serialize` for objects that can't be serialized (e.g. lambda functions) (author: Peter Harrison, reviewer: Frank Höger).

### Changed

- The implementation of submit buttons has been refactored under the hood. Please let us know if you experience any unexpected behaviour (author: Peter Harrison, reviewer: Frank Höger).
- Disabled `autocomplete` in `TextControl` (author: Eline Van Geert, reviewer: Peter Harrison).
- Refactored S3 tests and removed unnecessary `config` fixture (author: Peter Harrison, reviewer: Frank Höger).
- PsyNet now throws an error message if you try to use the same nodes in two modules or trial makers (author: Peter Harrison, reviewer: Frank Höger).

### Removed

- Removed old config variables `debug_storage_root` and `default_export_root` which were no longer being used. (author: Peter Harrison, reviewer: Frank Höger).

### Documentation changes

- Added `Configuration` subsection to section `Experiment development` (author: Frank Höger, reviewer: Peter Harrison).
- Added instructions for installing Docker to `Linux installation` subsection (author: Frank Höger).
- Added new testing example to `Tutorials/Tests` subsection (author: Peter Harrison).
- Added warning to `Synchronization` subsection (author: Peter Harrison).
- Updated `Example experiments` subsection (author: Peter Harrison).
- Updated `Docker installation` and `Developer installation` subsections (author: Eline Van Geert, reviewer: Peter Harrison).

## [10.3.1](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v10.3.1) Release 2023-08-25

### Fixed

- Fixed Dallinger dependency in demos' constraints.txt files (author: Frank Höger).
- Fixed broken links in learning/exercices documentation (author: Frank Höger).

### Changed

- Improved menu navigation of documentation (author: Frank Höger).

### Updated

- Updated 'Making a release' documentation (author: Frank Höger).

## [10.3.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v10.3.0) Release 2023-08-22

### Fixed

- Prevent double submission and submission of an experiment before page load (author: Pol van Rijn, reviewer: Peter Harrison)
- Fixed color-slider in `within_gibbs` demo (author: Eline van Geert, reviewer: Peter Harrison)
- Fixed bugs in video slider control, which was previously not working (author: Peter Harrison, reviewer: Eline van Geert).
- Fix protected routes test due to update to Dallinger 9.10.0 (author: Frank Höger, reviewer: Peter Harrison).
- Fixed bug in `get_participant_info_for_debug_mode` route used in Unity experiments development (author: Frank Höger).
- Fixed Docker check for local package installations in demos (author: Peter Harrison).
- Fixed missing documentation and tests for trial accessors like `network.all_trials`, `node.all_trials`, etc. (author: Peter Harrison, reviewer: Frank Höger).

### Added

- Added translations for `ColorBlindnessTest` prescreener (author: Pol van Rijn).
- Added `sensitive=True` to sensitive 'lucid' and 'cap-recruiter' config variables (authors, reviewers: Frank Höger, Peter Harrison).
- Added versioned PsyNet dependency in demo Dockerfiles (author: Peter Harrison).

### Added

- Added new boolean `Page` parameter `show_termination_button` for displaying a button which allows participants to terminate an experiment by setting `show_termination_button=True`, default: `False` (author: Frank Höger, reviewers: Pol van Rijn, Peter Harrison).
- Added `aggressive_no_focus_timeout_in_s` setting (author: Frank Höger, reviewers: Pol van Rijn, Peter Harrison).
- Added [Lucid] section to experiment demos' config template (author: Frank Höger, reviewers: Pol van Rijn, Peter Harrison).

### Updated

- Restructured developer documentation (author: Frank Höger, reviewer: Peter Harrison).
- Updated `update_demos.py` script to automatically set the PsyNet Docker image version in Dockerfiles (author: Frank Höger, reviewer: Peter Harrison).
- Documentation updates (author: Peter Harrison).
- Updated `Dallinger` to `v9.10.0`. See the complete release notes at <https://github.com/Dallinger/Dallinger/releases/tag/v9.10.0>.

## [10.2.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v10.2.0) Release 2023-07-31

### Fixed

- Fixed problem where importing individual PsyNet modules before `psynet.experiment` could produce an SQLAlchemy import error (author: Peter Harrison, reviewer: Frank Höger).
- Made `validate` messages translatable (author: Pol van Rijn, reviewer: Peter Harrison).
- Allow `.git` in PsyNet version specifiers in `requirements.txt` (author: Peter Harrison, reviewer: Frank Höger).
- Fixed bug where participants could submit `InfoPages` before the page was ready (author: Peter Harrison, reviewer: Frank Höger).
- Fixed CI process for Docker builds so that new Docker images are uploaded for each new tag (author: Peter Harrison, reviewer: Frank Höger).
- Changed imports of joblib, numpy, pandas, statsmodels to local imports to speed up PsyNet package import time (author: Peter Harrison, reviewer: Frank Höger).
- Fixed slow HTTP route in the dashboard timeline page (author: Peter Harrison, reviewer: Frank Höger).

### Added

- Added `jsPsychPage` as a utility for embedding jsPsych content in PsyNet. See `demos/jspsych` (author: Peter Harrison, reviewer: Frank Höger).
- Added experimental support for synchronous paradigms in PsyNet (see `demos/simple_sync_group` and `demos/rock_paper_scissors`) (author: Peter Harrison, reviewer: Frank Höger).
- Added a new function `psynet check-constraints` that checks whether the `constraints.txt` file is present and correct (author: Peter Harrison, reviewer: Frank Höger).

### Changed

- Simplified config.txt files for all demos (author: Peter Harrison, reviewer: Frank Höger).
- Under the hood, PsyNet now avoids the `dalligner.createParticipant` helper function, which previously would occasionally fail when running different participation sessions in different browser windows (author: Frank Höger, reviewer: Peter Harrison).
- Reinstated `constraints.txt` as a compulsory tool for pinning dependencies for Docker deployments (author: Peter Harrison, reviewer: Frank Höger).

### Updated

- Updated Unity demo's static file directory to work with PsyNet 10 (author: Frank Höger, reviewer: Peter Harrison).
- Propagated updated instructions to demos (author: Peter Harrison).
- Updated documentation (author: Peter Harrison).
- Updated `Dallinger` to `v9.9.0`. See the complete release notes at <https://github.com/Dallinger/Dallinger/releases/tag/v9.9.0>.

## [10.1.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v10.1.0) Release 2023-07-13

### Fixed

- Escape double quotes in translated JavaScript variables (author: Pol van Rijn, reviewer: Peter Harrison).
- Fixed an error when setting JavaScript variables on timeline pages; removed obsolete JavaScript function `checkParticipantId` (author: Frank Höger, reviewer: Peter Harrison).
- Fixed bug in dashboard visualization where trial plots weren't displaying (author: Peter Harrison, reviewer: Frank Höger).

### Added

- Added support for the Lucid(Cint) recruiting platform (author: Frank Höger, reviewers: Peter Harrison, Pol van Rijn).
- Users are now required to specify the version of PsyNet in `requirements.txt` explicitly. Additionally, demos' `requirements.txt` files are updated to the current version of PsyNet when running the `demos/update_demos.py` script (author: Frank Höger, reviewer: Peter Harrison).
- Added `--server parameter` to `psynet destroy` (author: Pol van Rijn, reviewer: Frank Höger).

### Changed

- Simplified some internal logic for RecordTrial (author: Peter Harrison, reviewer: Frank Höger).

### Updated

- Updated `Dallinger` to `v9.8.2`. See the complete release notes at <https://github.com/Dallinger/Dallinger/releases/tag/v9.8.2>.

## [10.0.0](https://gitlab.com/PsyNetDev/PsyNet/-/releases/v10.0.0) Release 2023-06-22

- TO BE ANNOUNCED

## [10.0.0rc4] Release candidate 2023-04-30

### Updated

- Updated `Dallinger` to `v9.7.0`. See the complete release notes at <https://github.com/Dallinger/Dallinger/releases/tag/v9.7.0>.

## [10.0.0rc3] Release candidate 2023-03-02

### Fixed

- Removed RSTCloth dependency (author: Pol van Rijn, reviewer: Peter Harrison).
- Fixed for compatibility with new Dallinger dashboard code (author: Pol van Rijn, reviewer: Peter Harrison).

### Added

- Added support in pyproject.toml for making PyPi releases (author: Frank Höger, reviewer: Peter Harrison).
- Added Video Gibbs support (author: Pol van Rijn, reviewers: Peter Harrison, Frank Höger).

### Changed

- Migrated build system requirements and project metadata from setup.py/setup.cfg to pyproject.toml, (see <https://pip.pypa.io/en/stable/reference/build-system/pyproject-toml/>) (author: Frank Höger, reviewer: Peter Harrison).
- Migrated AWS CLI (awscli) functionality to `boto3` to reduce dependencies (author: Pol van Rijn, reviewer: Peter Harrison).

## [10.0.0rc2] Release candidate 2023-02-07

### Fixed

- Scroll current item in sidebar menu into view when navigating Sphinx documentation (author: Frank Höger, reviewer: Peter Harrison).

### Added

- Added Prolific documentation with screenshots (author: Pol van Rijn).

### Changed

- Demographics are now saved in the participant table (author: Peter Harrison).
- Check if amount in cents/predicted duration in minutes for Prolific is identical to the hourly rate of the experiment (author: Pol van Rijn, reviewers: Peter Harrison, Frank Höger).

### Removed

- Removed unnecessary field `mode` in config.txt of all demos (author: Pol van Rijn, reviewers: Peter Harrison, Frank Höger).
- Removed old deprecated code (author: Frank Höger, reviewer: Peter Harrison):
  - psynet/consent.py
    - `MTurkStandardConsent`
    - `MTurkStandardConsentPage`
    - `MTurkAudiovisualConsent`
    - `MTurkAudiovisualConsentPage`
  - psynet/modular_page.py
    - `NAFCControl`
  - psynet/page.py
    - `NAFCPage`
    - `TextInputPage`
    - `SliderPage`
    - `AudioSliderPage`
    - `NumberInputPage`
  - psynet/timeline.py
    - `multi_page_maker`

## [10.0.0rc1] Release candidate 2023-01-27

### Added

- Added RUN.md instructions for running experiments in Docker (author: Peter Harrison).
- Drafted 'generic recruiter', an improved version of Dallinger's hot-air recruiter (author: Peter Harrison).
- Added missing parts of API documentation to Sphinx website (author: Frank Höger, reviewer: Peter Harrison).
- Added `config_defaults` to experiment class, which allows for specifying default config variables programmatically (author: Peter Harrison, reviewer: Frank Höger).

### Changed

- Store assets in `static/assets` rather than `static/local_storage` (author: Peter Harrison).

### Fixed

- Make assets display properly in dashboard again (author: Peter Harrison).
- Fix Unity integration with Prolific (author: Peter Harrison).

## [10.0.0rc0] Release candidate 2023-01-17

### Added

- Marked translatable parts of the PsyNet UI, consent, and demographics (author: Pol van Rijn, reviewer: Frank Höger and Peter Harrison).
- Added a locale variable to the participant (default: experiment language) which can be changed during the experiment (author: Pol van Rijn, reviewer: Frank Höger and Peter Harrison).
- Added a `currency` variable to the experiment, which allows using a currency different than dollars, e.g., in Prolific (author: Pol van Rijn, reviewer: Frank Höger and Peter Harrison).
- Wrote documentation for translating experiments (author: Pol van Rijn, reviewer: Frank Höger and Peter Harrison).

### Fixed

- Updated the translation demo (author: Pol van Rijn, reviewer: Frank Höger and Peter Harrison).
- Use latin-1 encoding for pickling JSON instead of ASCII to work well with non-ASCII characters (author: Pol van Rijn, reviewer: Frank Höger and Peter Harrison).
- Add additional dependencies to PsyNet: `babel` and `python-gettext` (author: Pol van Rijn, reviewer: Frank Höger and Peter Harrison).
- Replaced typo in `participant` (author: Pol van Rijn, reviewer: Frank Höger and Peter Harrison).

## [9.4.1] Released on 2023-01-11

### Added

- Added Princeton University consent for CAP-Recruiter deployment (author: Frank Höger, reviewer: Peter Harrison).

### Fixed

- Fixed warnings when building the Sphinx documentation (author: Frank Höger, reviewer: Peter Harrison).

## [9.4.0] Released on 2022-12-21

### Added

- Added MIT license.
- Added and updated experimenter and developer documentation; changed layout to `furo` theme (author: Peter Harrison, reviewer: Frank Höger).

### Fixed

- Fixed node details visualization in dashboard monitor (author: Peter Harrison).

### Updated

- Updated `Dallinger` to `v9.3.0` which comes with many Docker improvements. See the complete release notes at <https://github.com/Dallinger/Dallinger/releases/tag/v9.3.0>.
- Updated README.md (author: Peter Harrison).

## [9.3.0] Released on 2022-11-26

### Added

- Added support for panning in JSSynth (author: Peter Harrison).
- Added new parameter `show_free_text_option` to `RadioButtonControl` which appends a free text option to the list of options (author: Pol van Rijn, reviewer: Peter Harrison).

### Fixed

- Fixed typo in `LexTaleTest` (author: Pol van Rijn).

### Changed

- Changed gender questionnaire (author: Pol van Rijn, reviewer: Peter Harrison).
- Renamed 'hits' to 'tasks' in `CapRecruiter` API calls (author: Frank Höger).

### Updated

- Updated `Dallinger` to `v9.2.1` fixing the issue of not being able to deploy to Heroku. See the complete release notes at <https://github.com/Dallinger/Dallinger/releases/tag/v9.2.1>.
- Updated references for new GitLab repository path (`computational-audition-lab` -> `PsyNetDev`).
- Updated `README.md`.
- Updated Linux installation instructions.

## [9.2.0] Released on 2022-11-10

### Fixed

- Fixed display of `ExperimentConfigs`, `LucidRIDs`, and `Responses` database tables in dashboard (author: Peter Harrison, reviewer: Frank Höger).
- Hotfix that fixes import errors for experiment containing stimulus sets. Will be superceded by the storage branch, to be merged soon (author: Peter Harrison).
- Fixed bug where the wrong participant information was given in error pages (author: Peter Harrison, reviewer: Frank Höger).
- Renamed `psynet` to `PsyNet` in .gitlab-ci.yml (author: Frank Höger).
- Removed failing detection of `editable mode` in `psynet update` command (author: Frank Höger).

### Added

- Added `utils.get_experiment`, an easy way to get an `Experiment` instance from an arbitrary part of your code (author: Peter Harrison, reviewer: Pol van Rijn).
- Added the ability to customize the SQLAlchemy polymorphic identity of a given class by setting the `polymorphic_identity` attribute in the class definition (author: Peter Harrison, reviewer: Pol van Rijn).
- Added new tools for creating bots in PsyNet. Bots are artificially simulated participants that progress through the experiment in much the same way as ordinary PsyNet participants, with the exception that they never interact with the web browser itself, but instead interact with the Python objects that underlie the timeline. Bots can be used for creating tests for PsyNet experiments, for simulating emergent network dynamics, or for introducing controllable characters into the actual experiment deployment (author: Peter Harrison, reviewer: Pol van Rijn):

A bot is created with a command like the following:

``` py
from psynet.bot import Bot

bot = Bot()
```

At this point you can set custom variables within that bot object, for example to correspond to relevant participant parameters such as gender or musicianship. You might do this deterministically or stochastically, depending on your interest.

```py
import random

bot.var.gender = "female"
bot.var.is_musician = random.sample([True, False], 1][0]
```

You can also define a universal bot initialization method on the Experiment class, like this:

``` py
class Exp(...):
    def initialize_bot(self, bot):
        bot.var.is_musician = random.sample([True, False], 1)[0]
```

This method will be called automatically whenever a bot is initialized.

PsyNet needs to be told how bots respond to particular pages. This can be done in two ways.

The first way is to pass a `bot_response` function to the Page or Control constructor. For example:

```py
ModularPage(
    "How many years of musical training do you have?",
    TextControl(
        ...
        bot_response=lambda bot: 10 if bot.var.is_musician else 0,
    )
)
```

This `bot_response` can take various other parameters, including the `experiment`, the `page`, and the `prompt`, so that you have all the information you need to define the bot's response.

Alternatively, if you are defining a custom Page or Control class, you can define a custom `get_bot_response` method, which achieves much the same response.

To tell the bot to progress through the experiment, you can use one of two functions: `take_page` and `take_experiment`. The first advances by just one page, whereas the latter progresses through the experiment. The speed of advancement can be determined by a parameter that acts as a multiplier on each page's `time_estimate` value.

There are various ways to configure bots to take part in a real experiment. One of the easiest currently is to define a scheduled task that occurs periodically in the background of the experiment and runs a bot participant.

```py
    @staticmethod
    @scheduled_task("interval", seconds=5, max_instances=1)
    def run_bot_participant():
        # Every 5 seconds, runs a bot participant.
        experiment = get_experiment()
        if experiment.var.launched:
            bot = Bot()
            bot.take_experiment()
```

- Added `psynet generate-constraints` to command line (author: Frank Höger; reviewer: Peter Harrison).

### Updated

- Updated `Dallinger` to `v9.2.0` adding experimental support for Docker deployment. See the complete release notes at <https://github.com/Dallinger/Dallinger/releases/tag/v9.2.0>.

## [9.1.2] Released on 2022-08-13

### Fixed

- Fixed a bug that caused incorrect participant details in error messages (author: Peter Harrison, reviewer: Frank Höger).

## [9.1.1] Released on 2022-08-03

### Fixed

- Fixed a bug that introduced import errors for experiments containing stimulus sets (author: Peter Harrison, reviewer: Frank Höger).

## [9.1.0] Released on 2022-07-11

### Added

- Added PsyNetRecruiter base class passing down the missing `notify_duration_exceeded` method to `BaseLucidRecruiter`. (author: Frank Höger; reviewer: Peter Harrison)

### Fixed

- Fixed further issues with database tables not being exported properly. (author: Peter Harrison, reviewer: Frank Höger)

### Changed

- Prevent opening a new window when clicking on the `Begin Experiment` button on the Ad page when using `LucidRecruiter`. (author: Frank Höger, reviewer: Peter Harrison)
- Register `cap_recruiter_auth_token` config variable; cleanup CAP-Recruiter demo. (author: Frank Höger, reviewer: Peter Harrison)
- Changed fields of the `LucidRIDs` database table: Removed fields `failed`, `failed_reason`, and `time_of_death`; added field `termination_requested_at`.
 `termination_requested_at` is now set each time a termination request is made to Lucid Marketplace. (author: Frank Höger; reviewer: Peter Harrison)
- Ensure that `Exp.setup()` only happens in the once, in the launch routine. (author: Peter Harrison, reviewer: Frank Höger)

## [9.0.1] Released on 2022-07-08

### Added

- Added more comprehensive tests for data export. (author: Peter Harrison, reviewer: Frank Höger)

### Fixed

- Fixed problem where not all database tables were being exported. (author: Peter Harrison, reviewer: Frank Höger)
- Fixed problem where two 'ExperimentConfig' database objects were being created. (author: Peter Harrison, reviewer: Frank Höger)

### Changed

- PsyNet now just exports data as CSV files, not JSON files; doing both seemed redundant. (author: Peter Harrison, reviewer: Frank Höger)
- PsyNet's exported CSV files now correspond directly to the class names of the exported objects,
  without any automatic conversion from CamelCase to snake_case. This seems more transparent and less error-prone. (author: Peter Harrison, reviewer: Frank Höger)

## [9.0.0] Released on 2022-06-17

### Breaking changes

- The URL format for PsyNet experiments is now a bit cleaner, looking something like this:
  `http://127.0.0.1:5000/timeline?participant_id=1&auth_token=63252608-ee35-40cc-89be-9bbb82120c5d`
  (author: Peter Harrison, reviewer: Frank Höger).

### Fixed

- Fixed bug in `cls.inherits_table` (author: Peter Harrison, reviewer: Frank Höger).
- Fixed bug in `openwindow` JavaScript function in `ad.html` which prevented propagation
  of Prolific specific URL parameters (author: Frank Höger, reviewer: Peter Harrison).
- Refreshing the first page of the experiment no longer causes an error,
  as the participant's authentication token is now loaded automatically into the URL
  (author: Peter Harrison, reviewer: Frank Höger).
- Patched unreliable behavior in `dallinger.identity.participantId`
  (author: Peter Harrison; reviewer: Frank Höger).

### Added

- Added explicit support for `dict` and `list` types in `claim_field`; importantly, these now provide
  mutation tracking, so that in-place modifications to these fields will be picked up properly
  by SQLAlchemy (author: Peter Harrison, reviewer: Frank Höger).
- Added demos for `Prolific` and `CAP-Recruiter` recruitment (author: Frank Höger).
- Added Unity autoplay demo test (author: Frank Höger, reviewer: Peter Harrison).

### Changed

- Updated the Unity C# code to adapt to the new URL format (author: Frank Höger, reviewer: Ofer Tchernichovski).
- `PageMaker` has been made much more flexible. Instead of being constrained to
  returning just one page, they may now return pretty much any kind of
  (arbitrarily nested) logic. This flexibility likewise now applies to `show_trial`
  and `show_feedback` (author: Peter Harrison, reviewer: Frank Höger).
- It is no longer required to specify `num_pages` or `check_num_pages` when defining a custom `Trial` class,
  and such specifications will be ignored (author: Peter Harrison, reviewer: Frank Höger).
- `participant.elt_id` now takes a different form. Instead of comprising a single integer, it now
  corresponds to a list of integers, which index into nested page makers of arbitrary depth.
  This should not affect most PsyNet users directly (author: Peter Harrison, reviewer: Frank Höger).
- Made the test suite more scalable by splitting the single job which ran all tests into multiple (5) smaller jobs
  that run in parallel.The overall time to run the tests was thereby reduced from ~18 min. to ~8 min
  (author: Frank Höger, reviewer: Peter Harrison).
- Renamed the PsyNet base layout template to `psynet_layout.html` (author: Peter Harrison, reviewer: Frank Höger).
- Prevented opening a new window when clicking on the `Begin Experiment` button on the Ad page
  when using `LucidRecruiter` (author: Frank Höger, reviewer: Peter Harrison).

## [8.0.0] Released on 2022-05-23

### Breaking changes

- Dropped support for Python 3.7.

### Fixed

- Fixed bug whereby kwargs were not propagated properly in `TextInputPage`.
  (author: Peter Harrison, reviewer: Frank Höger)

### Added

- `var.get()` now supports default arguments.
  (author: Peter Harrison, reviewer: Frank Höger)

### Updated

- Updated `Dallinger` to `v9.0.0`, see release notes at <https://github.com/Dallinger/Dallinger/releases/tag/v9.0.0>.
  Includes a bugfix which adds `clock` support in Docker.
  (author: Frank Höger, reviewer: Peter Harrison)
- Update Google Chrome and driver to version 101.x in `.gitlab-ci.yml`.
  (author: Frank Höger)

## [7.2.0] Released on 2022-05-16

### Fixed

- Fixed broken loop in `AudioPrompt` when `controls=False`
  (author: Peter Harrison, reviewer: Frank Höger)
- More aggressive DB commits in `finalize_trial`
  (author: Peter Harrison)
- More robust jsonification in data export
  (author: Peter Harrison)
- Remove unintended timeout behavior from `run_subprocess_with_live_output`
  (author: Peter Harrison)
- Fixed participant resuming via the dashboard, which was broken by the introduction of the `auth_token`
  functionality.
  (author: Peter Harrison, reviewer: Frank Höger)

### Added

- Added LUCID Marketplace recruiting integration:
  - Added `DevLucidRecruiter` and `LucidRecruiter` classes.
  - Added HTML templates for final pages for the three cases 'successful', 'unsuccessful',
    and 'rejected consent').
  - Added LUCID recruiting demo.
  NOTE: Currently only to be used in conjunction with Dallinger branch `docker-clock`.
  (author: Frank Höger, reviewer: Peter Harrison)
- Added `failure_tags` to `RejectedConsentPage`; added `failed_reason` to data returned from
  `BaseCapRecruiter`'s `reward_bonus` method.
  (author: Frank Höger, reviewer: Peter Harrison)
- Notify the CAP-Recruiter API when a participant has failed.
  (author: Frank Höger, reviewer: Peter Harrison)

### Changed

- Replaced deprecated MTurk consents in demos with new consents `AudiovisualConsent` and `MainConsent`.
  (author: Frank Höger, reviewer: Peter Harrison)

## [7.1.0] Released on 2022-04-25

### Fixed

- Fixed developer mode by calling reset_console
  (author: Peter Harrison, reviewer: Frank Höger)

- Fixed an error which occasionally happened when PsyNet tried to close down zombie processes,
  when the process would close itself before PsyNet managed to close it, causing a
  psutil.NoProcessFound error. Now such errors are ignored. The implementation uses a new function
  called psynet.command_line.safely_kill_process.
  (author: Peter Harrison, reviewer: Pol van Rijn)

- Fixed Unity demo by replacing it with a new autoplay version containing updated WebGL files.
  (author: Ofer Tchernichovski, reviewers: Peter Harrison, Frank Höger)

### Added

- PsyNet now supports the definition of custom SQL classes that are not subclasses of pre-existing
  PsyNet/Dallinger objects.
  (author: Peter Harrison, reviewer: Pol van Rijn)

  These objects are stored in their own tables and can be seen in the dashboard. The API is very simple:

  ```py
  from psynet.data import SQLBase, SQLMixin, register_table

  @register_table
  class Bird(SQLBase, SQLMixin):
      __tablename__ = "bird"

  class Sparrow(Bird):
      pass

  class Robin(Bird):
      pass
  ```

  The above example defines a new database table called 'bird', in which we can store robins and sparrows.

- Added new demos custom_table_simple and custom_table_complex that illustrate sqlalchemy usage via this new PsyNet feature.
  (author: Peter Harrison, reviewer: Pol van Rijn)
- Added a new, more robust version of init_db for resetting database state: psynet.data.init_db
  (author: Peter Harrison, reviewer: Pol van Rijn)
- Added auth_token and authToken to be used by the Unity API.
  (author: Frank Höger, reviewer: Peter Harrison)

### Changed

- Changed the visual behavior of the five consent pages recently introduced by always showing the buttons at the bottom of the pages and making the text overall smaller.
  (author: Frank Höger, reviewer: Peter Harrison)

## [7.0.0] Released on 2022-03-27

### Fixed

- Fixed problem in `auth_token` verification for JS logging.
  (author: Peter Harrison, reviewer: Frank Höger)
- Fixed long-standing issue where console would behave strangely after cancelling Dallinger/PsyNet commands.
  (author: Peter Harrison, reviewer: Frank Höger)
- Bugfix in imitation chain demo.
  (author: Peter Harrison)
- Fixed out-of-date dependency in PsyNet timeline demos.
  (author: Peter Harrison, reviewer: Frank Höger)
- PsyNet now uses Dallinger's functionality from PR 2324 for supporting custom Participant classes. This should solve some occasional database inconsistency errors.
  (author: Peter Harrison, reviewer: Frank Höger)

### Added

- Added `start_trial_automatically` option to PsyNet pages (`default=True`), which can be used e.g. to disable autoplay for audio.
  (author: Peter Harrison, reviewer: Frank Höger)

### Changed

- Remove time estimate text in new consents.
  (author: Frank Höger)
- Increase timeout in regression tests.
  (author: Peter Harrison)
- Set default number of threads to 1 in `psynet debug`, which saves about a second off the start-up time.
  (author: Peter Harrison, reviewer: Frank Höger)
- Optimised some import logic to improve import times. This should become particularly relevant once a
  pending Dallinger pull request is merged.
  (author: Peter Harrison, reviewer: Frank Höger)
- PsyNet now detects and kills old Heroku and Chrome sessions before starting a new debug session.
  (author: Peter Harrison, reviewer: Frank Höger)
- Disabled `check_participant_opened_devtools` by default; detecting participants opening developer tools
seems to be unstable, so experimenters should only enable this check at their own risk.
  (author: Peter Harrison, reviewer: Frank Höger)
- Updated the categories in the dashboard database table to make more sense with PsyNet objects (e.g. replacing Infos with Trials).
  (author: Peter Harrison, reviewer: Frank Höger)
- The regression test fixtures have been updated with the goal of fixing recent problems with test unreliability.
  (author: Peter Harrison, reviewer: Frank Höger)
- `psynet debug` now provides hot-refresh functionality by default. This means that you can edit the experiment code and see your changes without relaunching the experiment, simply instead refreshing your web browser. This can be disabled by passing the `--legacy` option to `psynet debug`.
  (author: Peter Harrison, reviewer: Frank Höger)

### Updated

- Updated Dallinger to v8.1.0, see release notes at <https://github.com/Dallinger/Dallinger/releases/tag/v8.1.0>

## [6.0.1] Released on 2022-03-02

### Fixed

- Changed logic for verifying the participant identity by replacing `fingerprintHash`/`fingerprint_hash` with a randomly generated `authToken`/`auth_token` stored in the participant table.s
  (author: Frank Höger, reviewer: Peter Harrison)
- Fix Dallinger version in demos' constraints.
  (author: Frank Höger)

### Added

- Added new participant variable auth_token.
  (author: Frank Höger, reviewer: Peter Harrison)

## [6.0.0] Released on 2022-02-23

### Fixed

- The response buttons in the headphone screening task now are disabled until the audio has finished playing
  (author: Pol van Rijn, reviewer: Peter Harrison)
- Fix deprecation warnings by replacing Selenium `find_element_by_*` commands with `find_element`
  (author: Frank Höger)

### Added

- Add new consent pages:
  `MainConsentPage`,
  `DatabaseConsentPage`,
  `AudiovisualConsentPage`,
  `OpenScienceConsentPage`,
  `VoluntaryWithNoCompensationConsentPage`
  (author: Frank Höger, reviewer: Nori Jacoby)
- Added new experiment variables `window_width` and `window_height` to allow for customization of
  the experiment window's size. Default: 1024 x 768
  (author: Fotini Deligiannaki, reviewer: Peter Harrison)
- Added new optional property `block_copy_paste` in `TextControl` that prevents copying, cutting and
  pasting in text input pages
  (author: Raja Marjieh, reviewer: Peter Harrison)
- Added functionality for detecting users opening the developer console in their web browser. If
  users open the developer console, they are shown a warning message telling them that they might be
  in trouble. The event is then logged in the participant table. This functionality can be disabled
  by setting `check_participant_opened_devtools=False` in the experiment variables
  (author: Pol van Rijn, reviewer: Peter Harrison)
- Added pre-sandbox/deploy sanity checks that check whether the values of
  `initial_recruitment_size` and `us_only` are set appropriately
  (author: Erika Tsumaya, reviewer: Peter Harrison)
- Added Python version to experiment variables
  (author: Frank Höger, reviewer: Peter Harrison)

### Changed

- Use `fingerprintHash`/`fingerprint_hash` instead of `assignmentId`/`assignment_id` to verify
  participant identity
  (author: Frank Höger, reviewer: Peter Harrison)
- Changed text under ASCII logo in command line output
  (author: Frank Höger, reviewer: Peter Harrison)
- Changed signature of `BaseCapRecruiter.reward_bonus` method due to breaking change in Dallinger v8.0.0
  (author: Frank Höger)

### Updated

- Updated Dallinger to v8.0.0, see release notes at <https://github.com/Dallinger/Dallinger/pull/3853>
  (author: Frank Höger)
- Updated Python to version 3.10 and Dallinger to version 8.0.0. in `.gitlab-ci.yml`
  (author: Frank Höger)
- Update docs for Python 3.10
  (author: Frank Höger)
- Updated black, isort, and flake8 to latest versions (used when running the Git pre-commit hooks)
  (author: Frank Höger)

### Deprecated

- Deprecated `MTurkStandardConsentPage` and `MTurkAudiovisualConsentPage`
  (author: Frank Höger)

## [5.2.0] Released on 2022-01-21

### Fixed

- Fixed `psynet export` failure for large databases.
- Temporary fix for missing `time_taken` in `UnityPage` response's metadata.
- Fixed breaking changes of new `time_estiamte` in demo `imitation_chain`.
- Improved the error message for duplicated module IDs.

### Added

- Added a new parameter `fail_on_timeout` (default = `True`) to `wait_while`;
  if this is set to `False`, the participant is no longer failed once the
  `max_wait_time` is exceeded, but instead continues with the experiment.
- Added `source` and `participant` attributes for `Network` classes.
- Added command-line tool `psynet rpdb`, which is an alias for `nc` allowing
  to easily perform (remote) debugging.
- Added `degree` and `phase` as `export_vars` in `ChainSource`.
- Added `phase` as `export_var` in `ChainNode`.
- Added `degree`, `phase` and `node_id` as `export_vars` in `ChainTrial`.
- Added GitLab merge request template.
- Added `username` attribute to `HelloPrompt`.
- Added regression test for data export.
- Added Monterey installation documentation.

### Changed

- Link 'Edit in GitLab' button to `master`, not `docs-staging` branch.

## [5.1.0] Released on 2021-11-30

### Added

- Added 'Edit on GitLab' button to documentation pages.
- Added `FreeTappingRecordTest` to prescreens.

### Fixed

- Renamed `clickedObject` to `clicked_object` in the graph experiment demo's `format_answer` method.

### Updated

- Updated Dallinger to v7.8.0.
- Updated google-chrome and chromedriver to v96.x in .gitlab-ci.yml.

## [5.0.2] Released on 2021-11-15

### Changed

- The time taken by the participant is now stored as a property of the `Trial` object
  (`Trial.time_taken`).
- By default, dynamic updating of progress bar and bonus display now only occurs
  for Unity pages. This makes the logs cleaner for standard PsyNet pages.

### Fixed

- Updated `get_template` to remove use of deprecated function `read_text`.
- (Re-)Added `jQuery` (v3.6.0) to the HTML head section of timeline-page.html. In Dallinger jQuery
  only gets loaded in the body section which causes a `$ is not defined` JS error when using the
  `AudioRecordControl` in PsyNet.

## [5.0.1] Released on 2021-11-10

### Fixed

- Fixed regressions in prescreening tasks.
- Fixed demos' constraints.
- Improved changelog notes for v5.0.0.

## [5.0.0] Released on 2021-11-10

### Added

- Added ability to disable progress bar (`experiment.var.show_progress_bar`).
- Added dallinger version to `psynet --version` output.
- Added `dallinger_version` experiment variable.
- Added audio-forced-choice prescreening task (thanks Pol van Rijn, Harin Lee).

### Breaking changes

- Refactored JavaScript variable and function names to camelCase,
  and HTML IDs and attributes to kebab-case.
  Experiments referring explicitly to these components may need to be
  updated accordingly.

The time estimation process has been revised in PsyNet, resulting in the following changes:

- Time-based bonuses now work differently for page makers and multi-page makers.
  Instead of allocating bonus according to the (multi-)page maker's `
  time_estimate` attribute, bonuses are now allocated according to the
  `time_estimate` attributes of the page(s) generated by the (multi-)page maker.
  The (multi-)page maker's own `time_estimate` is now only used for time estimation purposes,
  determining for example the progress bar and the predicted experiment duration/bonus
  displayed in the ad. In the case where the generated page(s) is/are missing a time estimate,
  the time estimate from the page maker object will be used instead, as before.
  - As a result of the above improvement, inaccurate `num_pages` attributes in multi-page trials
    no longer cause inaccurate bonus estimations, only inaccurate progress bars. In these cases
    PsyNet now displays a warning message advising the experimenter to set the appropriate
    number of pages, with this appropriate number of pages being displayed on the basis of
    the current run-time evaluation.
- The mechanism for setting the time estimates for trials has now changed.
  Previously such time estimates were specified by passing an argument called
  `time_estimate_per_trial` to the trial maker. This introduced an undesirable
  non-locality to PsyNet implementations, whereby changes to the trial class
  that impacted on time estimation had to be propagated far away to the
  trial maker constructor call, which was easy to forget.
  In the new version, trial time estimates are specified by setting a
  class attribute called `time_estimate` in the custom trial class, for example:

```py
class CustomTrial(Trial):
    time_estimate = 5
```

  An error will be thrown if the user neglects to set this `time_estimate`,
  or if they try to set it via the trial maker.

  To update PsyNet code to follow this new convention, see below.
  Here's an example of what the code might look like before:

```py
class CustomTrial(Trial):
    def show_trial(self, experiment, participant):
        return InfoPage("Hello!", time_estimate=5)

trial_maker = TrialMaker(**params, time_estimate_per_trial=5)
```

The updated code should look like this:

```py
class CustomTrial(Trial):
    time_estimate = 5

    def show_trial(self, experiment, participant):
        return InfoPage("Hello!", time_estimate)

trial_maker = TrialMaker(**params)
```

- New ``Trial`` fields have been added to help keep track of how time credit was assigned for trials:
  ``time_credit_before_trial``, ``time_credit_after_trial``, and ``time_credit_from_trial``.
  If a trial turned out to give an unexpected amount of time credit,
  PsyNet now delivers a warning message and recommends a revised value for ``time_estimate``.

### Other changes

- PsyNet now supports serialization of arbitrary objects to database fields.
  Serialization is accomplished using `jsonpickle`.
  No change should be necessary to experiment implementations;
  however the underlying database representation for some fields
  will have changed slightly. As a result, it is unlikely to be possible
  to relaunch experiments from zip files using PsyNet >=5.0.0 if the original version
  was deployed on PsyNet <5.0.0.

### Fixed

- Removed external references to `jQuery` and `platform` JavaScript libraries.
- Specified the version of Dallinger in gitlab-ci.yml.

## [4.2.1] Released on 2021-10-31

### Fixed

- Implemented fix for networks not growing properly in within-participant experiments
  with asynchronous processing.

## [4.2.0] Released on 2021-10-27

### Added

- Added new argument 'mirrored' to VideoRecordControl and VideoPrompt allowing
  the video to be displayed as if looking into a mirror.
- Added a button "Abort experiment" to the ad and error page, including two new environment
  variables 'show_abort_button' and 'min_accumulated_bonus_for_abort'. These additions
  make it possible for the experimenter to allow the participant to abort an experiment and
  be compensated automatically given the minimum amount of bonus has already been accumulated.
  The default is to not display the button.

### Changed

- Replaced the Audio Gibbs demo with an implementation of the emotional prosody
  experiment from our 2020 NeurIPS paper (Harrison et al., 2020)
  (thanks Pol van Rijn!).

## [4.1.0] Released on 2021-10-15

### Added

- Added new dashboard panel called 'Participant'.
  Here one can search participants by participant ID, worker ID, or assignment ID,
  and easily see the current status of the participant
  as well as their current estimated bonus.
  Functionality is also provided for resuming a given participant's session
  via a special URL.
- Added documentation for the ``compute_bonus`` method.

### Changed

- Reduced the default performance threshold in `LexTaleTest` from 10 to 8.
  The previous performance threshold was found to be much too stringent.
- Migrated the ``compute_bonus`` method from the ``Experiment`` class to the
  ``Participant`` class. Researchers should not be using this method directly,
  so this change should not affect most people.

### Fixed

- Fixed ReppMarkersTest

### Updated

- Updated Dallinger to v7.7.0.

## [4.0.0] Released on 2021-09-13

### Added

- Added a collection of dense rating paradigms (see `psynet.trial.dense`).
  These are still experimental, but they do have draft documentation.

### Changed

- Refactored the logic for queueing asynchronous processes, and created a new method
  ``queue_async_method`` that makes it easy to queue asynchronous functions for
  database objects such as networks and trials.
  See the ``async_pruning`` demo for an example.

### Fixed

- Fixed bug in ``AudioSliderControl`` (renaming of ``wrap`` to ``random_wrap``
  and deletion of ``phase`` arguments not propagated properly).
- The `promptEnd` event of JSSynth is now triggered by `promptStart` rather than `trialStart`.
  This facilitates customization where the JSSynth is triggered multiple times in
  the same trial.

### Renamed

- Renamed `check_timeout_interval` to `check_timeout_interval_sec`.

### Breaking changes

- Repeat trials are now constructed in a slightly different way.
  Previously, they were constructed in a way that permitted slight variation
  in surface features between a repeat trial and its originator;
  in the case of GSP, for example, this would mean a different randomized
  starting location for the slider. However, this behavior ended up
  being problematic for extensibility. In the new implementation, repeat
  trials are by default exact clones of their parents.
- `with_trial_maker_namespace` is now changed to remove the leading hyphens
  from trial-maker variables as they are stored in the database.
  This has the consequence that these variables (e.g. performance check results)
  will now be exported directly by `psynet export` into the main CSV files,
  rather than only being available in `db-snapshot`.
  This is a breaking change in that it will not be possible to relaunch
  experiments from zip file that were originally deployed with a
  previous PsyNet version.

## [3.1.0] Released on 2021-08-10

### Added

- Added `show_footer` experiment variable.
- Added `psynet update` command.

### Changed

- In the footer, only display detailed bonus (basic + extra) if `performance_bonus` > 0.

### Fixed

- Fixed display of progress and bonus on Unity pages.
- Fixed wrong `import` documentation.
- Fixed code for black, isort, and flake8.

### Updated

- Updated Dallinger to v7.6.0.
- Updated singing_iterated and tapping_* demos.

## [3.0.0] Released on 2021-08-03

### Fixed

- Fixed bug in 'stop' button for `AudioPrompt`.
- Fixed bug when displaying tooltip and module details in dashboard.
- Removed temporary fix for 'assignmenId' from start page.

### Added

- Added demo of translation workflow (see `demos/translation`).
- Added new iterated singing demo (see `demos/singing_iterated`).
- Added a new type of slider for `SliderControl`: `circular_slider`.
- Added optional `random_wrap` functionality to `SliderControl`.
- Prepared PsyNet for new Docker functionality.
  Note new format of requirements in `requirements.txt`.
  The functionality will be ready-to-use once the Dallinger pull request
  <https://github.com/Dallinger/Dallinger/pull/3016> is merged.
- Added `generate_constraints.py` for regenerating constraints for all PsyNet demos.
- Added experimental graph network API.

### Changed

- Revised implementation for `audio_gibbs_demo`.
- Added more detailed info to the bonus displayed in the footer.

### Breaking changes

- The API for `ProgressDisplay` and `ProgressStage` has now been improved.
  `ProgressDisplay` no longer takes a `duration` argument, the duration
  is instead computed automatically from the provided `ProgressStage` objects.
  `ProgressStage` now accepts a single number as the `time` argument,
  which determines the duration of the stage. The start time and end time
  are then inferred automatically with respect to the previous stage in the sequence.
  One can therefore write something like this:

````python
from psynet.timeline import ProgressDisplay, ProgressStage

ProgressDisplay(
    stages=[
        ProgressStage(0.75, "Wait a moment...", color="grey"),
        ProgressStage(1, "Red!", color="red"),
        ProgressStage(1, "Green!", color="green"),
        ProgressStage(1, "Blue!", color="blue"),
    ],
),
````

## [2.4.0] Released on 2021-07-21

### Fixed

- Improved efficiency of StimulusVersion queries.
- Fixed experiment network display bug.
- Fixed bug in GSP seed generation,
  whereby the initial `active_index` selection was not entirely uniform.

### Added

- Added failed_reason text to nodes and infos when calling their respective fail methods
- Use bumpversion for incrementing release versions.
- Added MANIFEST.in
- Added installation instructions for macOS Big Sur 11.3/M1

### Changed

- Pin Dallinger to version >=7.5.0

## [2.3.0] Released on 2021-07-07

### Added

- Store browser and platform information in participant table.

### Changed

- New way of how the contents of the `Ad page` are specified. See <https://computational-audition-lab.gitlab.io/psynet/experimenter/ad_page.html> for details.
- PsyNet now enforces at least one consent element to be included in a timeline. See `psynet/consent.py` for available consent modules. If you're sure you want to omit the consent form, include a ``NoConsent`` element.
- Minor improvement to video synchronization.

### Updated

- Updated repp and tapping demos.
- Updated Dallinger to v7.5.0.

### Fixed

- Fixed SQLAlchemy start-up error introduced in v2.2.1.

## [2.2.1] Released on 2021-06-21

### Fixed

- Fixed bug to make pre-deployment routines work again

## [2.2.0] Released on 2021-06-16

### Added

- Added new experiment variable ``hard_max_experiment_payment`` which allows for setting a hard, absolute limit on the amount spent in an experiment. Bonuses are not paid from the point the value is reached and the amount of unpaid bonus is saved in the participant's `unpaid_bonus` variable. Default is $1100.
- Allow for changing the soft and hard spending limits from the dashboard's timeline tab. Clicking on the upper, green progress bar shows/hides the corresponding UI widgets.

### Changed

- Renamed the `media_url` property of `RecordTrial` to `recording_url` so as to not clash with the same method name in `StaticTrial`.

### Fixed

- Fixed bug with wrong `minimal_interactions` functionality of `SliderControl` due to duplicate event handling in `control.html`.
- The renamed `recording_url` method incorrectly only returned camera urls. This was replaced with the correct `url` key.
- Fixed issue where `max_loop_time_condition` would be logged to the participant table
  every trial in a trial maker.

## [2.1.2] Released on 2021-06-15

### Fixed

- Hotfix for bonus/time estimation bug: `time_estimate` for `EndPage`
  is now set to zero. This means that experiment estimated durations
  (and corresponding bonuses) will decrease slighly.

## [2.1.1] Released on 2021-06-10

### Fixed

- Fixed incorrect version number.

## [2.1.0] Released on 2021-06-10

### Added

- Added new support for trial-level answer scoring and performance bonuses,
  via the `Trial.score_answer` and `Trial.compute_bonus` methods.
- Added `fade_out` option to `AudioPrompt`.

### Fixed

- Improved robustness of browser-based regression tests.
- Fixed incorrect performance bonus assignment for trial makers initialized with `check_performance_every_trial = True`.
- Various bugfixes in audio-visual playback/recording interfaces.
- Reverted the new language config.txt parameter, which was causing problems in various situations.
  This functionality will be reinstated in the upcoming Dallinger release.

## [2.0.0] Released on 2021-05-31

### Added

- Added support for video imitation chains and camera/screen record trials.
- Added a new system for organizing the timing of front-end events.
The API for some `Prompt` and `Control` elements has changed somewhat as a result.
- Added `ProgressDisplay` functionality, which visualizes the  current progress in the trial with text messages and/or
progress bars.
- Added `controls`, `muted`, and `hide_when_finished` arguments to `VideoPrompt`.
- PsyNet now requires a `language` argument in config.txt.
- New function: `psynet.utils.get_language`, which returns the language
specified in config.txt.
- Added the ability to parallelize stimulus generation in `AudioGibbs` experiments.
- Added `current_module` to a participant's export data.
- Allow for arbitrary number of audio record channels in `VideoRecordControl`.
- Update Dallinger to v7.4.0.

### Renamed

- Changed several methods from English to US spelling: `synthesise_target` (now `synthesize_target`),
`summarise_trial` (now `summarize_trial`), `analyse_trial` (now `analyze_trial`),
and all prompts and pre-screening tasks involving `colour` (now `color`).
- The output format for `TimedPushButtonControl` has now changed to use
camel case consistently, e.g. writing `buttonId` instead of `button_id`.
This reflects the camel case formatting conventions of the trial
scheduler and the JS front-end.
- Renamed `REPPMarkersCheck` -> `REPPMarkersTest`.
- Renamed `AttentionCheck` -> `AttentionTest`.
- Renamed `HeadphoneCheck` -> `HeadphoneTest`.
- Renamed `active_balancing_across_chains` -> `balance_across_chains`.
- Renamed `NonAdaptive` -> `Static`.

### Fixed

- make `play_window` work in `VideoPrompt`.
- Add `try`/`except` blocks in case of an `SMTPAuthenticationError`/`Exception` when calling `admin_notifier()`.
- Make `switch` work when a `TrialMaker` is given as a branch.
- Add `max_wait_time` and `max_loop_time` to `wait_while` and `while_loop`,  resp., to prevent participants from waiting forever.

### Changed

- PsyNet now forces `disable_when_duration_exceeded = False` in `config.txt`.
This is done to avoid a rare bug where recruitment would be shut down erroneously in long-running experiments.
- `psynet debug` now warns the user if the app title is too long.
- Allow varying numbers of arguments in function argument of `StartSwitch`.

### BREAKING CHANGES

- Required `language` argument in config.txt.
- Required `disable_when_duration_exceeded = False` argument in config.txt
- Various renamings, see section 'Renamed' above.

## [1.14.0] Released on 2021-05-17

### Added

- It is now possible to use `save_answer` to specify a participant variable
in which the answer should be saved:

```python
from psynet.modular_page import ModularPage, Prompt, NumberControl

ModularPage(
    "weight",
    Prompt("What is your weight in kg?"),
    NumberControl(),
    time_estimate=5,
    save_answer="weight",
)
```

The resulting answer can then be accessed, in this case, by `participant.var.weight`.

- Implement consent pages as `Module`s to be added to an experiment `Timeline` (CAPRecruiterStandardConsent, CAPRecruiterAudiovisualConsent, MTurkStandardConsent, MTurkAudiovisualConsent, PrincetonConsent).

### Changed

- Migrate background tasks to Dallinger's new `scheduled_task` API.
This means that the tasks now run on the clock dyno,
and are now robust to dyno restarts, app crashes etc.
- Apply DRY principle to demo directories (delete redundant error.html and layout.html files).
- Change the way experiment variables are set. For details on this important change, see the documentation at <https://computational-audition-lab.gitlab.io/psynet/low_level/Experiment.html>
- PsyNet now uses the `experiment_routes` and `dashboard_tab` functionality
implemented in Dallinger v7.3.0.

### Fixed

- Fix bug in static experiments related to SQLAlchemy.
- Prevent multiple instances of `check_database` from running simultaneously.

## [1.13.1] Released on 2021-05-05

### Fixed

- Fix name attribute default value for RadioButtonControl, DropdownControl, and CheckboxControl
- Fix some deprecation warnings in tests
- Update black, isort, and flake8 versions in pre-commit hook config
- Update google chrome and chromedriver to v90.x in .gitlab-ci.yml
- Implement missing notify_duration_exceeded method for CAPRecruiter
- Update Dallinger to v7.2.1

## [1.13.0] Released on 2021-04-15

### Added

- Video and screen recording
- Unity integration including a WebGL demo.
- Filter options for customising stimulus, stimulus version, and network selection.
- Integration of external recruiter with new CapRecruiter classes.
- Add `auto_advance` option to `AudioRecordControl`.

### Fixed

- Update for compatibility with SQLAlchemy v1.4.

### Updated

- Pin to Dallinger v7.2.0
- Replace deprecated `Page` classes with `ModularPage` class.

## [1.12.0] Released on 2021-02-22

### Added

- Enforce standard Python code style with `"black" <https://black.readthedocs.io/en/stable/>`**and `"isort" <https://github.com/pycqa/isort/>`**.
- Enforce Python code style consistency with `"flake8" <https://flake8.pycqa.org>`__.
- Added a new section 'INSTALLATION' to the documentation page with installation instructions for _macOS_ and _Ubuntu/GNU Linux_, restructured low-level documentation section.

### Changed

- Revert recode_wav function to an older, non scipy-dependent version.

### Updated

- Updated Google Chrome and Chromedriver versions to 88.x in `.gitlab-ci.yml`.
- Updated Python to version 3.9 and Dallinger to version 7.0.0. in `.gitlab-ci.yml`.

## [1.11.1] Released on 2021-02-19

### Fixed

- Fix export command by loading config.
- Remove quotes from PushButton HTML id.
- Use Dallinger v7.0.0 in gitlab-ci.
- Fix minor spelling mistake.

## [1.11.0] Released on 2021-02-13

### Added

- Added `NumberControl`, `SliderControl`, `AudioSliderControl` controls.
- Added new `directional` attribute to `Slider`.
- Added optional reset button to `CheckboxControl` and `RadioButtonControl`.
- Added new pre-screenings `AttentionTest`, `LanguageVocabularyTest`, `LexTaleTest`, `REPPMarkersTest`, `REPPTappingCalibration`, `REPPVolumeCalibrationMarkers`, and `REPPVolumeCalibrationMusic`.
- Added demos for new pre-screenings.
- Added favicon.ico.

### Fixed

- Fixed `visualize_response` methods for `checkboxes`, `dropdown`, `radiobuttons`, and `push_buttons` macros.
- Fixed erroneous display of reverse slider due to changes in Bootstrap 4.
- Fixed compatibility with new Dallinger route registration.

### Deprecated

- Deprecated `NAFCPage`, `TextInputPage`, `SliderPage`, `AudioSliderPage`, and `NumberInputPage` and refactored them into `ModularPage`s using controls.

### Removed

- Deleted obsolete `psychTestR` directory.

## [1.10.1] - Released on 2021-02-11

### Fixed

- Fixed compatibility with new Dallinger route registration.

## [1.10.0] Released on 2020-12-21

### Added

- Demographic questionnaires (`general`, `GMSI`, `PEI`).
- Improved visual feedback to `TimedPushButtonControl`.

## [1.9.1] - Released on 2020-12-15

### Fixed

- Fix bug in `active_balancing_within_participants`.

## [1.9.0] Released on 2020-12-15

### Added

- Added a new ``Trial`` attribute called ``accumulate_answers``.
If True, then the answers to all pages in the trial are accumulated
in a single list, as opposed to solely retaining the final answer
as was traditional.
- Improved JS event logging, with events saved in the `event_log` portion of `Response.metadata`.
- New `Control` class, `TimedPushButtonControl`.
- Added a new `play_window` argument for `AudioControl`.

### Changed

- Renamed ``reactive_seq`` to ``multi_page_maker``.
- ``show_trial`` now supports returning variable numbers of pages.
- Moved `demos` directory to project root.

### Fixed

- Fixed audio record status text.
- Fixed bug in ``get_participant_group``.

## [1.8.1] Released on 2020-12-11

- Fix regression where across-participant chain experiments fail unless the networks
used participant groups.

## [1.8.0] Released on 2020-12-07

### Added

- Participant groups can now be set directly via the participant object, writing
  for example ``participant.set_participant_group("my_trial_maker", self.answer)``.
- Chain networks now support participant groups. These are by default read from the
  network's ``definition`` slot, otherwise they can be set by overriding
  ``choose_participant_group``.

### Changed

- Update IP address treatment (closes CAP-562).
- Update experiment network `__json__` method to improve dashboard display.

### Fixed

- Fix problem where wrong assignment_x `super` functions are being called.
- Fix bug in `fail_participant_trials`.

## [1.7.1] Released on 2020-12-01

- Fix regression in ColorVocabulary Test.

## [1.7.0] Released on 2020-11-30

### Added

- Stimulus media extension to allow multiple files.
- New OptionControl class with subclasses: CheckboxControl, DropdownControl, RadiobuttonControl, and PushButtonControl.
- New Canvas drawing module and demo 'graphics' based on Raphaël vector graphics library.
- Ability to disable bonus display by setting `show_bonus = False` in the Experiment class.

### Changes

- Optimization of 'estimated_max_bonus' function.
- Refactor ad and consent pages using new default templates.

### Fixed

- Register pre-deployment routines.
- Missing role attribute for experiment_network in dashboard.
- Make recode_wav compatible with 64-bit audio files.

## [1.6.1] Released on 2020-11-16

### Fixed

- Error when using psynet debug/sandbox/deploy

## [1.6.0] Released on 2020-11-12

### Added

- Command-line functions ``psynet debug``, ``psynet sandbox``, ``psynet deploy``.
- ``PreDeployRoutine`` for inclusion into an experiment timeline.
- Limits for participant and experiment payments by introducing ``max_participant_payment`` and ``soft_max_experiment_payment`` including a visualisation in the dashboard and sending out notification emails.
- `psynet estimate` command for estimating a participant's maximum bonus and time to complete the experiment.
- `client_ip_address` attribute to `Participant`.
- Reorganisation of documentation menu, incl. new menu items `Experimenter documentation` and `Developer documentation`.
- Documentation for creating deploy tokens for custom packages and a deploy token for deployment of the ``psynet`` package.
- Ubuntu 20.04 installation documentation (``INSTALL_UBUNTU.md``)

## [1.5.1] Released on 2020-10-14

### Changes

- Improve data export directory structure

## [1.5.0] Released on 2020-10-13

### Added

- Add a new tab to the dashboard in order to monitor the progress been made in the individual modules included in a timeline and to provide additional information about a module in a details box and tooltip.
- Improve upload of audio recordings to S3 by auto-triggering the upload right after the end of recording.
- Add new export command for saving experiment data in JSON and CSV format, and as the ZIP-file generated by the Dallinger export command.
- Document existing pre-screening tasks and write a tutorial
- Update deployment documentation

### Changes

- Move pre-screening tasks into new prescreen module.
- Attempt to fix networks not growing after async post trial
- Bugfix: Enable vertical arrangement of buttons in NAFCControl

## [1.4.2]

- Fixing recruitment bug in chain experiments.

## [1.4.0]

- Extending extra_vars as displayed in the dashboard.

## [1.3.0]

- Added video visualisation.

## [1.2.1]

- Bugfix, now `reverse_scale` works in slider pages.

## [1.2.0]

- Introducing aggregated MCMCP.

## [1.0.0]

- Added regression tests.
- Upgraded to Bootstrap 4 and improved UI elements.
