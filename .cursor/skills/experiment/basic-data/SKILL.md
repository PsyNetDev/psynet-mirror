---
name: basic-data
description: Implement basic data export functionality. Use when implementing an experiment to create clean export csv files that are helpful for future analysis.
---

# Basic data

## Read first

Read these pages before acting. Get the docs folder once with `psynet docs path`, then read `<folder>/<page>.txt` (or `.rst` in a source checkout) and search with `rg -n -i "<term>" <folder>`.

- `data/basic_data` — writing `get_basic_data` and the files it exports
- `data/exporting_data` — how to export data and where exports land
- `data/what_an_export_contains` — the raw database tables in an export

## Checklist

1. From the research question, list the units of analysis (rows) and the
   variables (columns) each analysis needs. Plan one table per unit, such as
   trials and participants.
2. Implement `get_basic_data` as described in `data/basic_data`, returning
   data frames only when `context == "export"`.
3. Give every row the IDs that trace it back to the database, such as
   `trial_id` and `participant_id`.
4. Leave out identifiers and sensitive values; basic data is not anonymized.
5. Run `psynet debug local`, take a few participants through the experiment,
   and export with `psynet export local`. Check the basic data files: row
   counts match the expected numbers of participants and trials, and no
   column is unexpectedly empty.
6. If participants interact in groups, also follow
   `basic-data-dyadic-experiment/SKILL.md`.
