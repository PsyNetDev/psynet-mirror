# README

Live bargaining in a cohort of four that is re-paired every round. Each pair
bargains over a stake of 10 or 20 coins, chosen at random for the pair, for
up to a minute: either player can propose a split
at any time, and change it, and either can accept their partner's current
proposal. Accepting ends the round with a deal; if the time runs out first,
nobody is paid.

It is the live counterpart of `ultimatum_pairing`, and uses the same cohort
and pairing set-up: a `SimpleGrouper` forms the cohort, a `Regrouper` pairs
it every round, and each round is one cued trial per player whose
`show_trial` starts the pair's live game. The stake is the round's trial
definition, which `cue` chooses once for the pair, and which the trial
passes to the game as its `settings`. Accepting a proposal names the
proposal the player saw, so a proposal that changed in the meantime is
rejected rather than accepted by mistake.

A player who hasn't reached the game 30 seconds after being paired has
probably closed their page, so they are failed (`late_action="fail"`),
which takes them out of the cohort as well as the pair. The next pairing
doesn't wait for them, and their partner goes on to a game page without a
game and is paired again next round. A player who reached the game but
hasn't opened its page 30 seconds later, for example because they closed
their page just as the pair formed, isn't coming either: the game ends at
once without a deal, and the feedback tells their partner that they didn't
arrive. A player who leaves the game page for 30 seconds has left the game,
which then ends, and the feedback tells their partner so. In both cases the
`PlayLiveGame`'s `absent_action="fail"` fails the absent player when the
game's result is saved, so the next pairing doesn't wait for them either.
Failing isn't a penalty: it ends a session that can no longer contribute,
and failed players keep what they earned.

The cohort keeps `below_quorum="continue_without_group"`: players leave it
as they finish, so failing those left below its quorum could fail the last
players still playing. When fewer than two remain, the rounds end for the
last player instead.

The game's `end_reason` says how each round ended: `"deal"`, `"no_show"`
when a player didn't open the game (`"not_joined"` when neither did),
PsyNet's `"players_left"` when a player left it, or `"finished"` when the
time ran out. The feedback page uses it to tell the player what happened,
and the export's `player_round` table has it in its `end_reason` column, so
there `"finished"` means a round that ran out of time without a deal:
it's PsyNet's reason for a game whose time is up. The `arrived` and
`partner_arrived` columns say who didn't arrive. The game's columns come
from its outcome, so a player who closed their page still has them; they
are `None` only for a player who had no game, because their partner didn't
reach it.

A round can take up to 30 seconds for the partner to arrive, a minute of
bargaining and the result and feedback pages, so a pair that finishes early
waits up to two minutes from the last pairing for the other pair to come
back, rather than being paired with each other again.

## Usage

Run `psynet debug local` and open the participant link in four browser
windows. `psynet test local` plays the game with bots, which settle on a
split that gives one of them 4 coins.
