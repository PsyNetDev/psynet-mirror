# Installation instructions

This demo is a PsyNet experiment. Install PsyNet in a virtual environment and
run it with the standard commands; see the
[PsyNet installation docs](https://psynetdev.gitlab.io/PsyNet/installation/index.html).

```bash
git init
uv venv --python 3.13
source .venv/bin/activate
uv pip install psynet
psynet setup
psynet debug local
```

To run the experiment in Docker after that setup, use
`psynet debug local --docker`.
