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
`show_trial` starts the pair's live session. The stake is the round's trial
definition, which `cue` chooses once for the pair, and which the trial
passes to the game as its `settings`. Accepting a proposal names the
proposal the player saw, so a proposal that changed in the meantime is
rejected rather than accepted by mistake.

## Usage

Run `psynet debug local` and open the participant link in four browser
windows. `psynet test local` plays the game with bots, which settle on a
split that gives one of them 4 coins.
