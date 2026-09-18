# Source notes for synchronous PsyNet experiments

These notes summarize the source review behind
`synchronous-experiments/SKILL.md`. Refresh them against current PsyNet
and platform docs when a study is near deployment.

## PsyNet package and docs

- `psynet.sync.Barrier` holds participants in a waiting area until
  `choose_who_to_release` releases them. It supports `waiting_logic`,
  `waiting_logic_expected_repetitions`, `max_wait_time`, and time-credit
  handling.
- `psynet.sync.GroupBarrier` releases all active members of a `SyncGroup` once
  they are waiting at the same barrier. It checks `min_group_size`, can wait for
  top-ups, can fail under-quota groups, and accepts `on_release(group,
  participants)` for atomic shared updates.
- `psynet.sync.SimpleGrouper` creates `SyncGroup`s by waiting for `batch_size`
  participants and partitioning them into groups of `initial_group_size`.
  `min_group_size`, `max_group_size`, `join_existing_groups`, and
  `join_criterion` control top-up behavior.
- `psynet.sync.GroupCloser` closes a group before participants are regrouped
  with the same `group_type`.
- `participant.sync_group` is convenient when the participant has one active
  group. Use `participant.active_sync_groups[group_type]` when multiple group
  namespaces may be active.
- Trial makers support `sync_group_type`. When it is set, the leader's ordinary
  node allocation drives the group and followers receive matching trials.
- Trial-maker synchronization uses internal `GroupBarrier`s such as
  `init_participant` and `prepare_trial`; `sync_group_max_wait_time` defaults to
  45 seconds.
- `wait_while` and `WaitPage` are useful for single-participant waits or
  background readiness, but they do not replace group barriers.
- `RecruitmentCriterion`, `recruit_mode`, `target_n_participants`, and
  `initial_recruitment_size` determine how PsyNet asks for more participants.
  Synchronous studies should size these values in whole groups.
- PsyNet does not provide a first-class calendar appointment scheduler. Session
  timing is built from recruitment platform controls, PsyNet lobbies/barriers,
  and custom `wait_while` checks when needed.

## PsyNet demos

- `simple_sync_group` is the minimal grouping and regrouping pattern:
  `SimpleGrouper`, role assignment with `GroupBarrier(on_release=...)`,
  `GroupCloser`, then a second group.
- `create_rate_sync` shows a group-of-three create/rate/reveal flow with
  barriers after creation and rating, partner state read from
  `participant.sync_group.participants`, and shared output written in
  `on_release`.
- `rock_paper_scissors` shows dyadic synchronized static trials, barriers inside
  `show_trial`, server-side scoring in `on_release`, and a `ChatRoom` scoped to
  `participant.sync_group.id` for communication after the round.
- `sync_quorum` shows a waiting-room/quorum pattern where participants complete
  filler trials while waiting for enough active participants.
- `gibbs_within_sync` shows `GibbsTrialMaker(sync_group_type=...)`,
  `join_existing_groups=True`, a task-specific `join_criterion`, dropout
  simulation, and a top-up participant joining a still-active group.

## Practical group-search findings

Authenticated search of the `computational-audition-lab` GitLab group found 479
non-archived projects. Group-level blob search was unavailable with basic search,
so project-level basic blob searches were run for current PsyNet synchronization
terms including `SimpleGrouper`, `GroupBarrier`, `sync_group_type`,
`GroupCloser`, `join_existing_groups`, `join_criterion`, `waiting_logic`,
`quorum`, `synchronous`, `dyad`, and `Prolific`.

The search found little direct use of the current native synchronization
primitives in private experiment repositories, but many PsyNet experiment
repositories and group-derived skill notes. The useful tacit lessons were:

- prefer server-side PsyNet state and asynchronous/background processing over
  blocking participant request cycles;
- store platform qualification and recruitment configuration in inspectable JSON
  or config helpers rather than burying it in participant logic;
- provide explicit unsuccessful-end and partial-compensation paths for
  participants who spend time but cannot complete the intended path;
- use engaging waiting content instead of passive waiting screens when matching
  can take time;
- use attention-capturing cues such as sounds or visual warnings when
  participants are matched or expected to act;
- use timers, warning states, and automatic submission or timeout handling to
  keep group phases responsive;
- avoid copying older ad hoc coordination patterns when current PsyNet barriers,
  `sync_group_type`, and chatrooms can express the design.

One repository reference in this workspace points to
`computational-audition-lab/niche-lucas` for a rolling inventory replication.
That project is a collective create/rate-style PsyNet study with practical
lessons around preserving network logic, condition structure, timing,
validation, and data-recording conventions when porting collective designs.

## Recruitment platform notes

### Prolific

- Prolific supports participant IDs, study URL parameters, participant groups,
  custom allowlists, messages, approval/review states, bonuses, and longitudinal
  waves/projects.
- Prolific help for interviews and focus groups says researchers must manage
  scheduling externally; it is not a full appointment scheduler.
- Longitudinal waves require participants to complete and usually be approved in
  previous waves before later waves become available. Participant counts should
  stay the same or decrease across waves.
- For partial participation, technical issues, or no-show-related stranded
  participants, use returns/manual review/bonus workflows rather than reflexive
  rejection.

### CloudResearch Connect

- Connect external projects send participants to the experiment URL; record
  Connect IDs so platform records can be matched to PsyNet data.
- Included participants, groups, prior-project targeting, scheduled messages,
  and longitudinal project guidance support cohort and wave management.
- Completion redirects/codes should represent the PsyNet exit path. Partial
  completes can be configured for screened-out or partially completed paths when
  payment and redirect logic are aligned.

### MTurk

- MTurk can host external PsyNet studies via `ExternalQuestion`; it appends
  assignment and worker identifiers and expects completion submission back to
  MTurk.
- `CreateHIT` controls `MaxAssignments`, `LifetimeInSeconds`,
  `AssignmentDurationInSeconds`, qualifications, rewards, and review settings.
  These are enough for coarse timing and capacity, but not ergonomic
  appointment scheduling.

### Cint/Lucid

- Cint fielding supports scheduled, live, paused, resumed, and completed runs
  for target groups.
- These platforms are optimized for survey fielding and redirect/status
  accounting. Use them cautiously for small tightly synchronized groups unless
  the researcher has explicit panel/API support and robust outcome handling.

## Search terms to reuse

Use these when refreshing this skill: `SimpleGrouper`, `GroupBarrier`,
`GroupCloser`, `SyncGroup`, `sync_group_type`, `sync_group_max_wait_time`,
`participant.sync_group`, `active_sync_groups`, `waiting_logic`,
`join_existing_groups`, `join_criterion`, `wait_while`, `WaitPage`,
`RecruitmentCriterion`, `recruit_mode`, `target_n_participants`,
`initial_recruitment_size`, `advance_past_wait_pages`, `quorum`, `dyad`,
`scheduled`, `participant group`, `allowlist`, `partial complete`, and
`completion redirect`.
