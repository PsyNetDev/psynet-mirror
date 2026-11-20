# CHANGELOG

## [14.0.0rc4](https://gitlab.com/PsyNetDev/PsyNet/-/tags/v14.0.0rc4) Release candidate - 2026-11-17

### Breaking Changes

- `compile_nodes_from_directory` now requires media under `static/` and stores `/static/...` URLs in the node definition instead of creating assets. Move the files from `data/` to `static/` and pass `self.definition["url"]` (or your `url_key`) to prompts; the old `asset_label` argument is replaced by `url_key`. Media extensions are matched case-insensitively against the end of the file name (so `.nii.gz` works), and nodes are compiled in alphabetical order by participant group, block, and filename.
- Asset classes are now named after how the file is made: `FileAsset` (formerly `ExperimentAsset` and `CachedAsset`) and `GeneratedAsset` (formerly `CachedFunctionAsset`), alongside `OnDemandAsset` and `ExternalAsset`. Whether an asset is included in `psynet export` now follows from when it was made rather than from its class: assets stored while the experiment is running, such as recordings and chain-generated stimuli, are exported; assets prepared before launch, which come from the experiment directory and code, are not. On-demand and external assets are never exported. As a result, stimulus files declared in the timeline are no longer exported, and `asset(function)` no longer requires `cache=True` or `on_demand=True`. The `type` column of the exported `assets/manifest.csv` changes accordingly, for example from `psynet.asset.ExperimentAsset` to `psynet.asset.FileAsset`; update any analysis scripts that filter on it.

  ```python
  asset("bier.wav")                 # FileAsset; not exported when declared in the timeline
  asset(generate_tone)              # GeneratedAsset; exported only if created during the run
  asset(plot_path, parent=trial)    # FileAsset created during the run; exported
  ```
- Experiment code that runs PostgreSQL `COPY` (for example `cursor.copy_expert`, `dallinger.postgres_copy.copy_from`, or a pandas `to_sql` COPY recipe) in a web request or background job must now wrap it in `psynet.db.blocking_psycopg()`. Otherwise psycopg2 raises `ProgrammingError`, because these processes now let other requests run during database waits. PsyNet's own export and import already do this.

  ```python
  from psynet.db import blocking_psycopg

  with blocking_psycopg():
      cursor.copy_expert("COPY my_table TO STDOUT WITH CSV HEADER", out)
  ```
- Video answers now upload after submission in LocalStorage experiments with in-place navigation. Playback outside trials must wait for deposit and handle missing recordings. Replace `PageMaker(playback, time_estimate=5)` with:

  ```python
  wait_for_recording(lambda participant: participant.assets["recording"]),
  PageMaker(
      lambda participant: playback(participant)
      if participant.assets["recording"].deposited
      else InfoPage("Recording unavailable. Please continue.", time_estimate=5),
      time_estimate=5,
  ),
  ```

  Import `wait_for_recording` and `InfoPage` from `psynet.page`. A missing answer recording fails only its parent trial, without recapturing: immediately when the browser reports it unavailable (for example, camera access denied), otherwise once the browser stops uploading it for 2 minutes (for example, because it was closed) or 30 minutes after acceptance. Slow uploads are not failed: the browser renews them while it holds the recording, and a participant can be at most one recording page ahead of their uploads, waiting at **Next** on slow connections instead of building a backlog. Received recordings have 5 minutes, including queueing, to be stored. A submission whose reply was lost can be resent safely. Camera and screen streams are reused across consecutive recording pages and released once a page that does not record is shown. Uploads require an EBML header but are not decoded. Full-document transitions and recruiter exit wait for pending uploads to be received or fail; manual navigation warns while uploads remain pending. Bots upload their recordings through the same route as participants. Legacy navigation and other storage backends still upload with the answer, but now share the capture code: recordings are WebM only, and if capture fails, the page cannot be submitted until the participant reloads it to record again. The `video_recording` browser capability now requires WebM recording support, so browsers that can only record MP4 are screened out.
- Removed `balance_across_nodes` and `balance_across_chains`; pass `node_order="balanced"` / `chain_order="balanced"` or `"random"` instead. Passing `block_order` while overriding `choose_block_order` now raises an error.
- Changed static trial makers so that `target_trials_per_node` only decides when `recruit_mode="n_trials"` stops recruiting: nodes are no longer withheld once they reach it, and planned node orders always give the planned nodes. With `node_order="balanced"`, no Python selection hooks and no `node_priority`, participants who request a trial at the same moment are given different nodes where possible. Chain `trials_per_node` remains a hard limit. Fixed `n_trials` recruitment letting surplus trials on one node offset a shortfall on another.
- Made trial maker blocks strict: participants only receive nodes or chains from their current block, and stay in it until `max_trials_per_block` or `should_finish_block` ends it or it runs out. When every candidate in the block is busy, `wait_for_networks=True` waits and `False` finishes the block early. `should_finish_block` now takes `(participant, block)`, `module_state.block` is read-only, `set_block_state` has been removed, and an empty list from `find_chains` or `find_nodes` finishes the block instead of the trial maker. `GeometricStaircaseTrialMaker` now defaults to `interleave_chains=False`, so each participant finishes one staircase before starting the next.
- Experiment code that runs while a participant moves through the timeline (code blocks, page makers, page methods such as `format_answer`, `validate`, `on_complete` and `pre_render`, trial methods and trial maker hooks such as `grow_network`, `finalize_trial` and `select_node`, and custom recruiter methods called from the timeline such as `release_participant`) now raises an error if it calls `db.session.commit()` or `db.session.rollback()`. Committing there released the participant's lock and could save half-finished work. The same applies to `grow_network` and `on_finalized` when the background growth and finalization checks run them, and to `on_finalized` in async workers after an async post-trial analysis or asset deposit. PsyNet commits for you; use `db.session.flush()` when you need a new object's ID. Recruiter calls that pay participants or end their panel session (`experiment.pay_decided_bonus`, `recruiter.reward_bonus`, `recruiter.report_submission_outcome`, and Lucid's `terminate_participant` and `complete_participant`) also raise there, before contacting the platform and even when there is nothing to send: make them from an `AsyncCodeBlock`, which runs after the step has been saved.
- Chain-based trial makers (including staircase and graph) now default to `recruit_mode=None` instead of `"n_participants"`, like static and dense trial makers, which leaves recruitment to the rest of the experiment. Every recruitment target now needs its matching `recruit_mode`: `target_n_participants` and `n_participants_completion="trial_maker"` require `recruit_mode="n_participants"`, and `target_trials_per_node` (or `target_trials_per_condition`) requires `recruit_mode="n_trials"`. Otherwise construction raises `ValueError`, as does a `recruit_mode` that is not in `recruit_criteria`.
- Lucid termination no longer saves the participant's failed status before calling Lucid; the termination is saved as soon as Lucid confirms it, and Lucid complete and terminate requests now give up if Lucid does not respond within 30 seconds. The private `BaseLucidRecruiter._terminate_participant` hook is removed: recruiters that customise Lucid termination should override `terminate_participant`, which now takes a keyword-only `raise_on_error` argument (default `False`) that the Leave button path sets to `True`.
- Renamed async processes to async jobs: `psynet.process` is now `psynet.async_job`, and `AsyncProcess`, `WorkerAsyncProcess` and `LocalAsyncProcess` are now `AsyncJob`, `WorkerAsyncJob` and `LocalAsyncJob`. Creating a job no longer runs it; call `.enqueue()`, which launches the job once the transaction commits, and PsyNet logs a warning for a job that is created but never enqueued:

  ```python
  # Before
  from psynet.process import WorkerAsyncProcess

  WorkerAsyncProcess(function=analyse, arguments={"trial": trial})

  # After
  from psynet.async_job import WorkerAsyncJob

  WorkerAsyncJob(function=analyse, arguments={"trial": trial}).enqueue()
  ```

  The old names still work with a `DeprecationWarning`: `AsyncProcess` is the same class as `AsyncJob`, `AsyncJob.get_process` calls `get_async_job`, and `WorkerAsyncProcess(...)` and `LocalAsyncProcess(...)` create and enqueue the job. Class attributes such as `WorkerAsyncProcess.query` and `isinstance` checks against the old names are passed on to the new classes, but a subclass of an old name is a subclass of the new class, so its jobs must be enqueued. The `async_processes` attribute of participants, trials, nodes, networks, responses and assets returns `async_jobs`. `Experiment.handle_error` now receives `async_job=` instead of `process=`, and `ErrorRecord.process_id` is now `async_job_id`. The performance test's JSON results report `async_job_stats` instead of `process_stats`. In exports, `database/process.csv` is now `database/async_job.csv`, its `type` column holds names such as `psynet.async_job.WorkerAsyncJob`, `error.csv` has `async_job_id` instead of `process_id`, and `participant.csv` has `awaited_async_code_block_job_id` instead of `awaited_async_code_block_process_id`. The unused `Trial.fail_async_processes` method is removed.
- Upgraded the jQuery that PsyNet timeline pages load from 3.7.1 to 4.0.0. The Lucid dashboard no longer loads a second jQuery on top of the one Dallinger's dashboard provides. Custom JavaScript that uses utilities jQuery 4 removed (for example `$.trim`, `$.isArray`, `$.isFunction` or `$.parseJSON`) must switch to native JavaScript, and templates that link `/static/scripts/jquery-3.7.1.min.js` must link `jquery-4.0.0.min.js` instead. See step 3 of the PsyNet 14 upgrade checklist.
- Bots in `psynet performance-test` and in parallel `psynet test` runs (`--parallel` or `test_mode = "parallel"`) now run as threads in one process, sharing one experiment instance, instead of starting a `psynet run-bot` process each. 200 bots take about 250 MB of memory and a third of a CPU core, so a local test can simulate hundreds of participants without the bots competing with the server. Bot code that relies on module-level state or on `self`, such as a global counter or `random.seed()`, now affects every bot at once: store per-bot traits on `bot.var` in `initialize_bot`, and use a `random.Random()` instance instead of seeding the global generator. Experiments whose `run_bot` override takes a `bot` argument now work in performance tests, parallel tests and `psynet run-bot`.
- Experiments now admit all modern browsers by default. `force_google_chrome` defaults to `false`, so Firefox and Safari participants are admitted unless you set `force_google_chrome = true`, which now admits all Chromium-based browsers (Chrome, Edge, Brave, Opera). Every experiment rejects browsers without CSS `:has()` support (Chrome < 105, Firefox < 121, Safari < 15.4), which PsyNet's own CSS needs, whatever `force_google_chrome` is set to. The `min_browser_version` config key has been removed; delete it from `config.txt` and `~/.dallingerconfig`, because PsyNet refuses to start with unknown config keys.
- `psynet.perf_test` is now a package. `PerformanceTester` runs a single test, and `PerformanceSuite(tester, limits=...)` runs several with `run(bot_counts)` or searches for capacity with `find_capacity()`, replacing `PerformanceTester.run`. Each result is a `PerformanceTestResult` dataclass whose fields are the keys that `--json-output` and the audit's `performance.json` save; `PerformanceTestResult.from_dict()` reads a saved result, and the fields are listed under "Saving results" in the docs on testing scalability. The JSON no longer includes `avg_response_time`, `p99_response_time`, `stddev_response_time`, `p95_wait_page_time`, `max_wait_page_time`, `avg_failed_duration`, `avg_incomplete_duration`, `avg_init_time`, `initialization_times`, `n_succeeded_bots` (the same as `bots_succeeded`) or `completed_during_test`; `queue_waits`, with an entry for each async job priority, replaces `q_delay_p95`; and `n_rq_workers` and `n_rq_job_slots` are `null` when the workers can't be counted.
- `psynet performance-test ssh` now only runs on apps that it deployed for performance tests, never on an existing deployment, because the tests fill the app's database with bots and may reset it. If the server has no app named `--app`, it deploys the experiment from the current directory in debug mode, as `psynet debug ssh` does and with the same `--server`, `--dns-host`, `--ingress`, `--use-local-psynet` and `--use-local-dallinger` options, so you no longer run `psynet debug ssh` first. The app's config sets the new `performance_test_app` variable, which later runs read inside the app's web container; they update the app in place from the current directory before testing, keeping its database. Apps without the mark, such as one deployed with `psynet debug ssh`, and apps whose deploy never finished launching the experiment are refused, with advice on what to do instead. After a run the app is kept, and the command prints how to destroy it. Setting `performance_test_app = true` in `config.txt` yourself declares that the app's data is disposable, and `psynet deploy ssh` refuses to deploy with it set. Your computer now runs the series of tests or the capacity search, one test at a time in the app's web container, with the same options, test lengths and summary as a local run, and `--json-output` works with `performance-test ssh`.
- Audio answers from `AudioRecordControl` now upload after submission in LocalStorage experiments with in-place navigation, like video answers. Any later page that plays back or processes the recording, including a later page of the same trial (other than feedback), must wait for it and handle a missing recording. Replace a `wait_while` on `.deposited` followed by playback with:

  ```python
  wait_for_recording(lambda participant: participant.assets["recording"]),
  PageMaker(
      lambda participant: playback(participant)
      if participant.assets["recording"].deposited
      else InfoPage("Recording unavailable. Please continue.", time_estimate=5),
      time_estimate=5,
  ),
  ```

  A missing audio recording fails only its parent trial, without recapturing: immediately when the browser reports it unavailable, otherwise when its upload expires. Trial analysis such as `analyze_recording` and trial feedback already wait for the recording. The warm-up playback in the built-in `FreeTappingRecordTest` prescreen now shows a message when the practice recording is missing. Subclasses of `AudioRecordControl` or `VideoRecordControl` that override `format_answer` or `macro` keep uploading with the answer, because they may read the recording bytes there. Bots upload their `bot_response_media` through the same route as participants, so it must be a WAV file; custom bot responses must also use `bot_response_media` rather than returning blobs. Uploaded audio may be at most about one and a half times the control's `duration` plus 5 seconds, so pages that end recording on their own event should set `duration` to the longest expected recording. Legacy navigation and other storage backends keep uploading audio with the answer.
- `PushButtonControl`, `KeyboardPushButtonControl`, `DropdownControl`, `RadioButtonControl` and `CheckboxControl` now save the picked element of `choices` with its original type, so `DropdownControl([1, 2, 3])` saves the integer `3` instead of the string `"3"`. Code that compares such answers to strings, such as `answer == "3"`, must compare to numbers instead. Choices that share the same text, such as `1` and `"1"`, now raise `ValueError`.
- The `/node/<node_id>/fail`, `/info/<info_id>/fail`, `/trial/<trial_id>/fail`, `/network/<network_id>/grow` and `/network/<network_id>/call_async_post_grow_network` routes now require a dashboard login and accept only POST. Previously anyone who could reach the server could fail any node, info or trial, or grow any network or queue its post-grow job, by loading a URL with its sequential id. Scripts that call these routes must now POST with the dashboard credentials, for example `requests.post(url, auth=(dashboard_user, dashboard_password))`.
- Dallinger's `/worker_complete` and `/worker_failed` routes now need the participant's `unique_id` as well as `participant_id`, so a request that knows only a participant's sequential id can no longer mark them complete or failed. PsyNet's Finish button, `dallinger.submitAssignment()` and the test bots send it. Custom code that posts to these routes with only `participant_id` now gets a 403 and needs to add `unique_id`, for example `dallinger.post("/worker_complete", {participant_id: dallinger.identity.participantId, unique_id: dallinger.identity.uniqueId})`. A `/handle-error` report without the participant's `unique_id` is still recorded but no longer completes the participant. An experiment that overrides `Experiment.check_worker_status` must return `super().check_worker_status(participant)` whenever it would otherwise return `None`.
- Opening the `/asset/<access_token>` URL of an HTML, XHTML, SVG, XML (including any `+xml` type), XSL (`text/xsl`) or JavaScript asset now downloads the file (`Content-Disposition: attachment`) instead of displaying it, including in a frame. An experiment that shows such an asset as a page must serve it from `static/` (outside `static/assets`) instead; an SVG asset still displays as an `img` source.
- The dashboard now refuses state-changing requests (POST, PUT, PATCH, DELETE) that a browser sends from another website, so a page on another site can no longer make a logged-in researcher's browser fail nodes, pay bonuses or archive deployments. This covers `/dashboard/...` routes and any other request made with the dashboard login. Scripts that call the dashboard with `requests` or the PsyNet CLI are unaffected. The dashboard routes that change state now accept only POST: `/dashboard/archive/deployment`, `/dashboard/restore/deployment`, `/dashboard/update/recruitment` and the Lucid status route. The Timeline tab's routes moved from `/module`, `/module/tooltip`, `/module/progress_info` and `/module/update_spending_limits` to the same paths under `/dashboard` (for example `/dashboard/module/update_spending_limits`), and the Lucid status route moved from `/change_lucid_status` to `/dashboard/change_lucid_status`. Scripts that call these routes must use the new URLs, and POST instead of GET where the route now accepts only POST, for example `requests.post(f"{url}/dashboard/change_lucid_status", data={"status": "paused"}, auth=(dashboard_user, dashboard_password))`. Experiment classes can no longer override these Timeline and Lucid route handlers. Opening `/dashboard/export/trigger` (such as the Slack "Trigger export" link) now shows a button that starts the export instead of starting it straight away.
- Experiment server responses now send `X-Frame-Options: SAMEORIGIN`, so other sites can no longer show the experiment in a frame. An experiment that must be framed by another site can remove the header in its own `after_request`. Dallinger calls this method on the experiment class, so define it as a class method:

  ```python
  class Exp(psynet.experiment.Experiment):
      @classmethod
      def after_request(cls, request, response):
          response = super().after_request(request, response)
          response.headers.pop("X-Frame-Options", None)
          return response
  ```
- Export and artifact downloads (`/dashboard/export/preflight`, `/dashboard/export/download` and `/dashboard/artifact/...`) now always require the dashboard login. Previously requests from `127.0.0.1` skipped it, so anyone reaching `psynet debug local` through a public tunnel could download the export. `psynet export` and logged-in browsers are unaffected; scripts on the server that fetched these URLs without a login must now send the dashboard credentials, for example `requests.get(url, auth=(dashboard_user, dashboard_password))`. `psynet export` now also says when the dashboard refuses its login, instead of reporting an unreadable response.
- `LanguageVocabularyTest` answers are now the screen position of the chosen picture (`"1"` to `"4"`) instead of `"correct"`/`"wrong1"`/`"wrong2"`/`"wrong3"`, so exported answers change meaning; find the chosen picture with the trial's `definition["order"]`. Custom `LanguageVocabularyTrial` subclasses that compare the answer with `"correct"` must compare it with `definition["correct_answer"]` instead, and subclasses that override `finalize_definition` must call `super()` or set `definition["correct_answer"]` (the 1-based position) themselves.
- `LocalStorage.get_url` and the `LocalStorage.local_path`, `LocalStorage.public_path` and `LocalStorage.label` properties have been removed, because locally stored assets are no longer reachable under `static/assets`; use the asset's `url` instead.
- `BaseLucidRecruiter.get_participant` now takes the Lucid RID instead of the request, as `get_participant(assignment_id)`, and no longer links the RID to the participant. Custom recruiter subclasses that override `get_participant(request)` must accept the RID instead. If several participants share the RID, it now raises `MultipleResultsFound` instead of logging an error and returning `None`; `/terminate_participant` reads it with `BaseLucidRecruiter.requested_assignment_id(request)`.
- Custom code that calls the Lucid `/terminate_participant` route for an existing participant with only `RID` or `assignmentId` now gets a 403 error and must add the participant's `unique_id`. Because PsyNet's mobile-phone and browser checks on the ad and consent pages send only the RID, a Lucid participant who has already started and opens the ad or consent page again now gets a 403 error page instead of being terminated and returned to Lucid.
- Participant pages now escape HTML in plain strings, as Flask's own templates do. A plain `str` is shown as text wherever a template writes it with `{{ ... }}`: control labels (for example `labels` and `choices` of `PushButtonControl`, `KeyboardPushButtonControl`, `CheckboxControl` and `RadioButtonControl`), `AudioPrompt` `controls` labels, `Button` text, `KeyboardPage` prompts, `WaitPage` content, and values passed through `template_arg` or read by custom prompt and control macros. Prompt, `InfoPage`, `wait_while` and `render_exit_message` text already worked this way. To keep HTML that you wrote yourself, wrap it in `markupsafe.Markup` or build it with `dominate` tags; `render_exit_message` now accepts `Markup` too. Never wrap participant-provided text in `Markup`: write `Markup("<b>{}</b>").format(answer)`, which escapes `answer`, instead of `Markup(f"<b>{answer}</b>")`. Strings in `Experiment.css` and page `css` are still written as CSS, instructions given to `AttentionTest` and `AudioForcedChoiceTest` are still shown as HTML, and messages translated in templates with `gettext` or `pgettext` may still contain HTML, so inside an HTML attribute write them as `"{{ gettext(...) | forceescape }}"`. Inside `<script>`, write values with `{{ value | tojson }}`. Custom dashboard tabs that render `dashboard_custom.html` or the card macros in `macros/dashboard.html`, and pages that render `custom_html.html`, now escape plain strings too: pass `html`, card bodies and list items as `Markup` (for a `dominate` tag, `Markup(tag.render())`). `compose_hold_overlay_html` now escapes a plain-string first argument as well; pass `Markup` for HTML. `AudioMeterControl.to_json` now returns a plain `str`, so custom templates must write `{{ params.to_json() | tojson }}`. A `REPPVolumeCalibration` subclass whose `what_are_we_playing` returns HTML must return `Markup`. `KeyboardPage` now requires `prompt`; in 13.3.0 it could be left out by mistake, which showed a Python type name in place of the prompt. The `static` demo's `KeyboardPushButtonControl` choices no longer contain `<kbd>` markup (the key hints moved to `labels`), so its answers now match the choices that `score_answer` checks. The Participants dashboard's resume link now shows `:` in unique IDs as `%3A`.

  ```python
  # Before: the label was written as raw HTML
  PushButtonControl(choices=["cat"], labels=['<img src="/static/cat.png">'])

  # After
  from markupsafe import Markup

  PushButtonControl(choices=["cat"], labels=[Markup('<img src="/static/cat.png">')])
  ```
- On SSH deployments, experiment code can no longer write files into ``static/`` at runtime, because the experiment image no longer makes ``/experiment/static`` writable for the account the experiment runs as. Write such files to a temporary directory (for example with Python's ``tempfile``) or store them as assets instead.
- A websocket connection that names a participant, on `/experiment-socket` or on `/chat`, must now send that participant's `websocket_scope` as its scope, or PsyNet refuses it. PsyNet's own sockets do this. Custom page code that opens one should pass the token, for example `dallinger.openExperimentSocket({scope: psynetTemplateData.websocketScope})`. The same applies to Dallinger helpers that send `dallinger.pageScope` by default when they name a participant, such as `openChatSocket`, `joinRealtimeSession` and `waitForRealtimeSession`: pass the token as their `scope`. Because every page of a participant sends the same token, a directed message sent with a scope reaches all of that participant's open pages. A connection that names no participant is unaffected. Built-in chat rooms (`ChatRoom` with `EnableChatrooms`) now run over checked connections: the sender of each message is the participant whose page sent it, a participant can join only the room their current page shows, and messages, occupancy and history go only to the room's current members. Each membership records the page it was joined from in a new `ChatRoomMember.page_uuid` column, which also appears in exports. A `WebSocketElt` can opt in to the same guarantee with `requires_checked_connection = True`. Custom JavaScript that polls `/timeline/progress_and_reward` or `/timeline/arrival_notice` must send `uniqueId` instead of `participantId`.
- Pages shown from a barrier's `waiting_logic` now end when the barrier releases the participant: the page moves on `release_grace` seconds (default 3) after the browser notices the release, which is usually within about 2 seconds, and saves an empty response with `interrupted` set in its metadata; the page's `on_complete` doesn't run, and the rest of the participant's pass of `waiting_logic` is run through without showing its pages (its code blocks still run, and each `while_loop` in it ends at its next check, including PsyNet's own waits such as waiting for a trial). The participant whose arrival completes the group runs through the whole pass in the same way. This includes trial pages, such as filler trials from a trial maker: a trial whose page ends before it is answered, any trial that the rest of the pass reaches, which is created but never shown, and a trial that a trial maker had prepared for its next pass, is failed with `failed_reason="interrupted_by_release"`, so it isn't finalized, shows no feedback page and doesn't count towards the trial maker's targets of completed trials (it still counts towards `max_trials_per_block` and `n_created_trials`). Keep `waiting_logic` atomic, with one short trial or page per pass as in the `sync_quorum` demo, so that a release fails at most the trial on screen and creates no unseen trials. A barrier with `waiting_logic` can't be placed inside a trial's own pages (it raises an error there); use `waiting_screen` instead. Before, participants finished the current waiting page first. Pass `release_grace=None` to `Barrier`, `GroupBarrier` or a grouper to keep the old behavior. `release_grace` only applies with `waiting_logic`, and passing it without raises an error. During the grace period the page shows a countdown such as "Your group is ready. Moving on in 3 s."; pages can listen for the new `psynetWaitingRelease` browser event and call `preventDefault()` on it to show their own notice instead. Experiments that override `Experiment.process_response` should accept `**kwargs`, because interrupted pages pass `interrupted=True`.
- The `min_group_size` column of `SimpleSyncGroup` (the `sync_group` table, its export and the dashboard) is renamed `quorum`. A `SimpleGrouper` whose `min_group_size` or `quorum` is below `initial_group_size` now raises an error unless it is given `below_quorum` (`"fail"` or `"continue_without_group"`), so that the experiment says what happens to the remaining members when a group falls below its quorum. A `SimpleGrouper` with groups of three or more and no `quorum` now warns; pass `quorum=initial_group_size` to keep the old behavior.
- `Trial.sync_group` now returns the group the trial was played in (`trial.sync_group_id`), also after the participant has left it, instead of the participant's current group of the trial maker's type. It also works for cued trials, where it used to raise `AttributeError`.
- `participant.var.get(name)` (and `get` on other variable stores, such as `experiment.var` and `node.var`) now returns `None` for a variable that isn't set, like `dict.get`, instead of raising `KeyError`. Code that relied on the error should use attribute access, as in `participant.var.name`, or `participant.var.has(name)`.
- Default bot answers on `NumberControl`, `TextControl`, `MonitorControl`, the slider controls, `FrameSliderControl`, `MultiRatingControl`, `RatingControl` and graphics pages now go through the page's or the control's `format_answer`, as browser answers do, so bots save the same type and shape as participants. For example, a `RatingControl` bot now saves the rating (`3`) instead of `{"rating": 3}`. A page or control that overrides `format_answer` now formats its default bot answers too, so it must accept them: a `TextControl` page whose `format_answer` returns `int(raw_answer)` now fails in bot tests unless it is given a `bot_response`. The built-in `get_bot_response` methods of these controls now return a `BotResponse` holding the browser's raw answer, so a subclass that calls `super().get_bot_response(...)` must read `.raw_answer` from the result: the typed text for `NumberControl` (`"57"`) and SurveyJS JSON text for `MultiRatingControl` and `RatingControl`. Such a subclass should return `BotResponse(raw_answer=...)` so that its answer still goes through `format_answer`. Whole-number floats in any `BotResponse(raw_answer=...)`, not only the built-in defaults, are now submitted as ints, as the browser's JSON does: a rating scale given as `{"low": 0.0, "high": 1.0}` saves `1`. Answers given with `bot_response` or returned as plain values from `get_bot_response` are still saved as given.
- `NumberControl` now saves the answer as a number, for participants and default bots alike: an `int` for a whole number such as `100` and a `float` otherwise, so typing `78.5` saves `78.5` instead of the string `"78.5"`. Code that converts the answer with `float(...)` or `int(...)` still works, but code that compares it to a string, such as `answer == "100"`, must compare to a number instead. The typed text is lost, so `02139` is saved as `2139`; use `TextControl` for codes such as postcodes or IDs where the exact text matters. `NaN`, infinity and text with `_` such as `1_000` are now rejected. A fixed bot answer is saved as given, so it must be a number too: `bot_response=25` passes validation, `bot_response="25"` and `bot_response=True` fail it.
- `PushButtonControl`, `KeyboardPushButtonControl`, `RadioButtonControl`, `DropdownControl` and `CheckboxControl` now reject a submitted answer that is not one of their choices, so check two patterns that would otherwise leave participants stuck on "You need to select an answer!". First, if a control or page overrides `format_answer` to save something other than a choice, such as a dictionary of the choice and a reaction time, set `restrict_to_choices = False` on the control class or pass `restrict_to_choices=False` to the control; `TimedPushButtonControl` and its subclasses already do this. Second, the page is built again when the response arrives, so choices picked at random while building a page, for example with `random.sample` in a `PageMaker` or `show_trial`, must be the same each time: pick them once (in `finalize_definition` or `participant.var`) or pass `restrict_to_choices=False`. Each rejection logs a warning with the page label, the answer and the choices. The check catches out-of-range values from a tampered request and a bot `bot_response` of the wrong type (`"3"` for the choice `3`), and runs before any `validate`, so a control's or page's own `validate`, including a page that overrides `validate` like the demography `CountryOfBirth` page, cannot accept such an answer. Empty answers such as `None` still pass this check and are left to `force_selection`, and the free-text option of `RadioButtonControl` accepts any text. `CheckboxControl(force_selection=True)` now rejects a `None` answer instead of raising an error, and `DropdownControl(force_selection=True)` and the required country and language demography pages reject it too.
- Changed the group barrier time-outs of the 14.0 release candidates. `GroupBarrier`'s `timeout_between_barriers_time` and `timeout_between_barriers_action` are renamed `late_after` and `late_action`, and trial makers' `sync_group_timeout_between_barriers_time` and `sync_group_timeout_between_barriers_action` are renamed `sync_group_late_after` and `sync_group_late_action`; the old names raise a `TypeError` naming the new ones. `late_action` no longer has a default, so `late_after` raises a `ValueError` unless it is given as `"fail"` or `"leave_group"`. With `late_after`, `max_wait_time` (and trial makers' `sync_group_max_wait_time`) now defaults to no limit instead of 20 seconds plus the timeout, and passing a limit raises an error, since `late_action` already moves slow members on. A member who has started a page with a `time_limit`, other than a waiting page, since the group last passed a barrier is not late until that time limit has run out plus 10 seconds, so that an answer sent at the deadline can arrive. `late_after` counts from a member's admission to the group, which is when they joined unless the grouper admits newcomers at admission points.
- Changed what happens to groups that fall below their minimum size since the 14.0 release candidates. Groupers' `fail_participants_below_min_size` is replaced by `SimpleGrouper(below_quorum=...)`: `"fail"` fails the remaining members, and `"continue_without_group"` lets them continue without the group, and their next page tells them why ("Your partner is no longer in your group. Please continue."). Passing `fail_participants_below_min_size` raises a `TypeError`; replace `fail_participants_below_min_size=False` with `below_quorum="continue_without_group"`. `below_quorum` must be given when groups are designed to shrink: when `quorum` is below `initial_group_size`, or when a `GroupBarrier` with `late_after` acts on the group type, directly or through `also_leave`. Otherwise it defaults to `"fail"`. The experiment refuses to load when a barrier with `late_action="leave_group"` acts on a group whose grouper has `below_quorum="fail"`, which would let the late member carry on while the members who were on time are failed; a barrier built in `show_trial` raises the same error when the trial is shown, and for barriers neither check can see, such as those built in a `for_loop`, PsyNet logs a warning when that happens. `SimpleSyncGroup.dissolve_if_below_min_size()` is renamed `dissolve_if_below_quorum()`. A member leaving with removal reason `"finished"` or `"moved_on"` doesn't dissolve a group by itself, but the group's next `GroupBarrier` dissolves a group left below its quorum. While a group accepts newcomers (`join_existing_groups=True`), its barriers wait for newcomers instead, up to the grouper's `top_up_wait`; with `use_admission_points=True`, only its admission points wait. "Groups below quorum" in the synchronization docs gives the full rule.
- The `content` option of `wait_while`, `AsyncCodeBlock`, `Barrier`, `GroupBarrier` and groupers, from the 14.0 release candidates, is renamed `waiting_message`, and trial makers' `sync_group_wait_content` is renamed `sync_group_waiting_message`. Barriers, groupers and trial makers given the old names raise a `TypeError` naming the new one; `wait_while` and `AsyncCodeBlock` raise Python's usual error for an unknown argument.
- Participants failed because their sync group fell below its quorum now get the failure tag `sync group below quorum` instead of `sync group below minimum size`. Update analysis scripts that filter on the old tag.
- `ParticipantFailRoutine`s no longer see in `participant.active_sync_groups` the groups that the participant left before being failed. Members failed by a `GroupBarrier`'s `max_wait_time` or `late_action="fail"`, or because their group fell below its quorum with `below_quorum="fail"`, now leave their groups first, so their removal reason is recorded. A fail routine that needs the group can use `participant.latest_sync_group(group_type)`.
- Removed `Notifier.python_dependencies` and `Experiment.check_python_dependencies()`. Deploys used them to check that `constraints.txt` pins `slack-sdk` for the Slack notifier, which it always does because `slack_sdk` is part of `psynet[experiment]`. A custom notifier that listed packages in `python_dependencies` no longer stops a deploy when one is missing; add those packages to your experiment's `requirements.txt` instead.

### Added

- `psynet performance-test local` now measures export time: after the last test,
  it runs `psynet export local` on the database the tests filled and prints how
  long it took and how many participants and responses it exported. Use
  `--no-export` to skip. The `--json-output` file records it in a top-level
  `export` object with `duration_s`, `error` and the exported table sizes
  (`db_rows`). Export time is tracked as a new `track_export_time_s` metric in
  the ASV benchmark suite.
- Added ``n_participants_completion`` to TrialMakers, which selects whether ``n_participants`` recruitment counts experiment completions or TrialMaker completions. The default ``"experiment"`` preserves the previous quota. In ``"trial_maker"`` mode, people still working in the experiment who have not finished this TrialMaker occupy a slot, including those who have not reached it yet. Participants who leave through early exit do not occupy a slot.
- Added an unauthenticated ``GET /health`` endpoint that checks the web process, PostgreSQL, and Redis, and returns a public-safe snapshot of title, label, experimenter name, recruitment status, and request volume.
- Added `--update` to `psynet deploy ssh` and `psynet debug ssh`. It rebuilds a running app's image in place after a confirmation, keeping its database, deployment ID and secret, and refuses to switch an app between debug and live.
- Added `psynet.media.static_url_for`, which returns the percent-encoded `/static/...` URL for a file under the experiment's `static/` folder.
- Added optional camera and screen background recording alongside ordinary page answers in in-place LocalStorage experiments, with a Recordings dashboard and recording outcomes in the asset manifest. Set `VideoRecordConfig(required=True)` within a trial to require its clips: the trial cannot finalize, and its feedback waits, until they arrive, and it fails if a clip is unavailable or its upload expires before it arrives. Optional clips never hold feedback or pages that do not record. Capture stops at its duration or size limit and keeps what was recorded. Later required pages offer another permission decision if capture was denied or stopped.
- Added `psynet docs`, which reads the documentation for the installed PsyNet version from disk, without the experiment runtime or a network connection. `psynet docs show code/participants/payment` prints a page (website URLs work too), and `psynet docs path` prints the folder so coding agents can search every page at once, for example with `rg -n -i --no-ignore "bonus" "$(psynet docs path)"`. Release packages now include the documentation as plain text, and a PsyNet source checkout uses `docs/` directly. The experiment `AGENTS.md` and the Agent Skills now tell agents to read the documentation this way.
- Added `--n-bots` to `psynet audit simulate`, which sets the number of bots for one run like `psynet test local --n-bots` (for example `psynet audit simulate --n-bots 40`). Without it, the command still uses `Experiment.test_n_bots`.
- Added ``psynet hibernate ssh`` and ``psynet awaken ssh``. ``psynet export ssh`` wakes a hibernating app before reading its database.
- When the recruiter is Prolific, `psynet estimate` warns if `prolific_estimated_completion_minutes` is shorter than the estimated duration, or if `base_payment` over the longer of the two falls below Prolific's minimum hourly rate (£6 or $8), which bonuses don't count towards.
- Added a Playwright 1.62+ helper to the `record-participant-video` Agent Skill that records headless participant walks as `participant.mp4` with audio on any OS, plus a sync probe that measures the audio latency correction; `psynet audit validate` now warns when a participant video's audio track is silent.
- A submission made while a hibernating SSH app is asleep or waking shows "Getting ready, please wait..." and is retried for up to five minutes, instead of showing the error page.
- Added ``--use-local-dallinger`` to ``psynet debug ssh`` to bake an unreleased Dallinger checkout into the experiment image. Without the flag, an exported ``DALLINGER_SOURCE`` is ignored, and ``psynet deploy ssh`` always installs the Dallinger version pinned in ``requirements.txt``.
- Added ``psynet deploy ssh --ingress cloudflare`` (and ``psynet debug ssh --ingress``) for per-app Cloudflare tunnels, when the installed Dallinger supports them.
- SSH deployments record ``kind=psynet`` in the Dallinger deployment manifest, so status pages can find PsyNet experiments.
- Release wheels now include the demos' code and text files (without media or vendored libraries), and `psynet docs demos` prints the folder that holds them, so coding agents can read and search demo code for the installed PsyNet version without a source checkout or web access.
- Added a `timelineHoldChanged` browser event that fires when one timeline hold leads straight into another while the waiting overlay stays visible, for example at stacked group barriers. Its `detail` has `holdId` and `previousHoldId`, so scripts listening to `timelineHoldStarted` and `timelineHoldEnded` can follow which hold is active.
- Added trial-maker hooks that keep trial selection fast with many nodes or chains: `filter_nodes_query` / `filter_chains_query` filter candidates in the database, `node_priority` / `chain_priority` rank them, `before_selection` returns `"wait"` or `"exit"` before PsyNet looks for candidates, and `selection_pool_size` limits how many eligible candidates reach `select_node` / `select_chain`. PsyNet logs a warning when Python selection hooks load 1000 or more candidates for one trial.
- Added `block_order`, `node_order` and `chain_order` trial maker arguments, which accept dynamic orders (`"balanced"`, `"random"`), planned orders (`"listed"` or a function, which may also leave items out) and per-block dicts; `interleave_chains=False`, which keeps a participant on one chain until it is finished (the new default for `GeometricStaircaseTrialMaker`); and `psynet.utils.shuffle_with_max_run` for shuffles that limit runs of similar items.
- Added a `max_wait_time` argument to `AsyncCodeBlock`, setting how long a waiting participant may wait for the function before being failed (default 20 seconds).
- Several local experiments can now run at once on one machine, for example when several coding agents test different experiments: give each terminal its own `DATABASE_URL`, `REDIS_URL`, `base_port` and `dallinger_develop_directory`. `psynet debug local` now serves on `base_port` in its default auto-reload mode, and tests that share an experiment directory wait for each other instead of deleting each other's generated files.
- Added an `on_timeout` argument to `wait_while` and `AsyncCodeBlock`, called with the participant when the wait reaches `max_wait_time`, for example to notify the researcher; `AsyncCodeBlock` skips it if its function has finished or failed by the time the participant's page next checks in. Like other timeline code, it must not call `db.session.commit()`.
- `psynet test local` and local `pytest` sessions (from the PsyNet checkout, or in experiments whose `pytest.ini` is up to date via `psynet scripts update`) now run in their own PostgreSQL database, Redis server, web port and development folder (without `redis-server` installed, they use a spare database on the shared Redis, so live notifications can still reach a debug server's participants), so they no longer reset or stop a running `psynet debug local`, and several test sessions can run at once. If that environment can't be set up, the session stops with an error instead of touching the shared services, and it refuses to start while `psynet debug` serves the same experiment directory, whose generated files the tests would replace. `psynet performance-test local` and `psynet audit performance-test` (without `--existing`) get their own services and refuse in that case too. Each session's database and development folder are removed, and any spare Redis database is emptied, when it ends. Set `PSYNET_TEST_ENVIRONMENT=shared` to use the current services instead (the session then prints a warning, and other values are rejected); CI is unaffected. The experiment `pytest.ini` template now also collects the generated `test.py`, so plain `pytest` runs an experiment's tests.
- Added a limit on simultaneous participants for studies recruited through a public link (`generic` and `hotair` recruiters). Set the experiment variable `max_concurrent_participants` (experiment code can change it while the study runs), or override `Experiment.is_at_capacity()` to measure load differently. When the study is full, newcomers wait on the start page, which lets them in automatically once there is space, so a spike of visitors no longer slows the study down for people already taking part. Bots from `psynet test` and `psynet performance-test` are not held back by the cap. The performance test's capacity search now suggests the matching `max_concurrent_participants` setting alongside its recommended number of participants when the recruiter supports it.
- Added `psynet debug local --isolated`, which runs the debug server on a free port with a temporary database and Redis of its own, like `psynet test local`, so it can run alongside another local debug server and tests. It prints an `export` line that points other local commands, such as `psynet export local`, at its data. The database and Redis are removed when the server stops, so export any data you need while it runs. `psynet debug local` and `psynet deploy local` now also refuse to start in a directory that tests or another server are using, and tests refuse, instead of waiting, while a server uses their directory.
- Added `psynet services list`, which shows the port, database, Redis server and directory of each PsyNet session you are running, and which session uses each local Redis server and database.
- Added `psynet debug ssh --use-local-psynet`, which builds your editable PsyNet checkout, including uncommitted changes, into the experiment image instead of installing the PsyNet version in `requirements.txt`. With this option or `--use-local-dallinger`, the image installs a copy of `constraints.txt` (or `requirements.txt`) without that package's lines, so an editable pin generated from your development environment does not break the build. Each option also skips the sandbox checks on that package's pin, so bundled demos can be launched on a server with `--use-local-psynet` without editing `requirements.txt`. Run `psynet scripts update` first in existing experiments, whose `Dockerfile` does not yet install local builds. If an interrupted run leaves a `psynet-*.whl` or `local-image-pins.txt` in the experiment directory, every command that builds a Docker image stops and asks you to remove it, so it can't replace the pinned versions. When a debug or deploy command stops because PsyNet is not pinned and PsyNet is installed editable, the error suggests this option.
- Added a `cpu_time` column to async jobs, recording the CPU seconds each job's function used. `psynet test local` now ends with a table of CPU and wall time per async job label that says whether each job runs in a worker or the web process and flags CPU-heavy jobs, and the new `plan-server-resources` Agent Skill explains how to use it to plan worker processes before a performance test.
- Added high and low priorities for worker async jobs, so that analyses a participant is waiting for start before analyses nobody is waiting for. PsyNet chooses the priority from whether a participant waits for the result (for example `AsyncCodeBlock(wait=True)` or an `async_post_trial` behind a performance check, feedback or the next trial of a within-participant chain); override it with `AsyncCodeBlock(priority=...)`, `Trial.async_post_trial_priority` or `WorkerAsyncJob(priority=...)`. The CPU time table after `psynet test local` now shows each job's priority.
- Added protection for pending async jobs on docker-ssh deployments: idle hibernation keeps the app awake while jobs are pending, `psynet export ssh` and `psynet export local` end with a warning that the export misses their results, and `psynet destroy ssh` wakes the app, reports its pending jobs, and asks for confirmation (or refuses when it cannot ask) unless `--discard-pending-jobs` is passed. `psynet destroy ssh --app ...` now exits with status 1 when the app is not destroyed.
- Added `--yes`/`-y` to `psynet destroy ssh` to skip the confirmation prompt, for single apps and for batches. The single-app confirmation now names the app and server it will delete.
- Added the `browser_capabilities` class attribute to `Experiment` for declaring browser capability requirements. When it is set, PsyNet inserts a `BrowserCapabilityCheck` prescreener at the start of the timeline, which tests the participant's browser and routes to `UnsuccessfulEndPage` if any check fails. Override `Experiment.get_browser_capability_check` to customize the check, or return `None` from it to place the check yourself. Supported tokens: `audio_playback`, `video_recording`, `screen_capture`, `microphone`, `camera`. Permission-requiring capabilities show a dedicated intro page before requesting access.
- Added `--n-bots auto` to `psynet performance-test local`, `psynet performance-test ssh` and `psynet audit performance-test`, which searches for the server's capacity. It doubles the bot count from 10 until a test exceeds the capacity limits, then bisects until the largest passing and smallest failing counts are within 10% of each other; each search test lasts one session, at most 5 minutes. It then runs a validation test at the recommended number of participants, with bots arriving over one session, for two sessions (at most an hour), and reports the recommendation as confirmed only if that test kept the limits and reached its steady state. Skip the validation test with `--no-confirm`. When the smallest failing count only showed limits of the test process, the summary reports the capacity as a lower bound, or as unknown, without recommending a number. The summary also estimates how many async worker processes (`worker_processes`) the recommended number needs and whether to set `worker_greenlets_per_process = 1`, from how busy the workers were in the steady state and the start-up burst, limited by the server's CPU cores; the JSON records `worker_load` and `server_cores`.
- Added `--reset-database` and `--prefill-participants N` to `psynet performance-test ssh`, so that every test starts from the same data and the tests of `--n-bots auto` compare load rather than amounts of data. Before the first test PsyNet copies the app's database into a temporary snapshot in the app's PostgreSQL container; before each later test it stops the app's containers except PostgreSQL, Redis and the front door, recreates the database from the snapshot, empties the async job queues and starts the stopped containers again. `--prefill-participants N` implies `--reset-database` and first runs N bots through the experiment, 50 at a time and without pauses. When the run ends, also after a failed reset or an interrupt, PsyNet restores the database to how the run found it, before any pre-fill, and drops its copies; if it can't restore it, or the restore is interrupted, it keeps the copy it restores from, drops the others, explains how to recover by destroying the app and running the test again, and fails. A failed reset stops the run but still prints the summary and writes the JSON for the completed tests, with the error as `reset_error`. A worker that hangs at start-up after a reset is left to Dallinger's `worker_startup_timeout`, which exits it so that Docker starts it again; PsyNet waits up to 180 s for the workers to register, printing progress, and otherwise fails with an error that names the workers that didn't register and gives the `docker compose restart` command. Resets never touch an experiment in live mode, even with `--force`, and are refused when the disk lacks twice the database's size free. These options are only available over SSH.
- Added options to `psynet performance-test local`, `psynet performance-test ssh` and `psynet audit performance-test` for more realistic loads. `--bot-processes` spreads the bots over several processes so that large tests aren't limited by what one process can send; the default, `auto`, uses one process per 250 bots, up to one per four CPU cores. `--arrival-minutes` spreads each test's bots evenly over that many minutes, as participants arrive while a study is open; it can't be combined with `--stagger` or with `--n-bots auto`. Without `--duration-minutes`, each test lasts 1.5 participant sessions (the timeline's estimated duration times `--time-factor`, at most 30 minutes), and the suite header warns when a test is shorter than one session. Performance tests refuse to run if the database has participants that PsyNet bots didn't create, if the experiment runs in live mode, or if its recruiter can bring real participants; pass `--force` if the experiment isn't collecting real data. `--json-output` is written after every test, replacing the file atomically, so an interrupted run keeps the tests that finished (`finished_at` is null until the run ends). Server and bot logs go to `~/psynet-data/performance-logs`, which keeps the 20 most recent of each.
- Added a `stack_depth` option to `--sql-profile-options` (and `PSYNET_SQL_PROFILE`), so that captured query stacks can reach the route that issued them. Chain trial makers now record in the participant's trial maker state, as `blocks_ended_busy`, the blocks that `wait_for_networks=False` ended early because every chain was busy, leaving out chains busy only with their last trials; participants are not failed.
- Added support for a callable `max_wait_time` in `wait_while` and `max_loop_time` in `while_loop`. The callable receives `participant` and/or `experiment` and is evaluated once, when the wait starts, so a time limit can depend on the participant's state.
- Added `psynet dev changelog next-alpha`, which prints the development version `master` should carry (the next major alpha while breaking-change fragments are pending, otherwise the next minor alpha) and sets it with `--write`. A `changelog-version` pre-commit hook, which also runs in CI, now rejects a version that names too low a major while breaking-change fragments are pending.
- Added `--use-local-psynet` to `psynet performance-test ssh`, which builds your editable PsyNet checkout into the app it deploys, as `psynet debug ssh --use-local-psynet` does. Use it to test bundled demos, whose `requirements.txt` doesn't pin PsyNet.
- The version check run before deploying now warns when `requirements.txt` pins the commit of an editable PsyNet or Dallinger checkout that has uncommitted changes to tracked files, because a server installs the pinned commit rather than the local edits. Changes inside the experiment directory, such as a bundled demo under `demos/`, are ignored, because those files are uploaded with the deployment.
- `psynet deploy ssh` and `psynet deploy heroku` now list deployed files with uncommitted changes and, in a terminal, ask "Deploy anyway?" (default no, which cancels the deployment); non-interactive deploys only warn. Deployments record the names of up to 20 such files, and `psynet export` names the uncommitted files when it reports a project mismatch.
- `psynet destroy ssh` asks whether to delete the apps' data on the server (database, Redis and Postgres volumes, `~/dallinger-data/<app>`), and reminds you to export apps it finds no local export of just before the question that decides whether their data is deleted. For a single app, Dallinger lists the data with its sizes and asks; for several apps, PsyNet asks once for all of them. `--remove-data` and `--keep-data` answer in advance and are required in non-interactive runs; kept data is listed with the `psynet destroy ssh <app> --server <server> --remove-data` command that deletes it, which also works once the app itself is gone. This needs a Dallinger version whose `dallinger docker-ssh destroy` has these options; with older versions, destroying works as before and the two flags are refused. `psynet destroy ssh` and `psynet destroy heroku` now show Dallinger's output directly instead of under a spinner.
- Added `--yes` to `psynet debug ssh` and `psynet deploy ssh`, which skips the confirmation of `--update`. When `--update` has no terminal or piped answer to read, it now stops with an error asking for `--yes` instead of a bare `Aborted!`.
- `psynet debug ssh` and `psynet debug heroku` accept `--no-consent`, which skips the check that the timeline has a consent page, so you can try a demo or an unfinished experiment on a server without adding `NoConsent()` to its timeline. When the check fails on these commands, its message mentions the option. `psynet deploy` commands still require a consent page.
- The `waiting_message` of `wait_while`, `Barrier`, `GroupBarrier` and `Grouper` now accept `dominate` tags as well as `markupsafe.Markup`, and `psynet.utils.finalize_template_value`, which marks a `dominate` tag as safe HTML for a template, is now public.
- Added an `extend_while` option to `while_loop`. It is checked at the start of each pass through the loop, and whenever it returns `True` the loop does not time out and the `max_loop_time` clock restarts from zero. Trial makers use it so that waiting for the next trial cannot time out until the participant's last required recording has been stored or has failed.
- The `waiting_message` of a `wait_while` hold can now be a module-level function of the participant, as for barriers, so that participants waiting at the same point can see different messages, for example by role.
- Added `psynet.group_prompt.GroupPrompt`, which shows the members of a group as their pseudonym animals drawn in their colours, in a row or a zigzag across the page, ticks members off live as they answer (in place of the group arrival notice), with a grey dash instead for members whose page's time limit ran out, and shows members who join or leave, and then shows everyone's answers in speech bubbles, with optional highlights such as the winner. Its `note` is part of `bot.current_page_text`. A page shows either progress (`show_progress`, on by default without `answers`) or `answers`, and contradictory combinations raise an error. A member has answered once they wait at a barrier of the group. `names=` chooses how members are named: `"on_hover"` (default), `"shown"` below each animal, or `"anonymous"`, which shows every member as the same neutral figure. Joining their first sync group now gives a newcomer a different pseudonym if an active member already has their derived one (`PseudonymScheme.assign_distinct` chooses it); pseudonyms set with `Participant.set_pseudonym` are kept. `PseudonymScheme.render_sticker` draws these animals, using bundled Microsoft Fluent Emoji pictures (MIT licence) for the built-in animals. The synchronous demos (`chatroom_simple`, `create_rate_sync`, `gibbs_within_sync`, `rock_paper_scissors`, `sync_quorum`, `group_closer` and `ultimatum_pairing`) show their groups with it.
- Added helpers for games played in rounds. `GroupPrompt` finds the participant's group of type `group_type` when `group` is omitted (`group_type` may also be left out while the participant has only ever been in groups of one type), and shows only the text when the participant is no longer in a group or `group=None`. `GroupPrompt` draws the group's active members and, on a results page, everyone in `answers`, even after they left the group, so that a results page reads the same after a reload; a member whose answer is `None` keeps their seat without a speech bubble, and a former member is faded and labelled "(left)" unless they moved on or finished. `advance_past_wait_pages` now keeps polling until a `timeout` (10 s by default; pass more for tests whose rounds start on a clock or deadline) and names the bots still waiting when it gives up.
- Added pseudonyms such as "Blue fox", shown as a picture of the animal in the participant's colour, so that participants can tell each other apart without seeing IDs. Chat rooms now label messages and the participant list by pseudonym instead of "Participant 12"; the list shows the participant's own name as "Blue fox (you)". `ChatRoom(names="anonymous")` labels the others as an anonymous `GroupPrompt` does, "Your partner" or "Another player", instead, and doesn't send that page their pseudonyms or participant IDs, which appear under per-room aliases such as `member-2`; a new `ChatRoomMember.anonymous` column, which also appears in exports, records it. The dashboard's Participants and Database pages show each participant's pseudonym (not searchable). A new "Pseudonyms" documentation page describes them. Use `participant.pseudonym` to show the same names on other pages, `participant.set_pseudonym(...)` to choose one, and a `PseudonymScheme` subclass on `Experiment.pseudonym_scheme` to change the colours, animals, names or pictures (`colors`, `animals`, `assign`, `format_name`, `render_sticker` and `artwork`). Each built-in name is translated as a whole, so that translations can make the colour agree with the animal.
- Added `Regrouper` for multiplayer games played in rounds. At the start of each round it splits everyone waiting into new groups, optionally within persistent cohorts (`within="cohort"`). Set `group_size` (and optionally `smallest_group`, the smallest group it forms when numbers don't divide, 2 by default), or `roles`. A round starts once everyone is ready or its `deadline` passes, or at fixed wall-clock ticks with `every=45`. Participants who miss a round join the next one instead of holding others up or being failed. Groups can be shaped with `form_groups(members, within_group, barrier)` or by overriding `Regrouper.form_groups`, as the `ultimatum_pairing` demo does to keep last round's partners apart (each group is a list of participants and, with roles, has one member per role), odd players out can be released to a sit-out page with `left_over="sit_out"` (a player waiting alone first waits up to one more deadline for cohort members who are still playing; the regrouper's default `max_wait_time` of 300 seconds grows to twice the deadline or `every` period plus 60 seconds when that is longer, and a value you pass must be longer than twice the period), and `on_release(within_group, groups, left_over, barrier)` runs after each split, with groups that already have their `id`, so it can be saved as a pair ID. A `{SECONDS}` placeholder in the regrouper's `waiting_message` shows a live countdown to the next round. To show other text while that time is unknown, for example "Waiting for another player.", pass a function of `seconds_left` as `waiting_message`; it gets `None` until the time is known, and returns a literal `{SECONDS}` for a live countdown. Only waits with a release time (a regrouper with `deadline` or `every`, or a `SimpleGrouper` with `start_short_after`) can count down; a `{SECONDS}` placeholder in any other `waiting_message` raises an error. A participant removed from their group, for example by `late_action="leave_group"`, now passes later `GroupBarrier`s of that group type alone instead of getting an error; only a participant who was never in such a group, or whose group was closed by a `GroupCloser`, gets one.
- A member removed from their group by a `GroupBarrier` with `late_action="leave_group"` now sees "Your partner went on without you. Please continue." or "Your group went on without you. Please continue." on the progress bar until they leave their page, even when their removal dissolves the group. Several late members removed at once are all recorded as late. Customize it with `on_arrival_message` (`kind="late"`), or return `None` there to hide it. A member removed with `max_wait_action="leave_group"` after waiting too long sees "Your partner didn't arrive in time. Please continue." (or "Not everyone in your group arrived in time. Please continue.") on the page they move on to (`kind="waited_too_long"`).
- Added `SimpleGrouper(start_short_after=..., start_short_with=...)`, which starts a smaller group once the longest-waiting participant has waited `start_short_after` seconds and at least `start_short_with` participants are waiting. `start_short_with` defaults to the grouper's `quorum`, and `quorum` defaults to `start_short_with` and may not be larger, so that a group started short isn't below quorum at its first barrier. Pass `quorum` or `start_short_with`; without either, `start_short_after` raises an error. A `{SECONDS}` placeholder in `waiting_message` counts down to that start once enough people are waiting, and until then the page shows "Waiting for other participants…".
- The early-end page now says why PsyNet ended a participant's session in a multiplayer experiment: they took too long to reach the next barrier, waited too long for other participants, or too few members of their group remained. To explain your experiment's own reasons, pass `UnsuccessfulEndLogic(failure_message=...)` either a string, which replaces PsyNet's lines for every participant, or a function of the participant that returns a sentence (or `None` to use PsyNet's line). End pages, which used to ignore a `failure_message` argument, now raise a `TypeError` pointing to `UnsuccessfulEndLogic`.
- Added the `ultimatum_pairing` demo of a round-based multiplayer game with `Regrouper`.
- Added `waiting_screen` to barriers and groupers: text, a prompt or a `ModularPage` the participant can't submit (no Next button, push buttons or `auto_advance`), or a function of the participant that returns one, to show in place of their last page while they wait, with the waiting message still on top. A wait without a waiting screen that follows another barrier's waiting screen shows a plain waiting page, since the participant's last page is no longer on screen. Bots read the waiting screen's text as their page text, and `advance_past_wait_pages(stop_at=...)` leaves bots waiting at the given barriers until those barriers release them, for example a responder while the test plays the proposer. The `ultimatum_pairing` demo uses it to show each player's choice while their partner decides, and to replace the instructions and results while cohorts and pairs form. The `ultimatum_pairing` decision page now also counts down from 30 seconds, and a player who runs out of time gets nothing that round, and nor does their partner.
- Added `time_limit` and `time_limit_answer` to pages: the page shows a countdown at the top, where waiting messages appear, and submits `time_limit_answer` when time runs out. Pass `time_limit_answer=CURRENT_ANSWER` (from `psynet.timeline`) to record what the participant has entered so far instead. The server counts from when the participant reached the page, so a reload does not restart the clock, and it records `time_limit_answer` for answers that arrive too late. `Response.time_limit_reached` says whether an answer was given because time ran out, and the browser dispatches a `psynet:timeLimitReached` event on `document` just before a timed page submits itself. Timed pages cannot have a `session_id`, and `time_limit_answer` needs a `time_limit`. End logic takes `time_limit`, so the final page continues by itself with a countdown instead of waiting for a click on Finish. The `rock_paper_scissors` and `create_rate_sync` demos time their choice or vote pages and `chatroom_simple` times its chat, so a player who keeps one of those pages open without answering no longer holds up the others; a player who closes the tab is still handled by the barriers' wait limits.
- `Regrouper` now does the bookkeeping of games played in rounds. By default it groups participants at random and sits out those who have played the most rounds. It counts each participant's rounds (`rounds_played(participant)`, `rounds_sat_out(participant)`, and `sat_out(participant)` for the latest round), and with `roles=["proposer", "responder"]` gives each group one member per role, which a cued trial reads as `trial.sync_group_role`. Roles are shuffled across each group's members by default; override `Regrouper.assign_roles` (or pass `assign_roles(members, within_group, barrier)`) for another rule, as the `ultimatum_pairing` demo does to give each role to whoever has held it least often. All of this happens under the regrouper's lock, so two rounds starting at once cannot hand out the same role twice. Sync groups record which grouper formed them and when, and each member's role is stored with their group membership, so exports show who played which role in every round.
- `wait_while` takes `waiting_screen`, which shows a screen in place of the participant's last page while they wait, as barriers and groupers do.
- `GroupBarrier`'s `on_release` can now take `leader`, the group's leader. `participant` still works and is the same object.
- Added helpers for testing how a group experiment handles dropouts. `bot.drop_out()` leaves the experiment as if the participant returned the study on the recruitment platform, and the default `test_check_bot` accepts bots that did so. It and `bot.fail()` check the group's barriers before returning, so the partners waiting there have already been released. `bot.failed` reads whether a bot has failed, and `bot.current_notice` returns the notice its progress bar shows, such as "Your partner is no longer in your group. Please continue.". `bot.allow_failure()` tells the default `test_check_bot` that a bot may fail, `bot.with_participant(function)` calls a function with the bot's participant, for example to read its role, and `bot.send_chat_message(text)` posts to the chat room on its page. `participant.in_sync_group("pair")` tells whether a participant is still in a group of that type. The `synchronous-experiments` skill now asks for a bot test for each kind of dropout; run `psynet scripts update` to get it.
- Added `psynet.bot.run_bots_to_completion(bots)`, which takes pages for several bots in turn until all have finished, for bots that still wait for each other, such as players a `Regrouper` keeps pairing, and `psynet.bot.bots_by_sync_group(bots, group_type)`, which sorts bots into their current groups so a test can find who plays with whom.
- Added `bot.run_out_of_time()`, which lets the time limit of a bot's current page run out without an answer, as a participant who leaves a timed page open does.
- Added support for `functools.partial` in saved callbacks such as `GroupBarrier(on_release=...)`, so one callback can serve several barriers with its own keyword arguments, which take precedence over the arguments PsyNet passes. PsyNet refuses arguments that would be lost, namely positional ones and names the function doesn't take. For example:

  ```python
  def score_question(group, question):
      ...

  GroupBarrier(id_="question_1", group_type="team", on_release=partial(score_question, question=1))
  ```

  Saved class methods and trial maker methods now receive every argument the callback is given, such as `leader`.
- A page with a `ChatRoom` now raises an error naming the missing element when the timeline has no `EnableChatrooms()`, instead of showing a chat whose messages go nowhere.
- Added the `crowd_estimate` demo, a wisdom-of-crowds game in an open lobby: groups may start short and take latecomers until the game starts, a group that falls below three before the game starts waits briefly for a replacement, and anyone left without a group answers the questions alone. Each question is one cued trial per player in the group's round of that number (`round=`), with the group's median on the round the group's trials share and on the trial whether each estimate counted towards it, and an export that includes whether each estimate timed out, from the estimate's own response (`Response.time_limit_reached`); the group design and synchronization docs use it as their example of top-ups and of solo play through ungrouped cued trials (`sync_group_optional = True`).
- Added group rounds for cued trials: a trial class with `sync_group_type = "room"`, cued with `PickTrial.cue(definition)`, records the participant's group, role and round, and the trials that a group's members cue in one module and round share one `SyncGroupRound` record (`trial.group_round`), whose `var` holds the group's results and whose `trials` lists the round's trials. Grouped cued trials use the module's default node, like ungrouped ones. Without `round=`, `cue` numbers each group's rounds from 0 by itself: a cue joins the group's newest round while it is open and the participant has no trial there, and otherwise starts the next. A round is open until one of its `GroupBarrier`s releases the group, so a round needs a barrier inside `show_trial`, and building a grouped trial's pages raises an error if `show_trial` has none. A `Regrouper`'s groups use this automatic numbering and play round 0. A fixed group that plays a loop of rounds should pass the loop value as `round=`, so that each iteration is the group's round of that number and its definition can come from the loop; two trial classes played one after the other in one round also pass the same `round=`. The round's first cue sets the round's definition, and a later cue with a different `dict` raises an error. `definition` can be a function of `group` and `round`, called once per group and round (for ungrouped cues, once per trial). `GroupBarrier` `on_release` callbacks can now take `trials`, the members' current trials, and `group_round`, the group's round when those trials are in it, so a `@classmethod` on the trial class can score the round. At any other barrier, such as one in `show_feedback` or at the start of a module or of a later run of the same module, `group_round` is `None` and `trials` holds each member's current trial. Module states now store `run_index`, which counts the participant's runs of the module from 1 and appears as a new column in exports. The `ultimatum_pairing` demo plays its rounds this way and builds its basic data from the trials and rounds. "Writing a round-based experiment" now builds the ultimatum game with cued trials.
- Added `remove_participant(participant, reason="finished")` for members who leave a group after playing their part, such as players leaving a cohort after their last round; `leave_group(group_type)` uses it by default. Their leaving doesn't dissolve the group by itself, so the last players aren't told that too few members remained while they finish their own rounds. The group's next barrier can still dissolve it if it is below its quorum then and isn't waiting for newcomers; see "Groups below quorum" in the synchronization docs.
- Added `GroupBarrier(stop_top_ups=True)`, which stops a group accepting newcomers once it passes the barrier, instead of calling `group.stop_top_ups()` in `on_release`. Use it at the start of a game of rounds: otherwise every later barrier waits for a newcomer while they go through the pages the group has already passed. See "Letting latecomers join before the game starts" in the synchronization docs for a recipe.
- Added `max_wait_action` to groupers. With `max_wait_action="continue_without_group"`, a participant who waits longer than `max_wait_time` without finding a group continues the timeline without one instead of being failed, and their next page says "We couldn't find a partner for you in time. Please continue.".
- Added `SimpleSyncGroup.stop_top_ups()`, which stops newcomers joining a group formed with `join_existing_groups=True` at once, for example once its game has started. A group already below its quorum is dissolved, usually at once; from then on the group is treated as one without top-ups, so `below_quorum` can now be combined with `join_existing_groups` (see "Groups below quorum" in the synchronization docs).
- `InfoPage` now accepts `label`, for example to recognise the page with `bot.current_page_label` in tests.
- A `GroupBarrier`'s `on_release` can now take `left`, the members who left the group since its previous barrier pass, so a callback can tell a player whether their partner returned the study or was removed for being late (`participant.sync_group_removal_reason(group_type)`). Each group membership records when it ended. The `ultimatum_pairing` demo uses it to tell players whose partner was away.
- Added `participant.sync_group_removal_reason(group_type)`, which says why a participant left their group: `"late"`, `"waited_too_long"`, `"no_group_formed"` (a grouper found them no group in time), `"group_dissolved"`, `"moved_on"`, `"finished"`, `"left_experiment"` (failed, including returning the study) or `"removed_by_experimenter"` (removed from the dashboard). `SyncGroup.remove_participant(participant, reason)` requires a `reason`, such as `"removed_by_experimenter"` or `"finished"`, so code that removes members says why. `"late"` is recorded with every `GroupBarrier` `late_action`: with `late_action="fail"`, the member leaves the barrier's group as `"late"`, and their other groups as `"left_experiment"`, before being failed. A member who waits at a `GroupBarrier` for longer than its `max_wait_time` leaves it as `"waited_too_long"`, also with the default `max_wait_action="fail"`, before being failed; their other groups record `"left_experiment"`. Members who are late together are all removed and failed at once, before the group's quorum is checked, so none of them is removed as `"group_dissolved"`. Every member still in a group when it dissolves below its quorum leaves it as `"group_dissolved"`, with any `below_quorum`; with `below_quorum="fail"`, they are then failed and leave their other groups as `"left_experiment"`. A member who times out on a barrier's `waiting_logic` pages is tagged `while_loop:barrier:<id>` whether their own request or the barrier poller times them out. Answers submitted on the page where a member was removed for being late have `response.too_late_for_group` set, so analyses can leave them out.
- Added the `public_goods` demo, a repeated public goods game in groups of three that carries on when members return the study or stop responding and, when one player is left, cancels the round and lets them keep their tokens for it. Each round is one cued trial per player (`Trial.cue(round=i)`), which pays that round's bonus, with the group's pot saved once on the round the group's trials share and each player's `sync_group_outcome` in the export.
- Added the `story_chain` demo, in which groups of three take turns writing a story. Each turn is a cued round whose definition stores the writer, chosen by seat with `group_seats`; the writer stores their sentence on the round (`group_round.var`) as soon as they submit it, and a turn that ends without one stores `None`, so every finished turn has a stored sentence and the export marks which turns finished. It shows what happens when a writer runs out of time, a member leaves, the group shrinks to one, or no group forms. The round-based tutorial and the group design page describe it, and the synchronization guide now points to `group_seats` for a stable member order.
- Added `SimpleGrouper(top_up_wait=...)`, which limits how long a group that accepts newcomers waits for one after falling below its quorum. The wait counts from when all its remaining members are at a barrier; then that barrier stops top-ups and dissolves the group, so the members left are no longer stuck waiting if recruitment has stopped. The barrier's `max_wait_time` counts from each member's own arrival, so give it `late_after`, or a `max_wait_time` longer than `top_up_wait` plus the time members may take to reach it. A barrier with `late_after` has no `max_wait_time`, so the experiment refuses to load (or, for a barrier built in `show_trial`, to show the trial) if a group could wait for newcomers at one (any of its barriers with `use_admission_points=False`, its admission points with `use_admission_points=True`) before top-ups are stopped with `stop_top_ups=True`, unless the grouper has `top_up_wait`.
- Added `trial.sync_group_id`, `trial.sync_group_role` and `trial.sync_group_round`: trials of a trial maker with `sync_group_type` now record the group the participant was in when the trial was created, their role in it, and which of the group's rounds the trial belongs to, counted from 0 like the `round` of a cued trial and shared by a member admitted to the group late, and keep them after the group ends. A group's rounds can now be read straight from its trials instead of matching trials to group memberships by time.
- A module whose cues pass `round=`, as in `Trial.cue({"question": i}, round=i)`, runs once per participant, and its cues raise an error if the participant has run the module before; give each run its own module id. Cueing a round that the group finished without the participant (one whose `GroupBarrier` in `show_trial` has released the group: a cued round closes only then), a round with `round=` again after a later one, or a trial class again in a round the participant played, raises an error; admit players who join during the game at an admission point before each round.
- Added `also_leave` to `GroupBarrier` (and `sync_group_also_leave` to trial makers): with `late_action="leave_group"`, it lists the other group types a late member leaves too, for example `also_leave=["cohort"]` for the cohort their pair was formed in, so the cohort's next split doesn't wait for them. Their groups of other types keep them. The groupers of those types must then be given `below_quorum`, and the experiment refuses to load if one has `below_quorum="fail"`, which would fail the cohort's other members while the late member carries on. The `ultimatum_pairing` demo uses it instead of removing late players from the cohort by hand.
- Added `stop_if=` to `join` and `for_loop`, a function of `participant` and/or `experiment`. `join` checks it before each argument and `for_loop` before each iteration; once it returns `True`, the participant skips the rest. A started argument or iteration always runs to its end, so a page, barrier or cued trial is never cut short. For example, `for_loop(..., stop_if=left_team)` ends a game's rounds once the participant has left their team.
- Added `psynet.sync.leave_group(group_type)`, a timeline step that takes the participant out of their group of that type, by default with `reason="finished"`, for example after their last round of a game.
- Added `ParticipantDriver.is_waiting` (and so `BotDriver.is_waiting`), which says whether a bot is on a waiting page, for example at a barrier, so bot tests no longer need to read the cached status or render the page to find out.
- Added `psynet.bot.regroup_now`, which makes a `Regrouper` split the bots' pools as its `deadline` or `every` tick would, so bot tests of round-based games don't wait for it.
- Added `stop_top_ups_after_rounds` to `Regrouper`, which lets latecomers join the `within` group, such as a cohort, only during its first rounds, without a hand-written `join_criterion`.
- Each `Response` now records the trial it was submitted on in a new `trial_id` column (and `Response.trial` relationship), which also appears in the `response` table of the export. It covers every submission on a trial's pages, including those rejected by validation, and is `None` for pages outside a trial, such as feedback pages and pages submitted after the participant failed. `Trial.time_taken` and `Trial.response` now use this link instead of re-deriving it.
- Groups formed by a `SimpleGrouper` record when they stopped accepting top-ups in a new `top_ups_stopped_at` column, which the data export and the sync-groups dashboard show.
- Added `Trial.sync_group_outcome`, which records how a group's round ended for each player of a trial in a group's round, made by `Trial.cue()` or a trial maker with `sync_group_type`: `"stayed"` once a `GroupBarrier` in the trial's pages (such as in `show_trial`) releases the group with the player in it, after which it doesn't change, or, before that, why the player left the group, such as `"late"`, `"left_experiment"` or `"group_dissolved"` (the values are listed in `psynet.sync.SyncGroupOutcome`). Leaving the group after the release or after the trial's pages, for example by being late at a later barrier, shows in `participant.sync_group_removal_reason(group_type)` instead. In a trial maker's round that no barrier in the trial released, the trials that members still in the group completed record `"stayed"` when the group's next trials are prepared. Feedback pages and exports can read it instead of working it out from current group membership. The `ultimatum_pairing` demo uses it.
- A `waiting_screen` function can now take `trial`, the participant's current trial, and `group_round`, that trial's `SyncGroupRound`, so a barrier inside a cued trial can show the round's state without going through `participant.current_trial`.
- Added admission points, so groups can take newcomers during a game without anyone waiting for them. With `SimpleGrouper(join_existing_groups=True, use_admission_points=True, target_group_size=...)`, a newcomer is a pending member: they hold a seat, but the quorum, barriers, leader, `GroupPrompt` and `group_seats` ignore them, and the group's other barriers let them straight through, until an admission point admits them. The admission points are a `GroupBarrier(admission_point=True, newcomer_max_wait=...)`, a synchronized trial maker's trial preparation (pass the trial maker `sync_group_newcomer_max_wait`), and a `Regrouper` split `within` the group type. An admission point waits up to the grouper's `top_up_wait` while the group is below `target_group_size`, `GroupBarrier(newcomer_page=...)` shows a page only to the members a visit admitted, and its `on_release` can take `admitted`. A pending member still waiting after `newcomer_max_wait`, or when the group stops taking top-ups or ends, is turned away with removal reason `"not_admitted"` and told so on their next page; they are never failed. `use_admission_points=False` keeps admitting newcomers at once; leaving `use_admission_points` out with `join_existing_groups=True` warns and uses `False`. `SimpleGrouper(max_groups=...)` caps how many of a grouper's groups may be active at once. Each membership stores `admitted_at` and `admission_points_passed`, `group.pending_participants` lists pending members and `group.active_participants` only admitted ones, and `late_after` counts from a member's admission if that is later than the group's last barrier pass. A cue of a trial class with `sync_group_type` now raises an error for a participant without such a group unless the class sets `sync_group_optional = True`, and for a pending member. For example:

  ```python
  SimpleGrouper(
      "society",
      initial_group_size=3,
      max_group_size=4,
      quorum=2,
      target_group_size=2,
      join_existing_groups=True,
      use_admission_points=True,
      below_quorum="continue_without_group",
  )
  ...
  GroupBarrier(
      id_="round_starts",
      group_type="society",
      admission_point=True,
      newcomer_max_wait=90,
      newcomer_page=PageMaker(history_page, time_estimate=20),
  )
  ```
- Added the bot helper `psynet.bot.make_late_now(bots, barrier_id)`, which makes the members who haven't reached a `GroupBarrier` late as its `late_after` would, then advances the bots waiting there, so a bot test of a player who goes quiet doesn't wait in real time. The `public_goods` demo's bot test uses it.
- Added the `microsociety` demo: a fishing society of three whose members are replaced one at a time. A newcomer is admitted at the start of the next round, where they read the society's recent catches and the tips of members who have left, and the longest-serving member then retires and leaves a tip.
- Added `participant.latest_sync_group(group_type)`, which returns the participant's latest group of that type even after they left it or it ended, and `participant.sync_group_link(group_type)`, which returns their membership of it, with when they were admitted (`admitted_at`) and how many admission points they have passed (`admission_points_passed`).
- Added `SyncGroupRound.dissolved_at`, which records when a sync group dissolved during a round, so exports can tell a cancelled round from one still in progress without storing a marker of their own. It stays `None` for a round that a group barrier released and for a group that dissolved between rounds.
- A trial maker with `sync_group_type` now puts the trials it prepares for a group, including those of newcomers admitted at the trial preparation, in one `SyncGroupRound` (`trial.group_round`), numbered per group and trial maker and continuing across runs of the trial maker. A `GroupBarrier` in the trial gets it as `group_round` in `on_release`, so the group's results can be stored once in `group_round.var`, as the `create_rate_sync` demo now does. The round closes when such a barrier releases the group, or else when the group's next trials are prepared, and records `dissolved_at` if the group dissolves during it. `SyncGroup.rounds(trial_maker_id)` returns a group's rounds of a trial maker.
- Added `Trial.time_limit_reached`, a stored column that says whether the trial's latest timed page ran out of time before it was answered. Later untimed pages, pages shown while waiting at a barrier and the trial's feedback pages leave it unchanged. Added `psynet.sync.reached_barrier_after_time_limit(participant, group)`, which says whether a participant waiting at a barrier of the group got there because their latest timed page ran out of time; untimed pages in between and a trial's feedback pages, even if timed, don't count, and `GroupPrompt` marks members as having run out of time by the same rule. Added `SyncGroup.rounds(module_id)`, which returns a group's `SyncGroupRound` records for a module in round order, also after the group has ended.
- Performance-test reports for experiments with sync groups now count the bots' removals from groups by reason (such as `late`, `not_admitted` or `group_dissolved`), since removed bots can still count as completed.

### Changed

- GitLab CI no longer starts Docker, Postgres, or Redis for lightweight Python jobs, runs the changelog fragment check without installing the development extra, skips the merge-request ASV regression job unless the diff can affect those benchmarks, and skips the Docker pytest and Playwright matrix on docs, changelog, and skill-only merge requests.
- `psynet translate` now uses `gpt-6-luna` instead of `gpt-4o` by default, which gave better translations in a blind comparison at about a twentieth of the price. `openai_default_temperature` is no longer set by default, because `gpt-6-luna` only accepts the model's own temperature; set it only when you use a model that accepts it, such as `openai_default_temperature = 0` with `openai_default_model = gpt-4o`. A config that still sets `openai_default_temperature = 0` keeps working: PsyNet prints that `gpt-6-luna` rejects it and ignores it. Retries of a failed request raise the temperature to 0.7 only when one is configured; otherwise they rely on the model's default temperature to give a different reply.
- The default deployment-plan size limit is now 1024 MB (measured in decimal megabytes, matching Dallinger), so a typical stimulus set can ship in `static/` with the experiment image. PsyNet sets `EXP_MAX_SIZE_MB` to this default when it starts, unless you set it yourself. Before raising `EXP_MAX_SIZE_MB` further, run `dallinger deployment-files list` and exclude anything that should stay local. PsyNet's pre-check now rejects Heroku deploys over 500 MB even when `EXP_MAX_SIZE_MB` is higher. Invalid values, including zero or negative numbers, now raise a clear error.
- Remote deployments (`psynet deploy` and `psynet debug` to SSH servers or Heroku) now stop during pre-deployment checks when a generated `constraints.txt` is out of date with `requirements.txt`. Previously, Docker deployments built the image from the stale lockfile and Heroku deployments without Docker regenerated it silently. Set `SKIP_DEPENDENCY_CHECK=1` to deploy anyway. A non-empty `constraints.txt` without the generator's header counts as written by hand, as in Dallinger: `psynet setup`, `psynet check-constraints` and the deployment check leave it unchanged.
- The experiment `AGENTS.md` and Agent Skills no longer assume a PsyNet source checkout: `AGENTS.md` names `implement-experiment` as the entry point for implementing an experiment, `explore-psynet-repository` reads demo code from GitLab when there is no local clone, and `playwright-testing` defines the few helpers an experiment's tests need instead of citing PsyNet's own test harness. Analysis and design-simulation packages now go in `requirements.txt`, so `psynet setup` keeps them.
- Changed Lucid recruitment to stop new entrants as soon as finished plus working participants cover the target, by lowering the survey's total quota while it stays live. The survey is set to complete once nobody is still working, and entry reopens if a working participant drops out. Experiments no longer need to close the Lucid survey themselves.
- Experiments now receive the `upgrade-to-psynet-14` Agent Skill that PsyNet's error messages recommend, and the experiment `AGENTS.md` gives coding agents a map of which documentation page covers each topic. It also now starts PostgreSQL and Redis with `psynet services ensure` rather than native installs, where Docker is available.
- Shortened the front-end, back-end, CINT, psychophysics and tapping Agent Skills so that they point to the documentation instead of repeating it, and merged `prepare-experiment-tunnel` into `public-tunnel`. The documentation now covers how bot answers interact with `format_answer`, nesting `Markup` in `dominate` tags, measuring reaction time from the event log, and the CINT `publish_experiment` and qualification-file requirements.
- The audit's Experiment code section shows the experiment's other deployed Python modules after `experiment.py`, such as a `response_model/` package (files that `deploy.toml` excludes, such as `local_only/`, are left out, and a note says when modules beyond the first 30 are omitted), and the audit header shows `experiment.py` as the entry point when none is configured.
- Audit sites collapse notebook code cells behind a "Show code" toggle, so readers see the text, figures and tables first.
- The audit's design simulation section is now called "Power analysis" and comes straight after the Plan. Agent guidance asks for power analysis and analysis notebooks that open with a plain-language summary and assumptions, with the numbers given alongside the plain words.
- `psynet audit validate` warns when a present notebook has code cells but no saved outputs, and the Data exports section says "No real data yet" before launch.
- The design-simulation guidance (`power-analysis` and `precision-estimation` skills) no longer sets a default precision threshold. The agent agrees the required precision with the experimenter, derives it from the research question if the experimenter has no view, uses power when the question is whether an effect exists, or presents precision and cost curves without a pass/fail decision. Power calculations now use the planned multiplicity procedure and an estimator that reflects repeated participant and stimulus observations. Margins of error are stated in the response's own units, such as rating points, and the report gives the smallest adequate design under each assumption set. For profiles, the guidance adds the margin of error of a difference, root mean square and largest margins across the set, the profile correlation and the smallest true spread at which the design reaches a 0.9 correlation. It distinguishes typical pairwise precision from an every-pair or whole-ranking requirement, and it asks the analysis to report the achieved precision and split-half reliability after data collection. When an effect is stated on an observed scale, such as a correlation between a questionnaire score and behaviour, the simulation calibrates the response model to reproduce it. Design-simulation notebooks now lead with a plain-language summary and an example of what the results would look like, answer one question per figure with assumption sets named by what they mean, and keep definitions and the full metrics table in a final section for reviewers.
- The stacked-hold Playwright tests no longer fail when CI is slow. They check the hold behaviour itself (response status, busy pages, server wakes, hold-resume requests and reloads), log request and overlay timings for diagnosis, and fail on time only when something hangs for 30 seconds.
- Timeline pages now load jQuery only once. They use Dallinger's new `jquery` template block to skip the copy that Dallinger's base layout loads at the end of the page. Requires Dallinger 12.5.0 or later.
- Upgraded the CI images to Node 22 and Playwright 1.64, added ffmpeg to the Playwright image, and added a Playwright smoke test for the participant audio recording helper.
- Group barrier arrivals now use the same number of database queries whatever the group size. Previously each arrival loaded every group member separately, and the last arrival also reloaded each waiter's hold one by one, so a group of 16 needed about 280 queries for the last arrival instead of about 75.
- With `accumulate_answers=True`, `participant.answer` now becomes a dict when the page maker or trial starts and each page adds its answer as soon as it is submitted, so later pages can read earlier answers. Code that read `participant.answer` during such a trial to get the previous trial's answer now sees the current trial's answers instead.
- Changed across-participant chain and static trial makers to find a new participant's blocks with one grouped query instead of loading every network.
- New experiments no longer stop on their first debug or test run to review the generated `deploy.toml`. The one-time stop now happens only when an existing experiment moves to `deploy.toml` and its `.gitignore` ignores files that `deploy.toml` does not exclude, and it lists exactly those files. The check uses the experiment's original `.gitignore` rules even if `psynet scripts update` has replaced `.gitignore`, and it still stops if Git cannot answer.
- Trial makers now find each trial's node with one database query and load only that node, instead of loading every eligible network and node, so selection no longer slows down as the number of nodes grows. Hooks such as `select_node` and `custom_node_filter` still receive the full list, unless `selection_pool_size` limits it. A static network without a head node now raises an error instead of being skipped.
- CI pipelines now finish in about 9 minutes instead of 17–21. Pytest shards are balanced using recorded test durations (`ci/test_durations.json`), and each of the twelve shards runs two tests at once, each with its own database, Redis server and port (`psynet dev ci run-tests`). Each Playwright job now runs as three duration-balanced shards (`psynet dev ci playwright-files`). Test jobs run Postgres without durability (`fsync=off`), and on feature branches no longer run the null translator.
- Made deployment preparation and launch faster for experiments with many nodes or assets: launch now marks nodes as deployed in one database statement (25 s down to 3 s for 100,000 nodes), and preparing new assets does less database and file work per asset (39 s down to 19 s for 10,000 file assets).
- The full ASV benchmark suite (`asv_benchmarks`) now runs from a nightly pipeline schedule, comparing `master` with its state 24 hours earlier, instead of on every merge to `master`. It is still available as a manual job on `master` pipelines.
- Lucid's periodic recruiter checks (`run_checks`) no longer commit the status entries they record, saving a Lucid respondent's termination details no longer commits the caller's transaction, and `GraphChainTrialMaker.create_graph_network` now flushes instead of committing. Commits that save state around a payment or Lucid API call remain; custom recruiters can use `experiment.commit_payment_state()` for the same purpose. An `AttributeError` raised inside a recruiter's `release_participant` is no longer reported as the method being missing.
- CI no longer runs pipelines on `deployment-tests/*` branches, whose deployment-prep commits always failed the repository-state tests while repeating checks already run on the base tag or branch.
- `WorkerAsyncProcess.redis_job_id` is now derived from the process ID instead of being stored, so the `redis_job_id` column no longer appears in database exports.
- The participant table stores `answer_accumulation_depth` (an integer) instead of the `answer_accumulators` list, so exports have the new column in place of the old one.
- When a participant rejects consent, the recruiter's platform calls (Lucid termination and the recruiter's `after_rejected_consent` hook, which reports the outcome for Lab Recruiter) now run in a background worker instead of inside the participant's web request, and the participant goes straight to the debrief page. `after_rejected_consent` therefore no longer runs as a timeline step, and custom overrides cannot read `flask.request`. No worker job is queued when the recruiter has nothing to report.
- Calling `Experiment.report_error` directly no longer commits; the error record is added to the current transaction, so code that reports an error outside a request or worker job must commit afterwards for the record to be saved.
- Reduced log noise from timing messages (`Task '...' took ... s`): timed participant-request steps and scheduled tasks are now only logged when they take longer than 100 ms, instead of 10 ms. This is the new default `threshold` of `psynet.utils.time_logger`.
- Trial feedback now waits until the trial is finalized or failed, so `show_feedback` sees a set `score` and the results of `on_finalized`, or a failed trial it can check with `self.failed`. A failed trial does not fail its participant, and participants waiting for feedback move on as soon as background work fails the trial.
- `psynet dev docs linkcheck` now fails only on internal links, missing anchors, and pages not found (404/410). It still reports 403s, timeouts, and SSL or connection errors, which usually come from the remote site or the network. Pass `--strict` to fail on every broken link; a weekly scheduled CI pipeline runs the strict check on `master`.
- GitLab merge-train pipelines now skip the pytest, Playwright, docs and fast ASV benchmark jobs when the merge request's last merged-results pipeline already passed them on identical files, so a merge no longer waits for a second full test run when `master` hasn't moved and nothing is ahead of it in the train.
- Sped up loading stored Python values, such as node and trial definitions and answers: values that are plain JSON are now decoded with `json.loads` instead of `jsonpickle`, which is several times faster. Values that need `jsonpickle` (tuples, sets, objects, NumPy arrays and similar) decode as before.
- Made Python 3.14 the recommended Python version. `psynet setup` creates new virtual environments with Python 3.14, and the documented `uv venv` commands use 3.14. Python 3.11 to 3.13 remain supported.
- `psynet debug ssh` and `psynet deploy ssh` now always list `--ingress`. With a Dallinger version that lacks Cloudflare ingress, such as 12.4, `--ingress cloudflare` stops with an explanation instead of the option being missing from the command, and `--ingress classic` is accepted.
- `psynet deploy ssh` and `psynet deploy heroku` now ask for confirmation when `requirements.txt` installs a development PsyNet rather than a release, for example a Git commit or an alpha version. Setting `SKIP_CHECK_PSYNET_VERSION_REQUIREMENT=1` skips the question and prints a warning instead; this also covers entries that only pass the deploy checks because of that variable, such as a branch or a local path.
- Async jobs created without a `timeout` now time out after one hour (`AsyncJob.default_timeout`), counted from when they start. This extends the 180-second limit that RQ previously applied to `WorkerAsyncJob`s without a timeout, including `AsyncCodeBlock` functions, and adds a limit to `LocalAsyncJob`s such as asset deposits, which previously had none. One experiment-level clock check now handles timeouts for all async jobs, including in experiments without trial makers, and also fails a `LocalAsyncJob` that has not started within an hour of being enqueued as lost.
- PsyNet's dashboard pages now work with Dallinger's Bootstrap 5 dashboard. The Basic data page no longer loads a second copy of Bootstrap, which had stopped the Database dropdown from opening, timeline module tooltips render their HTML again, and the close button of the sync groups participant dialog shows one × instead of two overlapping ones. PsyNet also drops CSS overrides that only countered Dallinger's old page font and consent-button float.
- Merge requests stacked on another feature branch now run only the fast CI checks, and offer the pytest, Playwright, docs and fast benchmark jobs as optional manual jobs. Merge requests targeting `master` or a `release-` branch, merge trains, and `master`, tag and scheduled pipelines run the full suite as before.
- Bots now load the server more like participants' browsers do. They keep their HTTP connections open between pages and resend a request once if the server drops the connection just as they reuse it; dashboard sessions from `get_authenticated_session` also keep their connections open but resend only requests that are safe to repeat. Bots running in threads share one dashboard login per process. The `/participant_status` route that bots poll returns plain JSON unless the bot's response includes files, instead of always building a zip file. Bots with a `time_factor` above 0 never submit a page before its new `Page.min_duration`, the earliest time its `submitEnable` event can fire (for example a recording's `duration`), check a timeline hold every `check_interval` seconds as a browser's fallback poll does, and in `psynet performance-test` each get a random pace factor between 0.7 and 3 that averages 1. Correctness tests with the default `time_factor` of 0 are unchanged.
- `psynet performance-test` now judges every test against capacity limits and ends with a summary table. A test passes if the 95th-percentile response time of `/timeline` and `/response` stays under `--max-p95-ms` (default 500), the 95th-percentile wait of high-priority async jobs stays under `--max-queue-p95-s` (default 5), at most 0.1% of requests and 1% of bots fail, at most 1% of requests are answered as busy or stale (HTTP 503 or 409), and at most 1% of bots in a chain trial maker finish a block early because every chain was busy. Low-priority async jobs are reported but never fail a test. Bots that the experiment failed, for example at a prescreen or after timing out on a waiting page, are reported separately with their reasons, and timeouts count against the limits. A test counts as not testable, rather than as a limit of the server, when the bots couldn't keep up: when they didn't all start in time, when they ran more than 50 ms late, or when PostgreSQL ran out of connections for them. Each test's report adds a start-up versus steady-state section (from the first bot to finish the experiment), queue waits by priority with the jobs still queued, how busy the async workers were, and the rows in the growing tables before and after (`db_rows_before` and `db_rows_after`). The summary has one row per test with a pass or FAIL result, labels the largest passing test, names the limits the next count exceeded with their values, and adds notes: when the database grew during the tests, when the workers were more than 85% busy or fewer ran than configured, when low-priority backlogs grew, and what the bots don't measure (participants' own uploads, media downloads, the web proxy or Cloudflare tunnel, and browser rendering). In a terminal the summary is coloured and wraps to its width; in logs and with `NO_COLOR` it is plain text, and progress is printed as a new line every 30 seconds. The audit's *Performance test* section and `psynet audit performance-test` judge each test against the same limits.
- `psynet setup` and `psynet scripts update` now base the experiment `Dockerfile` on the active Python version, the same version they write to `.python-version` and that `constraints.txt` is compiled for. Previously the `Dockerfile` used a fixed Python version, so an experiment developed on a different Python installed its constraints into a mismatched deployment image. Existing experiments keep their current `Dockerfile` until `psynet scripts update` refreshes it.
- When `psynet translate` splits a long file such as a country list into several requests, ChatGPT now sees the translations from the earlier requests as examples, so the whole list uses consistent wording.
- The PostgreSQL container that PsyNet starts for local debugging and testing (`dallinger_postgres`, also in CI) now runs with JIT off, as Dallinger's Docker PostgreSQL does, because JIT compilation slows down the short queries that experiments make.
- A test now checks that the performance test's list of async job priorities matches the one async jobs use.
- `while_loop` now applies `max_loop_time` only while its condition still holds: a loop whose condition is already false when it is next checked exits normally, even after the deadline, instead of timing out. This also affects synchronization barriers and other waits built on `while_loop`.
- Changed `psynet destroy ssh` to refuse to destroy an app whose pending async jobs can't be checked, for example because its web container is down, it runs an older PsyNet version, or it doesn't answer within 30 seconds, unless `--discard-pending-jobs` is passed. The message says why the check failed and how to proceed. Apps deployed with `psynet debug ssh` or `psynet performance-test ssh` are still destroyed, even if they recruit real participants; these commands now mark the app with the new `debug_ssh_app` config variable, so apps deployed by older PsyNet versions, and sandbox-mode apps deployed by other means, are refused. Live deployments (`psynet deploy …`) refuse to start with `debug_ssh_app` set. When destroying several apps, the others are still destroyed. `psynet export ssh` still completes with a warning that the export may lack the results of unfinished jobs.
- `psynet performance-test ssh` no longer requires the experiment to have a consent page, because only bots take part. `psynet debug ssh` and `psynet deploy` still check for one.
- The dashboard password no longer appears in server logs. `psynet debug local` now prints the dashboard address and login once in the launching terminal, whether or not it opens browsers, and local launches no longer log a second, redacted copy. For remote deployments the server log says `Password: not shown in logs (printed by the command that launched the experiment)`.
- `psynet export` and `psynet experiment-variables` now explain database problems without a traceback. A refused local connection points to `psynet services check` (showing the host and port, but never the credentials), a refused Heroku or SSH connection names the app and how to check the app name, and an empty or missing `experiment` table is reported as a short error saying that the experiment may not have finished launching.
- When `psynet load` finds other clients of the local database, the message now shows each client's address (or `local socket`) and connection time, for example `Postgres backend pid 123 (gunicorn, idle, 127.0.0.1:54321, since 09:12)`.
- `psynet debug local` and `psynet test local` now stop straight away when a standalone experiment has no `requirements.txt` or `constraints.txt`, and say how to create it (`psynet generate-constraints` or `psynet setup`). Previously a missing `constraints.txt` could fail later with a raw `FileNotFoundError`. Bundled demos and runs with `SKIP_DEPENDENCY_CHECK` set are not affected, and whether `constraints.txt` is up to date is still only checked before remote deployments.
- `psynet setup` now asks before setting up an experiment in a folder that contains unrelated files, and stops when it cannot ask; pass `--yes` to set it up anyway. A `static/` or `audit/` folder, the files `uv init` creates, licence files, editor settings and caches don't count as unrelated.
- When `experiment.py` or a module it imports fails to load, PsyNet commands now print a short traceback showing only the lines from the experiment folder and the line that raised the error, and exit with status 1. Set `PSYNET_SHOW_TRACEBACK=1` to see the full traceback.
- `psynet deploy ssh` and `psynet debug ssh` now end with a short *Ready* summary listing the participant link (or, without one, the recruitment message, such as a new Prolific study), the dashboard address and user, where the passwords are saved, the command for following the logs and, without a Cloudflare tunnel, the log viewer address. With an up-to-date Dallinger, this summary replaces Dallinger's own, so passwords no longer appear in the output of a successful deployment. Deploy output without a terminal no longer includes `stty: stdin isn't a terminal` or an empty asset progress bar, the experiment Dockerfile template uses the exec form of `CMD` (silencing Docker's `JSONArgsRecommended` warning; run `psynet scripts update` to refresh it), and `--use-local-dallinger` says when PsyNet itself passes the checkout to Dallinger as `DALLINGER_SOURCE`. `launch-info.json`, which holds the passwords, is now readable only by your user account.
- `psynet destroy ssh` treats app names given as arguments and with `--app` as one list, so the two forms can be combined, and no longer suggests the batch syntax when you use `--app`. A single app given as an argument is now confirmed like one given with `--app`, including the prompt to destroy it despite pending async jobs.
- Simplified the internal pattern configuration of the pre-deployment TODO check; the check itself behaves as before.
- `psynet deploy ssh`, `psynet debug ssh` and `psynet performance-test ssh` to a Cloudflare-ingress server now stop with Dallinger's `Error: Cloudflare error: …` message before they start local services, contact the server or run `prepare`, if the Cloudflare API token can't be read.
- The *Ready* summary of `psynet deploy ssh` and `psynet debug ssh` names the deployed Docker image when Dallinger reports it, and its log viewer row says that the password is saved in `launch-info.json`.
- Remote launches (`psynet debug ssh`, `psynet deploy ssh`, `psynet debug heroku`, `psynet deploy heroku` and the first deploy of `psynet performance-test ssh`) no longer touch your local database, Redis or local PsyNet servers. They still build the experiment's starting database on your computer, but now in a scratch PostgreSQL database and Redis of their own, which are removed when the build finishes, so a running `psynet debug local` keeps its data and several remote launches can be prepared at once. Because they replace the experiment directory's generated files, remote launches and local servers or test sessions in the same directory no longer run at the same time: whichever starts second refuses to.
- `psynet debug local` output now has one layout. Messages before the server starts are plain one-sentence lines, without `❯❯ ` or blank lines (this also applies to every other message PsyNet's command line prints with its `log()` helper, and to shutdown), and the server's lines start with the time and the process. Start-up ends with one `Ready.` block of aligned lines: the participant link (for a recruiter without a single recruitment link, the only link of its initial recruitment list, and its other details as `Recruitment`), `Dashboard: <url> (user …, password …)`, where the full log is (with a Dallinger version that writes one) and, for `--isolated`, `Other terminals: export DATABASE_URL=… REDIS_URL=… base_port=…`. The block replaces the recruiter's "Initial recruitment list:" and "Additional details:" text, the `❯❯ Experiment dashboard: …` and `Dashboard user: … password: …` lines, the "To use this server's data from another terminal…" lines and the `Opening dashboard` and `Opening ad: …` lines. The isolated session's `Using database …` line now reads `Using database dallinger_test_5100, Redis 127.0.0.1:6479 and port 5100.`. With a Dallinger version that supports it, the console shows `Conclusion: …` once until the conclusion changes, instead of once for every participant who finishes; the server's full log, and deployed servers' logs, still have every one. Scaffolding prints one line, such as `Scaffolded experiment in hello_world: created 12 boilerplate files.`. Experiment audits redact the password in both formats.
- The server log is much quieter: routine messages about trial selection, trial finalization, rewards, timeline loops and holds, received responses, uploaded trial assets, browser-side `info` messages (`[CLIENT n]`) and the details of each recruitment check (`Target number of participants = …`, `Recruitment criterion …`) are now logged at DEBUG instead of INFO. The `GET /timeline` and `POST /response` timing lines and the `Task '…' took … s` lines appear at INFO only for requests and tasks that take at least 1 second. With a Dallinger version that shortens the development server's request lines, `psynet debug local` shows one line per page request (such as `GET /timeline 200 in 38 ms`) but leaves out successful requests for assets, the browser's log messages and progress polling. Warnings, errors and recruitment decisions (`Conclusion: …`) still appear at INFO. Messages from Dallinger's `Experiment.log`, such as recruiter notifications, now go through the `psynet` logger instead of being printed with a `>>>>` prefix, and without Dallinger's `-----` tag. `Reporting outcome with bonus 8.86 for 2` now reads `Reporting participant 2's outcome to the recruiter (bonus 8.86).`. `psynet debug`, `psynet test` and `psynet deploy` report healthy local PostgreSQL and Redis in one line, report an unreachable one in one line that names the host and port they tried (previously Redis always said port 6379), and the "Creating networks" and "Staging assets" progress bars are only shown in a terminal, not in redirected output. These bars and the "Generating/uploading assets..." bar are cleared when they finish instead of leaving a blank line. To see the DEBUG messages again, add `logging.getLogger("psynet").setLevel(logging.DEBUG)` to your `experiment.py`.
- `psynet deploy ssh`, `psynet debug ssh` and `psynet performance-test ssh` no longer need `docker_image_base_name` in `config.txt` or `~/.dallingerconfig`. These commands build the image on the server without pushing it, and name it after the app when the setting is unset. Heroku deploys with `--docker` push the image, so they still require the setting.
- Default bot answers on `PushButtonControl`, `DropdownControl`, `RadioButtonControl` and `CheckboxControl` pages now go through the same answer formatting as browser answers, so bots and real participants save the same values. `CheckboxControl` bots now tick a list of choices instead of answering with a single choice.
- Option controls convert NumPy choices, such as `list(np.arange(1, 4))`, to the equivalent Python values, so answers are saved and shown on the dashboard as plain numbers.
- `psynet performance-test ssh` now starts its tests with the same `Ready:` block as `psynet debug ssh`, with an extra `Bot log` row. As for `debug ssh`, Dallinger's own launch summary, including the dashboard password, is hidden once PsyNet runs with a Dallinger that supports it; the password is saved in `launch-info.json`. Performance test output, including the `performance-test local` server lines, uses plain lines instead of emoji and `====` banners, with sentence-case headings. Notes such as the short-test warning and the capacity-search limits follow the settings list instead of interrupting it, the wait-page time moves into `BOT RUNTIMES`, and the trials-per-bot table is left out when no bot completed the experiment, instead of showing zero trials.
- `psynet debug ssh` and `psynet deploy ssh` without `--app` now name the app after the experiment directory (with `-2`, `-3`, ... if the server already has that app) and serve it at its own subdomain, instead of a random `dlgr-…` name on the server's bare domain. In an interactive terminal, PsyNet asks for the name and offers this suggestion; otherwise it prints the name it uses. SSH launches, including `psynet performance-test ssh`, now reject app names longer than 63 characters or starting or ending with a hyphen, which can't be used in a web address.
- Participant signups queue on a PostgreSQL advisory lock, which Dallinger now always takes, instead of retrying `SERIALIZABLE` transactions when they conflict. A signup that waits more than 5 seconds for the lock fails. The `lock_table_when_creating_participant` config variable has no effect, and setting it raises a `FutureWarning`.
- `psynet deploy heroku --docker` and `psynet debug heroku --docker` now use Dallinger's check of `docker_image_base_name`, before preparing the experiment. Besides being set, it must name a registry or namespace, for example `ghcr.io/<github-user>/<experiment>` or `<dockerhub-user>/<experiment>`.
- The Heroku CLI is no longer a PsyNet installation requirement, because local servers now run with honcho; you only need it for `psynet` commands that work with Heroku apps, such as `psynet deploy heroku` and `psynet export heroku`. `psynet deploy heroku` and `psynet debug heroku` now stop before preparing the experiment, with install instructions, if it is missing. The experiment `Dockerfile` and GitHub test workflow templates no longer install it, so once an existing experiment's `requirements.txt` and `constraints.txt` use this PsyNet version, run `psynet scripts update` to drop it there too. Older PsyNet versions still need the Heroku CLI for local runs.
- Answering no to a confirmation before a deployment, such as the question about installing a development version of PsyNet or about Docker settings in `config.txt`, now prints "Deployment cancelled." instead of a bare "Aborted!".
- PsyNet's CI images and the experiment Dockerfile template are now based on Debian 13 (Trixie) instead of Debian 12 (Bookworm). An experiment image's ``apt-get install nodejs`` therefore installs Node 20 instead of Node 18. Run ``psynet scripts update`` to rewrite an existing experiment's Dockerfile. Library names Debian renamed for 64-bit time, such as ``libasound2``, still install, because the new packages provide the old names. If your ``prepare_docker_image.sh`` installs other Debian packages, check that they still exist on Debian 13.
- A function exposed with `expose_to_api` that returns a string now sends it as `text/plain` rather than HTML, so a string that echoes its arguments can no longer run script in the participant's browser. Return a Flask `Response` to send another content type.
- `psynet scripts prune` no longer deletes a real `static/assets` file or directory, only a link left there by an earlier PsyNet version. The stock `.gitignore` and `deploy.toml` still exclude `static/assets`, so files you put there are not tracked or deployed; keep your own files elsewhere in `static/`.
- Experiment server responses, including error responses, now send `Referrer-Policy: strict-origin-when-cross-origin`, so other sites receive only the experiment's address and not participant URLs (which contain `unique_id`) in the `Referer` header, even in browsers or setups with a looser default; embeds that need a referrer, such as YouTube videos, keep working. They also send `X-Content-Type-Options: nosniff`. With `nosniff`, browsers refuse a script or stylesheet served with the wrong content type, so give your script and style files standard extensions such as `.js` and `.css`.
- When the server is briefly busy, participants' submissions and bots now keep retrying with growing gaps for about 10 seconds before giving up. Previously the browser retried once after 250 ms and then asked the participant to try again, and bots failed after about a second of retries. Push buttons now show a spinner while their submission is in progress, as the Next button already did.
- Hid the Deployments tab from the experiment dashboard until the deployment monitor is fixed, because it finds no deployments on servers set up with `psynet deploy ssh`. The page is still available at `/dashboard/deployments`.
- The Next button, including on keyboard pages, now shows the same pending spinner as push buttons: the spinner covers the label without moving or resizing the button, and the label returns when a submission is rejected or busy retries run out. The `#next-button-spinner` and `#next-button-text` elements no longer exist; custom scripts or tests should target `#next-button` instead. `psynet.page.control.nextButton.disable()` and `enable()` now only toggle the button, without showing or hiding a spinner.
- `psynet debug local` now relies on the launch login and start-up message helpers in Dallinger 13.0.0 or later and no longer falls back for older Dallinger versions.
- PsyNet's SSH deploy, debug, performance-test, destroy, hibernate and awaken commands, its Dozzle log links and its Prolific lookups no longer carry fallbacks for Dallinger versions older than the one PsyNet pins, so the messages asking for a newer Dallinger (for `--ingress cloudflare`, `--remove-data`/`--keep-data` and hibernation) are gone. `psynet destroy ssh --remove-data` also no longer reports "Nothing left to delete" when Dallinger aborts for an app that is no longer deployed, for example after you decline a changed SSH host key.
- A `GroupBarrier` `waiting_message` function can now take `waiting_count` and `group_size`, and can return `psynet.sync.hold_message(title, progress)` to write or hide the waiting indicator's progress line. `on_arrival_message` is no longer called with `kind="hold"`; if you customized hold copy there on a 14.0 release candidate, move it to a `waiting_message` function.
- Trial makers now warn when `sync_group_max_wait_time` is passed without `sync_group_type`, since it only applies to synchronized trial makers and was silently ignored. The other `sync_group_*` options, which are new, raise an error in that case.
- `conditional` now converts its condition's result with `bool()`, so a condition that returns, for example, a number or a list chooses a branch instead of raising an error.
- Renamed the `basic-data-dyadic-experiment` Agent Skill to `basic-data-group-experiment`; it now covers groups of any size and builds the player-round table from the trials' `sync_group_id` and `sync_group_round`, with group results from shared `SyncGroupRound` rows. If you used a 14.0 release candidate, run `psynet scripts update` in experiment checkouts to pick up the new skill name.
- Renamed the `"kick"` value of `GroupBarrier`'s `max_wait_action` and `late_action`, and of trial makers' `sync_group_max_wait_action` and `sync_group_late_action`, to `"leave_group"`, since the member is not removed from the experiment but carries on without their group. Experiments written against the 14.0 release candidates must replace `"kick"` with `"leave_group"`.
- `psynet services ensure` and the local CI scripts now run PostgreSQL 18 (`postgres:18-trixie`) instead of PostgreSQL 12, which no longer gets security fixes, matching `dallinger docker start-services` in Dallinger 13.1, which PsyNet now requires. PostgreSQL 18 can't open the old data, so `psynet services ensure`, `psynet debug local` and `psynet test local` offer to replace an existing `dallinger_postgres` container that runs PostgreSQL 12 (`psynet services ensure --yes` replaces it without asking; the CI scripts replace it too), and the local database then starts empty in the new volume `dallinger_postgres18`. The old data stays in the `dallinger_postgres` volume; remove it with `docker volume rm dallinger_postgres` once you no longer need it.
- Trials made by `Trial.cue()` now set `position`, counting the participant's trials in the same module from 0, and a trial with `accumulate_answers = True` now starts with an empty dict as its `answer` instead of `None`.
- Trials played in a group (with `sync_group_id`) no longer log "received an unexpected amount of time credit", because their barriers credit the time actually spent waiting for the other members.
- Tidied the multiplayer demos to use public interfaces and store results rather than infer them: `create_rate_sync` scores each phase from `trial.answer` in a barrier's `on_release` and keeps the results in `trial.var`, `ultimatum_pairing` stores each pair's `proposer_id` and `responder_id` on its round, its per-player export table is now `player_round`, and the demos name their group types with constants (`GROUP`, or `COHORT` and `PAIR` in `ultimatum_pairing`).
- A newcomer reaching a `SimpleGrouper` with `join_existing_groups=True` while another request is changing the open group, such as a barrier check, now waits up to a second to join it, instead of waiting at the grouper for the background barrier check.
- `trial.answer` now holds the answer so far while a trial's pages are being answered, the same value as `participant.answer`, instead of staying `None` until the trial ends. A `GroupBarrier` inside `show_trial` can therefore read each member's answer in `on_release` from `trial.answer`, without `save_answer` and `participant.var`:

  ```python
  @classmethod
  def score_room(cls, trials, group_round):
      group_round.var.picks = [t.answer for t in trials]  # None: the page ran out of time
  ```

  When the trial ends, `trial.answer` is set to the result of `format_answer` as before. As a result, an unfinished trial in an export, whether abandoned or still running, can have an `answer` (the answer so far, not yet passed through `format_answer`); filter on `complete` as well as `failed` when analysing answers.
- `Trial.cue()`'s `definition` now defaults to `{}`, so a round with no content of its own can be cued as `MyTrial.cue()` or `MyTrial.cue(round=i)`.
- A `GroupBarrier` waits for every active member of its group, wherever it is: in `show_trial`, in `show_feedback`, between iterations, between runs of a looped module or after the loop. A member stops being waited for only by leaving the group, with `leave_group` or by being removed (for example as late), so a member whose loop ends earlier should leave the group first. Pages between rounds or runs, inside the module or outside it, need nothing special: the next barrier waits for a member who reads slowly. A release closes a cued round when every member it releases is in that round's trial. Every release except a member's own time-out is the group's pass, which runs `on_release` and counts for `left` and `late_after`. When every member of a group waits at one of its barriers but no barrier has them all, so none can pass until `late_after` or `max_wait_time` moves someone on, the background barrier check records one error for the group and that set of barriers, naming the barriers and who waits at each, however the members got there, logs it and lists it under the dashboard's Errors tab; a bot test run by `psynet test local` then fails with `GroupDivergenceError` and that message when it ends. The usual cause is a newcomer who joins a fixed group during a loop of rounds and waits at a barrier outside the round's trial while the others wait for them in the round, so stop top-ups before such a game with `stop_top_ups=True`, or admit newcomers only at the start of each round with `SimpleGrouper(use_admission_points=True)`.
- `psynet performance-test ssh` remembers `--use-local-psynet` and `--use-local-dallinger` from the deploy of its app: later runs that update the app build the local checkouts in again without the options, and say so. Apps deployed with an earlier PsyNet version have no record, so pass the options once more on their next run; they are remembered from then on.
- Participants who arrive at a `Regrouper` with `every` by pressing Next no longer wait for a check of the whole waiting pool, since an arrival cannot make the pool ready; the background barrier check makes each split at its next check after the tick, normally within a second. An arrival or reload while loading the timeline page still checks the waiter's visit. This makes large regrouped experiments faster under load. The troubleshooting docs explain that PostgreSQL's `could not obtain lock on row` errors in group experiments are expected.
- `GroupBarrier`'s `notify_arrivals`, from the 14.0 release candidates, is replaced by `on_arrival_message=None`, and passing it raises a `TypeError`; replace `notify_arrivals=False` with `on_arrival_message=None`. Longer arrival notices now wrap onto at most two lines, then ellipsize, instead of ellipsizing on one line.
- `SimpleGrouper` now raises a `ValueError` when `quorum` is larger than `max_group_size`, since such a group could never reach its quorum.
- Synchronized trial makers no longer wait at an `init_participant` group barrier before their first trial. They initialize their members when the trial preparation barrier, `{id}__prepare_trial`, first releases them, so code, tests or dashboards that looked for the `init_participant` barrier should look for `{id}__prepare_trial` instead.
- Barrier checks issue fewer database statements: a check of a waiting group visit now takes 15 statements instead of 19, so the barrier poller gets round its waiting visits faster and time-based releases lag less under load. Queries for sync groups now load the `SimpleSyncGroup` columns in the same query.
- The barrier check's "Barrier '…' currently has N participant(s) waiting" log line is now logged at DEBUG instead of INFO, which keeps app logs of busy multiplayer experiments readable.
- The periodic sync-group check (`check_sync_groups`, every 2.5 s) now counts all active groups' members in one query and locks and recounts only the groups whose stored member counts are out of date or that may close, instead of locking and recounting every active group. With 100 idle groups a tick takes one statement instead of about 600.
- Requests answered with HTTP 503 because of transient database contention are now logged as one warning line, naming the participant, the route and the error type, instead of with a full traceback.
- Time-based barrier rules (`late_after`, `top_up_wait`, `start_short_after` and `Regrouper` deadlines and `every` ticks) now act within about a second of their time even when hundreds of visits are waiting. Previously the barrier poller reached each waiting visit in turn, so with many visits these rules could act several seconds late.
- Removed PsyNet's `<5` cap on `markdown-it-py` and its `rich>=13` minimum, so these packages can follow the versions that Dallinger and Rich require.
- The `psynet[experiment]` extra now lists the packages that PsyNet imports even when Dallinger already installs them, such as `flask`, `sqlalchemy`, `psycopg2`, `numpy` and `beautifulsoup4`. It no longer installs `progress` and `python-gettext`, which PsyNet doesn't use, or `pytest-dependency`, `pytest-mock` and `pytest-timeout`, which only PsyNet's own test suite needs and which are now in a new `test` extra (included in `dev`). If your experiment's tests use one of these pytest plugins, add it to your experiment's `requirements.txt`.

### Deprecated

- `ExperimentAsset`, `CachedAsset`, and `CachedFunctionAsset` still import from `psynet.asset` but emit a `DeprecationWarning`; use `FileAsset` and `GeneratedAsset`. The old names are aliases for the new classes, so `isinstance` checks and queries behave differently: `OnDemandAsset` instances are no longer `ExperimentAsset` instances, generated assets are no longer `CachedAsset` instances, and `ExperimentAsset.query` now returns former `CachedAsset` rows but no on-demand rows. `asset(..., cache=...)` is deprecated and has no effect; combining `cache=True` with `on_demand=True` now warns instead of raising.
- Deprecated `force_google_chrome`; declare the browser features your experiment needs with `browser_capabilities` instead. Setting `force_google_chrome = true` logs a deprecation warning.
- The `max_iterations` argument of `advance_past_wait_pages` is deprecated and emits a `FutureWarning`; pass `timeout` in seconds instead. `timeout` defaults to 10 seconds, or to no limit when only `max_iterations` is given.
- Barriers' and groupers' `waiting_logic_expected_repetitions` is deprecated and raises a `FutureWarning`; pass `expected_wait` (in seconds) instead. `expected_wait` now also works with `waiting_logic`, which is then expected to repeat often enough to fill that time.

  ```python
  SimpleGrouper("quorum", initial_group_size=3, waiting_logic=filler, expected_wait=30)
  ```
- `SimpleGrouper(min_group_size=...)` is deprecated and emits a `FutureWarning`; pass `quorum=...` instead, the number of active members a group needs to keep going. `min_group_size=0` is read as `quorum=1`.

### Removed

- Removed `InheritedAssets`, which raised `NotImplementedError` when used, together with the unused `Asset.inherited` and `Asset.inherited_from` columns and the disabled `pre_deployed_assets.csv` loader. Also removed internal asset helpers that are no longer used: `FunctionAssetMixin.instructions`, `FunctionAssetMixin.get_md5_instructions()`, `CachedFunctionAsset.cache_key`, `threadsafe__prepare_asset_for_deployment`, and `AssetRegistry.initial_asset_manifesto_path`.
- Removed unused developer files: the pylint and JSHint configuration and their disable comments, `.git-blame-ignore-revs.txt`, `MANIFEST.in`, `dev-requirements.in`, `run-ci-tests-locally.sh`, the empty `__init__.py` at the repository root, and the `tests/test_run_all_demos.py` and `tests/test_run_isolated_tests.py` files, which no longer contained any tests. The source distribution no longer includes `postgres_setup.sql` or `run-ci-tests-locally-v2.sh`. The root pytest settings moved from `pytest.ini` to `pyproject.toml`, and a bare `pytest tests` now skips `tests/isolated`, `tests/experiments`, and `tests/template_experiment_tests` as intended.
- Removed the unused participant language switcher: `Participant.locale`, which always returned `None`, the `supported_language_dict` template variable, and the front-end handler and route entry for a language selector that PsyNet never rendered. Each deployment runs in the single locale set by `locale`.
- Removed the `/debugger/<password>` experiment route. Its password was hard-coded in PsyNet's public source, so anyone could pause a web worker in a remote debugger. To debug a running local server, add `import rpdb; rpdb.set_trace()` where you need it, as described in the development workflow docs.
- Removed outdated `DEPLOYMENT_ID` files from demos and test experiments, and the outdated `INSTALL.md` from the `static_audio` demo; installation is covered by the quickstart docs.
- Removed the `--ci-node-total` and `--ci-node-index` options from `psynet list-experiment-dirs` and `psynet list-isolated-tests`, together with the matching arguments of `psynet.utils.list_experiment_dirs()` and `psynet.utils.list_isolated_tests()`. CI now shards tests by recorded duration with `psynet dev ci run-tests`.
- Removed `AsyncProcess.launch_all`. Async processes still launch automatically once the transaction that created them commits. If a launch fails, for example because the worker queue is unavailable, the error is now logged and sent to the experiment's notifier where possible, instead of being raised from `db.session.commit()`, and the other processes saved in that commit still launch.
- Removed `psynet.data.disable_foreign_key_constraints`, which dropped every foreign-key constraint and never restored them. `ingest_to_model` and `ingest_zip` still drop them before importing.
- Removed `paramiko` from the `experiment` extra. PsyNet no longer imports it directly; Dallinger provides it for SSH deployments.
- Removed Google Translate support from `psynet translate`, along with `GoogleTranslator` and `UnsupportedLanguageError`; use ChatGPT (`chat_gpt`, the default) instead. If you set `default_translator = google_translate`, remove that line. `google_translate_json_path` and `google_translate_project_id` are now ignored, so existing config files that set them still load.
- PsyNet no longer generates or rewrites the unused `Dockertag` file, so commands no longer leave it as an uncommitted change. Existing `Dockertag` files can be deleted.
- Removed the unused Norwegian Bokmål (`nb`) catalog. PsyNet translates Norwegian as `no`; experiments could not select `nb`, and the translation dashboard listed it as complete although it lacked 122 texts.
- Removed the legacy `/on-demand-asset?id=...` route, which served any on-demand asset given its sequential id. On-demand assets are served from `/asset/<access_token>`.
- Removed the `/on-demand-asset?id=…&secret=…` route, which served any on-demand asset by its ID (in 14.0 release candidates, redirected to its `/asset/<token>` URL) without checking the secret; on-demand assets are served only at `/asset/<access_token>`.
- Removed `Experiment.check_unique_id` and `Experiment.UniqueIdError`. Look the participant up with `Experiment.get_participant_from_unique_id` instead, which already proves the request carried their `unique_id`.
- Removed PsyNet's bundled copy of jQuery UI 1.12. Experiments no longer serve `/static/scripts/jquery-ui.min.js` or `/static/css/jquery-ui.css`; a custom template that loaded them should ship its own copy in the experiment's `static/` directory.
- Removed the `psynet[slack]` extra. `slack_sdk` is already part of `psynet[experiment]` (and so of `psynet[dev]`), which is what Slack notifications and `psynet dev release announce` use. Installs that still name `slack` print a warning and continue; drop it from your install command.

### Fixed

- Fixed ``GraphChainTrialMaker`` so ``target_n_participants`` defaults to ``None`` instead of the ``Optional[int]`` type object.
- Playwright wait_while hold tests silence the 1s safety poll so a websocket wake is not lost.
- Fixed `psynet export ssh` so it reaches a deployment at its public origin. Cloudflare apps are no longer requested at `https://<app>.<ssh-host>`.
- SSH deployments record the account that launched the experiment. ``os.getlogin`` had reported the Docker daemon, so ``/health`` showed ``experimenter_name`` as ``root``. The experiment image also lets that account create ``server.log`` without making the shipped source writable.
- Timeline pages now load the SurveyJS library only when they contain a `SurveyJSControl`. Previously every page waited for it, which could leave buttons disabled for minutes on slow connections. Custom templates that use `Survey` without `SurveyJSControl` must list `/static/scripts/survey-jquery/survey.jquery.min.js` in `js_dependencies`. jQuery plugins loaded through `js_dependencies` now also stay registered on full page loads.
- Generated function assets now delete their temporary files after they are stored, instead of leaving them behind at every launch.
- Fixed `LanguageVocabularyTest` showing broken images instead of the picture choices for each word.
- Fixed `SurveyJSControl`, `MultiRatingControl` and `RatingControl` overflowing the page on phones.
- `psynet deploy local` now accepts the `generic` recruiter, which its error message recommends; previously it accepted only `hotair`.
- Error pages and ``/response`` error reports no longer fail when the participant's current trial cannot be loaded because the participant is detached from the database session; the error is reported without trial context and a warning is logged.
- Missing entries in PsyNet's own translation catalogs now fall back to English, with a warning, under ``psynet debug local`` as well as in tests. Sandbox deployments and release-branch CI still raise an error, and live deployments still report it.
- Fixed `bot.id` being `None` inside `Experiment.initialize_bot`. The bot is now flushed to the database before the hook runs, so `initialize_bot` can use the bot's ID, for example to seed per-bot randomness.
- Fixed cached function assets leaving their temporary file open until garbage collection, which Python 3.14 reports as an error.
- Fixed `psynet debug local --no-browsers` failing in the default auto-reload mode. It now skips opening browsers with any supported Dallinger version, and prints the recruitment message and the dashboard login that the browsers would otherwise have handled.
- Fixed the one-time `deploy.toml` review message describing a migration from `.gitignore` for brand-new experiments. New experiments now get a short neutral message; the migration wording is kept for existing experiments that previously relied on `.gitignore`.
- Fixed `psynet audit simulate` and other local exports printing a `FileNotFoundError` traceback about `.deploy/deployment_info.json` after the experiment server had stopped. The export manifest now takes the deployment ID from the database in that case, and reading a missing deployment info file fails immediately instead of retrying.
- Fixed a crash when rendering the "Your submission has been sent to Prolific" confirmation after a participant who left early clicks Submit. Participants previously saw a generic error page in place of the confirmation; the error page that offers the Submit button is unchanged.
- Fixed `@expose_to_api` turning a static method into a plain function, so calling it on an instance passed the instance as the first argument. `AudioMeterControl` without `calibrate=True` now sets `sliders` to `None` rather than creating an unused `slider` attribute, and the `api` demo reads its plain-text `hello` response as text. The `static` demo's `get_basic_data` now returns plain records outside exports, so its dashboard tab and `/basic_data` endpoint work.
- Fixed `psynet debug local --legacy` failing with "missing a .python-version file" for experiments using the stock `deploy.toml`. The template no longer excludes `.python-version`, which Dallinger needs to check the experiment's constraints when staging it. Experiments whose `deploy.toml` was created by PsyNet 14.0.0rc1 should remove `".python-version"` from `[exclude] names`.
- Fixed the experiment audit header showing no PsyNet version. `psynet audit init` now records the installed PsyNet version in `audit.json`.
- Fixed Lucid submissions not sending PsyNet's server-side complete or terminate call, so Lucid only recorded a complete when the participant's browser made it back to the panel. Calling ``reward_bonus`` on the Lucid recruiter raises; the complete or terminate is sent from ``report_submission_outcome``.
- Fixed the wrong-browser and mobile-device warnings, which crashed before they appeared, so participants were neither warned nor, on Lucid, sent back to the panel.
- Fixed `psynet setup` silently pinning PsyNet to a local `file://` path in `requirements.txt` when PsyNet was installed from a local wheel or directory. Setup now warns that such an experiment cannot be deployed remotely, and the pre-deploy PsyNet requirement check explains how to replace the pin.
- Fixed seeking in audit videos served by `psynet audit serve` or static hosts such as GitLab Pages, which ignore byte-range requests.
- Fixed deployments that omit the ``[experiment]`` extra from the PsyNet pin. The image installed only the command-line tools, so the clock process failed to start. Deploy now refuses that pin and shows the corrected line.
- Fixed `psynet deploy` accepting a local development version of PsyNet or Dallinger when `requirements.txt` pins a release. The deployed image installs the pinned release but copies templates and static files from the local package, so a mismatch could ship outdated participant pages.
- Fixed page loads and responses slowing down over time, especially on Prolific studies. Checks such as `with_prolific_recruitment()` and `with_lucid_recruitment()` no longer build a new recruiter on every request, and page rendering no longer reads every config value. Templates still read any config value on demand.
- The `BasicDemography` gender question now wraps its options into rows instead of stacking them, so the page fits a 1280×720 window together with the Prolific reward footer.
- Fixed `RatingControl` and `MultiRatingControl` scales on narrow screens. They no longer turn into a "Tap to rate here..." dropdown that hid `min_description` and `max_description`, and SurveyJS pages no longer overflow the page on phones. Scales now always show buttons, and screen readers announce each option by its label (plus the description at either end) rather than as "rating".
- Local launches, `psynet test local` and `psynet audit simulate` no longer stop other experiments' processes on the same machine. Leftover `dallinger_heroku_*` workers are stopped only if they use the current `DATABASE_URL` (their process supervisor then exits by itself), the test fixture no longer runs `pkill -f heroku`, and Chrome and chromedriver cleanup is limited to the browsers PsyNet's test driver started.
- Fixed Lucid participants who close the tab staying `working` indefinitely. The recruiter clock now terminates them one minute after `termination_time_in_s` has passed, so a paused survey can complete on its own.
- Fixed Lucid elapsed-time checks that wrapped around every 24 hours. A participant who reloaded a page a day or more after entering got a fresh time limit, and the Lucid dashboard's time since the last API call and the rate-limit cache check were wrong after a day.
- Fixed the launch notification written to the server log (for example the `web.1` lines of `psynet debug local`) including the dashboard password. The log now shows `<redacted>`. The launch banner and Slack notifications still show the password.
- Fixed push buttons (for example in `PushButtonControl` and the headphone tests) rendering an invalid `,=""` attribute.
- Fixed `CountryOfBirth` and `CountryOfResidence` (both part of `BasicDemography`) saving to the same `participant.var.country`, so the country of residence overwrote the country of birth. They now save to `participant.var.country_of_birth` and `participant.var.country_of_residence`, matching their page labels. Code that read `participant.var.country` should read one of these instead.
- Fixed `psynet debug local` with `recruiter = prolific` reporting "Study created on Prolific". The launch output now says the Prolific study is simulated and nothing was created.
- The rendered audit header now shows the experiment's short Git commit, with `-dirty` when files outside `audit/` have uncommitted changes, instead of `-`. A value set in `experiment.git_commit` in `audit.json` still takes precedence.
- `BotDriver.current_page_label`, `current_page_text` and `current_page_time_estimate` return `None` once the participant has left, instead of raising `KeyError`, and `BotDriver.take_page()` returns `False` once the participant has finished, as documented. Deployment IDs replace punctuation in the experiment label with hyphens, so labels such as "The prisoner's dilemma" no longer put apostrophes in launch-data paths.
- Prolific participant status checks no longer log a `ProlificServiceException` traceback every few seconds when no Prolific study is recorded for the experiment, for example in `psynet debug local` with `auto_recruit = false`. PsyNet now skips the check and logs a single warning.
- Fixed experiment status rows storing the dashboard password. Each row's `extra_info` included `basic_data_url`, whose query string contains the dashboard credentials, so every export's `database/experiment_status.csv` contained the password, including exports of deployed experiments. Status rows no longer store `basic_data_url` or the launch `secret`, and the dashboard endpoint that reads retained status backups now requires authentication. Exports made before this fix still contain the password: change the dashboard password (or treat the deployment as retired) before sharing them.
- Stopping `psynet debug local` by sending `SIGTERM`, `SIGINT` or `SIGHUP` to its process ID (for example with `kill <pid>`, from a script or an agent) now also stops the `flask run` server, worker and clock processes it started. Previously only Ctrl-C in the terminal stopped them, and a signal to the `psynet` process alone left the server running on port 5000.
- Fixed a race where a participant waiting at a barrier could miss its release if the barrier released while the wait page's WebSocket was still connecting, and was then failed for timing out even though the barrier had already released them.
- The dashboard routes for deployment status, archiving, restoring, recruitment updates, deployment comments and `/dashboard/export/trigger` now require a dashboard login, as do the routes behind the Timeline tab's spending limits and progress counts and the Lucid tab's status picker. Previously anyone who knew the URL could call them. Logged-in dashboard users are unaffected, and the Slack "Trigger export" link still works via the login page.
- Fixed `psynet deploy` rejecting a PsyNet or Dallinger git pin with an abbreviated commit hash (for example `@2da1cc66`) even when it matched the locally installed commit. A pinned hash now matches when the installed commit starts with it.
- PsyNet now removes any username, password or access token from the Git `origin` URL (for example `https://user:token@gitlab.com/...`) before storing it in deployment records, status files and exports, or showing it in `psynet` error messages.
- Fixed the Lucid recruiter reusing stale cached submissions for the rest of the experiment after the Lucid API had rate-limited it once. It now uses the cache only for five minutes after a rate limit and then polls the API again.
- Survey pages now load the minified SurveyJS 1.9.60 build (1.5 MB instead of 8.3 MB), so they become interactive sooner on slow connections.
- Fixed async processes (async code blocks, `async_post_trial`, background asset deposits) sometimes launching when a different request committed, before the request that created them had saved them. If that request took more than 4 seconds to commit, the process never ran and stayed pending, leaving participants stuck on any hold that waited for it. Processes created in a transaction that is rolled back are no longer launched.
- Closing a database session without committing now discards the timeline hold wakes it queued, so a later commit on the same session no longer sends them.
- Stopped sending a "worker restarted" notification for every web worker when the server first starts; the notification is now sent only when a worker is replaced.
- Fixed participants failed from the dashboard, by a partner leaving their group, or by a background job staying on their timeline hold overlay until its next safety check. Failing a participant now wakes their hold immediately.
- Fixed web servers (gunicorn and the `psynet debug local` dev server) and background workers freezing for up to 5 seconds when one request waited on a database lock. Group barriers and other timeline holds could return 503 errors when the participant holding the lock shared a process with participants waiting for it. Database queries in Dallinger's gevent processes now let other requests run while they wait.
- Fixed `GroupBarrier` release checks with `late_after` ignoring late members who were about to be removed from their group or failed. When another request was checking the same barrier at the same time, the last arrival could briefly see the waiting overlay until the background poller released the group.
- Fixed stale browser tabs bypassing the "multiple browser tabs" check by submitting from an old timeline hold. A hold's page id is now accepted as a catch-up only until the participant advances past the first ordinary page after that hold.
- When a participant's timeline moved on to a later `wait_while` hold during a hold check, PsyNet could show that hold without checking its condition. The participant then waited until the next safety poll even if the condition had already cleared. Consecutive `wait_while` holds share a `hold_id`, so the check mistook the later hold for the earlier one.
- `VideoRecordControl` now deposits recordings synchronously under `LocalStorage`, matching `AudioRecordControl`, so a playback page that follows the recording no longer intermittently gets a 404 for the video. The audio demo also waits for the video recording to be deposited before playing it back, so it works with asynchronous storage such as S3.
- Fixed an empty definition (`{}`) passed to `ChainNode` or returned from `make_next_definition` being treated as no definition and falling back to `create_seed`; a node created without a definition now raises an error that explains how to fix it.
- Fixed a missing experiment `title` raising a bare `KeyError`; PsyNet now explains where to set it.
- Sped up experiment launches and `psynet load` by dropping foreign-key constraints once per database import instead of once per table, which removes about 1,200 schema-reflection queries per launch.
- Growing a graph network no longer commits the surrounding transaction partway through, so a participant's response is saved all-or-nothing and the growth poller keeps its network lock until growth finishes.
- Answers from an accumulating page maker nested inside an accumulating trial or page maker are no longer lost; they are added to the same `participant.answer` dict.
- Fixed chain and create-and-rate nodes receiving more than `trials_per_node` trials when several participants were assigned trials at the same moment.
- The background check that fails timed-out trials now skips trials that a participant's request is still processing, instead of waiting for that request to finish.
- `psynet performance-test` now ends a test early with an explanation and reports the results collected so far when the experiment server stops mid-test (for example once a local experiment reaches its participant target), instead of respawning failing bots until the timeout and then crashing with a connection error.
- Rejected answers (those that fail page validation) no longer overwrite `participant.answer` or `save_answer` variables, no longer add duplicate entries to accumulated answers, and no longer trigger the page's `on_complete` hook. The rejected response is still stored with `successful_validation = False`.
- The experiment status job, which runs every minute, now counts participant statuses in the database and loads only the fields it needs from participants and request logs, so it stays fast in large experiments.
- Trial-based recruitment (`recruit_mode="n_trials"`) now counts the trials still required with one database query instead of loading every network.
- `WorkerAsyncProcess.cancel()` now cancels the queued background job instead of raising an error. It no longer commits, so it can be called from code blocks and trial hooks, and the change is saved with the surrounding step. The background job is cancelled only when that step commits; if the step rolls back, the job still runs. Cancelling twice is harmless, and a process cancelled before its transaction commits is never launched.
- Fixed the dashboard's Errors tab, which failed to load once an error had been recorded, and made its "View in logs" links and error notifications point to the error's line in the log.
- Fixed error reporting so that a missing translation in a live experiment no longer breaks page rendering or saves a timeline step's half-finished work, and so that errors raised by a failed database write are recorded with the IDs of the participant, trial and other objects involved.
- Fixed failed participants skipping waits in end logic, such as an `AsyncCodeBlock` with `wait=True` in the unsuccessful end; they now wait like other participants. A participant failed while waiting elsewhere in the timeline still leaves the wait for the unsuccessful end.
- Fixed Prolific return-for-bonus for failed participants, who were told their return had not worked and were never paid the bonus. The return check and bonus payment run in background workers while the participant waits; the payment may take up to 60 seconds.
- Fixed an intermittent failure in the timeline hold busy-retry Playwright test, where a leftover queued hold wake could land in the probe's counters.
- Fixed the graph demo's `CustomTrialMaker` so that `target_n_participants` defaults to `None` and `n_participants_completion` is passed through to `GraphChainTrialMaker`.
- Local test runs no longer close Chrome windows and chromedriver processes that belong to another local experiment, and asset HTTP export no longer assumes the local server is on port 5000.
- Fixed `recruit_mode="n_trials"` recruiting forever when a node or chain failed before reaching its target: failed networks no longer count towards the trials still required.
- Fixed `psynet performance-test local` stopping its server partway through a run. The local debug server shuts down when the experiment reports completion, which could happen whenever no bot happened to be mid-participant, so experiments without trial makers often failed with a connection error on `/request_statistics`.
- CI image builds now retry PyPI requests for longer, so a brief PyPI outage no longer fails every test job.
- Fixed Prolific return-for-bonus checks treating a connection error or timeout as a permanent failure. The participant is now asked to try again, as for other temporary Prolific errors, instead of seeing the error page.
- Fixed a trial staying pending forever, which also stopped a chain from growing, when the async process that deposits one of its assets fails, for example because `on_finalized` raised or the storage upload failed. The trial is now marked failed, unless it was already finalized.
- Fixed one failing network or trial in the background network-growth and trial-finalization checks undoing the work already done for other networks and trials in the same check. Each item now runs in its own database savepoint, so a failure rolls back only that item, which is recorded as an error and marked failed, and the researcher is notified only once the check's changes are saved; a lock conflict or deadlock is retried on the next check instead. If such an item commits or rolls back, which now raises, it is recorded and failed in the same way. The internal `Experiment.isolate_batch_item_failure` is removed.
- Fixed an intermittent failure in the timeline hold client Playwright test. Its busy livelock check no longer waits for timers to fire, so wakes left over from earlier steps cannot affect the result.
- Fixed the researcher not being notified when a Prolific return-for-bonus payment does not finish within 60 seconds, for example because the worker queue is stalled. The participant was already told that the researcher had been notified.
- Fixed waiting participants occasionally staying on a group barrier until the safety poll or hold timeout when the next stacked barrier was released while their previous release check was still loading.
- Fixed a database deadlock between finalizing a trial in the background and a request that fails the same participant. Finalization now locks the participant before the trial, the background finalization check skips trials whose participant is busy, and async post-trial analyses and asynchronous asset deposits finalize their trial after the worker commits. As a result, if `on_finalized` raises after an async process, the process still counts as finished and the trial is failed by the background check.
- Fixed trials sometimes staying unfinalized for several seconds when an async post-trial analysis or asset deposit finished at the same time as the participant's response: async workers now re-check finalization with fresh data after committing, and the finalize backstop runs every 0.5 s instead of every 5 s. The end-of-trial-maker performance check now also waits for such trials to finalize, so their scores are set, and the `create_and_rate/gap` demo assigns roles from complete rather than finalized creations.
- Fixed `psynet db <location>` failing with `Invalid location: None` for every location, including `psynet db ssh`, which prints the URI of the SSH tunnel to a deployed experiment's database.
- Fixed several local development papercuts. `psynet debug local` no longer reloads when another debug server on the same machine writes its development folder, nor, in a PsyNet or Dallinger source checkout, when files under `tests/`, `demos/` or `docs/` change. With `--no-browsers` (and without `--legacy`) it no longer says that recruitment requests will open browser windows. `psynet experiment-variables local` no longer needs an SSH server to be configured, and `--help` works for every subcommand outside an experiment directory. The documented `createdb` command for parallel sessions no longer waits on a password prompt. Ctrl-C no longer forces the background worker of `psynet debug local` into a cold shutdown with a `SystemExit` traceback, and commands that scaffold an experiment automatically no longer print "Nothing to scaffold" when its files are already present.
- Fixed `psynet setup` sending you round in circles when you decline to install packages into a virtual environment that is not the experiment's `./.venv`. Setup now still creates the Git repository and prints the commands that set up a dedicated `./.venv`, so `psynet debug local` no longer asks you to run `psynet setup` again. Without a terminal to ask, setup does the same and then exits with status 1. The missing-files error now starts with the command to run and puts each further hint on its own line, and the `--no-install` docs now say that it also sets up Git.
- `psynet installation update` and the PsyNet folder-name check before auto-reload now recognise editable installs made by current pip and uv. Before, `psynet installation update` treated an editable Dallinger checkout as a normal install and replaced it with a non-editable copy.
- Async job timeouts, including trial makers' `async_timeout_sec`, now count from when the job starts running, so jobs waiting in a busy queue are no longer failed before they run. A worker async job that has not started within an hour of being enqueued is failed as probably lost only if RQ no longer has it queued; a genuine backlog keeps waiting. Workers skip jobs that have already failed.
- `psynet deploy heroku --docker` no longer runs a second, non-Docker deploy afterwards.
- When the local PostgreSQL server runs out of connections ("sorry, too many clients already"), local test sessions, `psynet test local` and `psynet performance-test local` now explain that every local session shares the server's `max_connections` limit and suggest running fewer bots or sessions, stopping other local experiments, or raising `max_connections`.
- Fixed `psynet deploy heroku --docker` also running a plain Heroku deploy after the Docker deploy, and `psynet debug heroku --docker` skipping the Heroku package-size, asset-storage and Prolific payment checks that `psynet debug heroku` runs. Like `psynet deploy heroku --docker`, `psynet debug heroku --docker` now also asks you to confirm before launching, because Heroku Docker deployment has been unreliable.
- Fixed `psynet setup --psynet-source editable` warning about an unpushed commit pin on alpha PsyNet versions; a new `requirements.txt` now records the editable requirement directly.
- Fixed `psynet db ssh` crashing when `--server` was omitted or named an unknown server; it now selects the server the same way as other SSH commands, using your only configured server automatically or asking you to choose one.
- Fixed balanced node selection (the ``StaticTrialMaker`` default, ``node_order="balanced"``) slowing down as an experiment collects trials: each candidate node's trial count is now read from a new partial index on the trial table instead of from every trial row, so in local tests with 300 nodes and 200,000 trials, choosing a trial took about 15 ms instead of about 430 ms. The same applies to chain trial makers with ``chain_order="balanced"`` and to node capacity checks.
- Fixed the complex audio Gibbs demo failing early participants when its start stimuli took more than a minute to synthesise; participants now wait up to five minutes for a trial.
- Fixed `POST /response` holding a database connection idle in transaction while a participant's recording or file upload was still arriving; the request body is now read before the first database query, so slow uplinks no longer tie up the connection pool.
- The "Sliders" and "Documentation" tabs of `AudioMeterControl(calibrate=True)` now switch. The control now loads Bootstrap's JavaScript, which the tabs rely on but participant pages did not load, so the documentation tab could not be opened.
- Fixed the browser entry check letting participants through when incognito detection fails, as it does in Firefox: with `force_incognito_mode = true` an unknown incognito status now fails the check, and `force_google_chrome = true` now rejects Firefox.
- Fixed several problems with bots, performance tests and remote tests. `psynet run-bot` without `--dashboard-user` and `--dashboard-password`, and `psynet performance-test local --existing` and `psynet test local --existing` against a server started with `psynet debug local`, now read the running server's config instead of failing. Ctrl-C and SIGTERM no longer make PsyNet processes that load the experiment, such as `psynet test local` and bots, exit silently with status 0: Ctrl-C raises `KeyboardInterrupt`, prints `Aborted!` and fails, and SIGTERM runs the process's cleanup and exits with status 143. Dallinger's web, worker and clock processes still exit with status 0. `psynet test ssh` and `psynet performance-test ssh` stop the test on the server when the SSH connection drops or on Ctrl-C, read the deployed app's own configuration, such as its mode, rather than the copied `config.txt`, and copy the bot log back to your computer. Performance tests count bots whose run raised an error as failed, no longer fail bots on Redis connection limits above about 100 bots, and over SSH send the bots' requests straight to the app inside its container instead of through its public URL, so the bots no longer spend their CPU on encryption. The bot process raises its open-file limit, and impossible options such as `--duration-minutes 0` are refused.
- Fixed participants who close the page while waiting at a grouper or barrier never being timed out, and the background barrier check slowing down in proportion to the number of waiting participants. With a few thousand of them it took over 20 seconds per run instead of its 0.5-second interval, keeping one CPU core busy. For waits that use the default wait indicator, the background check now applies `max_wait_time` once the deadline has passed, failing or kicking the participant as `max_wait_action` says, so their partners are handled as if they had timed out in the browser. It also spreads its re-checks of waiting groups over several runs, so each run normally takes well under a second however many participants are waiting.
- Fixed a race in barriers without `waiting_logic`, including `SimpleGrouper`: a participant whom the barrier released just after their `max_wait_time` ran out, but before their next check, was still failed for waiting too long, which also failed the rest of the group they had just joined.
- Fixed a race at groupers and group barriers under heavy load that could fail a waiting participant, and with them their partner, with an `IntegrityError` on `ix_barrier_instance_active_ungrouped`. The barrier check now reopens a leftover waiting pool only while it holds the same lock that arriving participants take to open one, and otherwise leaves it for a later check.
- Fixed `SimpleGrouper(join_existing_groups=True)` leaving participants waiting until they timed out while an existing group still had room, for example after a burst of arrivals that was not a multiple of `initial_group_size`: participants already waiting now join such a group on the next barrier check. Closed groups and groups with no active members are no longer joined.
- Fixed an error page (HTTP 500) for participants whose sync group closed because a partner left or timed out: their next submission or page load now takes them to the unsuccessful end without rebuilding the open page, whose code may need the closed group. The answer submitted from that abandoned page is no longer stored.
- When a test in a `psynet performance-test` run crashes, for example because the server's database stopped answering under load, the command now prints the summary of the tests that completed before it, and says which test stopped the run, instead of failing with only the error.
- Fixed `SimpleGrouper(join_existing_groups=True)` letting a group grow past `max_group_size` when several participants joined it at the same moment, for example a new arrival and a participant already waiting at the grouper. Joins to one group now take turns and check the group's current size before joining; a participant who finds the group busy tries the next suitable group, or waits at the grouper and tries again shortly.
- Fixed the trial time estimates of the `rock_paper_scissors` and `create_rate_sync` demos, which counted only one page of each trial, so that their progress bars, reward estimates and default performance-test lengths match the full trial.
- Fixed a flaky participant-failure test by removing it: the experiment's finalize backstop could finalize its trial mid-test, and its remaining check duplicated test_exit_fails_incomplete_and_preserves_completed.
- Fixed a database deadlock when two members of a sync group failed at the same moment, for example when both timed out waiting for a third member. When a group without top-ups drops below its `quorum`, its remaining members are still all failed (or, with `below_quorum="continue_without_group"`, removed) together. If another member is in the middle of a request at that moment, nobody is removed yet: the background barrier check dissolves the group usually within a second or two of that request finishing.
- The Playwright hold tests no longer fail when a busy HTTP 503 is slowed by CI load; a unit test checks that hold-resume requests use `NOWAIT` instead.
- `psynet translate` now retries ChatGPT replies that are empty or that drop or change an HTML tag, such as `<i>` becoming `<em>`, instead of saving them. A translation may still use a tag fewer times than the English text.
- `psynet translate` now translates a fuzzy entry whose translation is still the English text once more, instead of keeping it forever. If the model gives the English text again, as is correct for many country names and for "OK", the entry is marked `psynet-kept-source` and kept on later runs. Remove the fuzzy flag to keep an English translation without the retry.
- For large source files, `psynet translate` now gives ChatGPT the code around every text in a request. Before, long lines near the first text could use up the whole budget, so the request was sent without any code.
- `psynet translate od` now tells ChatGPT to write in the Odia script. PsyNet's Odia locale code `od` is not the ISO code (`or`), so the script lookup used to find nothing.
- `psynet translate` now saves each locale's catalog after every request, so translations already received are kept if the run stops early, for example on a timeout or an API outage. The next run only sends what is still untranslated.
- `psynet translate` now works with OpenAI models that only accept their default temperature, such as gpt-6-luna. When the API rejects `openai_default_temperature`, the request is sent again without it, and later requests for that model leave it out.
- Fixed the deploy-time check that compares installed PsyNet and Dallinger versions with `requirements.txt`: it now reads the active interpreter's package metadata instead of running whatever `pip` is on `PATH`, so it works in `uv` virtual environments without pip and recognises editable installs from Git worktrees. A branch or commit pin now fails with a clear error when the editable install's directory is not the root of a readable Git checkout.
- Fixed `psynet destroy ssh` and `psynet export ssh` skipping the check for pending async jobs when the app's public address doesn't answer, as with a Cloudflare tunnel that is reconnecting: the check now queries the app's database from its web container over SSH and no longer needs the dashboard credentials on your computer.
- `psynet performance-test ssh` now works on the first run in an experiment without generated boilerplate, such as a bundled demo, instead of failing with "The experiment needs a title". `psynet debug ssh --use-local-psynet` and `--use-local-dallinger` likewise no longer ask for `psynet scripts update` when the Dockerfile hasn't been generated yet.
- Fixed messages and docs that sent users of servers with Cloudflare ingress, such as lab computers, to a Dozzle log viewer that those servers don't have. For such apps, the Slack launch notification and the `psynet destroy ssh` and `psynet performance-test ssh` error messages now give the `ssh … docker compose logs -f` command instead of the Dozzle URL, and the deployment monitor no longer shows a logs link. The error messages follow each app's own ingress, read from its compose file on the server or from the experiment directory's deployment record, so they stay right on servers that mix ingress modes. The deployment docs say that Dozzle is available with classic ingress only.
- `psynet debug local` and `psynet deploy local` now refuse to start, with exit status 1 and before resetting anything, while another local PsyNet server uses the same port or database or another program listens on the port. Leftover worker processes from a killed server are still stopped automatically. Previously a second server stopped the first one's workers and emptied its database before failing, and a busy port exited with status 0.
- `psynet deploy ssh`, `psynet deploy heroku`, `psynet debug ssh`, `psynet debug heroku` and `psynet performance-test ssh` now compare the installed Dallinger with its pin in `constraints.txt` (including the commit of an editable checkout) and stop if they differ, instead of reporting a match that was never checked; `psynet debug ssh --use-local-dallinger` skips the comparison. An exact pin in `requirements.txt` still takes precedence, version pins compare by version (`==12.4` matches 12.4.0), and Git branch pins defer to `constraints.txt`. Each package gets its own check line naming what was compared, mismatch errors explain how to install the pinned version, and the version and requirement check spinners no longer print colour warnings or garbled output outside a terminal.
- `psynet load` no longer counts database connections that PsyNet itself still holds as other clients of the local database, unless they lock a table that loading would drop.
- The performance-test progress line shows `Avg: -` until the first bot finishes, instead of `Avg: 0.0s`.
- `psynet setup` now keeps an editable Dallinger checkout instead of replacing it with the pinned version, and installs any new dependencies the checkout needs. `requirements.txt` and `constraints.txt` still record PsyNet's Dallinger pin for deployment. Pinning PsyNet to a commit still replaces the checkout, and setup now warns and says how to restore it.
- `psynet destroy ssh` and `psynet export ssh` now stop straight away when an app name isn't on the server, listing the apps that are and suggesting the closest one, instead of reporting misleading pending-job or DNS errors. Destroy asks one clear question, `Destroy 1 app on <server>: <app>? [y/N]`, that defaults to no in both the `--app` and batch forms, and asks for `--yes` when there is no terminal to answer in. Deploying onto an existing app name now prints the `--update` command that keeps its database, and a local-path, editable or wheel PsyNet requirement is reported before the `constraints.txt` check, as a short error with examples for the current PsyNet version instead of a traceback.
- The nightly ASV benchmark job now reinstalls Dallinger for each compared commit, so an older commit is no longer benchmarked against the newer commit's Dallinger.
- CI image builds now time-limit and retry `apt-get update`, so they fail within minutes instead of hanging until the 3-hour job timeout when the Debian mirror is unreachable, and the nightly ASV job is retried once after a timeout.
- Fixed an unclosed `<b>` tag on the `REPPVolumeCalibration` instructions page (and its tapping demo copy) that made the rest of the page bold and pulled the footer up from the bottom of the window.
- `psynet destroy heroku` no longer tries to expire MTurk HITs; PsyNet meant to turn this retired-platform step off but did not detect Dallinger's option.
- `psynet destroy ssh <app> --remove-data` now succeeds, saying "Nothing left to delete", when the app and its data are already gone, for a single app as well as several. With `--remove-data`, the destroy confirmation now says that the apps' data is deleted too and cannot be undone.
- `psynet translate` and the translation checks now treat a folder containing `experiment.py` as an experiment even when it also has a `pyproject.toml` (for example from `uv init`), instead of failing to find a package source directory.
- SSH commands such as `psynet export ssh` now suggest checking the SSH connection only when listing the server's apps fails because of the connection. An invalid configuration, such as an `Experiment.config` key that an older PsyNet accepted, is reported as a configuration problem that names the key, and other server-side failures are reported without the SSH hint.
- Fixed Dozzle log viewer links in Slack launch notifications, the deployment monitor and `psynet destroy ssh` / `psynet performance-test ssh` messages pointing at `https://logs.<--server>` when the server's DNS name differs, for example for a server registered by IP address or selected by a short name. The links now follow where the installed Dallinger serves Dozzle.
- The "When was the last time you danced?" demography question (`LastTimeDanced`) now has its own translation context, `last_time_danced`. It shared the context `dance` with `DanceSociallyOrProfessionally`, so `psynet translate` warned in every locale that translates "I never dance" and "I never danced" the same way, as languages without tense do.
- `psynet export ssh` now exports apps deployed without `--app`, which are served at the server's own (root) domain. `psynet export ssh`, `psynet hibernate ssh` and `psynet awaken ssh` accept such an app's `dlgr-...` name as listed by `psynet apps ssh`, and a full experiment UUID suggests that name. When neither a local launch note nor the server's deployment record gives the app's address, the export reads it from the server's Caddy routes instead of assuming `https://<app>.<server>`.
- `psynet translate` now lists a text once in the translation template when it is used in several files, for example in both a Python file and an HTML template. Previously each copy was translated separately, and when the copies got different translations the catalog check failed with an empty error message; that message now names the text and both translations.
- Fixed asset uploads to an SSH server failing with a closed-socket error after the SSH connection dropped or was closed earlier in the same Python process; PsyNet now opens a new SFTP connection instead of reusing the dead one.
- CI image builds now give ``pip install uv`` a longer timeout and more retries, so a brief PyPI blip is less likely to fail the job.
- Ctrl+C now stops `psynet debug local --isolated` in about 2 seconds instead of about 10, and without the screens of Redis connection tracebacks that the worker and clock printed after the session's own Redis server was stopped too early. When `psynet debug local --isolated` or `psynet test local` isn't the foreground job of a terminal, for example when an agent runs it, a SIGINT sent to its `psynet` process now stops the session too, instead of leaving the server running. This includes sessions that a script started in the background (`psynet debug local --isolated &`), which previously ignored SIGINT. Pressing Ctrl+C while the clock reloads the experiment after a code change no longer prints a screen of `Could not import experiment` errors and an `ImportError` traceback.
- `psynet debug ssh`, `psynet deploy` and related commands now print two common set-up problems as a short error message instead of a long traceback: an experiment without a consent page ("It looks like your experiment is missing a consent page…"), and an SSH deploy whose `server_pem` setting is missing or names a file that doesn't exist.
- The temporary scaffold that PsyNet's pytest fixtures add to an experiment directory is now removed from that directory even if the test session has changed directory in the meantime. Previously, a test session stopped by a signal could run this cleanup in the directory pytest was started from, deleting files such as `README.md`, `AGENTS.md` or `.gitignore` there.
- The `Launched experiment "…"` message in the server log and in Slack no longer includes the deployment secret. For local launches it is now logged at DEBUG, because "Experiment launch complete!" follows straight away.
- `psynet translate` no longer leaves a few "extracting messages from …" lines on screen while it extracts the HTML templates; the progress now stays on the spinner line.
- SIGTERM or SIGHUP to `psynet dev ci run-tests` now stops its running test processes and removes the database and Redis server of each slot, instead of leaving them behind.
- Fixed the output of `psynet debug ssh` and `psynet deploy ssh`: after `--update`, the closing summary shows the participant link or recruiter's message saved when the app was deployed (or says that recruitment is unchanged), and the saved launch data keeps them; a confirmation answered through a pipe no longer runs onto the next line; and `psynet debug ssh --use-local-dallinger` no longer repeats Dallinger's message about the checkout it deploys. After an `--update`, `psynet export ssh` checks this directory against the commit the app now runs, instead of warning that it was launched from the first deploy's commit. `psynet export ssh` shows its download steps as one plain line each, such as `Downloading export...` and `Downloading media files...` (previously `Fetching missing asset bytes`) (in a terminal, after a spinner while the step runs), instead of `✔ Downloading export` or, when its output is redirected, spinner frames and a yaspin colour warning, and no longer reports materializing zero assets from the local cache. `--use-local-psynet` now says `Using the PsyNet checkout at … instead of the version in requirements.txt.` instead of `Baking local PsyNet from … into the experiment image.`
- A participant page whose session is no longer in the database (for example a browser tab left open across a `psynet debug local` restart) now shows "This session is no longer available" with HTTP status 404, and the server logs one warning line instead of a 500 error and a traceback. This covers `/timeline`, `/response`, `/log`, `/participant_opened_devtools` and `/timeline/progress_and_reward`. A page waiting at a timeline hold, or polling its progress bar, goes to that message instead of retrying.
- Translation tests that simulate local debug now ignore GitLab's ``CI_COMMIT_REF_NAME``, so they no longer fail on ``release-*`` branches.
- `psynet export ssh` no longer asks to confirm a project mismatch (or needs `--allow-project-mismatch`) just because the experiment leaves scaffold boilerplate such as `Dockerfile`, `test.py` and `AGENTS.md` out of Git, as PsyNet's demos do, or because the repository gained commits that don't change the experiment directory. Deploys no longer warn about that boilerplate as uncommitted changes either; files authors customize, such as `README.md` and `deploy.toml`, still count once they differ from the template. Apps deployed with an earlier version keep their recorded list of uncommitted files until they are updated with `--update`. The logs command that PsyNet records for notifications passes a user name containing `@` with `ssh -l`.
- Importing PsyNet no longer turns on every package's `DeprecationWarning`s: only those from PsyNet, Dallinger and the experiment are shown, unless Python's `-W` option or `PYTHONWARNINGS` says otherwise. With a Dallinger version that does the same in its server processes, `psynet debug local` no longer prints warnings meant for other packages' maintainers, such as Flask-Login's `datetime.utcnow()` warning.
- `psynet debug local` now stops with one `Error:` line, instead of a traceback, when the `dallinger_develop_directory` setting can't be used, for example because its folder name isn't a valid Python identifier or its path contains a period.
- `psynet export ssh` (and other remote exports) run in a terminal can ask again whether to export a deployment whose code doesn't match the experiment directory exactly. Previously it stopped with `ImportError: cannot import name 'user_confirms'`.
- On Python 3.11 and 3.12, `psynet dev ci run-tests` now waits for its running tests to stop after SIGTERM or Ctrl+C, instead of exiting while they are still running.
- The dashboard visualizations of `PushButtonControl` and `TimedPushButtonControl` responses no longer raise an error; they highlight the chosen button and every pressed button, respectively.
- Removed the timing assertion from the static_big prepare test so a busy CI runner does not fail the check.
- Fixed `--use-local-dallinger` (in `psynet debug ssh` and `psynet performance-test ssh`) building an image that lacked dependencies added in the local Dallinger checkout, so the app could build and then answer 503. The image now installs the checkout's missing dependencies, keeping the pinned versions that satisfy it, and the build fails if a local PsyNet or Dallinger build conflicts with the other installed packages. If you scaffolded or updated an experiment from PsyNet master between 30 September 2026 and this fix, run `psynet scripts update` to pick up the new `Dockerfile`, or copy its local-wheel install steps into a customised one. A PsyNet or Dallinger version mismatch before deploying now shows a short error instead of a Python traceback, and the `SKIP_VERSION_CHECK` message names both packages.
- A request that has no dashboard login and knows only a participant's `participant_id` can no longer get the identifiers it needs to act as that participant through Dallinger's `GET /participant/<participant_id>` or `/recruiter-exit` routes, the Lucid `/terminate_participant` route, or `/response`. `GET /participant/<participant_id>` now returns nothing unless the request is logged in to the dashboard (nothing in Dallinger or PsyNet calls it), and `/recruiter-exit` needs the participant's `unique_id` as well as `participant_id`. PsyNet's Finish button, its redirect for finished participants and, on PsyNet pages, `dallinger.submitAssignment()` include it. Custom code that builds its own `/recruiter-exit` link with only `participant_id` now gets an error page and needs to add `unique_id`. `/terminate_participant` no longer finds a participant by `participant_id` alone; it takes `unique_id`, `RID` or `assignmentId`. `/response` now rejects an answer from a page other than the participant's current one even when a redirect is queued for them, for example after a sync-group partner leaves, and it only records the request's IP address for an answer from the participant's current page. Setting the `protected_routes` config variable no longer unprotects the routes PsyNet protects by default, such as `/network/<network_id>`: the configured routes are added to PsyNet's. To unprotect one of PsyNet's routes, override `Experiment.protected_routes` in your experiment class.
- PsyNet's Docker image compiles its constraints for the image's full Python version, and `psynet dev ci update-dallinger-constraints` checks each supported Python at its latest patch release. Both passed a bare minor version such as `3.11`, which uv resolves as Python 3.11.0, so the Python 3.11 image failed to build with Dallinger's pins (`soupsieve==3.0.4` requires Python 3.11.5).
- Fixed built-in pre-screens that let participants read the correct answer from the page. The stimuli of `LanguageVocabularyTest`, `LexTaleTest`, `ColorBlindnessTest` and the headphone tests are now downloaded by the experiment server from an http(s) `media_url` and served under opaque URLs. The experiment server therefore now needs outbound internet access to the stimulus host (S3 by default), where previously participants' browsers fetched the files; if a download fails, the stimulus request returns HTTP 502. A `media_url` that isn't http(s), such as `/static/...`, is still used directly and stays visible to participants, with a warning. `VocabTest` (including `WikiVocab` and `BibleVocab`) uses random item IDs and gives no credit unless the answer lists exactly the trial's items, in the order shown, each answered `"real"` or `"fake"`. With `n_trials` above 1, `VocabTest`'s per-trial performance check now scores the latest trial instead of always the first.
- Closed several routes that trusted or revealed information given only a participant's sequential id. `/execute_early_exit_plan` returns a participant's release link only to a request that sends their exit plan's id. The Prolific exit page and the error page's Submit to Prolific button send the participant's `unique_id` to `/prolific-submission-listener`. `/response` refuses a `page_uuid` that isn't a string with a 400 instead of failing with a server error. `/basic_data` refuses every request when no dashboard username or password is configured. The dashboard's export and artifact routes no longer treat a request from a tunnel such as cloudflared as coming from the local machine. `/get_participant_info_for_debug_mode`, which returns the first participant's `unique_id` in debug mode, used to answer anyone who could reach the server; it now answers only direct requests from the local machine.
- Fixed the browser entry check treating iPadOS 13+ as a desktop browser, so `allow_mobile_devices = false` now also rejects iPads.
- Exports no longer include `database/lucid_submissions.csv`. That table caches Lucid's session API responses, which hold Lucid respondent and panelist IDs that identifier separation did not remove.
- Fixed cross-site scripting (XSS) in participant and dashboard pages. Participant pages rendered with translations had autoescaping turned off, so a crafted link to the error page, or text that one participant typed and another saw (for example in chain experiments), could run JavaScript. The ad, consent and Lucid exit pages now write the request's query string and redirect URL as JSON instead of pasting them into JavaScript, as do the Prolific submitted page, the browser compatibility check, the Unity page and the Deployments and Resources dashboards for the values in their scripts. The Basic data, Participants, Timeline and Lucid dashboards escape participant IDs, termination reasons and exported data, and graphic `Text`, `Image` and `Path` objects write their text, media ID and path string as JSON, so quotes, backslashes and `</script>` no longer break the page. The `create_and_rate` demo no longer shows raters another participant's description as raw HTML, and Lucid qualification questions that `verify_lucid_qualifications` re-asks show Lucid's question text as plain text, like their answer options.
- `LocalStorage` no longer links `static/assets` to the asset storage folder, and removes such a link left by an earlier version when the experiment launches. The link let anyone who knew an asset's SHA-256 digest (for example of a published stimulus file) download it from `/static/assets/objects/sha256/<digest>` without its access token; assets are now served only through `/asset/<access_token>`. Locally stored assets are also served with the content type of their extension (for example `image/png` for a `.png` asset) rather than `application/octet-stream`, and never with a `Content-Encoding` header, so a `.gz` file inside a folder asset now reaches the browser still compressed. Every file served from `/asset/<access_token>` also comes with `Content-Security-Policy: sandbox`, so an uploaded file cannot run as a page on the experiment's origin; PDF, audio and video files, which Chrome's built-in viewers would not display when sandboxed, and redirects (for example to S3) are left unchanged. Assets still work as `img`, `audio` and `video` sources.
- Choosing a disallowed answer on a Lucid screening question (`LucidScreeningQuestion` and its subclasses) terminates the participant and returns them to Lucid again; since PsyNet 13.2 the click raised a JavaScript error and did nothing. With another recruiter, for example in `psynet debug local`, the click logs an error to the experiment log instead. The ad and consent pages also no longer raise a JavaScript error after their mobile-phone check redirects to Lucid.
- The Lucid `/terminate_participant` route now terminates an existing participant only when the request carries that participant's `unique_id`. PsyNet sets a Lucid participant's worker ID to their RID, so their `unique_id` is `RID:RID`, and anyone who knows a respondent's RID can still terminate them; what protects the route is that Lucid generates the RID for each respondent. A bare `RID` still terminates a respondent who has no participant yet, as PsyNet's mobile-phone and browser checks on the ad and consent pages need; those pages now run the mobile-phone check before moving a Lucid respondent on, so a respondent on a phone is returned to Lucid before a participant is created. The route also refuses with a 403 error a request whose `assignmentId`, `RID` and `unique_id` name different respondents, refuses any request with a server error when several participants share the RID, returns a 404 error in experiments that don't recruit through Lucid, and returns a 400 error instead of a server error when the request names no respondent or its `unique_id` is not of the form `worker_id:RID`. PsyNet's timeline pages already send the `unique_id`.
- The module details and tooltips on the dashboard's Timeline tab now require a dashboard login. Previously anyone could read module details such as participant counts. The tab also works when the browser logged in with the password prompt that `psynet debug local` shows. Artifact storage also refuses deployment IDs and filenames that are not a single path component (such as `../x`), so dashboard requests can no longer read, write or move files outside a deployment's folder.
- Fixed a security hole in which any page could read and publish on a participant's timeline-hold channel, injecting markup into their waiting overlay, faking arrival notices, or reading their wake tokens. Hold wake-ups and arrival notices now go only to that participant's checked WebSocket connections, and the browser ignores anything else published on the channel. `Experiment.publish_to_participants` now raises `ValueError` for the message types PsyNet reserves for its own directed messages (currently `timeline_hold_wake`), so experiment code that forwards a participant's payload cannot forge a hold wake-up. The fix relies on the Dallinger version PsyNet pins, which admits a participant's WebSocket only with their token.
- A request whose `unique_id` query parameter names no participant no longer fails with a server error when PsyNet logs the request.
- The dashboard's Export button now downloads the export as `<deployment ID>__export.zip` (`Content-Type: application/zip`) instead of some browsers showing the zip as text. Artifact downloads from the dashboard are also sent as attachments.
- `psynet debug local` and `psynet test local` no longer crash at start-up on macOS when a process exits while PsyNet is looking for leftover Chrome or chromedriver processes.
- Fixed `MediaSliderControl` never playing or showing its media (audio, video, images or HTML) when the slider moved or on autoplay; it now uses the slider for its `modality`. This also fixes `MediaGibbsTrial`'s default slider and the `simple_multimedia_slider` demo.
- `psynet debug local` uses the dashboard login that Dallinger's `develop debug` puts in its launch job (Dallinger [#10292](https://github.com/Dallinger/Dallinger/pull/10292) and later). So the launch succeeds, and the printed login and the opened dashboard tab are right, even if another experiment's worker on the same Redis database runs the job.
- Fixed the RAM and CPU usage warnings: their worker list no longer crashes with a `psutil.ZombieProcess` traceback when a worker exits while it is being built (for example when stopping `psynet debug local` with Ctrl+C), and CPU warnings now report the CPU use that triggered them and each worker's measured CPU use, busiest first, instead of figures near 0%.
- Fixed the Resources dashboard's time-range slider, which stopped working when Dallinger moved its dashboard to jQuery 4. It is now a pair of native "From" and "To" range inputs, and the chart opens on about the last two hours.
- Consecutive `UnityPage`s that share a `session_id` now update in place under in-place navigation instead of reloading the whole document.
- PsyNet's page websocket channels, used by timeline holds and arrival updates, now stop reconnecting and log a console warning when the server refuses the connection (close code 1008, for example a wrong scope token), instead of retrying forever. Other close codes still reconnect.
- The stock experiment `.gitignore` now ignores `static/fonts/GoNotoKurrent-Bold.ttf`, the font `VocabTest` downloads to draw its word images, so it no longer shows up as an untracked file, and deploys, exports and the one-time `deploy.toml` migration check no longer warn about it. Deployments still include it, because `deploy.toml` chooses the deployed files. Run `psynet scripts update` to refresh an existing experiment's `.gitignore`. `VocabTest` now also raises an error when the font download fails, instead of saving the error page as the font; if word images look wrong, delete `static/fonts/GoNotoKurrent-Bold.ttf` so that it is downloaded again.
- Fixed group arrival notices undercounting when several members arrive at the same moment, for example "1/6 of your group are ready." when four were. The browser now fetches the notice after each arrival is saved, so `on_arrival_message` can be called several times per arrival and should depend only on its arguments.
- Fixed barriers with explicit `waiting_logic` never timing out a participant who closed the page while waiting: the server now applies `max_wait_time` (failing or kicking them, as `max_wait_action` says) shortly after the deadline, as it already did on the default waiting screen. `max_wait_time` is now a hard limit from arrival on `waiting_logic` pages too: it also applies to a participant who is partway through a filler page, not only between filler pages, so make it long enough to cover long filler pages (for example trials used as filler).
- Fixed a synchronized trial maker crashing with `AttributeError` (or giving a follower the wrong participant group or block order) when the group's leader had already moved on to another module, for example when a participant joined a group that was already playing. A participant removed from their sync group, for example kicked at a barrier, now skips a later synchronized trial maker for that group type (it ends before their first trial) instead of getting an error. Group members who have left, or not yet reached the trial maker, no longer have its block and plan bookkeeping written into another module's state.
- Fixed sync groups staying active after all their members had left. The periodic sync-group check (every few seconds) now closes groups that accept top-ups once they are empty, and any group whose members have all finished or returned the experiment. Closed groups show `active=False` and an `end_time` in exports and on the sync group dashboard.
- On windows narrower than 720 pixels, the waiting indicator no longer covers the first line of the page. It now uses the arrival notice's compact size and sits on the progress bar.
- On Python 3.11, trial-maker deprecation warnings now point at the experiment code that triggered them, as they already did on Python 3.12 and later.
- Fixed `while_loop` changing the elements passed to it: it scaled their time estimates in place, so resolving a barrier's waiting pages again (for example when estimating the experiment's duration) multiplied its progress estimate each time. Loops now scale copies, so several barriers can also share the same `waiting_logic`.
- Fixed `advance_past_wait_pages` occasionally leaving a bot on a stale waiting page when a barrier released it mid-check, which made its next `take_page()` resubmit the waiting page instead of answering the page it had moved on to. Bot status now reports `is_wait_page` and `barrier_id`.
- Fixed a bot's `current_page_text` reading "Not implemented" while it waited at a barrier without a waiting screen or on a `WaitPage`; it is now the waiting message.
- Fixed `Trial.cue` failing with `MultipleResultsFound` after several participants started their first cued trial of a module at the same time: they now share one node, and the module's cued trials share one network. The default node of a module's cued trials is now always a `GenericTrialNode`, never another node that happens to be in the module.
- A member who leaves the group of a synchronized trial maker, for example through `sync_group_max_wait_action="leave_group"`, before finishing any of its trials now skips the rest of that trial maker, including its introduction if they hadn't started and an end-of-trial-maker performance check that would have failed them on no trials. A member who leaves later gets no more trials, then the trial maker's `on_complete` and performance check run over the trials they did. Previously a member removed while waiting for their next trial was shown their previous trial again, or hit an error if they had no trial yet, and a member removed at the trial maker's start barrier was never initialized.
- Fixed `trial.participant` being `None` in the request that created the trial, so a trial with no pages, which ends in that request, crashed when it scored the answer or paid its performance reward.
- Fixed `GroupBarrier` arrivals costing one extra database statement per group member: an arrival now counts the group once when it updates every waiting member's hold message, so its cost no longer grows with group size.
- Fixed bot tests (`psynet test local`) executing `experiment.py` a second time partway through a test, for example when a timeline hold wake was sent from the test process, which registered duplicate SQLAlchemy classes and made later queries such as `Trial.query` raise `InvalidRequestError`. Tests that load the same experiment directory again in one pytest process now reuse the experiment module as well.
- Fixed a `GroupBarrier` on a group that accepts top-ups (`join_existing_groups=True`) sometimes releasing the group without a newcomer whose join committed while the barrier was checking. Every `GroupBarrier` now locks such a group while it decides, as `stop_top_ups=True` barriers already did, so a newcomer joins either before the check counts them or after the group has passed.
- Fixed participant requests, dashboard sync-group fail and kick actions, and locking participant lookups (such as `Experiment.get_participant_from_participant_id(..., for_update=True)` and `Barrier.get_waiting_participants(..., for_update=True)`) that waited for another request's lock on the participant (for example a barrier release) reading the participant's current trial as it was before that request committed, which could skip a results page or score a synchronized round as 0.
- `Trial.time_taken` and `Trial.response` now cover only the trial's own pages: `time_taken` sums the times of its accepted pages, and `response` is the response of its last page. Previously they also counted submissions rejected by validation, feedback pages, performance checks between trials, pages after a `Trial.cue` trial and a failed participant's remaining pages, and a page that reports no time (such as `UnityPage`) raised a `TypeError`.
- Dissolving a sync group, or marking it to be dissolved, no longer waits for its leader's other requests to finish.
- Fixed synchronized trial makers giving members of one group different participant groups or block orders: a newcomer promoted to leader chose new ones, and in a loop a member who looped faster than the others copied the previous run's. The group now stores each run's participant group, block order and current block in its new `trial_maker_runs` column (keyed by trial maker id, one entry per run); members, newcomers and a promoted leader copy the current run's, and in a loop the whole group starts each run together.
- `GroupBarrier(late_action="leave_group")` no longer removes a late member while their own request is in progress, for example while they submit a page; like `late_action="fail"`, it then acts on none of the group's late members until a check finds none of them busy, so equally late members are removed together as `"late"`. Both actions now also recheck lateness once the members' rows are locked, so a member who reaches the barrier or starts a timed page during the check is not removed as late. Code that runs in a late member's own request, such as a `CodeBlock` storing their answer, no longer needs a row lock to avoid racing the removal.
- Fixed `psynet test local` running an experiment's `experiment.py` a second time during the bot test, for example when a bot drops out, which made later queries of custom trial classes fail with SQLAlchemy `InvalidRequestError: ... is not a sub-mapper of ...`.
- `--use-local-psynet` now stops with an explanation when the command runs PsyNet from another checkout than the editable one it would build (for example a git worktree on `PYTHONPATH`), instead of silently deploying the editable checkout.

### Updated

- PsyNet now needs a Dallinger version with the `worker_processes` and `worker_greenlets_per_process` settings, which the performance test's worker advice reads, the `web_processes` setting, and `worker_startup_timeout`, which lets an async worker that hangs at start-up after a database reset exit so that Docker starts it again. `psynet debug local --legacy` passes its gunicorn process count as `web_processes` instead of the deprecated `threads`.
- Updated the vendored Bootstrap CSS and JavaScript from 5.3.3 to 5.3.8.
- Updated the Dallinger requirement to version 13.1.0 or above (see the [Dallinger 13.0.0](https://github.com/Dallinger/Dallinger/releases/tag/v13.0.0) and [13.1.0](https://github.com/Dallinger/Dallinger/releases/tag/v13.1.0) release notes). Dallinger 13.1 moves PostgreSQL from 12 to 18. New docker-ssh servers start on PostgreSQL 18; a server set up by Dallinger 13.0 or earlier stays on PostgreSQL 12 until `dallinger docker-ssh servers upgrade` moves it, which stops every classic app on the server during the copy. Read [Moving to PostgreSQL 18](https://dallinger.readthedocs.io/latest/docker_support.html#moving-to-postgresql-18) before you run it. On a server that runs PostgreSQL 18, no one may deploy with PsyNet 13 or earlier or with PsyNet 14.0.0rc1 to rc3, which use Dallinger 12 or earlier, nor run `servers upgrade` on it with Dallinger 13.0; any of these can take every classic app on the server offline. A Cloudflare-ingress app deployed with Dallinger 13.0 or earlier keeps PostgreSQL 12 when updated with `--update`; to move it, export it, destroy it and deploy it again with `--archive`. `POST /launch` now requires the dashboard login and refuses cross-site requests; `psynet debug local` and the deploy commands send the login for you, and `psynet debug local` launches its own experiment even when another experiment's worker on the same Redis database runs the launch job. `psynet deploy ssh` and `psynet debug ssh` leave naming an unpushed image to Dallinger, which names it after the app. Dallinger runs local servers with honcho rather than `heroku local`, adds real-time engine tables (`realtime_session`, `realtime_event`), which PsyNet now loads from database templates, and real-time runner processes, which PsyNet's local cleanup now stops along with web and worker processes, and ignores `lock_table_when_creating_participant`, which PsyNet no longer sets or documents. SSH launches with an app name that Dallinger reserves for the server, such as `logs` or `dallinger`, now stop before PsyNet prepares the experiment. Dallinger also adds `Experiment.check_recruiter_exit`, which lets an experiment refuse a `/recruiter-exit` request whose `unique_id` doesn't match the participant, moves to RQ 3 and Debian 13 Docker images, closes routes that trusted guessable participant ids, escapes JSON on the monitoring page, quotes worker ids in the dashboard's compensate commands, lets websocket clients stop reconnecting when the server refuses the connection, makes database resets check that Redis is reachable before dropping any tables, and makes `dallinger ec2` commands choose the right Route 53 hosted zone and wait for SSH after `ec2 start`.
- Updated the CI images to Docker 29 and PostgreSQL 18 on Debian trixie (from Docker 26.1.1 and PostgreSQL 16.2 on bookworm). Both now follow their releases within a major version.
- Updated dominate from 2.9.1 to 3.1 or later, and removed PsyNet's patch for dominate's Python 3.12 event-loop warning, which dominate 3.1 fixes itself. dominate 3.1 renders `a`, `span` and `sup` as inline elements, so it no longer starts a new line before them, and the space that used to appear before each of these tags is gone: `tags.p("Click", tags.a("here", href=url))` now shows "Clickhere" instead of "Click here", and `tags.span("A"), tags.span("B")` shows "AB" instead of "A B". Add the space explicitly where you want one, for example `tags.p("Click ", tags.a("here", href=url))` or `tags.span("A"), " ", tags.span("B")`. Attributes set to `0`, such as `value=0` or `tabindex=0`, are now rendered instead of being dropped.
- Updated the browsers in the CI test images. Chrome and ChromeDriver go from 149.0.7827.54 to 157.0.8103.78, so that the Selenium bot tests run on the Chrome version participants currently use. The Playwright browsers now come from the Ubuntu 24.04 (noble) variant of the Playwright 1.64.1 image instead of the Ubuntu 22.04 (jammy) one, whose standard support ends in April 2027.

### Documentation

- Removed Heroku deployment documentation.
- The documentation and the `simple_rating`, `similarity`, `step_tag`, `timed_push_buttons`, `simple_audio_rating`, `audio_similarity`, and `audio_stimulus_set_from_dir` demos now recommend keeping ready-made stimulus files in the experiment's `static/` folder and referring to them by URL (for example with `psynet.media.static_url_for`), rather than registering them as assets.
- The `rock_paper_scissors` demo now uses a single node played for three rounds instead of three colour-labelled nodes, and the `unity_autoplay` demo names its between-participant condition (`gain`) and explains that each node is one condition.
- Removed the nonexistent `max_unique_nodes_per_block` argument from the `StaticTrialMaker` docstring and the documentation, and corrected the `DenseTrialMaker` docstring to describe its `conditions` argument instead of a nonexistent `ConditionList` class.
- Added a Design section with concept pages on timelines, pages, trials, chains, stimuli and media, participants (screening, payment, leaving early and failure, and language) and group experiments (forming groups, barriers, dropouts and chatrooms). Each has a matching Code page drawn from tested demos, and together they replace the old tutorial chapters on these topics.
- Replaced Getting started with a single Install page, with a tab for each operating system and Docker for the database and cache, and a Quickstart that goes from an empty folder to a working experiment with a coding agent. The remote-server and first-Prolific-study walkthroughs moved to Deploy.
- Added a Test section on testing back-end logic (bots, simulated participants and practice data), testing front-end logic (browser layout checks), testing scalability (performance tests), and audits, including design simulation and power analysis, with the audit format reference alongside.
- Corrected stale code examples, commands and API names across the documentation, including PsyNet 10-era examples, pre-screening instructions, deployment configuration examples and the Hello world demo page.
- The documentation guide now explains how Design concept pages pair with Code pages and sets writing rules on direct tone, navigation and introductions.
- Reorganized the Code documentation by task into Starting a project, Timeline, Pages, Trials, Stimuli and media, Participants, Groups and Database, and revised every page: code examples now come from tested demos, wrong API names and commands are fixed, and maintainer and migration material moved to the developer and What's new pages. New pages cover payment, creating pre-screening tasks, running and debugging, using local PsyNet and Dallinger checkouts, exchanging data with the server, and hosting stimuli on S3, and the Git tutorial is replaced by a short page on how PsyNet uses Git. The ad page moved to the Deploy reference and SQLAlchemy profiling to Test. Old URLs redirect.
- Reorganized the documentation website into top-level About, Install, Quickstart, Design, Test, Deploy, Data, Code, Demos, Agent Skills and Reference sections, with What's new and Contributing under More. Design, Test, Deploy and Data explain concepts and commands; Code holds the experiment code, including the former tutorial and guide pages. Old page URLs redirect to their new locations, and each redirect page also links to the new page for tools that don't follow redirects. The site now uses the blue accent of PsyNet's participant pages, with one hover colour for every link, and no longer shows a copyright notice in the footer.
- Rewrote the Deploy documentation as "How deployment works", "Setting up a server", a single "Running a study" runbook, separate Prolific, CINT and Lab Recruiter guides, and reference pages that each cover a topic once (the AWS and physical server pages are merged into "Manual server setup"), with SSH examples that no longer assume a particular lab's server or registry. Lab-specific instructions appear in "In a lab" boxes, export instructions moved to the Data pages, a glossary was added to Design, and old Deploy page URLs redirect to their new locations.
- Rewrote the landing page to summarize what makes PsyNet distinctive. The About section now has a "What's PsyNet for?" gallery of experiment types, each with a carousel of demos and linked example publications; a "What's it like to use PsyNet?" page that follows one study from idea to data in seven illustrated steps; a "PsyNet's software stack" page that introduces Dallinger, Flask, PostgreSQL, Redis, Docker and the other tools PsyNet builds on; a "Research using PsyNet" page generated from a BibTeX file; and a "Citing PsyNet" page. The Overview page is removed.
- Split the Data documentation into pages on what an export contains, exporting data, analyzing data, basic data, and sharing data, with each topic described once.
- Testing back-end logic now shows how to make bots fail a prescreener and lists the arguments a `bot_response` function can take, and the API reference documents `ParticipantDriver`, the pass criterion of the built-in headphone tests, and when a performance check passes. Testing front-end logic explains how to install Playwright and how to wait for the next page after a click, the audit reference specifies the screenshot caption format, and API signatures no longer show paths from the machine that built the documentation.
- Documented how to build basic data for group experiments: which exported tables record sync groups and their members, how `trial.sync_group_id` and `trial.sync_group_round` identify a group's rounds, a one-row-per-participant-per-round `get_basic_data` example for the rock-paper-scissors demo, and a pandas example for joining group tables in an export. The `basic-data` and `basic-data-group-experiment` Agent Skills now point to this documentation.
- Added a "Real-time interaction" page on live WebSocket interaction between participants: how channel messages travel, `WebSocketElt` handlers, `PsyNetWebSocketChannel` in page modules, keeping the server as the authority on shared state, disconnects, and testing. The groups design page now describes real-time interaction.
- The API reference is now grouped like the Code section, and it covers commonly used helpers that were missing, including `get_logger`, `get_config`, `Bot`, `randomize`, `compile_nodes_from_directory`, the create-and-rate mixins, `WikiVocab`, `BibleVocab`, `MonitorInformation`, `expose_to_api`, artifact storage, the CINT (Lucid) qualification helpers, `Event`, `FailedValidation`, `ProgressDisplay`, `ProgressStage`, `VolumeCalibration`, `get_trial_maker`, the create-and-rate module, the payment methods shared by all recruiters, and the language questionnaire pages. "Exchanging data with the server" now explains `expose_to_api`.
- Added an Agent Skills section to the documentation that publishes every Agent Skill PsyNet ships with experiments, generated from the skill files at build time, with maintainer skills listed under Contributing. The documentation describes what PsyNet provides, and the skills describe recommended workflows; the Code and Test pages now document the PsyNet facts the `power-analysis` and `make-experiment-adaptive` skills rely on (page-maker re-runs, node and chain selection hooks, staircases, and the audit's design-simulation files).
- Replaced the per-demo pages and the Example experiments pages with a single Demos catalog that describes every demo in `demos/experiments`, `demos/features` and `demos/pipelines`, grouped by topic and linked to the matching Design and Code pages. The exercises are now at the end of the Code section, and running demos in a PsyNet source checkout is described in "Starting from a demo or an existing experiment".
- Tidied the remaining documentation sections. About no longer has a History page, and the separate Dependencies section is gone; how PsyNet uses Docker and Dallinger is now explained in "How deployment works". Reference now holds only configuration, the command line (with a command table and shell completion) and the API; the audit and troubleshooting pages moved to Test and Install. What's new lists the current major version first, with older versions and a changelog link below. The PsyNet 14 page now summarizes the release's changes to participant pages, setup, trials and groups, stimuli, deployment, recruitment and data export, with what to change in existing experiments. The PsyNet 14 upgrade checklist now also covers setup, deployment files, Prolific screen-out payments, participant failure, response processing, groups and barriers, assets and exports. Contributing groups its pages by task and describes a uv-based development setup. Old URLs redirect.
- Added a Consent page explaining that the built-in consent forms name the institutions they were written for and showing how to write your own; documented recipes for Playwright walks (passing built-in prescreeners, `force_incognito_mode` in headless Chromium, SurveyJS rating controls, action timeouts, keeping a background `psynet debug local` alive), the audit `checks` and blocker severity fields, and when to synthesize stimuli with `JSSynth` rather than as files.
- The payment page shows `wage_per_hour` and `currency` in `config.txt`, the form new experiments already use, and explains how Prolific lists a study's hourly rate from the base payment alone. The implement-experiment skill asks agents to set the Prolific listing from `psynet estimate`.
- Shortened the experiment `AGENTS.md` so it keeps only what agents need in every task: the entry-point skill, setup, the one-experiment-at-a-time rule and the documentation map. Database inspection moved to the "Running and debugging locally" page, and PsyNet contributor notes moved to the repository `AGENTS.md`.
- The SSH deployment guide now warns not to use idle hibernation for experiments that recruit throughout their lifetime, and explains that the app stays awake while `auto_recruit` is on or participants are still working.
- The `uv pip install psynet` commands in the docs now install the PsyNet version the docs were built from: the release itself for release docs, or the exact commit otherwise. The quickstart no longer needs its note about PsyNet 13 and earlier.
- Added a "Choose a PsyNet version" section that explains releases, release candidates and development versions, and how to install each; the quickstart and "Creating an experiment" pages link to it from their install commands.
- Documented `Experiment.test_check_bots` for checks that span all bots in an experiment test.
- Documented PsyNet's nightly ASV benchmark pipeline schedule, the `BENCHMARK_RESULTS_TOKEN` variable a fork needs to run it, how to keep it running when its owner changes, and why the nightly job can fail without a comparison.
- Updated the "Contributing a feature/bugfix" developer tutorial to match the current test layout, `changelog.d/` fragments, the merge request template, and merging from `master`.
- Excluded the GNU gettext home page from the documentation link check, because gnu.org rate-limits or drops automated requests.
- Updated the agent instructions so that Cloud Agents push Dallinger feature branches to `Dallinger/Dallinger` when their token allows it, falling back to the fork, because CI on PRs from a fork runs without the repository's secrets.
- The server setup guide now explains how to replace a DSA `server_pem`: check the key with `ssh-keygen -l -f`, install a new public key through a login that already works, and point `server_pem` at the new private key.
- Rewrote the guide to testing scalability for the new `psynet performance-test`: running a test, controlling the load, reading the results, finding the server's capacity, sizing async workers, database size and resets over SSH, and every field of the `--json-output` file. It also documents that response times exclude time spent waiting for a free web worker, and how many participants can wait on waiting pages at once, which the bots don't measure, and that an `async_post_trial` job that participants wait for in a way PsyNet can't detect, such as a custom `wait_while`, needs `async_post_trial_priority = "high"` for the test to judge its queue wait. "Setting up a server" adds guidance on choosing a server size, with a measured example and a rule of thumb of 20 to 30 participants per vCPU. The implement-experiment agent skill suggests running the capacity search on an abridged version of a long experiment, then testing the full experiment at the recommended number of participants.
- Documented that `bot_response=None` makes bots answer `None` while leaving `bot_response` unset keeps the default bot answer, and that the `bot_response` argument of pages and controls also accepts a function.
- The performance-test guide and the summary's note on wait timeouts explain that, in a group experiment, a bot count that isn't a multiple of the group size leaves bots waiting at the grouper, and how to avoid it.
- The release guide now says that `master` carries the upcoming major's alpha version (for example `14.0.0a0`) while breaking changes are pending, before the major release branch is cut.
- The synchronization guide explains how to choose `max_wait_time` for the recruitment rate so the grouper fails few participants, and "Setting up a server" gives measured capacities for experiments whose participants wait for each other at barriers.
- The quickstart now gives the real experiment folder-name rule: the name must not clash with an existing Python module such as `code`, and lowercase letters, digits and underscores are safest because the name also becomes the Docker image name.
- Rewrote the README as a short pointer to the documentation, with a summary of what PsyNet is for and the commands to create and run a first experiment.
- Updated the SSH deployment docs and the deployment skills for Dallinger's `dallinger docker-ssh servers upgrade`: deployments only add their own Caddy route, `servers add` and `dallinger ec2 provision` set up the shared Caddy, Postgres and Dozzle services and leave their files read-only, and the log viewer has its own password at `https://logs.<server>`. A new section explains how to upgrade an existing server once and why everyone who deploys to it must update Dallinger. The docs also say that server commands read a real `contact_email_on_error` only from `~/.dallingerconfig` or the environment, what `dallinger ec2 provision` checks before booting an instance, which app names and addresses a deployment refuses, which commands accept the `dlgr-…` names of apps deployed by older PsyNet versions, and that `dallinger ec2 stop`, `start` and `teardown` no longer need `--dns-host` on the computer that ran `dallinger ec2 provision --dns-host`. The troubleshooting page covers the new setup, contact-email and `PermissionError` messages.
- Corrected the PsyNet 14 documentation: Python 3.14 is the recommended version, `psynet setup` runs in an already-activated `.venv`, the default theme is light, the upgrade guide covers the removal of Google Translate, the new `gpt-6-luna` translation default and SurveyJS loading only on pages that use it, server-size advice reflects the database pool in the pinned Dallinger, `experimenter_name` defaults to the current user, Heroku commands no longer appear beside the SSH ones in the docs and experiment Agent Skills, the command-line reference lists the translation, Lucid, app-management, asset-cache and `test ssh` commands, and the README links to the stable documentation.
- `AGENTS.md` now says that behavior that never reached a final PsyNet release, such as behavior only on `master`, needs no backward-compatibility code.
- Added a `branch-review-loop` agent skill that repeats `/branch-review`, preferably alternating reviewer model families, until two consecutive reviews find no high or medium issues.
- The AWS automatic provisioning page now says that `dashboard_user` and `dashboard_password` are checked before the instance boots.
- `AGENTS.md` and `/branch-review` now ask agents to record small follow-ups worth doing later, such as Known limitations items, as GitLab issues linked from the merge request.
- Added a "Writing a round-based experiment" page that builds the `ultimatum_pairing` demo step by step, with screenshots: forming cohorts, pairing players each round with roles, timed decisions, moving slow players on, scoring, sitting out and ending the game. The synchronization guide, now titled "Groups and barriers in detail", summarizes `Regrouper` and links to it and lists the default maximum waiting times, and the groups design page walks through the group demos without code, from one group for the whole experiment to cohorts that regroup each round, with a block diagram of each demo, explains what happens to a group when a member is failed or leaves and when to use a trial maker or a loop of rounds, and explains with screenshots how group members see each other by pseudonym or anonymously. "Writing a timeline" explains how page time limits and barriers' `late_after` work together.
- The group design page lists the main kinds of group experiment, with the demo to start from for each.
- Documented how to build one row per player per round for games that re-pair players with a `Regrouper`, in "Games with a regrouper" under basic data, with a `get_basic_data` example in the `ultimatum_pairing` demo. Also documented that a `PageMaker` builds its page again on submit, when the participant may have left their group.
- Documented one cued trial per player per round as the way to write round-based group games, across the group design, synchronization, basic data and analysis pages and the multiplayer skills. The analysis example now matches a player's trials to their partner's by the `sync_group_id` and `sync_group_round` the trials record, which also works when players are regrouped.
- The agent instructions now say that several `psynet test local` runs can go at once, and that runs in the same experiment directory wait for each other, so agents don't queue tests behind their own locks. Rerun `psynet scripts update` to refresh an experiment's copy.
- Moved the rules for rounds of cued trials (when a cue joins a round, whom a `GroupBarrier` waits for, `sync_group_round` versus `position`, `round=` in a fixed group's loop, and several trial classes in one round) from the round-based tutorial into a new "Rounds of cued trials" section of "Groups and barriers in detail", and made the tutorial follow the `ultimatum_pairing` demo more closely.
- The `rock_paper_scissors` demo now plays its three rounds as cued trials, `Trial.cue(round=i)` in a `for_loop`, like the other round-based games, instead of a static trial maker with a single repeated node. The barrier that ends each round saves on each player's trial the action they played, their partner's action, the result and the points, and the basic data has one `player_round` row per player per round, with `pair_id` and the trial's `sync_group_outcome`.
- Clarified in the multiplayer docs that groups accept top-ups until they are stopped explicitly, with `group.stop_top_ups()`, `GroupBarrier(stop_top_ups=True)`, `Regrouper(stop_top_ups_after_rounds=n)` or the grouper's `top_up_wait`, and that a `join_criterion` only turns newcomers away.
- Documented that a recording made on a feedback page is stored with the trial that just finished, even though that page's response has no `trial_id`.
- Added "Late, slow and leaving players: case studies", which follows group designs (a fixed pair, members who leave, a slow reader between runs, an odd player out, a barrier's maximum wait running out and a group dissolving mid-round) and says what each player sees, whom they wait for and when they move on, each checked by a test.
- "Synchronization" and the case studies of late, slow and leaving players now show how to score the round of a group that dissolved with `below_quorum="continue_without_group"`: no callback runs when a group dissolves, so when a trial's `sync_group_outcome` is `"group_dissolved"`, `show_feedback`, an export or `on_finalized` computes the result from every stored `answer` in `trial.group_round.trials`, with `accumulate_answers = True` when `show_trial` has pages after the barrier.
- Added "Failure cases" to the multiplayer synchronization docs and the `synchronous-experiments` skill: one table of the ways a group game can go wrong for a player (running out of time, being removed as late, waiting too long, the group dissolving, leaving the study, removal from the dashboard, no group forming and sitting a round out), with the value code checks for each, the setting behind it and how to simulate it in a bot test, followed by how to tell the player and the others what happened. The demos map the reasons they can meet to their own text.
- The scalability docs now say that the database-growth warning also needs a table to grow by at least 10,000 rows, and that destroying a performance-test app without a terminal needs `--remove-data --yes` (or `--keep-data --yes`).

## [14.0.0rc3](https://gitlab.com/PsyNetDev/PsyNet/-/tags/v14.0.0rc3) Release candidate - 2026-09-30

### Fixed

- Fixed Lucid participants who close the tab staying `working` indefinitely. The recruiter clock now terminates them one minute after `termination_time_in_s` has passed, so a paused survey can complete on its own.
- Fixed Lucid elapsed-time checks that wrapped around every 24 hours. A participant who reloaded a page a day or more after entering got a fresh time limit, and the Lucid dashboard's time since the last API call and the rate-limit cache check were wrong after a day.

## [14.0.0rc2](https://gitlab.com/PsyNetDev/PsyNet/-/tags/v14.0.0rc2) Release candidate - 2026-09-29

### Changed

- Changed Lucid recruitment to stop new entrants as soon as finished plus working participants cover the target, by lowering the survey's total quota while it stays live. The survey is set to complete once nobody is still working, and entry reopens if a working participant drops out. Experiments no longer need to close the Lucid survey themselves.

### Fixed

- Fixed the Lucid deployment test closing its survey while participants were still working, which made Lucid record their completes as Survey Closed.
- Fixed Lucid submissions not sending PsyNet's server-side complete or terminate call, so Lucid only recorded a complete when the participant's browser made it back to the panel.
- Fixed Prolific participants who leave early seeing an error page instead of the "Your submission has been sent to Prolific" confirmation when the page reloads after Submit.
- Fixed the wrong-browser and mobile-device warnings, which crashed before they appeared, so participants were neither warned nor, on Lucid, sent back to the panel.
- Fixed cached function assets leaving their temporary file open until garbage collection, which Python 3.14 reports as an error.

## [14.0.0rc1](https://gitlab.com/PsyNetDev/PsyNet/-/tags/v14.0.0rc1) Release candidate - 2026-09-23

### Breaking Changes

- ``JsPsychPage`` no longer accepts HTML/Jinja timeline templates; pass a JavaScript module exporting ``buildTimeline()`` instead. See ``docs/whats_new/upgrading_to_psynet_14.rst``.
- Replaced Git and `.dockerignore` deployment file selection with explicit
  `deploy.toml` policies as a breaking PsyNet cutover. PsyNet scaffolds
  `deploy.toml` (and creates it automatically when missing without overwriting
  an existing file). When an existing experiment's `.gitignore` ignores files
  that the new policy does not exclude, the next debug, test, or deploy stops once
  and lists them; otherwise the switch is silent. Git-ignored files are deployed
  unless `deploy.toml` excludes them. Leftover generated `.dockerignore` files are removed on
  debug, deploy, scaffold, and prune; custom copies are preserved by scaffold
  commands but must be migrated to `deploy.toml` and removed before debug or
  deployment.
  The generated experiment `docker/` helper scripts are no longer scaffolded
  and recognized generated copies are deleted by `psynet scripts update` and on
  debug/deploy; customized helpers and `docker/` symlinks are preserved.
  `psynet setup --docker` is removed; use `psynet setup` then
  `psynet debug local --docker`. Membership no longer depends on Git visibility,
  while Git remains required to identify the source commit and dirty state.
  Experiments ignored by a containing repository must run `psynet setup` to
  create a dedicated repository. The package-size check now measures the
  deployment plan. Deprecated source-export compatibility options emit warnings
  when used.
  Stock excludes include virtualenv directories (`env`, `.venv`). Heroku
  deploys no longer ask authors to remove `.deploy` from `.gitignore`.
  This requires Dallinger with `deploy.toml` (12.4.0 or later), Python 3.11 or later, and a POSIX filesystem.
- Made in-place timeline transitions the default. Custom pages that still use complete templates or other SPA-incompatible patterns now raise errors unless ``inplace_timeline_transitions = false`` is set or the page is migrated; see ``docs/whats_new/upgrading_to_psynet_14.rst``.
- Bundled demos now track authored experiment files only. Generated scaffold files and per-demo `constraints.txt` are omitted; use the shared PsyNet development environment in-repo, or run `psynet setup` after copying a demo into a standalone experiment.
- Breaking: ``pip install psynet`` now installs only a small bootstrap CLI. Run ``psynet setup`` in your experiment (or ``pip install -e '.[dev]'`` from a PsyNet source checkout) to get the full runtime.
- Prolific studies now pay unsuccessful (failed or errored) participants via a fixed screen-out completion code by default (`prolific_pay_unsuccessful = true`). PsyNet registers an `UNSUCCESSFUL` completion code with Prolific's `FIXED_SCREEN_OUT_PAYMENT` action; those participants submit normally, receive a fixed payment from Prolific (`prolific_unsuccessful_base_payment`, defaulting to 0.25), and are topped up to their accumulated reward with a bonus (controlled by `prolific_unsuccessful_topup`). The Prolific error page offers a submit button for this flow instead of asking participants to message the experimenter. Deployments must set `prolific_screen_out_slots` explicitly (it caps worst-case automatic screen-out spend); otherwise deployment fails with an explanatory error. Set `prolific_pay_unsuccessful = false` to restore the previous return-for-bonus behavior — also the remedy when a Prolific workspace rejects the screen-out completion code at study creation (PsyNet logs a hint alongside the error).

  Prolific-specific experiment logic now lives on the Prolific recruiter. `Experiment.error_page_content__prolific`, `Experiment.error_page_content`, and recruiter `error_page_content` have been removed; override `error_page_presentation` on a custom recruiter instead (stale experiment overrides fail a pre-deployment check, while stale recruiter overrides fail when used, both with migration instructions). Recruiter timeline hooks were renamed: `approve_assignment` to `submit_assignment` and (Prolific) `reject_assignment` to `request_return_for_bonus`. Custom recruiters overriding the old names must be updated. Screen-out participants have their recorded base payment corrected to the fixed screen-out reward and are labeled `screened_out` rather than `approved`. `Experiment.error_page` has also dropped its unused `error_type` and `request_data` arguments; callers that passed them should simply omit them.
- Overriding `Experiment.fail_participant` now raises `RuntimeError` at class definition. Call `Participant.fail()` or register a `ParticipantFailRoutine`. Dallinger's `data_check_failed` and `attention_check_failed` log a warning and no longer fail the participant or their nodes. `TrialMaker` and `NetworkTrialMaker` constructors now take keyword-only arguments, matching chain, static, dense, and graph trial makers.
- Required `SyncGroup.add_participant()` and `SyncGroup.remove_participant()` for membership changes; `SyncGroup.participants` is now read-only and reports only active members.
- Replaced trial assignment hooks ``find_networks``, ``find_node``, and
  ``prioritize_networks`` with paradigm-specific APIs. Chain trial makers use
  ``find_chains``, ``select_chain``, and ``custom_chain_filter``; static trial
  makers use ``find_nodes``, ``select_node``, and ``custom_node_filter``.
  Selection hooks receive a nonempty eligible list and may return the selected
  value or ``Selection(value, context)``. Returning ``None`` from
  ``select_chain`` or ``select_node`` raises ``TypeError``. ``find_chains`` and
  ``find_nodes`` must return a list, ``"wait"``, or ``"exit"``; ``None`` raises
  ``TypeError``. The selected object must be one of the supplied eligible values
  (object identity); a re-queried copy with the same id raises ``ValueError``. ``get_trial_class``
  must return a trial class for every eligible selection; synchronized followers
  reuse their leader's concrete trial class without calling this hook again.
  PsyNet raises an actionable ``TypeError`` at construction when a removed or
  wrong-paradigm hook is overridden. ``CreateAndRateTrialMakerMixin`` no longer
  provides ``get_non_failed_creations``; classify nodes with
  ``get_creation_phases`` and load finalized creations with
  ``get_finished_creations``. Heads that still have unfinalized creator
  trials wait or exit instead of raising. ``Trial.position`` is now a stored,
  zero-based creation sequence shared across all trial classes in a participant's
  trial maker, rather than a live index within each concrete trial class.
- Moved audit evidence collection to ``psynet audit simulate`` and
  ``psynet audit performance-test``. Top-level ``psynet simulate`` is removed;
  use ``psynet audit simulate``. These commands require an initialized
  audit packet, write canonical evidence paths, and update ``audit.json``.
  The audit performance-test command runs locally; remote SSH collection is
  not part of this command. Top-level ``psynet performance-test`` remains
  available for measurement-only runs and no longer accepts ``--audit``.
  Simulated exports now exist only at
  ``audit/simulate/analysis/simulated_export/``. A failed rerun leaves the
  previous export in place. Directory artifacts are limited to
  ``simulate_export``; other present artifacts must be files. Extra files beside
  ``analysis.ipynb`` appear in the Analysis panel.
- Data exports no longer include empty table CSVs. An experiment that never used
  chat, Lucid, or barriers therefore no longer has header-only files such as
  `chat_message.csv` in `database/`. `manifest.json` still lists every table under
  `table_row_counts`, with a count of `0` for the omitted files, and `psynet load`
  and `--archive` skip tables whose CSV is absent. Analysis code that loops over
  table names and reads `database/<table>.csv` unconditionally should consult
  `table_row_counts` first, or tolerate a missing file.
- Experiments now allow phones and tablets by default (`allow_mobile_devices = True`). Set it to `false` to keep a study desktop-only.
- Radio buttons and checkboxes now render each option as a full-width row (`label.psynet-option` wrapping the input and a `span.psynet-option-label`) so that the whole row is clickable and meets the recommended 46px minimum touch target. Experiments that styled these controls by targeting bare `label` or `input` elements, or that relied on `PushButtonControl`'s previous default `style` of `"min-width: 100px; margin: 10px"`, should target the new classes instead. The bundled Inter font is also now actually applied; previously it was downloaded but never loaded as a stylesheet, so participants saw a system font.
- Reward display now follows the recruiter unless the experiment says otherwise. Leaving `show_reward` unset means the recruiter decides: Prolific and the lab recruiters show the participant's reward, while generic and local recruitment does not, because PsyNet cannot pay anyone in those cases and quoting a figure promises something the experimenter has to honour by hand. Set `show_reward = true` in `config.txt` to show it anyway. Lucid recruitment now defaults to hiding rewards instead of refusing to launch until you set `show_reward = false`, and `Experiment.show_reward` is the single place the decision is made, read by the footer, the progress endpoint, and the end-of-experiment page.
- Replaced the text on the page shown while a participant's assignment is submitted with a spinner. It used to say "Communicating with the recruiter...", which exposed PsyNet's internal term for the recruitment platform, and the page is normally over within a quarter of a second, too brief to read. `ExecuteFrontEndJS` now renders an accent-coloured spinner with a screen-reader label instead of prose, and no longer takes a `message` argument.
- Standardised early-leave vocabulary on ``early_exit`` across the public API, configuration, DOM, routes, and database columns. Experiments must migrate to ``show_early_exit_button``, ``min_reward_for_paid_early_exit``, ``#early-exit-button``, ``Participant.early_exited``, and ``/execute_early_exit_plan/``; the deprecated ``Page.show_abort_button`` and ``Page.show_termination_button`` aliases remain temporarily available. Participant-facing labels use **Leave**, and the removed ad-page abort popup is replaced by the timeline and error-recovery flow. The unused ``Experiment.ad_requirements`` and ``Experiment.ad_payment_information`` properties are removed; customize ``templates/ad.html`` instead.
- Removed MTurk recruitment support ahead of the platform's permanent closure on September 30, 2026. Experiments configured with the MTurk recruiter now stop with a migration error instead of falling back to Dallinger's transitive integration.
- Experiments configured with Dallinger's ``bots`` or ``multi`` recruiters, including subclasses of those classes, now stop with a clear error; PsyNet's internal bot-based test commands remain supported.
- Custom ``Barrier`` subclasses must use ``check_waiting_participants()`` and ``choose_who_to_release()`` instead of overriding ``check()`` or querying waiting participants directly. Barrier instances persist versioned declarative specifications instead of complete Python objects; custom release state must use JSON-compatible values, supported callables, importable classes, or persisted ORM references, and nested or otherwise non-importable classes are rejected when the Timeline is constructed. Waiting pages and hold-page construction stay on the live timeline object; scalar fields such as ``content`` and ``max_wait_time`` are restored on reconstructed ``barrier`` objects so release callbacks may still read them. ``Markup`` ``content`` round-trips instead of being saved as a plain string. ``Barrier.get_waiting_participants()`` now takes a participant as the first argument instead of ``for_update`` (pass ``for_update`` as a keyword). Grouped barriers require a participant or the visit link; ungrouped groupers can still list the active pool without a participant. ``Barrier.get_waiting_participants_from_barrier_id`` was removed. ``SimpleGrouper`` auto-ids now include the initial group size (``{group_type}_grouper_{size}``); pass ``id_`` when two groupers should share a pool. Sequential groupers that share an ID must have the same release behavior. The trial-maker ``GroupBarrier`` id for trial preparation is namespaced with the trial-maker id (``{id}__prepare_trial``), so two trial makers in one timeline no longer share a waiting pool.
- Timeline requests now commit state changes before rendering in a read-only transaction; experiments that write from ``render()`` or templates must move those changes to ``pre_render()``. Custom overrides of ``Experiment.process_response`` must return ``ResponseResult`` (imported with ``from psynet.experiment import ResponseResult``) and should accept ``**kwargs`` or the keyword-only ``timeline_hold_resume`` flag. ``Experiment.response_approved`` has been removed; customize approved responses via ``process_response`` / ``ResponseResult`` or the page-rendering hooks. Overrides of ``render_partial_timeline_payload`` must move to the structured result or page-rendering hooks. Same-session response metadata is serialized after page preparation.

### Added

- Added `fail_participants_below_min_size` parameters to groupers, allowing experiments to release participants to continue the experiment when a group drops below `min_group_size` instead of failing them by default.
- Added synchronous group timeout controls to `GroupBarrier` and synchronized trial makers, allowing experiments to kick or fail group members who wait too long at a barrier or fall behind after their group passed a previous barrier. The between-barrier timeout counts from the group's last barrier pass, or from when the member joined the group if that is later, so it also applies at a group's first barrier. With `timeout_between_barriers_time` set, `GroupBarrier`'s `max_wait_time` defaults to 20 seconds plus that timeout (`None` still means no limit), and trial makers' `sync_group_max_wait_time` defaults to the longer of 45 seconds and 20 seconds plus the timeout. A value passed explicitly that isn't longer than the timeout raises an error (unless it is a function), so members who arrive promptly are not timed out while they wait for slower ones.
- Added an authenticated synchronous group dashboard showing active and recent groups, grouper wait progress, participant statuses, barrier waits, and manual controls for kicking or failing active group participants.
- Added a second deployment-test experiment at `tests/deployment/audio_gibbs` (an audio Gibbs sampler exercising audio synthesis, assets, async workers, and the approved cultural-foundation consent). It defaults to HotAir, while a full deployment test runs its Prolific and Lucid variants alongside the payment-flow test.
- Added support for Python 3.11 through 3.14, with Python 3.14 recommended.
- Added ``get_js_vars()`` so modular page components can contribute page-scoped JavaScript variables, merged into ``psynet.var`` for the active page.
- Added ``psynet setup``, ``psynet scripts`` (``scaffold``/``update``/``prune``), and ``psynet generate-constraints`` for standalone experiments.
- Added an ASV benchmark for the static_big experiment's launch time.
- Added ``js_dependencies`` for document-level libraries, ``js_page_code`` for short inline activation bodies, and ``js_page_modules`` for reusable lifecycle-managed page behavior.
- Added namespaced package-owned static resources for built-in and third-party components through the ``psynet.static`` entry-point group, including the chatroom widget.
- Added an ASV benchmark for debug launch with representative static-file payloads, recorded on `master` as the fastest of three launches per profile.
- Added ASV coverage for canonical local database and asset export performance.
- Added ``get_css_links()`` so modular page components can contribute stylesheet URLs, matching ``css_links`` on pages.
- Added a soft size warning for the local asset export cache (50 GiB by default, overridable via ``PSYNET_ASSET_CACHE_SOFT_LIMIT_BYTES``); exports never fail or prune because of the limit.
- Added a persistent local asset cache (``~/psynet-data/cache/assets``) that
  stores read-only content-addressed objects between export runs; subsequent
  exports hardlink cached objects into the export directory instead of
  re-fetching from storage, writable cache entries are reverified before reuse,
  and new ``psynet assets cache info/list/prune`` commands allow inspection and
  manual pruning of the cache.
- Added a deployment-time warning when a value set in `Experiment.config` is overridden by a higher-priority configuration source such as an environment variable.
- Added a ``requires_full_page_reload`` constructor argument on ``Page`` so authors can opt a single page into full browser reloads without disabling in-place transitions experiment-wide.
- Added ``psynet services check``/``ensure`` for local PostgreSQL/Redis. Setup checks softly; ``debug``/``deploy``/``test`` require services before launch or packaging.
- Added a scheduled finalize backstop that recovers trials whose event-driven finalize check was missed, with a partial index and SQL prefilters so the poller stays cheap in steady state. Finalization requires successful async post-trial when async was requested; a failed async post-trial fails the trial and does not finalize. Fixed Asset parent typing so custom Trial subclasses correctly set ``trial_id`` for deposit-pending SQL checks.
- Added ``psynet audit`` (package ``psynet.audit``, Click group on the core
  ``psynet`` CLI) to package and render portable experiment readiness audit
  bundles without depending on the PsyNetSkills workshop repo.
- Added audit profile/extensions hooks. The starter packet includes an optional plan section for agent-led audits.
- Added PsyNet-owned Agent Skills for experiment development. They are available
  to PsyNet contributors under ``.cursor/skills/experiment/`` and
  ``psynet scripts update`` installs the managed bundle into experiment
  repositories under ``.cursor/skills/psynet/`` while preserving user skills.
  ``psynet scripts scaffold`` installs the bundle when it is missing.
- Added a ``docs:build`` CI job that builds Sphinx docs on MRs without Pages deploy.
- Added a `psynet dev docs linkcheck` command that wraps Sphinx's ``linkcheck`` builder and reports broken documentation links grouped by failure category.
- Added ``psynet audit serve`` to preview a rendered experiment audit site over
  HTTP (optional ``--render``), without creating a public tunnel.
- Rendered ``experiment.py`` (or the configured ``experiment.entry_point``)
  from the experiment directory (the parent of ``audit/``) in a dedicated
  Experiment code audit section.
- Added ``Selection`` and ``NetworkTrialMaker.on_trial_created`` so adaptive
  experiments can record why a node or chain was assigned. Static ``select_node``
  and chain ``select_chain`` hooks may return their selected value directly or
  wrap it in ``Selection`` when request-local decision context must reach
  ``on_trial_created``. The hook runs once per primary policy choice, after the
  trial is fully prepared and excluding repeat trials and synchronized follower
  copies.
- Added ``CreateAndRateTrialMakerMixin.get_participant_role`` so experiments can
  keep participants in creator or rater roles while the mixin consistently
  filters eligible chains and validates the final trial class.
- Added interactive Plotly figures to rendered audit notebooks. Plotly MIME
  outputs render with a vendored Plotly.js runtime, so audit sites remain
  self-contained and work offline. The runtime is copied into a rendered site
  only when that audit actually contains a figure.
- Added an optional Design simulation section to experiment audits. Its
  ``simulate/design/simulation.ipynb`` contains a Power analysis section and may
  also contain an Adaptive procedure section. The run record and results live
  beside it. ``psynet audit init`` declares ``simulation_notebook``,
  ``simulation_run``, and ``simulation_results`` as optional artifacts.
- Added offline MathJax rendering for inline and display equations in experiment
  audit Markdown and notebooks. The runtime is copied into a rendered site only
  when that audit could contain an equation.
- Added transactional `on_trial_created` callbacks to `Trial.cue`.
- Added ``demos/features/trial_cue_adaptive``, a participant-level 1-up/1-down
  staircase that uses ``Trial.cue``, ``while_loop``, and a decision table.
- Before transferring anything, `psynet export` now asks the deployment to
  identify itself and compares it with your experiment directory. Running the
  command from the wrong folder stops the export instead of overwriting your
  export directory with another experiment's data. A differing Git commit, or
  uncommitted changes on either side, produces a warning and a confirmation
  prompt; pass `--allow-project-mismatch` to proceed in a non-interactive shell.
  Exports also declare an `export_format_version` in `manifest.json`, and PsyNet
  refuses an archive it cannot read rather than downloading it first.
- Downloaded exports are checked against the identity recorded during preflight
  before publication, so replacing a deployment during transfer cannot publish
  the wrong archive. Missing manifest identity fields count as a mismatch when
  preflight supplied them.
- Added an `expect_scrolling` page attribute. It declares whether a page is expected to be taller than the browser window. A page that does not set it should fit without scrolling at a typical laptop viewport (1280×720). Experiment Playwright tests check this with `psynetLayout.check()`. Long pages such as consent forms set it to `True`; the bundled consent pages already do. Passing `expect_scrolling=False` to the constructor overrides a class-level `True`. It does not change how the page behaves for participants.
- Added `psynetLayout.check()` on every participant page so experiment Playwright tests can assert layout without copying PsyNet's test helpers. Pages that do not set `expect_scrolling=True` must fit the viewport; long pages that declare it may scroll as long as nothing is trapped behind the footer.
- Added a CI job that fails on Sphinx documentation warnings and broken links, using ``psynet dev docs make --strict`` then ``psynet dev docs linkcheck``.
- Added a short Prolific deployment test for sequential automatic recruitment.
- Added ``timeline_lock_timeout_seconds`` (default 5) to bound participant-facing database lock waits. Contended ``POST /response`` and JSON ``/timeline`` requests return a translated HTTP 503 busy response instead of stalling; automated participants retry a structured busy 503 once. A hold-resume that is still busy after that retry schedules one delayed queued wake instead of waiting for the hold timeout.
- Group barriers now show a pill on the progress bar when a partner is already waiting (``Your partner is ready.``, or ``{ARRIVED}/{TOTAL} of your group are ready.``). Waiting participants in groups of three or more see remaining-not-ready copy on the hold overlay (``{REMAINING} of {TOTAL} not ready yet``); pairs keep the hold title only. Longer notice copy ellipsizes instead of wrapping over the prompt. Set ``notify_arrivals=False`` to disable notices, pass ``on_arrival_message`` to customize the notice copy, or return ``hold_message(title, progress)`` from a ``content`` function to write the overlay's progress line. Pages omit the arrival-update websocket unless the participant is in an active sync group or has a removal notice to show. Notices catch up when that websocket opens after a partner is already waiting, and unreconstructable barrier specs skip notice rendering instead of returning HTTP 500.
- ``ParticipantDriver.refresh_status()`` reloads a bot driver's cached page from the server. ``advance_past_wait_pages()`` uses it after each wait so drivers see the live timeline page. Automated drivers retry a rejected submit once when last-arrival has already rotated the cached page uuid, POST hold-resume, pause on still-waiting overlays, and retry busy 503s plus JSON 409 stale timeline GETs.
- ``POST /response`` and ``GET /timeline`` report Server-Timing so hold-resume queueing can be distinguished from handler time. ``GET /timeline`` splits lock, page, barriers, and render. Phases that never ran are omitted rather than reported as zero.

### Changed

- `psynet translate` now only sends texts that do not have a translation yet, so existing translations (including fuzzy ones) are no longer rewritten when another text in the same file changes. Requests hold at most 30 texts, and ChatGPT also receives each text's context label, existing translations from the same file, the lines around each text in large source files, and the script to write in (from CLDR, e.g. Ol Chiki for Santali, except Arabic for Kurdish and Latin for Serbian to match PsyNet's catalogs). ChatGPT is also told to translate button labels and to match them wherever a text refers to one. ChatGPT replies use structured output, so a reply can no longer return the wrong number of translations. Replies that drop a variable such as `{NAME}` are retried, and ChatGPT retries use a higher temperature and a bounded reply length, so a reply stuck repeating itself fails fast and is not repeated verbatim. To get a fresh machine translation for a text, delete its translation and rerun `psynet translate`.
- Simplified slow ASV benchmark metrics to focus on median request time and median async queue delay.
- Renamed `tests/manual_recruiter_testing` to `tests/deployment`; the basic Prolific test (previously `prolific`) is now `tests/deployment/payment_flows_prolific` and defaults to HotAir, with the paid setup (including the approved cultural-foundation consent) in an `experiment.py.prolific` variant.
- Changed barrier processing so `Barrier.check()` replaces `Barrier.process_potential_releases()` and `GroupBarrier.check_waiting_participants()` handles group-specific waiting-participant checks before release decisions.
- Simplified local-server startup to take an explicit command with no automatic legacy fallback.
- ``JsPsychPage`` and ``UnityPage`` now take a full document reload when entering or leaving their runtimes, and reload transitions skip unused timeline fragments.
- In-repo demos/tests auto-prepare missing scaffold for local debug/test; pytest removes only files it added.
- Batched completed-trial counting in ``ChainTrialMaker.n_trials_still_required``
  via ``count_completed_trials_for_networks``, avoiding one query per network when
  evaluating the ``n_trials`` recruit criterion.
- Changed database export to one PostgreSQL repeatable-read snapshot with
  identifier separation. All table CSVs and identifier sidecars are read through
  the same database transaction.

  ``export.zip`` contains physical table CSVs under ``database/`` with
  pseudonymous participant identifiers. Original recruiter identifiers are written
  to ``participant_identifiers.csv`` (and ``lucid_entrant_identifiers.csv`` for
  Lucid). The ``--anonymize`` flag and class-based ORM CSV export have been
  removed. Analysis helpers ``load_export_table``, ``unpack_json_column``, and
  ``merge_participant_identifiers`` are provided under ``psynet.export``. The
  ``extra_var`` registry and implicit VarStore flattening have been removed;
  ``claim_var`` no longer accepts ``extra_vars``. Runtime properties created with
  ``claim_var`` are preserved. VarStore values remain in the physical ``vars``
  column and can be unpacked with ``unpack_json_column``. Selected assets are
  always exported when requested.
- Changed managed assets to SHA-256 content-addressed ``objects/sha256/<digest>``
  storage with permanent ``/asset/<access_token>`` URLs, and removed the
  ``obfuscate`` flag. Exported archives materialize those bytes under semantic
  ``export_path`` trees with ``assets/manifest.csv``. Generated assets are hashed
  after their content has been prepared.
- Replaced auto-loaded trial and network count ``column_property`` attributes with
  explicit query helpers.

  ``TrialNetwork`` no longer defines PsyNet aggregates such as ``n_all_trials`` or
  ``n_completed_trials`` that ran correlated subqueries on every ORM load. Chain
  allocation now uses ``count_viable_trials_for_nodes`` and related helpers.
  ``ModuleState.n_completed_trials`` remains a stored counter. Also fixed
  ``TrialNetwork.alive_nodes`` / ``failed_nodes`` to filter by node failure state.
- Replaced dual ``psynet.zip`` / ``database.zip`` downloads with a single
  ``export.zip`` product.

  Table CSVs now live in a flat ``database/`` directory (no nested zip and no
  ``data/`` prefix). Asset exports use semantic ``export_path`` trees again;
  ``--assets none`` omits the assets folder. Lucid identifier sidecars are written
  only when Lucid rows exist. ``--archive`` and ``load_export_table`` accept
  ``export.zip``, a ``database/`` directory, or an extracted export directory.
- Dashboard export archives now use ZIP_STORED for already-compressed file types
  (media, images, nested ZIPs) and ZIP_DEFLATED for text formats, removing
  redundant DEFLATE overhead on the dashboard download path. The dashboard and
  automatic backup write ``export.zip`` beside a temporary export tree rather than
  into the process working directory. Dashboard downloads keep that tree until the
  file response has been sent.
- Removed duplicated participant identifiers from ``ErrorRecord`` and ``Response``.
  ``Response`` no longer stores an IP address; Flask still updates
  ``Participant.client_ip_address`` on ``/timeline`` and ``/response``, and
  custom page ``process_response`` methods continue to receive the client IP.
  ``LucidRID`` is linked to participants via nullable ``participant_id`` instead of
  a foreign key on ``worker_id`` without committing the enclosing request
  transaction. Export remaps recruiter identifier columns on copied tables (for
  example ``notification.assignment_id``) to participant pseudonyms, and blanks
  unmatched values plus ``request.params``.
  ``SQLMixin.scrub_pii`` is removed; shareable archives use identifier
  separation rather than in-place JSON scrubbing.
- Changed :class:`~psynet.trial.main.Trial` from a Dallinger ``Info`` subclass to an
  independent PsyNet table (``trial``), and retargeted trial foreign keys accordingly.
- Pruned test experiment directories under ``tests/experiments``, ``tests/playwright/experiments``, and ``tests/deployment`` to authored-only layouts (like bundled demos), normalized their ``requirements.txt`` files to bare ``psynet``, and ignored generated scaffold/constraint files while keeping tracked custom ``config.txt`` files where needed.
- Renamed the default export asset mode from ``experiment`` to ``collected``.

  ``--assets collected`` exports managed assets deposited during the deployment
  (for example recordings), excluding cached stimuli, external URLs, and
  on-demand generation. The dashboard export UI uses the same wording.
- Simplified export asset caching helpers and identifier sidecar builders.
- Values set in the `Experiment.config` dictionary now take priority over `~/.dallingerconfig`: they are only overridden by `config.txt` (which PsyNet forbids sharing keys with), environment variables, and runtime configuration writes.
- Simplified in-place timeline incompatibility errors to one short message: HTML/JS needs a full reload, parenthesized error codes, then migrate-first vs per-page ``requires_full_page_reload=True`` on Page/ModularPage (or temporary experiment-wide config opt-out), with the published checklist / ``/upgrade-to-psynet-14``. Plain ``js_page_code`` is checked with JavaScript heuristics rather than HTML parsing.
- The `audio_gibbs` deployment test now selects its Prolific recruiter via the config file: `config.txt` defaults to the simulated `devprolific` recruiter for safe local runs, and `config.txt.prolific` opts into real recruitment for paid deployments. The separate `experiment.py.prolific` file is removed. Each remaining experiment file aborts launch unless the configured recruiter matches that file (`prolific` or `devprolific` for the shared experiment; `lucid-recruiter` for `experiment.py.lucid`).
- ``psynet audit`` commands use ``./audit/`` from the experiment directory,
  so ``validate`` works from the experiment root. Validate success copy now says
  the packet is coherent and readiness may still be incomplete.
- Experiment-audit monitor snapshots now use static assets from installed
  Dallinger, and audit rendering confines static references and configured output
  paths to safe locations.
- Experiment audit support is available from the core ``psynet audit`` Click
  command group without an optional ``[audit]`` extra.
- Polished `psynet audit` UX: readiness score card, validate-before-render (with `--allow-invalid`), `mark-present`, clearer starter/validate messaging, and source_path defaults for audits inside the experiment directory.
- Changed the thin-bootstrap Dallinger ``constraints.py`` GitHub fallback to
  derive its release tag from PsyNet's declared Dallinger lower bound in
  ``pyproject.toml`` (via package metadata), instead of a hand-maintained
  ``_DALLINGER_CONSTRAINTS_REF`` constant.
- Removed ``psycopg2-binary``, ``redis``, and ``yaspin`` from PsyNet's core
  bootstrap dependencies (now ``click``, plus ``tomli`` only on Python < 3.11 for
  parsing ``pyproject.toml``). ``psynet services`` probes Redis with a stdlib RESP
  ``PING`` and PostgreSQL via ``psycopg2`` when available, otherwise ``pg_isready``
  or a PostgreSQL protocol fingerprint that does not authenticate. Version-check
  spinners still use ``yaspin`` via a lazy import under ``psynet[experiment]``.
- Changed ``psynet setup`` so that choosing a dedicated ``.venv`` completes in a
  single invocation: setup creates the environment, installs the same PsyNet into
  it, and finishes there so every experiment file and lockfile is produced by the
  PsyNet the experiment will use. Setup now also ensures the experiment has a Git
  repository for deployment: an experiment already inside a repository uses it,
  while one that is not in a repository (or that its surrounding repository
  ignores) gets a dedicated repository via ``git init``. After finishing, setup
  tells you to activate the new environment when it created one on your behalf,
  then how to launch the experiment.
- Lab Recruiter reports every terminal outcome (complete, fail, zero bonus, and consent rejection) through its completion endpoint, authenticated with ``Authorization: Token <value>`` from the ``lab_recruiter_auth_token`` config key. Deploying with the lab recruiter now requires this key. Posts verify TLS certificates, time out after 30 seconds, and log failures without aborting participant submission. Calling ``reward_bonus`` on Lab Recruiter raises so that path is not confused with a bonus transfer. Local debug without a token skips the outcome POST instead of leaving the participant in payment review.
- Removed legacy per-demo ``synth_files/.gitignore`` files (``output_batch`` /
  ``output_single`` are not written by current synthesis paths), dropped empty
  nested ``__init__.py`` markers under asset directories, and removed the outdated
  ``develop`` ignore special-casing for in-repo demos and recruiter tests.
- Participant payment is now decided and recorded on the recruiter (`decide_payment` / `record_payment`), then transferred separately. Customize those recruiter methods instead of `Experiment.bonus`, which is unused (overriding it, `check_bonus`, or Dallinger's `data_check` / `attention_check`, fails at deploy). PsyNet posts a bonus automatically at most once: the participant row is locked, then the unconfirmed claim is committed before the platform POST. A failed transfer stays unconfirmed for dashboard Pay or Dismiss; Pay re-applies spend caps and posts only the remaining room, not the full decided amount, and records at most the payable amount if the platform already reports more. Recruitment continues after a failed first transfer but is not repeated on replay. Exceeding `hard_max_experiment_payment` clips the bonus to remaining room (or pays nothing if that is below $0.01), records bonus status `capped` after the transfer claim, and keeps `planned_bonus` as the decided amount. The issued completion code is persisted on recruiter exit. Local recruiters such as HotAir and Generic are omitted from payment review.
- When a participant leaves or is failed, PsyNet now fails that person's unfinished trials and keeps the trials they already submitted. Completed trials are failed only if a TrialMaker performance check treats those responses as unusable (`fail_trials_on_participant_performance_check`, default True for static and dense experiments, False for chain and graph experiments). Recruiter events such as a Prolific return, abandonment, or reassignment fail still-working participants, redirect them to `unsuccessful_end` if they are still in the experiment, fail unfinished trials, keep submitted trials, and no longer fail owned chain nodes. Failing a participant also removes them from their sync groups; if a group then falls below its minimum size and does not accept top-ups, remaining members are failed immediately when `fail_participants_below_min_size` is True. `Participant.fail()` can also fail someone who has already completed; they are not redirected off the successful-end page. Recruiter events after a successful completion remain a no-op. Use `n_participants` or `n_trials` to control recruitment quotas; do not fail submitted trials for that purpose.
- Made the plan section optional for the default psynet.core profile; validate now warns when it is missing instead of failing.
- Hardened audit validation with unified credential redaction, mark-present
  parity, rejection of unfetched Git LFS videos, blocker integrity, explicit and
  confined source bases, protected render output paths, practical notebook and
  section size limits, and clearer missing-packet errors.
- Restructured rendered experiment audits: screenshots, participant video,
  monitor snapshot, performance test, data exports, and analysis are now
  top-level sections instead of one combined evidence panel, ``Timeline`` and ``Report`` are titled
  ``Implementation timeline`` and ``Implementation notes``, and blockers are
  explained rather than emphasized.
- ``psynet dev ci update-dallinger-constraints`` now fetches the vendored
  Dallinger snapshot from a git SHA pin as well as from a version lower bound.
- Renamed experiment Agent Skills to drop a redundant ``psynet-`` prefix and to
  use verb-object names for workflows (``implement-experiment``,
  ``deploy-experiment``, ``monitor-experiment``, ``simulate-participants``,
  ``filter-participants``). Domain skills stay as nouns (``psychophysics``,
  ``tapping-experiments``). ``explore-psynet-repository`` keeps ``psynet`` because
  it is part of the object, not a prefix.
- Ignored PsyNet-managed Agent Skills (``.cursor/skills/psynet/``) in the
  experiment ``.gitignore`` and ``.dockerignore`` templates. These copies are
  regenerated by ``psynet setup`` / ``psynet scripts update`` and are not part of
  the running experiment. Experiment-owned skills under ``.cursor/skills/`` stay
  eligible to commit. Already-tracked copies need ``git rm -r --cached
  .cursor/skills/psynet``.
- Skip JavaScript, CSS, variables, and SPA checks from ModularPage prompt
  and control components that are omitted from ``layout``.
- Warn at page construction when ``js_vars`` keys collide with existing
  ``window`` properties such as ``name``, ``status``, ``event``, and ``history``,
  so legacy global reads cannot silently return the browser's value.
- Stock experiment ``deploy.toml`` uses a nested ``[exclude]`` table:
  ``paths`` for root-relative prefixes such as ``static/assets``,
  ``names`` for nested junk such as ``__pycache__``, and ``suffixes`` for
  literal endings such as ``.db``.
- Ignore ``custom_network_filter`` deprecation warnings in experiment CI until
  ``psynet-step`` can migrate to ``custom_chain_filter`` on a released PsyNet 14.
- Experiment audits always live in ``./audit/`` under the experiment
  directory. Run ``psynet audit`` from that experiment directory; commands take
  no packet path and no ``--experiment`` option. Running from a directory named
  ``audit`` is an error. Use ``psynet audit simulate`` and
  ``psynet audit performance-test`` to collect canonical evidence; the ordinary
  performance-test command never updates an audit. Experiment source is the
  parent of ``audit/``; leftover ``experiment.source_path`` and
  ``experiment.source_base`` fields are ignored with a warning.
- Rendered audit sites treat experiment notebooks, Markdown reports, and the
  PsyNet audit templates as trusted author content. Notebook HTML and SVG
  outputs are included as produced, including any scripts they contain.
- Expanded the stock deployment exclusions for credentials, exports, and local IDE metadata; required a Git commit for remote deployments; and aligned PsyNet's recommended Dallinger series with the temporary 12.4 pre-release dependency.
- ``import_local_experiment()`` no longer appends the experiment directory to
  ``sys.path``. Sibling imports in ``experiment.py`` still use
  ``from . import adaptive_logic``. A later bare ``import adaptive_logic`` after
  the experiment class is loaded no longer works.
- Increased the bounded rendered-notebook preview allowance from 100 KB to 10 MB,
  without changing the 100 KB limit for plain-text artifacts, so rich Plotly
  figures are not prematurely truncated.
- Command-line exports now write to ``exports/latest/`` in the experiment
  directory and keep the previous export under ``exports/history/<timestamp>/``.
  A new export is assembled in a staging directory and only moved into place once
  it is complete and validated, so a failed or interrupted export always leaves
  your previous export intact.
- Exclude the experiment-root ``audit/`` review packet from the stock
  ``deploy.toml`` template. Existing experiments keep their current
  ``deploy.toml``; add ``audit`` to ``[exclude].paths`` if it is missing.
- Remote data exports are now built entirely by the deployed experiment and
  streamed to your computer, rather than being reconstructed locally. Your local
  database is no longer wiped and repopulated, your local experiment code is no
  longer executed against remote data, and archives are streamed to disk instead
  of being held in memory, so exporting a large deployment no longer depends on
  how much RAM your computer has.

  For SSH deployments whose assets live in local storage, PsyNet streams a small
  core snapshot and then fetches only the asset objects your computer is missing,
  so re-exporting an experiment whose recordings have not changed transfers almost
  nothing. Deployments that PsyNet cannot transfer that way (Heroku, S3-backed
  assets, or a missing `rsync`) automatically fall back to a complete
  server-built archive, and the command says which transport it used.
  `psynet export local` builds the export directly from your local deployment's
  database instead of downloading it from its own dashboard.
- Exports record the deployment git commit in ``manifest.json`` instead of bundling ``source_code.zip``.
- SSH exports now establish one SSH connection and reuse it for every step, rather
  than opening a separate connection to probe for rsync, to look up the remote home
  directory, and to fetch `logs.jsonl`. Each connection cost a full handshake, which
  was a noticeable share of the runtime for a small or fully cached export.
- SSH command-line exports copy missing local-storage asset objects with one rsync
  into a persistent content-addressed cache, so repeat exports transfer only new
  objects. If rsync is unavailable, fails, or cannot supply every requested object,
  the export falls back to a complete server-built archive rather than failing or
  publishing an incomplete result.
- Remote ``psynet export`` now stops immediately if the deployment has no
  ``/dashboard/export/preflight`` endpoint, instead of attempting a download this
  client cannot publish. Install the earlier PsyNet (see ``constraints.txt``) and
  retry, or export from the dashboard.
- Data exports now write boolean columns as ``True`` / ``False`` instead of PostgreSQL's raw ``t`` / ``f``, so analysis tools can treat them as logical values. Archives remain loadable with ``psynet load``.
- Long response lists grow with the page instead of scrolling inside a 420px panel. This applies to `PushButtonControl`, `RadioButtonControl`, and `CheckboxControl`: mark the page with `expect_scrolling=True` when the list is meant to be taller than the window. Radio and checkbox rows keep the panel behind them, since each row is its own card, while push buttons now sit directly on the content surface. Vertical push-button lists still stay in one column. The bundled `HouseholdIncomePerYear` and `AttentionTest` pages declare `expect_scrolling=True` accordingly.
- Named colours on trial progress stages, event captions, and the audio meter now follow the participant theme instead of the browser's primary red, green, and blue. `color="red"` resolves to `--psynet-danger`, `green` to `--psynet-success`, `blue` to `--psynet-accent`, `orange` to `--psynet-warning`, and `grey` to `--psynet-text-muted`. Hex values and `var(...)` expressions are unchanged.
- The experiment completion page no longer reports a performance reward of $0.00, and the remaining reward sentence now ends with a period.
- Refreshed the default participant theme. Page content now sits on a bounded content surface over a tinted background; prose is limited to a readable measure; the accent colour meets WCAG AA contrast; keyboard focus follows the accent token; and animations respect `prefers-reduced-motion`, with wait-page text switching to the accent contrast colour when the gradient is replaced by a solid fill. The theme lives in a cacheable stylesheet (`/static/css/participant.css`) built from `--psynet-*` custom properties. Recolouring an experiment means setting both `--psynet-accent` and `--psynet-accent-rgb` (Bootstrap links read the RGB form); see the new Theming tutorial. The content surface no longer overflows narrow viewports, and the waiting page uses the space between the progress rail and footer without creating a stray scrollbar. In the footer, the media-download progress bar overlays the top edge so that download progress cannot shift the footer layout. The footer is omitted altogether when it would be empty, that is when there is no reward to show, no `Comment` button, and no termination button, so that a blank bar does not take up space.
- The audio meter is a themed CSS track rather than a 50px canvas brick. Level and status colour follow the participant palette (including the named red/green/blue mapping), the track matches the trial progress bar, and the microphone name is shown when the browser provides it.
- `ProgressStage`'s default colour is now `var(--psynet-accent)` rather than a hard-coded blue, so an unstyled trial progress bar matches the participant theme and adapts to dark mode. Stages that pass an explicit `color` are unaffected.
- Missing package translations (such as PsyNet's own) no longer abort test runs outside release branches; the English source text is shown instead, and catalogs are refreshed on the release branch. Missing experiment translations still raise, as do all missing translations under `psynet debug`.
- The media-download progress bar is now the bottom counterpart of the timeline progress bar at the top of the page: a thinner 6px rail (`--psynet-media-progress-height`) in the same accent colour, held steady while loading instead of animating through the four-colour gradient used by the wait page. It rides the footer's top edge when there is a footer, and pins to the bottom edge of the window when there is not. The footer itself is omitted when it would be empty, which happens whenever rewards are hidden and there is no comment or termination button, so pages no longer reserve space for a blank bar. In-place timeline transitions treat the footer as optional, inserting or removing it as pages differ, rather than requiring it to be present.
- Removed unstable export benchmarks from the ASV regression gate.
- The final page shown after an experiment now uses the participant theme for generic and local recruitment, and for the lab recruiters. It previously fell through to Dallinger's `exit_recruiter.html`, the one participant-facing page that never picked up the theme, which showed the recruiter's Python class name above a table of raw payment fields, including a bare `None` bonus on recruiters that never pay one. PsyNet now renders `psynet_exit_recruiter.html` instead: a thank-you, a note that the window can be closed, and the assignment ID as a reference. It says nothing about payment, since the participant has already been told what they earned on the debrief page. Prolific and Lucid keep their own exit pages, which return participants to the platform, and `Experiment.render_exit_message` still overrides the page for generic recruitment.
- Raised the default-branch ASV regression factor from 1.25 to 2 so noisy slow load-test medians do not fail the job. The merge-request fast-benchmark gate stays at 1.25.
- The timeline progress percentage sits on a grey pill, the same `--psynet-border` as the track, centred on the rail rather than inside the fill. Early in an experiment the fill is too narrow to hold a label; the pill stays opaque so one text colour remains readable wherever the fill has reached.
- Restyled the participant footer as page chrome rather than content. The footer and the timeline progress rail now share one blue tint (``--psynet-chrome-bg``, defined for light and dark mode, with ``--psynet-footer-bg`` available to retint the footer alone) instead of the footer sharing the white content surface and the rail using the border grey, so the two read as a pair framing the page. The tint is set deeper than the page background so that an empty progress rail stays legible, the footer keeps its own identity, and the footer's surface-filled controls read against the bar. Footer contents line up with the page's content column rather than being spread across the whole window by Bootstrap's navbar spacing, with the reward on the left and the controls grouped on the right. The reward is a borderless readout set exactly like the controls beside it, with a small information glyph in its own colour marking that it explains itself on hover or keyboard focus. **Comment** and **Leave** are outlined in the accent and danger colours so that their boundaries clear the 3:1 contrast WCAG asks of a control's edge. The filled portion of the progress rails follows a new ``--psynet-rail-fill`` token, which tracks the accent in light mode and is dimmed in dark mode, where a fully saturated accent dominated the page. ``--psynet-danger-soft`` is available for quiet danger surfaces.
- Participants can use **Leave** for a recruiter-specific early exit with clear payment or panel-return consequences. Successful, unsuccessful, voluntary, consent-rejection, and error-recovery outcomes share a server-owned ``ExitPlan`` and ``PaymentDecision``, so recruiter handoff and later payment settlement use the same recorded decision. Voluntary Leave requires confirmation and is unavailable once the participant is already finishing.
- PsyNet now adds content versions to generated local static URLs and caches matching static files and deposited assets immutably, while unversioned custom URLs and on-demand assets continue to revalidate.
- Fatal experiment errors now fail the participant as ``error_recovery`` when a recovery plan is stored, while the exception type remains on ``failure_tags``. Error pages reuse an already executed voluntary leave plan instead of treating a known participant as an unidentified session.
- Prolific submission reads now go through Dallinger's ``get_participant_submission(..., translate=False)`` instead of a raw HTTP GET, so the dashboard and unpaid-base retry use the same mocked path in ``devprolific``.
- Fatal errors on generic, HotAir, and lab recruitment skip the interactive recovery page: PsyNet commits the plan during the failing request and shows that an error occurred, with no Finish or Submit. Recruiter-exit is reserved for finished and Leave sessions. Prolific and Lucid still present recovery UI and commit when the participant continues. Custom recruiters that show recovery UI must override ``shows_error_recovery_page``. Error-page Submit, Continue, and auto-redirect are armed only while a tracked recovery plan is still prepared. Error pages return HTTP 200; recovery copy is visible from first paint.
- Participant-facing error, leave, and recruiter-exit copy is shorter and more consistent. Error pages share one heading; Prolific Submit leads to a confirmation shared with recruiter-exit; terminal close-outs tell people they may close the page. Generic Leave no longer says responses have been saved; finished sessions and the Leave confirmation modal still do. Lucid talks about returning to the panel.
- Retried transient timeouts in ``psynet dev docs linkcheck`` instead of failing on the first one, so a momentarily slow but healthy site no longer breaks the documentation build.
- ``wait_while``, ``AsyncCodeBlock(wait=True)``, trial feedback processing, and default barriers now preserve the current page, show a compact status indicator that floats above the page instead of shifting its content, and use shared wake notifications when available. Default holds credit actual visible waiting time up to ``max_wait_time``; setting ``fix_time_credit=True`` credits ``expected_wait`` instead, while progress and advertised duration always use ``expected_wait``. ``wait_while`` and barriers accept custom hold ``content``, and barriers accept ``expected_wait``. Explicit ``WaitPage`` or custom waiting logic retains a dedicated waiting screen. ``AsyncCodeBlock`` uses a 2-second fallback check interval. Hold timeouts use ``timeline_hold:<id>`` failure tags and trigger when the configured limit is reached.

  Group barriers and groupers now release or form groups as soon as the last member arrives, so that participant self-skips the wait indicator on the default hold path. Waiting partners stay on their overlay until they resume; last-arrival does not advance their timeline cursors. A hold consumed immediately after skipping a released wait stays a silent spinner for that visit, and the overlay chip and websocket are reused across stacked holds. Leftover hold uuids catch up onto a later stacked hold instead of treating a partner skip as a second browser tab. If a partner's wait row is locked, the 0.5-second barrier check still finishes the release. Last-arrival ``on_release`` and spec errors leave the group waiting instead of failing the arriving participant.

  Synchronized trial makers accept ``sync_group_wait_content`` so their own grouping waits can share overlay copy with the experiment's grouper and ``GroupBarrier`` waits; author-defined groupers and group barriers still use their own ``content``. The rock-paper-scissors demo no longer waits at an extra group barrier before each choice. Holds restore the previous control state when they end, sit under the Leave confirmation overlay, and fall back to a full reload if the committed next page cannot be activated in place. Rejected hold-resume checks reload the current timeline page, and the hold WebSocket closes when the hold ends. Lucid inactivity and no-focus clocks pause while the overlay is showing; overall HIT time still counts.
- In-place ``/response`` pages render ``timeline-fragment.html`` instead of compiling Dallinger's full document shell and discarding it, and Jinja translation environments are reused per locale. Fragment extraction ignores HTML comments and no longer rewrites ``<script>`` tags that appear inside JSON bootstrap data or other script, style, or template bodies. Full-page timeline render and in-place fragments skip BeautifulSoup unless the HTML contains a ``type="module"`` script or cannot be extracted as a fragment root. Browsers no longer cache live timeline JSON snapshots such as partner-ready arrival notices and progress/reward.
- Started ``psynet debug --legacy`` with four gunicorn workers by default so last-arrival ``GET /timeline`` can overlap waiter hold-resume POSTs in a group of four. Playwright stacked-hold tests set ``PSYNET_LEGACY_DEBUG_GUNICORN_THREADS`` to the session count. GitLab Playwright jobs use that gunicorn path; the default vs legacy job split remains in-place vs full reload.
- The `auto_recruit_prolific` deployment test now ends with a short custom debrief that describes the technical test, instead of the generic cultural-foundation IRB letter.

### Deprecated

- Deprecated reading page JavaScript variables from ``window`` in favor of ``psynet.var``. Compatibility can warn, raise an informative error, or be disabled with ``legacy_js_var_globals``, while leaving existing or externally locked ``window`` properties untouched.
- Deprecated the ``js_links`` and ``scripts`` Page arguments in favor of ``js_dependencies``, ``js_page_code``, and ``js_page_modules``. Pages that still use the deprecated arguments keep classic script semantics and force a full page reload.
- Deprecated `fail_trials_on_premature_exit`. The argument is still accepted, defaults to `False`, and is ignored. It is not stored on the trial maker, so reading `trial_maker.fail_trials_on_premature_exit` now raises `AttributeError`. Premature exit always fails incomplete trials and preserves completed trials.
- Deprecated ``custom_network_filter`` in favor of ``custom_chain_filter`` on
  chain trial makers and ``custom_node_filter`` on static trial makers. Existing
  overrides still filter candidates, but construction emits a
  ``DeprecationWarning``.
- Deprecated the `--n_parallel` export option: asset export has been sequential
  for some time, so the option had no effect. It is still accepted so older
  scripts keep running.

### Removed

- Removed deployment-time source code archives and source export, replacing them with lightweight Git commit and working-tree provenance.
- Removed raw `.config.backup` files from deployment packages so source configuration cannot bypass deployment-plan filtering.
- Removed the Asset ``personal`` flag.

  Passing ``personal=...`` to asset constructors, the ``asset()`` helper, or
  recording controls now raises an informative error. Selected assets are always
  exported when requested; treat exported media as potentially identifying.
- Dropped support for Python 3.10.
- Removed the `prolific_enable_screen_out` config parameter, which had been a deprecation stub since Prolific retired the corresponding screen-out API route; experiments still setting it now fail config loading with Dallinger's standard invalid-key error. Unsuccessful participants are paid via Prolific's completion-code-based screen-out mechanism instead (see `prolific_pay_unsuccessful`).
- Removed the unused ``tomli`` bootstrap dependency now that PsyNet requires
  Python 3.11 or later.
- Removed `psynet export --legacy`. The old engine downloaded the raw database,
  replaced the contents of the local database with it, and rebuilt the export
  locally. Use the default server-built export, or `psynet load` if you
  intentionally want to replace the local database. Existing positional calls to
  ``ArtifactStorage.download_export`` remain supported with a deprecation warning.
- Removed the ``--assets all`` export option.

  Exports now include either no assets (``--assets none``) or files deposited
  during the run (``--assets collected``, the default), such as recordings.
  Cached stimuli, external URLs, and on-demand assets are no longer copied into
  the archive. Copy stimuli from the experiment directory or storage if you need
  them for supplementary materials. Passing ``all`` (CLI ``--assets all``, or
  dashboard ``?assets=all``) raises an error with this guidance. The dashboard
  export page no longer offers an All choice.
- Removed the unused ``Experiment.export_classes_to_skip`` attribute.

  Canonical exports copy physical database tables, so that list no longer
  controlled what appeared in the archive.

### Fixed

- Fixed `psynet translate` making three provider calls per file instead of one, because the retry loop never stopped after a successful translation.
- Added adversarial lifecycle Playwright coverage.
- Avoided duplicate page control bindings after trial restarts.
- Cleaned up media capture streams on page transitions.
- Covered same-session page updates in Playwright.
- Disposed SurveyJS controls on page cleanup.
- Fixed stale in-place timeline events during audio demo transitions.
- Hardened in-place timeline transition end-to-end tests.
- Used reloads for non-same-session Unity transitions.
- Used trial timers for auto-advance page actions.
- Scoped page-local stylesheets during in-place timeline transitions, preventing CSS from leaking between pages and warning authors to use managed page CSS APIs instead of raw prompt markup styles.
- Hardened Selenium timeline readiness checks for in-place page transitions.
- Cleaned up page-scoped timers so SPA timeline transitions do not leave stale callbacks behind.
- Isolated in-place timeline media loads so late responses from previous pages cannot overwrite current page media.
- Fixed audio cleanup during in-place timeline transitions.
- Fixed the docs pages job crashing in the window between a release branch being merged back into master and the post-release alpha bump landing; the version switcher now omits the alpha entry when the default branch carries a stable version.
- Removed the `(author: [Your Name])` placeholder from fragments generated by `psynet dev changelog new`.
- Fixed intermittent Postgres deadlocks in CI when resetting the database between experiment tests, by waiting for the previous experiment server to fully stop before the next reset and, on deadlock, terminating leftover connections before retrying.
- Fixed in-place timeline transitions to preserve full-page script execution order and to show each loading error only once.
- Fixed `/start` to resume existing assignments across recruiter URL formats using structured lookup errors, recover after browser back/forward navigation, and support configured repeat worker IDs. Worker-id lookups now return the most recent participant when repeats exist. Advancing from `/ad`, gateway `/consent`, and `/start` now replaces those history entries so Back from the timeline leaves the experiment instead of replaying the recruiter handshake or participant creation.
- Fixed failed in-place transitions so they no longer re-enable unusable timeline controls, and stopped omitted chatrooms from loading their resources.
- Fixed in-place timeline transitions hanging when audio ended during cleanup.
- Fixed performance tests to preserve explicit zero-valued options in local and SSH modes, and to bound randomized bot staggering relative to the configured interval.
- Trials and WaitPage auto-advance now wait for ``pageReady``, so pages cannot start or auto-advance while navigation setup is still in progress.
- Fixed ``count_participant_trials_in_block`` to query ``ChainTrial.block_position`` instead of the base ``Trial`` class.
- Fixed config loading so values set in `Experiment.config` remain available after an initialized experiment process changes into a non-experiment directory. Previously such processes could skip the experiment's config defaults and resolve different values (e.g. `dashboard_user`), causing bots to fail authentication with HTTP 401 errors.
- Hardened chatroom widget cleanup: WebSocket and DOM listeners are removed if page-module activation fails mid-setup, and the null-room path waits for ``pageReady`` before continuing.
- Ignored stock ``config.txt`` files under test-experiment trees like demos, while leaving already-tracked custom configs tracked (use ``git add -f`` for new customs).
- Fixed the dashboard network monitor so PsyNet trials appear after Trial left the Info table.
- Fixed Trial JSON serialization for the dashboard network monitor when Dallinger details fields are absent.
- Fixed locale loading for deployed experiments imported as namespace packages.
- Made SPA contract failures visible during ``psynet test local`` by checking static timeline pages before bots run (including non-template ModularPage codes when external templates need an app context) and by extracting SPA messages from bot HTTP 500 bodies via a stable footer marker. Documented the full experiment scaffold files needed for local validation.
- Fixed deployment config snapshots to follow config source priority and exclude sensitive-looking keys.
- Fixed ``psynet setup`` and ``psynet scripts scaffold`` failing in editable alpha
  checkouts whose current commit cannot be served by ``origin`` (for example
  unpushed work, or CI merge-result commits). These now record an editable PsyNet
  requirement and warn that it only resolves locally; use ``psynet setup
  --psynet-source commit`` to require a deployable commit pin.
- Fixed a Prolific payment gap where a participant who finished the experiment but never entered the completion code was approved locally while their submission timed out unpaid on Prolific. Local submit is now the Prolific success path: PsyNet completes the still-active (or already timed-out) submission server-side with a researcher-actor completion code, Prolific pays the study reward or fixed screen-out payment, and PsyNet posts the top-up bonus as before. Participants stay on a PsyNet confirmation page and do not enter a completion code.
- Fixed thin-bootstrap ``psynet services`` probes to read Redis/PostgreSQL
  responses robustly and release TLS sockets, and declared ``tomli`` for
  Python 3.10 bootstrap installs.
- Fixed experiment-audit notebook previews so executed notebooks between 100 KB and 10 MB still appear in the Analysis panel, and stopped ``init`` from writing ``source_path`` values that ``validate`` would reject.
- Polished experiment audit sites: audit completeness now appears at the top,
  section headings are not duplicated, timelines retain structured styling,
  performance precedes analysis, empty checks are hidden, and screenshot
  manifests publish their referenced images.
- Thin-bootstrap constraint generation now reads a Dallinger git SHA pin from
  installed package metadata when `pyproject.toml` is absent.
- Fixed ``psynet scripts scaffold`` / prune so copied Agent Skills under
  ``.cursor/skills/psynet/`` are treated as scaffold-managed paths. Demo round-trip
  tests no longer treat those generated files as authored experiment sources.
- Fixed ``psynet setup`` pinning a GitLab/git install of an unpublished alpha
  as ``psynet[experiment]==13.4.0a0``, which cannot be resolved from PyPI.
  Standalone experiments now reuse the installed VCS commit
  (``psynet[experiment] @ git+<url>@<commit>``) when compiling constraints.
- Show a refresh prompt when full-page managed JavaScript activation fails,
  including missing ``js_page_modules`` and ``js_dependencies``, instead of
  leaving the participant on a permanently disabled page.
- ``psynet audit validate`` now warns when ``TIMELINE.md`` lines look like
  entries but were ignored (for example an actor tag other than
  ``agent-start`` / ``agent`` / ``agent-stop`` / ``manual`` / ``system``), and
  when ``implementation.summary`` is still the starter TODO. The rendered page
  omits that TODO so it is not the subtitle under the experiment title.
- Keep ``js_dependencies`` available to first-page body scripts by emitting them
  as blocking head tags, while still routing failed loads through the guarded
  loader so missing files show the refresh prompt.
- Fixed vocabulary tests so chosen item hashes stay on the trial after
  creation. Item selection now happens in ``VocabTrial.finalize_definition``.
  ``VocabTest`` rejects synchronized groups, which would otherwise assign
  followers a different item set.
- Local CI Docker network setup now aborts if Redis or Postgres cannot be started.
- Fixed ``Column ... conflicts with existing column`` errors when an experiment
  class adds a column to a table it shares with other classes, such as a ``Trial``
  subclass on Dallinger's ``info`` table. PsyNet now reuses the existing column,
  so plain ``Column`` declarations survive reimporting ``experiment.py`` from its
  staging copy. When a different class redeclares the same column name, the two
  declarations must agree on type, length, nullability, uniqueness, indexing,
  primary key, foreign keys, defaults, update values, constraints, autoincrement
  behavior, system-column status, and comments, or PsyNet raises a clear error
  asking you to rename one of them. Callable defaults such as
  ``default=lambda: 0`` cannot be compared between two classes, so declare such a
  shared column on a single class.
- Stopped debug, test, and deployment once after PsyNet auto-creates `deploy.toml`, including when setup or scaffold wrote the file, so authors can review the deployment plan before rerunning. Git-ignored files may still be deployed after that one-time review. Temporary pytest scaffolds and in-repo auto-prepare skip that pause. Git dirty-state provenance is scoped to deployment-selected files, including experiments nested in a parent repository, and uses the same ``deploy.toml`` exclude rules as the deployment plan.
- Fixed Markdown display outputs being omitted from rendered audit notebooks.
  The audit now renders ``text/markdown`` with the same Markdown renderer used
  for reports, before falling back to ``text/plain``.
- Fixed matplotlib plots rendering as solid black blocks in audit sites.
  Notebook SVG outputs are included as produced, including ``defs``/``use``
  glyph references, ``transform``, ``clip-path``, and inline ``style``.
- Fixed interactive Plotly figures in rendered audits collapsing to the minimum
  container height when the browser window was resized, which squashed tall
  faceted figures and made their labels overlap.
- Sped up trial candidate discovery by batching viable-trial counts, skipping
  those counts for unlimited unbalanced static nodes, and pairing static nodes
  with their already-loaded networks so assignment no longer issues a network
  query per candidate. ``TrialNode.n_viable_trials`` is still readable on a node
  and usable in SQLAlchemy filters and ordering, but it is no longer a mapped
  column, so it is queried on access instead of loaded with every node. As a
  result it no longer appears as a column in node data exports or in the
  Dallinger dashboard; count the trials at a node directly if you need it in an
  analysis.
- Protected ``audit/simulate/`` from being used as the rendered site output
  directory, so rendering cannot overwrite simulated exports or design results.
- Participant navigation no longer loads module-state and barrier relationships
  until the current request actually uses them.
- Dashboard Pay no longer posts a bonus twice when two Pay clicks overlap.
- Looking up a participant's trials for one trial maker, as used by performance
  checks and repeat-trial selection, no longer loads trials belonging to the
  participant's other trial makers before discarding them. The results are now
  ordered by trial ID.
- `psynet.export.merge_participant_identifiers` now accepts a
  `pathlib.Path` for its `identifiers` argument, not only a string.
- `psynet test ssh` and `psynet performance-test ssh` no longer stop early when
  run without an interactive terminal, for example from a script or an editor's
  integrated shell. They previously watched local standard input so that you could
  quit by pressing `q`, which made them exit immediately on end-of-file and report
  that no participants had run. They now also fail with a non-zero exit code when
  the remote command fails, echo the remote output in full rather than dropping
  whatever was still in flight when the remote process exited, and report how many
  bots ran instead of succeeding silently.
- ``StaticTrialMaker`` now rejects ``target_trials_per_node`` values of ``0``
  or less. Use a positive number, or ``None`` for unlimited.
- When the deployed experiment cannot build an export, `psynet export` now reports
  why instead of only "Internal Server Error (500)".
- Stopped ``SAWarning: This declarative base already contains a class`` and
  ``SAWarning: Reassigning polymorphic association`` appearing when PsyNet loads
  ``experiment.py`` more than once in a process, which happens during
  ``psynet debug`` and ``psynet deploy`` and when Dallinger's config loader reads
  the experiment's extra parameters. Any experiment that defines a ``Trial``
  subclass or a custom table saw these warnings, which described PsyNet's own
  reloading rather than anything an experimenter could act on. Experiment test
  suites that run pytest with ``-W error`` no longer fail because of them.
- Folder assets deposited into local storage are now stored with predictable
  permissions (`0755` directories, `0644` files) instead of inheriting the source
  directory's. A folder deposited from a `tempfile.TemporaryDirectory` was
  previously stored as `0700`, which stopped anything running as another user
  from reading it, including rsync during an SSH export.
- `psynet deploy`/`debug --archive` now re-packs the archive you supply and sends
  only the table CSVs under `database/` to the server. Passing an `export.zip`
  previously uploaded the whole archive, including the recruiter identifier
  sidecars and any exported asset files, even though only the table CSVs are read.
- The ``bot_2`` demo timing check no longer treats the first recorded HTTP
  request as a failure. That cold-start load can exceed one second on busy CI
  runners while later pages remain fast.
- If replacing ``exports/latest`` fails and the previous export cannot be
  moved back, that tree is left at its recovery path and the error names both
  locations instead of deleting it. Interrupting the final replacement restores
  the previous export before propagating the interruption.
- Identifier separation no longer produces exports that fail to load. Removing a
  recruiter identifier from a `NOT NULL` column used to leave a blank field, which
  `COPY` reads back as NULL, so `psynet load` and `psynet deploy --archive` failed
  on the resulting archive. Nullability is now read from the live schema:
  `participant.entry_information` is written as `{}`, and an identifier belonging
  to no exported participant (such as Dallinger's literal `unknown` assignment on
  an error notification) is replaced by a `redacted-<table>-<row id>` placeholder
  rather than blanked.
- Identifier separation now inspects column types before copying tables and
  fails if a recruiter-identifier column cannot store a text or JSON
  placeholder. Integer, UUID, enum, short ``VARCHAR``, and ``NOT NULL``
  identifier columns on tables without ``id`` are rejected instead of
  producing an archive that cannot be reloaded.
- Export archives now accept only exact ``database/<table>.csv`` or legacy
  ``data/<table>.csv`` members. Nested lookalikes, path traversal, duplicate
  members (including normalized or case aliases), and mixed zip or extracted
  layouts are rejected. Downloaded zips are classified before unpack and streamed
  into the destination directory without allowing path traversal. Asset manifest
  export paths are validated before any bytes are transferred, so an unsafe path
  is rejected even when the transfer itself cannot run. ``psynet export``
  publishes only ``database/`` layouts; legacy ``data/`` zips remain valid for
  ``psynet load`` and ``--archive``.
- Graphics, vertical push-button lists, named colours, and footers no longer break participant pages in the cases the default-theme review found. A `GraphicPrompt` keeps a minimum size on short viewports instead of collapsing to zero, vertical `PushButtonControl` lists stay in one column, `color="white"` remains CSS white so captions stay visible in dark mode, and the footer follows the content instead of covering controls.
- The audio-meter status message now wraps inside the viewport on phones instead of sitting in a 500px table that overflowed the screen.
- Participant pages no longer render in quirks mode. Templates that included partials outside a block emitted markup before `<!doctype html>`, which forced every ad, consent, timeline and error page into quirks mode and included the theme twice. Layouts that depended on that behaviour (the waiting page, `GraphicPrompt`, and the jsPsych stage) now size themselves against the viewport or their aspect ratio instead of an undefined percentage height. `GraphicPrompt`'s `viewport_width` is measured against the browser window, as its documentation always stated, and `max_viewport_height` (default `0.6`, now also a constructor argument) caps the graphic's height. Both caps, the content surface, and room for page chrome (`--psynet-graphic-vertical-chrome`) are applied as width constraints so a landscape graphic keeps its aspect ratio and a square graphic still fits a typical laptop window without scrolling.
- Fixed a crash when running a Prolific experiment with the `devprolific` recruiter. Reading a Prolific submission uses a direct HTTP request that bypasses the dev recruiter's mocked API, and the dev recruiter holds no API credentials, so local submits and the Participants dashboard failed with an `AttributeError`. PsyNet now reports no platform payment data instead of raising when the recruiter has no Prolific credentials, and the dev recruiter reports the submission status a local submit really sees, so debugging a Prolific experiment locally exercises the completion-code choice and logs the completion request instead of sending it.
- Custom tables that link to trials now foreign-key ``trial.id`` rather than
  ``info.id``.
- Passing ``anonymize=`` to ``psynet export`` now warns that the option has been
  removed and has no effect, instead of ignoring it silently.
- Fixed a Prolific participant looking fully paid when the recruitment platform refused to pay their study base. PsyNet records the decided base before asking the platform to pay it, so a failed completion previously left the recorded base in place with no sign that the money never arrived. The Participants dashboard now shows the base as unpaid, with the reason. PsyNet retries the same completion quietly on its existing once-a-minute recruiter check, and clears the flag if Prolific has already paid. If the row is returned or rejected, or if a handful of retries still fail, PsyNet stops and asks you to settle the submission on the platform. The top-up bonus is still paid; the study base is not reconstructed as a bonus. A completion request that cannot be sent at all (for example a network failure) is now reported as a failure rather than interrupting payment and recruitment.
- Fixed media loading on experiments that hide the footer. `psynet.media.init()` runs on every trial and unconditionally styled the media-download progress bar, which lives in the footer, so `show_footer = false` left the page stuck: the trial never finished constructing and its controls stayed disabled.
- Participant layout checks now detect ordinary response controls hidden behind
  a custom fixed footer and preserve the exact inline height declaration, including
  `!important`, while probing percentage-height behavior. Graphic dimensions,
  `viewport_width`, and `max_viewport_height` now reject strings and invalid real
  numbers before generating CSS. The experiment scaffold no longer promises a
  visible reward when its generic recruiter hides rewards by default.
- In-place timeline transitions keep a single media-download progress bar when consecutive pages disagree about whether they have a footer. Mixed pages (for example a Lucid screening question with no terminate button, then a later page with one) previously left either two rails or none, because the bar lives inside the footer on some pages and as a sibling on others.
- The jsPsych stage sizes itself from leftover viewport chrome (`--psynet-graphic-vertical-chrome`) rather than a 70vh minimum, so an empty jsPsych page still fits a 1280×720 laptop window with the footer visible.
- `prefers-reduced-motion` no longer freezes every CSS animation on the page. The wait-page splash still swaps to a solid accent fill, but CSS-animated stimuli keep running instead of being stopped by a document-wide `!important` rule.
- Every participant page now declares a viewport, so pages other than the timeline, ad, and consent pages are laid out for the device rather than for a notional 980px-wide screen and scaled down. Exit and error-recovery pages previously arrived on a phone with tiny text and none of the theme's mobile rules in effect, because Dallinger's base layout provides no viewport meta and only pages running browser detection supplied one. The viewport now comes from ``macros/head.html``, used by ``psynet_layout.html`` and by pages that extend Dallinger templates directly.
- The participant footer is now compact and can no longer cover the last control on a page. It shows the total reward and a **Leave** button, with the time and performance breakdown and an explanation of **Leave** available as tooltips on hover, keyboard focus, and to screen readers. The footer stays in document flow, so one that wraps onto several rows on a narrow window, in another language, or at a larger font size naturally moves below the response control instead of hiding it.
- Consent pages keep their agree/decline actions in the document flow instead of a fixed overlay that covered the last paragraphs and fought the themed footer. A finished participant who hits Back from the exit page stays on the thank-you screen rather than a stale timeline or start page: exit navigation uses `location.replace`, the exit page keeps Back on itself, `/timeline` responses are not stored in the back/forward cache, and the server redirects finished timeline visits.
- Prolific's completion page now uses PsyNet's participant theme and viewport settings while preserving its platform submission control.
- The consent decline button now uses the theme's outlined danger style, matching the footer's **Leave** control, instead of Bootstrap's solid red, which outweighed the **I agree** button beside it. Solid and outlined ``btn-danger`` controls generally follow the ``--psynet-danger`` tokens, so a custom theme can restyle them. Solid danger hover and active fills use dedicated hex tokens rather than ``color-mix()``, so they work at the theme's Chrome 105 floor.
- The participant footer now follows the content at every window width and comes to rest at the bottom edge of the window or at the end of the page, whichever is lower. A page that fits therefore looks as it did before, while a longer one gives its whole window to the content instead of keeping chrome over it. The wait page fills the space between the progress bar and the footer instead of claiming a second full viewport. In dark mode, solid buttons use a new `--psynet-accent-solid` fill with a white label rather than the accent itself, which made a button the brightest thing on the page; the accent stays light for link text, where it needs to read against a dark surface.
- Kept the media-download progress bar attached to the footer on long participant pages.
- Footerless participant pages now show media-download progress only while they have media to load, avoiding a completed stripe floating over pages such as consent forms.
- Participant pages no longer resize their text when the Inter webfont finishes loading. The theme now falls back to a metric-matched face while the font is in flight, and preloads the bold weight that headings use.
- The error page no longer paints Dallinger's placeholder logo before swapping in the experiment's own logos.
- Tracked fatal recovery is prepared in the original failing request and opened with a reloadable ``GET /timeline?unique_id=...``. ``/error-page`` stays untracked and does not treat enumerable ``participant_id`` as session authority. A complete participant who revisits ``/timeline`` still gets the ``/worker_complete`` backstop.
- Fixed ``psynet dev docs linkcheck`` reporting "no broken links" when Sphinx had in fact found some; the summary now reads Sphinx's ``linkcheck/output.json`` instead of parsing coloured console output.
- Rejected unknown, negative, non-finite, boolean, and string payment amounts; preserved Lucid termination outcomes (including terminate callbacks at 100% progress) without reclassifying them as completes; and recomputed managed-asset digests when bytes change at an existing input path.
- Isolated Gibbs export tests now stop the debug experiment before reloading the archive, so ``drop_all`` cannot deadlock against a live clock process.
- Fixed the consent pages in the deployment tests' vendored `consents_cococo` package, which
  overrode the template's `stylesheets` block without calling `{{ super() }}` and so rendered
  without the PsyNet participant theme, leaving the agree/decline buttons flush against the
  bottom of the page. The pages now use the standard surface panel and spacing.
- Loading an export refuses to reset the database while another client using the same database role is still connected, and retries leftover table-drop lock errors. Export ingest retries foreign-key drops after a deadlock with the live barrier poller. Every launch path, including SSH, Heroku, and Docker, stops leftover local debug workers first because prepare resets this machine's Postgres.
- Modular-page chatrooms wait for the join-time history snapshot before enabling Send (an empty snapshot still counts), append leftover live messages after that snapshot using counts so two identical lines in the wait window are not collapsed to one snapshot match, and republish the persisted log after each message so a partner who missed the live relay can still fill an empty feed.
- Planned timeline reloads no longer trigger Lucid leave-page termination.
- Prevented chat messages from being sent before the WebSocket connection opens or while it reconnects.
- `psynet destroy ssh` continues with the remaining apps if destroying one app fails, then exits with an error. It also errors if no app name is given.
- Playwright stacked-hold tests allow a fourth hold-resume POST after concurrent last arrivals.
- Fixed intermittent test timeouts in Selenium bot tests. PsyNet's pytest bot now finalizes the session with a direct HTTP request to `/worker_complete` instead of navigating the browser there, because the participant page has already called that route by the time the bot fixture runs.

### Updated

- Updated the Dallinger requirement to version 12.3.0 or above.
- Updated the Dallinger requirement to version 12.4.0 or above.

### Documentation

- Documented Sphinx cross-reference guidance for documentation updates.
- Reworked the deployment-test skill (renamed from `debug-deployment-test-experiments`) and coordinated it with the release skill: each deployment gets a fresh branch, RC promotion requires per-app promotion verdicts, and audit trails are archived in the private `psynet-deployment-tests` repository.
- Added an ASV benchmarks link to the documentation navigation.
- Added a GitLab merge request description template and linked AGENTS.md to it.
- Added a tutorial explaining how to load-test an experiment with ``psynet performance-test``.
- Added PsyNet 14 What's new docs with a human upgrade checklist as the migration source of truth, patterns living in the custom-frontends tutorial, and a thin ``/upgrade-to-psynet-14`` Cursor skill that wraps that checklist.
- Documented content-addressed asset storage, access-token URLs, the assets manifest/object export layout, and the local asset cache CLI.
- Documented the precedence of runtime writes, environment variables, experiment settings (`config.txt` and `Experiment.config`), `~/.dallingerconfig`, PsyNet experiment defaults, and Dallinger package defaults.
- Demo and scaffold README files now open with experiment-specific guidance (patterns, when to use them, and how the example fits), followed by a shared Usage section that links to the PsyNet documentation.
- Documented standalone setup (Git, uv, ``psynet setup``/``scripts``/``services``) and that every experiment needs a ``config.txt``.
- Clarified accepted cleanup shapes for ``window_listener_no_cleanup`` SPA errors
  (``return () =>``, ``return function cleanup``, or ``psynet.addPageCleanupCallback`` /
  ``psynet.addPageEventListener``) in the incompatibility message and PsyNet 14
  upgrade checklist.
- Pointed the ``/upgrade-to-psynet-14`` skill and experiment agent instructions at
  the published PsyNet 14 upgrade checklist URL, with local ``docs/*.rst`` paths
  as a source-checkout shortcut (pip wheels do not ship the docs tree).
- Added a tutorial on participant and trial failure, including that ``Participant.fail()`` can fail a completed participant, redirects still-working participants to the ``unsuccessful_end`` timeline branch, fails incomplete trials before fail routines run, that recruiter exit no longer fails within-chain start nodes or networks, and that Dallinger's post-submission data and attention checks are unused in PsyNet.
- Added a developer Future work page for unconfirmed ideas.
- Documented agentic programming with PsyNet, including Agent Skills, the audit
  handover, and a from-scratch implementation workflow. On Windows, use WSL
  (Ubuntu) and the Linux commands; native Windows is not supported.
- Added Cursor commands that merge the GitLab merge-request target before `/branch-review`, and documented that workflow for developers.
- Added experiment skills for shared participant-response models, standardized power-analysis artifacts, and simulation-based precision estimation.
- Prefer SVG plot outputs in analysis notebooks
- Instruct participant-flow screenshot capture to use Playwright ``fullPage:
  false`` so audit images show the participant viewport rather than a
  stitched full-page layout.
- Require audit ``monitor.html`` snapshots from ``/dashboard/monitoring`` (the
  Monitor tab). Remove the temporary PsyNet-revision note from the audit
  population reference.
- Documented how to implement adaptive PsyNet experiments, including a
  benchmarking workflow that compares adaptive policies with non-adaptive
  baselines and tests robustness to misspecification.
- Documented how to import Python files that sit beside ``experiment.py``.
  From the experiment package use ``from . import my_module``. Standalone
  scripts such as ``python -m audit.simulate.design.core`` keep top-level
  imports and must be run from the experiment root.
- Documented packaging constraints for adaptive experiments: keep calibrated
  item banks in ``item_bank/``, not under the excluded experiment-root
  ``data/``, ``audit/``, or ``exports/`` directories, and choose between
  extra trial columns and a dedicated observation table on the basis of how
  the model reads the data.
- Documented how to lay out Plotly figures for the rendered audit column, which
  is narrower than a notebook authoring window. The audit skill now covers facet
  overlap, label length, legend placement, and figure height, with reference
  layout code.
- Documented that adaptive power analyses should disable early stopping for
  matched-budget cells or report realized ``mean_n_observations`` next to
  precision metrics.
- Documented fixed-budget-first adaptive-test power analyses, configurable
  accuracy and calibration metrics, compact Plotly metric controls, and explicit
  cost--precision comparisons for optional adaptive stopping rules.
- Documented how to report precision at single-budget resolution in power
  analyses, including why such curves must be computed with early stopping
  disabled, and added row-faceting guidance for audit figures that genuinely
  need separate panels.
- Documented `plotly_white` as the audit default, confidence ribbons for dense
  budget curves, and short introductory sections explaining statistical concepts
  and simulation assumptions in power-analysis notebooks.
- Asked agents to reread skills and documentation after editing them, preferring
  a short correct example, one place for each rule, and headings that match how
  a reader will look up the next step.
- Documented that performance tests should be judged by ``/timeline`` and
  ``/response`` latency, and that high percentiles warrant SQL profiling before
  changing the scientific policy.
- Documented SQLAlchemy profiling methodology, retained optimization patterns,
  rejected approaches, and criteria for revisiting future performance work.
- Note that a short performance test is a good first pass, and that a longer window is needed when finalizing if bots should finish.
- Documented ``Trial.cue`` as the usual way to wire an adaptive policy into a
  PsyNet timeline, including transactional decision records, ``while_loop``
  stopping, and item-level audio assets on the module.
- Removed the developer export performance roadmap now that the export layout it described has shipped.
- Document that Dallinger loads ``experiment.py`` as a package, so sibling imports are relative and ``python experiment.py`` is not a valid check.
- Document that table CSVs and identifier sidecars are one repeatable-read snapshot, while basic data and assets are built afterwards from live state. Document that read-only asset-cache hits are trusted without re-hashing.
- Documented how to share an export: delete the identifier sidecar CSVs, review
  the rest of the archive for private content, and drop asset ``access_token``
  and ``url`` columns only if the deployment is still running.
- Added a `playwright-testing` experiment skill that owns participant-flow Playwright walks and `psynetLayout.check()` layout checks. Experiment authors find it under `.cursor/skills/psynet/playwright-testing` after `psynet scripts update`.
- Fixed documentation links that ``psynet dev docs linkcheck`` reported as broken: internal pages now use Sphinx ``:doc:`` roles, and 404ing, missing-anchor, bot-blocked, or TLS-failing URLs now point at current official pages or are ignored only when the official page still works in a browser.
- Updated the deployment-test skill (version-first naming, running-container inspect) and abort ``audio_gibbs`` Lucid and Prolific launch if the configured recruiter does not match that variant.
- The PsyNet 14 upgrade checklist now includes recruiter configuration, leave and error-recovery APIs, and changed participant-theme defaults.
- Documented how timeline holds resume on ``GET /timeline`` versus ``POST /response``, including last-arrival traces and the invariants tests must witness. Playwright hold-release tests log overlay linger and fail only if it exceeds a 30-second hung-overlay cap.
- Stopped the Sphinx docs build from failing on Flask ``make_response`` autodoc and SQLAlchemy's inherited ``cache_ok`` reference.

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
