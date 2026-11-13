# README

Live bargaining in a cohort of four that is re-paired every round. Each pair
bargains over 10 coins for up to a minute: either player can propose a split
at any time, and change it, and either can accept their partner's current
proposal. Accepting ends the round with a deal; if the time runs out first,
nobody is paid.

It is the live counterpart of `ultimatum_pairing`, and uses the same cohort
and pairing set-up: a `SimpleGrouper` forms the cohort, a `Regrouper` pairs
it every round, and each round is one cued trial per player whose
`show_trial` starts the pair's live session. Accepting a proposal names the
proposal the player saw, so a proposal that changed in the meantime is
rejected rather than accepted by mistake.

## Usage

Run `psynet debug local` and open the participant link in four browser
windows. `psynet test local` plays the game with bots, which settle on a
6–4 split.
