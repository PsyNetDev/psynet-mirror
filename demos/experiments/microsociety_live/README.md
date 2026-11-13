# README

A fishing society on a lake, played live, that keeps going while its members
are replaced. Each round, every member steers a boat between eight fishing
spots. Every few seconds each boat catches a noisy number of fish around its
spot's hidden average, and everyone sees who caught what, where, so members
can learn where to fish from each other as they play.

It is the live counterpart of `microsociety`, with the same membership
rules: newcomers are admitted at the start of a round, where they see the
society's recent catches and the tips of members who have left, and when a
round had more than three members the longest-serving member retires at its
end.

## Usage

Run `psynet debug local` and open the participant link in three browser
windows, and in a fourth later to join as a newcomer. `psynet test local`
plays with bots, which follow whoever catches the most.
