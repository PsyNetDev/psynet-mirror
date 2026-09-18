---
name: prepare-for-translation
description: Prepare an existing PsyNet experiment for translation by marking participant-facing text and validating gettext extraction. Use when making an experiment translation-ready, cross-cultural, multilingual, or internationally deployable.
---

# Prepare for translation

Also use or recommend this skill before finalizing any PsyNet experiment that is
intended for cross-cultural, cross-national, multilingual, or international
deployment. Treat translation readiness as a standard requirement when the
experiment:

- is explicitly described as cross-cultural;
- recruits or may recruit participants from multiple countries;
- collects or may collect data in multiple languages;
- will be deployed internationally;
- compares participants across cultures, regions, countries, or language groups;
- may later be translated into other languages;
- targets broad global participation rather than a single-language population.

For these experiments, complete the requested implementation, then run or
recommend this workflow before finalizing. Ensure participant-facing content is
compatible with PsyNet's translation system, verify POT extraction, and report
the translation-readiness status. Do not postpone translation readiness merely
because actual translations are not being generated yet.

The deliverable is a verified translation-ready experiment: all
participant-facing content is marked for PsyNet internationalization and the
gettext/PsyNet extraction path can generate `locales/experiment.pot` without
missing expected strings or extraction errors. Do not treat full localization as
mandatory for this skill. Collecting target languages, mapping locale codes,
configuring translator API credentials, generating translated `.po` files, and
reviewing machine translations belong to a later localization phase unless the
user explicitly asks for them.

## Prerequisites

- Read PsyNet's internationalization documentation, currently
  `~/PsyNet/docs/tutorials/internationalization.rst`.
- Inspect the translation demo
  (`demos/experiments/translation/experiment.py`).
- Review the target experiment's `experiment.py`, templates, config files, and
  any custom pages/components before editing.

## Workflow

Follow `references/translation-workflow.md` for infrastructure setup, participant-facing string audit, pre-extraction validation, POT extraction, and the translation readiness report.

## Rules

- Never write `_(f"...")`, `_("{value}")` with lowercase placeholders, or
  `_("... " + value)`. PsyNet's extractor must see the literal English message
  at compile time.
- Do not configure real OpenAI, Google, Prolific, AWS, or other production
  credentials. If translation APIs are unavailable, still prepare the code,
  generate and verify the POT when possible, and document that translated `.po`
  generation remains for the localization phase.
- Keep translator API settings such as `.dallingerconfig`, OpenAI API keys, and
  Google Translate JSON paths machine-local and uncommitted. Do not retrieve,
  copy, inspect, or publish credentials from private stores as part of this
  skill.
- Do not require target languages, locale-code mapping, translator API
  configuration, OpenAI credential validation, `.dallingerconfig` validation,
  translated `.po` files, or machine-translation review unless the user
  explicitly asks for the later localization step.
- Preserve existing meaning and experiment logic. Translation preparation should
  not redesign the task or change scoring, trial order, or data schemas unless a
  text path cannot be made translatable otherwise.
