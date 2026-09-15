Changed ``psynet setup`` so that choosing a dedicated ``.venv`` completes in a
single invocation: setup creates the environment, installs the same PsyNet into
it, and finishes there so every experiment file and lockfile is produced by the
PsyNet the experiment will use. Setup now also ensures the experiment has a Git
repository for deployment: an experiment already inside a repository uses it,
while one that is not in a repository (or that its surrounding repository
ignores) gets a dedicated repository via ``git init``. After finishing, setup
tells you to activate the new environment when it created one on your behalf,
then how to launch the experiment.
