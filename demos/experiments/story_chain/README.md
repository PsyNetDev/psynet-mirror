# README

Groups of three write a story together, one sentence at a time. Members take
turns in seat order; while one writes, the others see the story so far on a
waiting screen. After two rounds of turns everyone rates the story.

Good reference for turns one after the other in a fixed group: each turn is
one cued round, `StoryTurn.cue(..., round=turn)`, whose definition stores the
turn's writer, chosen once with `group_seats`. The writer stores their
sentence in `node.var` as soon as they submit it, and a turn that ends
without one stores `None`, so the export has one row per turn. A writer who
runs out of time adds nothing, a member who leaves or goes silent plays no
more turns and the next seat writes in their place, the last member left goes
on to the story so far, and someone who finds no group is told so. The bot
test plays a full story, one whose group dissolves while the writer is still
writing, and one whose writer goes silent and is left behind before the last
writer leaves while the other member waits.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
