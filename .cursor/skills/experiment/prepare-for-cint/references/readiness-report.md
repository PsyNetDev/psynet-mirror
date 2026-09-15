# Cint Readiness Report

End with a concise report that explicitly lists every required step and whether
it is complete, blocked, skipped, or not applicable. Do not collapse blockers
into a single final status; reviewers should see exactly what remains.

Use this structure:

- `Experiment parameters`: imports, `LANGUAGE`, `COUNTRY`,
  `LUCID_CONFIG_PATH`, `get_lucid_settings`, class-level `Exp.config`, recruiter,
  locale, wage, and `publish_experiment`.
- `Parameter review notes`: explain which Cint parameters likely need
  experimenter review, especially timeouts, `bid_incidence`, locale, language
  tag, country tag, and per-target wage.
- `Deployment targets`: language-country pairs, PsyNet locale, Lucid tags,
  whether they were verified with `psynet lucid locale`, and any provisional
  source used when API access was unavailable. Include an empty `wage_per_hour`
  column when wages have not been supplied.
- `Deployment CSV`: path, rows added, and any blank wage values requiring human
  review.
- `Qualification tooling`: script path, enabled target tuples, enabled filters,
  and whether real generation was attempted.
- `Lucid API access`: available, missing, unusable, or not checked. Never include
  secret values.
- `Qualification files`: real files generated and temporary placeholder JSON
  files created, with placeholders clearly marked as needing regeneration.
- `Translation files`: per-target `.po` status, warnings for missing files, and
  the exact `psynet translate ...` command needed to create them later.
- `Validation run`: commands run and whether they passed.
- `What the experimenter needs to know`: concise explanations of locale, Lucid
  tags, wage, qualification files, selected filters, API access, and timing/
  incidence parameters.
- `Remaining decisions/blockers`: targets, filters, locale files, wages, Lucid
  credentials, or anything else needed before deployment.
- `Local generation reminder`: state that `create_qualifications.py` has been
  prepared according to the requested targets/filters, but the experimenter must
  run it in their own local repo terminal with valid Lucid API credentials to
  generate real JSON files.
- `Final deployment warning`: emphasize the exact steps the experimenter must
  complete after this agent pass: run `psynet lucid locale` with API access and
  compare tags against `cint_deployment_targets.csv` because locally derived
  tags can be wrong; inspect `create_qualifications.py` before running it because
  it controls Cint screening filters and target JSON files; confirm all target
  `.po` files exist and have been reviewed because `locale` controls the
  participant language; fill `wage_per_hour` for every row because wages are
  country-specific; then, before each deployment, update `locale`, `LANGUAGE`,
  `COUNTRY`, and `wage_per_hour` from `cint_deployment_targets.csv`, either
  manually or with an AI assistant.
- `Readiness status`: one of `target-ready`, `parameter-ready only`, or
  `blocked`.

In the final chat response, repeat the `Final deployment warning` steps in
plain language even if they are already in `CINT_READINESS_REPORT.md`, so the
experimenter sees the next actions without opening the report.

### Example report shape

```text
Cint Readiness Report

Experiment parameters
- COMPLETE: Added get_lucid_settings import.
- COMPLETE: Added LANGUAGE, COUNTRY, and computed LUCID_CONFIG_PATH.
- COMPLETE: Added class-level Exp.config with recruiter, locale,
  recruiter_settings, wage_per_hour, and publish_experiment.
- REVIEW: LANGUAGE/COUNTRY/locale/wage_per_hour must be updated for each real
  deployment target.
- REVIEW: LUCID_CONFIG_PATH is computed as
  f"qualifications/lucid/lucid-{LANGUAGE}-{COUNTRY}.json"; if this file was
  copied from the example JSON, regenerate it before deployment.
- REVIEW: Before each deployment, re-check LANGUAGE, COUNTRY, locale,
  the generated qualification file selected by LUCID_CONFIG_PATH, and
  wage_per_hour against that target's row in cint_deployment_targets.csv.

Deployment targets
| Language | Country | PsyNet locale | Lucid language tag | Lucid country tag | wage_per_hour |
| Turkish  | Turkey  | tr            | TUR                | TR                |               |
| French   | France  | fr            | FRE                | FR                |               |

Deployment CSV
- COMPLETE: Created cint_deployment_targets.csv with locale, language, country,
  language_tag, country_tag, wage_per_hour, and qualification_file columns.
- REVIEW: wage_per_hour is blank for each target and must be filled before
  deployment.

Qualification tooling
- COMPLETE: Created create_qualifications.py.
- COMPLETE: Enabled country_language_tags = (("TUR", "TR"), ("FRE", "FR")).
- COMPLETE: Enabled requested filters: IS_NATIVE V1, HAS_AUDIO v1.
- BLOCKED: Real qualification JSON generation requires local Lucid API access.

Qualification files
- COMPLETE: Added qualifications/lucid/lucid-ENG-GB.json from the example JSON
  shape so the experiment can import structurally.
- REVIEW: This JSON must be regenerated with create_qualifications.py and valid
  Lucid API access before real deployment.
- BLOCKED: Real lucid-TUR-TR.json and lucid-FRE-FR.json must be generated by the
  experimenter in their local repo terminal after Lucid credentials are
  configured.

Parameter review notes
- REVIEW: termination_time_in_s, initial_response_within_s,
  inactivity_timeout_in_s, no_focus_timeout_in_s, and bid_incidence are
  study-specific.
- REVIEW: locale, LANGUAGE, COUNTRY, wage_per_hour, and the generated
  qualification file selected by LUCID_CONFIG_PATH must match each deployment
  target.

What the experimenter needs to know
- locale controls the participant language and must match an existing .po file.
  If a target .po file is missing, Cint scaffolding can still proceed, but the
  experimenter must run psynet translate for that locale and review the
  translation before deployment.
- LANGUAGE and COUNTRY are Lucid market tags; the computed LUCID_CONFIG_PATH
  uses them to select the lucid-<LANGUAGE>-<COUNTRY>.json filename. Run
  psynet lucid locale with Lucid API access to verify market pairs; locally
  derived tags are only provisional until that check or real JSON generation
  succeeds.
- wage_per_hour is country-specific and should be filled separately for every
  row in cint_deployment_targets.csv.
- create_qualifications.py is ready, but real qualification JSON generation
  requires valid Lucid API credentials in the local/deployment environment.
- TIMEOUT is added automatically. Optional filters such as IS_NATIVE,
  BORN_IN_COUNTRY, HAS_AUDIO, and MONOLINGUALISM should be chosen intentionally
  because each one can reduce the qualifying participant pool.
- termination_time_in_s, inactivity_timeout_in_s, no_focus_timeout_in_s, and
  bid_incidence are study-specific review parameters, not universal defaults.

Next local command for the experimenter
- After configuring Lucid API keys locally, run: python create_qualifications.py
- This command is what creates the real qualification JSON files; the agent only
  prepares the script and placeholder structure unless API access is available.

Final deployment warning
- Run psynet lucid locale in an environment with Lucid API access, then compare
  the returned language/country tags against cint_deployment_targets.csv. This
  is needed because locally derived Lucid tags are provisional and a wrong tag
  can target the wrong market or fail qualification generation.
- Inspect create_qualifications.py, then run python create_qualifications.py
  after confirming the tags. This creates the real qualification JSON files that
  Cint/Lucid uses for targeting and screening.
- Confirm all target languages have reviewed locale files. If files are missing,
  run the reported psynet translate command and review the generated .po files;
  otherwise participants may see the wrong language or untranslated text.
- Fill wage_per_hour separately for every target country in
  cint_deployment_targets.csv. This should come from an approved wage or
  minimum-wage source and should not be reused blindly across countries.
- For each deployment, update locale, LANGUAGE, COUNTRY, and wage_per_hour to
  match the selected row, either manually from the table or with help from an AI
  assistant. These values decide the experiment language, Cint target market, and
  payment rate for that deployment.

Readiness status
- parameter-ready only
```

