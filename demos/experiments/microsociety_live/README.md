# README

A fishing society on a lake, played live, that keeps going while its members
come and go. Every member steers a boat between eight fishing spots. Every
few seconds each boat catches a noisy number of fish around its spot's
hidden average, and everyone sees who caught what, where, so members can
learn where to fish from each other as they play.

It is the live counterpart of `microsociety`, played as one continuous game:
newcomers sail onto the lake while the others fish, after seeing where the
society has been catching fish lately and the tips of members who have left.
Each member fishes for 40 seconds, and when a newcomer makes the lake more
crowded than three boats, the longest-serving member retires. The lake
closes once nobody is left on it.

It shows a live game that players join while it runs (`join_running_game`
and `on_add`), in which each player can finish before the others
(`is_done`), and which records its history with `record` and `moments`.

## Usage

Run `psynet debug local --legacy` and open the participant link in two
browser windows, and in more windows later to join as newcomers. `--legacy`
runs gunicorn, the web server deployed experiments use, instead of the
auto-reloading development server, under which the lake's catches can show
late. `psynet test local`
plays with bots, which follow whoever catches the most.
