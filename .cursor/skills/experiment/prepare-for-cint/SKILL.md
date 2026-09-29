---
name: prepare-for-cint
description: Make an existing PsyNet experiment ready for Cint/Lucid recruitment by collecting per-target decisions (language-country pairs, qualifications, wages), wiring get_lucid_settings into experiment.py, preparing the qualification-generation script, and reporting what still blocks deployment. Use when preparing an experiment for Cint/Lucid.
compatibility: Requires target experiment checkout; do not use production Cint/Lucid/AWS credentials for local readiness work.
---

# Prepare for Cint

This skill owns Cint/Lucid recruiter settings and qualification files. For
translation marking or catalog extraction, use `prepare-for-translation`. For
servers, deployment, export, or teardown, use `deploy-experiment`.

## Read first

Read these pages before acting. In a PsyNet source checkout read `docs/<page>.rst`; otherwise fetch `https://psynetdev.gitlab.io/PsyNet/<page>.html`.

- `deploy/recruiters/cint`: recruiter settings, consent, qualifications, and the qualification script
- `deploy/recruiters/index`: choosing and configuring a recruiter
- `code/participants/payment`: `wage_per_hour` and bonuses
- `code/participants/internationalization`: locales and translated experiments

The CINT guide is the reference for every setting named below; do not restate
it to the user, link to it.

## 1. Collect the deployment decisions

Read `experiment.py`, `config.txt`, any `qualifications/` and `locales/`
folders, and any existing qualification scripts first; preserve their
entries. Then ask the user for anything missing, explaining briefly why each
matters and linking the CINT guide:

- the language-country pairs to recruit from;
- the qualifications to enable, if any (`TIMEOUT v1` is added automatically).
  If the user is unsure, ask what the experiment measures and suggest a
  minimal set, for example audio playback for an audio study;
- a wage source for each country. Never guess wages; leave them blank until
  the user supplies an approved source.

Each deployment targets one pair, and `locale`, `LANGUAGE`, `COUNTRY`, and
`wage_per_hour` must be changed for every deployment. Record the targets in
`cint_deployment_targets.csv` in the experiment root, one row per target:

```text
locale,language,country,language_tag,country_tag,wage_per_hour,qualification_file
```

If targets are unknown, write the header only and continue with the generic
setup below. Do not invent languages, countries, locales, tags, or wages.

## 2. Check translations and tags

- For each target locale, check that `locales/<locale>/LC_MESSAGES/experiment.po`
  exists. If one is missing, do not generate it here: keep going, leave that
  locale inactive, and report the `psynet translate` command to run
  (`prepare-for-translation`).
- Lucid tags come from `psynet lucid locale`, which needs API access. Without
  it, derive provisional tags from the requested names and mark them
  unverified in the report.

## 3. Edit `experiment.py`

Follow the CINT guide's configuration example with the smallest edit:
`LANGUAGE`, `COUNTRY`, and `LUCID_CONFIG_PATH` constants,
`recruiter_settings = get_lucid_settings(...)` with every timeout and
`bid_incidence` written out, and a class-level `Exp.config` containing
`**recruiter_settings`, `locale`, `wage_per_hour`, and `publish_experiment`.
Do not also set `recruiter`; `get_lucid_settings` sets it. Keep existing
config keys, and tell the user which values are study-specific.

Until real targets exist, use `ENG` / `GB` / `en` as a structural placeholder.
`get_lucid_settings` reads the qualification file on import, so when no real
file exists yet, copy `assets/example_lucid_ENG_GB.json` to
`qualifications/lucid/lucid-ENG-GB.json` and report it as a placeholder that
must be regenerated. Do not add mock paths or alternative settings.

## 4. Prepare the qualification script

Create `create_qualifications.py` in the experiment root from the CINT guide's
example, or update the existing script under its current name. Enable only
the target tuples and qualifications the user chose; leave everything else
commented out.

Generating the files needs `lucid_api_key` and `lucid_sha1_hashing_key`.
Check whether they are configured without printing, copying, or committing
them. Run the script only when they are; otherwise tell the user to run
`python create_qualifications.py` locally once they have access.

## 5. Validate

For each known target, check that the tags match `psynet lucid locale` (or
are marked unverified), the locale is supported and its `.po` file exists,
`LUCID_CONFIG_PATH` resolves to a generated file, and the wage comes from the
approved source. Then run `psynet test local` to confirm the experiment still
loads and runs.

## 6. Report

Write `CINT_READINESS_REPORT.md` and summarize it in chat. Mark each item
complete, blocked, or needing review; do not collapse blockers into one line:

- experiment parameters and which ones are study-specific;
- deployment targets, with tag verification status and blank wages;
- the qualification script, enabled targets and filters, and whether real
  generation ran;
- Lucid API access (available, missing, or not checked; never values);
- real and placeholder qualification files;
- translation files and the commands still to run;
- commands run and their results;
- the steps the user must take before each deployment: verify tags, run
  the qualification script, review translations, fill wages, and set
  `locale`, `LANGUAGE`, `COUNTRY`, and `wage_per_hour` from the target's row;
- overall status: `target-ready`, `parameter-ready only`, or `blocked`.

## Rules

- Preserve existing experiment logic and deployment notes.
- Never configure, inspect, print, or commit AWS, Cint, Lucid, Prolific, or
  other production credentials, and do not use real credentials for local
  readiness work unless the user provides a safe workflow.
- Never present a copied placeholder JSON as a generated qualification file.
- Report missing locales, wages, and qualification decisions as blockers for
  target-specific readiness, not as optional extras.
