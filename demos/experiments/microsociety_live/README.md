# README

A fishing society on a lake, played live, that keeps going while its members
come and go. Every member steers a boat between eight fishing spots. Every
few seconds each boat catches a noisy number of fish around its spot's
hidden average, and everyone sees who caught what, where, so members can
learn where to fish from each other as they play.

It is the live counterpart of `microsociety`, played as one continuous game.
The first participant founds the society and opens its lake at once, alone,
so nobody waits for anyone. Newcomers sail onto the lake while the others
fish, after reading the tips of members who have left. Each member fishes
for 40 seconds, and when a newcomer makes the lake more crowded than three
boats, the longest-serving member retires and leaves a tip for the newcomers
who come after them. The lake closes once nobody is left on it, and the next
participant founds a new society with a new lake.

It shows a live game that players join while it runs (`join_running_game`
and `on_add`), in which each player can finish before the others
(`is_done`), and which records its history with `record` and `moments`.

## Usage

Run `psynet debug local --legacy` and open the participant link in a
browser window, and in more windows later to join as newcomers. `--legacy`
runs gunicorn, the web server deployed experiments use, instead of the
auto-reloading development server, under which the lake's catches can show
late. `psynet test local`
plays with bots, which follow whoever catches the most.
