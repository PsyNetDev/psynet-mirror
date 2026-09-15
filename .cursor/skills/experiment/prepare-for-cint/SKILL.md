---
name: prepare-for-cint
description: Prepare a PsyNet experiment for Cint/Lucid recruitment by adding required recruiter settings, locale and wage parameters, qualification-generation tooling, and readiness validation. Use when making an existing experiment ready for Cint/Lucid recruitment.
compatibility: Requires target experiment checkout; do not use production Cint/Lucid/AWS credentials for local readiness work.
---

# Prepare for Cint

This skill owns Cint/Lucid recruiter parameters and qualification files. For
translation marking or POT extraction, use `prepare-for-translation`. For server
provisioning, SSH deployment, export, app destruction, or EC2 teardown, use
`deploy-experiment`.

## Prerequisites

- Read the target experiment's `experiment.py`, `config.txt`,
  `requirements.txt`, existing `qualifications/`, `locales/`, and deployment
  notes before editing.
- Inspect any existing `create_qualifications.py`, `qualifications.py`, or
  Lucid/Cint helper scripts. Preserve existing entries and comments.
- Read `references/create_qualifications_template.py` before creating a new
  qualification-generation script.
- Read `assets/example_lucid_ENG_GB.json` as a shape example for generated
  Lucid qualification JSON. Do not treat it as a deployable qualification file
  for the target experiment.

## Workflow

Follow `references/cint-workflow.md` for the full phased workflow (deployment context, recruiter settings, qualification generation, validation, and commit checklist).

When complete, write the deliverable using `references/readiness-report.md`.

## Rules

- Preserve existing experiment logic and deployment notes.
- Do not configure, inspect, print, or commit real AWS, Cint, Lucid, Prolific, or
  other production credentials.
- Do not use custom or real service credentials for local readiness work unless
  the user explicitly provides a safe deployment workflow.
- Do not claim a copied placeholder Lucid JSON is a real generated
  qualification file. It must be documented as needing regeneration before
  deployment.
- Do not treat missing locales, wages, or qualification decisions as optional;
  report them as blockers for target-specific Cint deployment readiness.
