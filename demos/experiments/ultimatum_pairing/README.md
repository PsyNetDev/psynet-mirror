# README

An ultimatum game played in cohorts. Players wait in a lobby until a cohort
forms, or start in a smaller cohort if nobody else arrives in time. Every
round, the cohort is randomly re-paired into proposers and responders, an odd
player out sits out, and nobody is failed for being slow: a player who isn't
back in time for a split joins the next round, and one who closes their tab
mid-round is taken out of their pair and cohort, so nobody waits for them.
An anonymous `GroupPrompt` shows the pair,
with a tick once the partner has decided, and then both decisions in speech
bubbles; partners appear as the same grey figure, so nobody recognises a
partner from an earlier round.

Good reference for nesting a `Regrouper` inside persistent cohorts made by a
`SimpleGrouper` with `start_short_after` and top-ups, with re-pairing that
avoids last round's partner and alternates roles (short `form_groups` and
`assign_roles` overrides in `pairing.py`) and `stop_top_ups_after_rounds`,
which turns latecomers away once the cohort's second round starts. Its bot
test uses `regroup_now` to start a round at the deadline without waiting for
it.
Each round is one cued trial per player (`Trial.cue(...)` with
`sync_group_type = PAIR`, in a `switch` on the player's `round_status`), so
the pair's offer and result live on a node shared by its two trials, sit-outs
get a page instead of a trial, and the basic data is read from trials and
nodes.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
