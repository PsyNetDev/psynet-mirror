# README

Groups of three write a story together, one sentence at a time. Members take
turns in seat order; while one writes, the others see the story so far on a
waiting screen. After two rounds of turns everyone rates the story.

Good reference for turns one after the other in a fixed group: each turn is
one cued round, `StoryTurn.cue(..., round=turn)`, whose definition stores the
turn's writer, chosen once with `group_seats`. The writer stores their
sentence in `trial.group_round.var` as soon as they submit it, and the last page reads the
story with `SyncGroup.rounds("story")`, which also works after the group has
ended. The bot test plays a full story in which one writer runs out of time.

## Dropouts and edge cases

- A writer who runs out of time adds nothing that turn (the sentence is
  `None`) and stays in the group.
- A member who returns the study, or takes more than `LATE_AFTER` seconds to
  finish a turn, leaves the group and plays no more turns. If they were due to
  write, the member in the next seat writes instead, so turns become uneven
  (for example A, C, C).
- A writer who has left the group stores nothing, unless the group dissolved
  while they wrote, in which case their sentence ends the story. When a
  member's trial finishes and the turn still has no sentence, it stores
  `None`, so every finished turn has a `sentence`. The writer trial's
  `sync_group_outcome` says why a sentence is `None`: `"stayed"` if they ran
  out of time, otherwise why they left the group.
- The group continues while two members remain. When only one is left, the
  group dissolves and that member goes on to the story so far. A sentence
  written while the group dissolved still counts.
- Someone who finds no group within `GROUPER_WAIT` seconds is told so and
  finishes.
- A member the experimenter removes on the dashboard writes no more turns
  and is told they were removed from their group.

The `turn` export has one row per turn; its `finished` column tells a turn
that stored `None` from one that never finished.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
