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
probably closed their page. They leave the cohort as well as the pair, so
the next pairing doesn't wait for them, and their partner goes on to a game
page without a game. If they come back, the last page tells them they
didn't arrive in time. A player who reached the game but hasn't opened its
page 30 seconds later, for example because they closed their page just as
the pair formed, isn't coming either: the game ends at once without a deal,
and the feedback tells their partner that they didn't arrive. A player who
leaves the game page for 30 seconds has left the game, which then ends. In
both cases the `PlayLiveGame`'s `absent_action="leave_group"` takes the
absent player out of the cohort when the game's result is saved, so the
next pairing doesn't wait for them either, and the last page tells them why
the game is over for them if they come back. The export's `arrived`,
`partner_arrived` and `n_no_shows` columns tell no-show rounds apart from
pairs that bargained without a deal; a round that a player left mid-game
looks like one without a deal. A player who didn't submit their game page
has `None` in these columns.

A round can take up to 30 seconds for the partner to arrive, a minute of
bargaining and the result and feedback pages, so a pair that finishes early
waits up to two minutes from the last pairing for the other pair to come
back, rather than being paired with each other again.

## Usage

Run `psynet debug local` and open the participant link in four browser
windows. `psynet test local` plays the game with bots, which settle on a
split that gives one of them 4 coins.
