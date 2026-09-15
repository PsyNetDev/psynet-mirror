# Slack Announcement Guidance

This file is runtime configuration for `psynet dev release announce`
(implemented in the sibling `slack_announcement.py`). It controls the
wording of the announcement envelope. The experimenter-facing summary of
changes is not generated from this file: it is written by the release
manager (usually with AI-agent assistance, following the repo's release
skill) and passed to the command via `--summary-file`.

## Stable Release Description

This is a stable minor release with new experiment-building features, demo
updates, export improvements, and deployment/dependency cleanups.

## Experimenter Summary Intro

Here are the key changes relevant for experimenters:

## Stable Upgrade Instructions

Upgrade options:

- Standard PyPI: `pip install --upgrade psynet`
- PyPI with demo dependencies: `pip install --upgrade "psynet[demos]"`
- Editable installation: `git fetch --tags && git checkout v{version} && pip install -e .`
- Editable installation with demos: `git fetch --tags && git checkout v{version} && pip install -e ".[demos]"`
