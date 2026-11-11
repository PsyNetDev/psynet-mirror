#!/bin/sh
# Install PsyNet's dependencies (experiment and demos extras) into the image's
# Python. Both CI images, Dockerfile and Dockerfile.playwright, run this, so
# they resolve the same versions.
#
# Run it next to copies of pyproject.toml and dallinger-dev-requirements.txt,
# a vendored snapshot of Dallinger's dev requirements, so that parallel CI
# Docker builds do not depend on raw.githubusercontent.com availability.
#
# Compile for the full Python version of the interpreter on PATH: uv reads
# "3.11" as 3.11.0.
set -eu
python_version="$(python -c 'import platform; print(platform.python_version())')"
uv pip compile --python-version "$python_version" pyproject.toml \
    --extra experiment --extra demos \
    --constraint dallinger-dev-requirements.txt \
    --output-file constraints.txt
uv pip install --no-cache --system -r constraints.txt
