---
name: synchronous-experiments
description: Design and implement PsyNet synchronous experiments using cohort, grouping, barrier, waiting-room, and recruiter coordination patterns without assuming websocket interaction.
---

# Implement synchronous PsyNet experiments

If participants exchange live actions or messages within a trial, also read
`realtime-synchronous-experiments/SKILL.md`.

## Prerequisites

- Read `implement-experiment/SKILL.md` for the general PsyNet
  implementation workflow and validation expectations.
- Read `references/source-notes.md` for the source map, platform notes, and
  practical caveats behind this skill.
- Inspect current PsyNet docs and demos before coding:
  `~/PsyNet/docs/tutorials/synchronization.rst`,
  `~/PsyNet/docs/api/sync.rst`,
  `~/PsyNet/demos/experiments/simple_sync_group/`,
  `~/PsyNet/demos/experiments/create_rate_sync/`,
  `~/PsyNet/demos/experiments/rock_paper_scissors/`,
  `~/PsyNet/demos/experiments/sync_quorum/`, and
  `~/PsyNet/demos/experiments/gibbs_within_sync/`.

## Choose the synchronization model

1. Classify the design before coding:
   - cohort/quorum: participants must enter a phase together;
   - grouped trials: group members should receive the same node or trial order;
   - phase barriers: participants work independently, then wait for partners;
   - live interaction: use the realtime websocket skill as well.
2. Prefer PsyNet server-side grouping and barriers over browser-side polling or
   custom JavaScript for shared state.
3. Decide what happens to late arrivals, no-shows, dropouts, and overflow
   participants before implementing the happy path.
4. Size the study in whole groups. Align `target_n_participants`,
   `initial_recruitment_size`, platform slots, and any over-recruitment buffer.
5. Make waiting fair: explain the expected wait, cap waits with
   `max_wait_time`, and provide filler tasks or a paid exit when waits can be
   long.

## PsyNet implementation hints

- Prefer `TrialMaker`s for organizing rounds. For choosing `StaticTrialMaker`
  vs chain-based makers, read `develop-experiment-back-end/SKILL.md`.
- Use `SimpleGrouper(group_type=..., initial_group_size=...)` to create cohorts
  and `GroupBarrier(id_=..., group_type=...)` to release group members together.
- Use `GroupBarrier(on_release=...)` for atomic shared updates such as role
  assignment, scoring, aggregation, or recording round outcomes.
- Sort `sync_group.participants` by participant ID before deterministic role
  assignment; PsyNet does not guarantee the stored order.
- Use `sync_group_type` on trial makers when all group members should follow the
  leader's node allocation and trial sequence.
- Put additional `GroupBarrier`s inside `Trial.show_trial` for phase boundaries
  such as submit, rate, reveal, score, or bonus computation.
- Read partner state through `participant.sync_group.participants`,
  participant vars, trial vars, node vars, or `on_release` outputs. Do not let
  the browser decide shared experiment state.
- Use `GroupCloser(group_type=...)` before regrouping participants with the same
  `group_type`.
- Use `join_existing_groups=True` only with a task-specific `join_criterion`
  that rejects stale, completed, or unsuitable groups.
- For lobbies/quorums, combine `SimpleGrouper(..., waiting_logic=...)` with
  filler work via `trial_maker.custom(...)`, as in `sync_quorum`.
- For chain or Gibbs designs, distinguish true co-presence from async
  across-participant chains. Use `wait_for_networks=True` when participants may
  otherwise exit while async network growth is still pending.
- Use `ChatRoom(room_id=f"group_{participant.sync_group.id}")` only for
  participant communication; keep phase advancement and scoring in barriers.
- Prefer engaging waiting trials over passive wait screens when waits may be
  long. Participants may be distracted or running multiple experiments at once;
  useful filler tasks can improve retention and reduce idle no-shows.
- Add participant-facing alerts for important transitions, such as an audible
  cue when a group is matched or when the participant is expected to act. Make
  sure alerts are compatible with browser autoplay rules and the study's audio
  consent/device requirements.
- Use visible timers, warning states, automatic staging/submission, and clear
  timeout behavior for timed phases. These patterns keep groups responsive and
  prevent one inactive participant from blocking everyone else indefinitely.

## Recruitment and platform design

- Treat Prolific, Connect, MTurk, Cint, or Lucid as recruitment layers. PsyNet
  should still own the lobby, grouping, timeout, overflow, and completion logic.
- Prefer Prolific or CloudResearch Connect for small scheduled cohorts because
  they support participant IDs, targeted recontact, messages, quotas, and manual
  review workflows.
- Put session time, time zone, expected waiting window, device/audio
  requirements, no-show policy, and partial-payment policy in the study
  description and participant instructions

## Validation

- Run `psynet test local` with at least as many bots as the group size, plus
  extra bots for late-arrival or top-up paths.
- Use serial bot tests with `advance_past_wait_pages(bots)` for deterministic
  barrier progression; use concurrent bot runs when arrival races matter.
- Assert group formation, active group size, role assignment, shared node/trial
  IDs, barrier IDs, `on_release` side effects, and failed/overflow exits.
- Test dropout and top-up behavior, not only a complete group that finishes.
- Test waiting-phase retention aids: filler trials should save usable data or
  stay harmless, alerts should fire at the intended transition, timers should be
  visible, and automatic submissions should record a valid response or failure
  reason.
- For participant-facing waiting rooms or multi-browser behavior, collect
  separate browser-context evidence. Use `record-participant-video/SKILL.md` for
  participant-flow recordings.
- Inspect exported data to confirm group IDs, platform IDs, roles, phase
  timestamps, responses, failures, and partial-completion reasons are analyzable.

## Common failures

- Make sure to close groups with `GroupCloser`.
- Do not leave default wait limits in place for real recruitment sessions
  without checking whether they are appropriate.
- Do not assume top-ups are safe; define exactly which groups may accept late
  participants.
- Do not set recruitment targets that leave stranded participants unable to form
  a full group.
- Do not auto-reject participants who waited or were stranded by no-shows; plan
  a platform-compliant return, partial payment, or manual review path.
