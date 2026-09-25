# The `data` directory

The `data` directory holds source material that stays on your machine. The
stock `deploy.toml` leaves it out of the deployment package.

In this demo, `data/music_stimuli` contains the source music and onset files.
The experiment turns them into tapping stimuli with the REPP library, using
function assets (`asset(generate_music_stimulus, is_folder=True)`).
PsyNet runs the generation at each launch and deploys only the generated
stimuli, skipping the upload when identical files are already stored.

`data/iso_bot_responses` contains example tapping recordings used by the
test bots.

Ready-made stimuli that need no processing belong in `static/` instead,
referred to by URL. See the `simple_rating` pipeline demo.
