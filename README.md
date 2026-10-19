![PsyNet logo](https://gitlab.com/PsyNetDev/PsyNet/-/raw/master/psynet/resources/logo.svg)

[![Pipeline](https://gitlab.com/PsyNetDev/PsyNet/badges/master/pipeline.svg?ignore_skipped=true)](https://gitlab.com/PsyNetDev/PsyNet/-/pipelines)
[![Latest release](https://gitlab.com/PsyNetDev/PsyNet/-/badges/release.svg)](https://gitlab.com/PsyNetDev/PsyNet/-/releases)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/PsyNetDev/psynet-mirror)

PsyNet is a Python framework for behavioral experiments that are difficult to
run on conventional platforms: procedures that adapt to each response, chains
in which one participant's response becomes the next participant's stimulus,
ratings balanced across thousands of stimuli, and groups of participants
interacting in real time. It builds on [Dallinger](https://dallinger.readthedocs.io/)
and provides recruitment and payment, testing with simulated participants,
deployment, monitoring and data export.

**[Read the documentation](https://psynetdev.gitlab.io/PsyNet/)**

## Get started

First install uv, Git, Docker, Google Chrome, the PostgreSQL client library
and the Heroku CLI ([install guide](https://psynetdev.gitlab.io/PsyNet/install.html)).
On Windows, use WSL (Ubuntu). Then create an experiment and run it:

```bash
mkdir my_experiment && cd my_experiment
uv venv --python 3.14 && source .venv/bin/activate
uv pip install psynet
psynet setup            # starter experiment, Git repository, agent instructions
psynet services ensure  # starts PostgreSQL and Redis in Docker if needed
psynet debug local      # opens the dashboard and the participant view
```

Then open the folder in a coding agent (Cursor, Claude Code, Codex, ...) and
describe your study, or write the code yourself, starting from
[Creating an experiment](https://psynetdev.gitlab.io/PsyNet/code/project/creating_an_experiment.html).
The [Quickstart](https://psynetdev.gitlab.io/PsyNet/quickstart.html) walks
through this in about ten minutes.

## Learn more

- [Demos](https://psynetdev.gitlab.io/PsyNet/demos/index.html): working experiments to copy from.
- [Deploy](https://psynetdev.gitlab.io/PsyNet/deploy/index.html): servers, recruiters and going live.
- [What's new](https://psynetdev.gitlab.io/PsyNet/whats_new/index.html): release notes and upgrade guides.
- [Contributing](https://psynetdev.gitlab.io/PsyNet/developer/index.html): developing PsyNet itself.

## Credits

PsyNet is primarily developed by Peter Harrison, Frank Höger, Pol van Rijn and
Nori Jacoby, with contributions from many other users. It is released under
the [MIT License](https://gitlab.com/PsyNetDev/PsyNet/-/blob/master/LICENSE).
