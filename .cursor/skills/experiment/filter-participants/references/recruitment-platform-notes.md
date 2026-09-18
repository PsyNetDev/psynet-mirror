# Recruitment platform notes for pre-screening

These notes summarize platform behavior relevant to PsyNet prescreening. Verify
the live platform documentation before launch, because payment and screen-out
policies change.

## General mapping

- Use platform filters or qualifications for stable attributes already known to
  the recruiter, such as age range, country, language, education, prior
  participation, or panel-profile fields.
- Use in-experiment PsyNet gates for current capabilities that the platform
  cannot know reliably, such as headphones, microphone/tapping setup, volume,
  task comprehension, attention, or stimulus-specific vocabulary.
- Use both when the platform recommends validation of a profile attribute. Put
  validation questions at the start of the participant flow and word them
  consistently with the platform-side screener when policy requires it.
- Avoid screening late. If a participant can fail, the failure branch should come
  before expensive main-task trials and before grouped or limited-capacity trial
  makers whenever possible.

## Prolific

- Built-in pre-screeners, also called filters, restrict study access by
  participant attributes. API filters are either `select` or `range` types.
- For criteria not covered by built-in filters, Prolific documents custom
  screening and two-study screening approaches. Custom screening requires
  screen-out slots, a fixed screen-out reward, and a redirect/completion path for
  screened-out participants.
- Prolific recommends keeping custom screening questions vague, required, and at
  the beginning of the study so participants are not influenced toward the
  desired answer and are screened out promptly.
- PsyNet's Prolific integration has its own failure and return-for-bonus paths.
  Check the current PsyNet recruiter code and configuration before assuming that
  an in-experiment failure maps to Prolific's current custom-screening API.

## Lucid/Cint

- Cint/Lucid standard qualifications are profiling questions used as
  pre-screeners for audience targeting. Custom qualifications are used for more
  specific audiences or quality checks.
- In PsyNet, Lucid studies often combine `LucidConsent`, a Lucid qualification
  JSON file, `get_lucid_settings(...)`, and optional
  `verify_lucid_qualifications(...)` pages in the timeline.
- PsyNet maps `performance_check` failure tags to Lucid security termination
  behavior, so failure tags are not just local metadata.
- Keep country/language-specific qualification files synchronized with the
  experiment's language, consent, and translation plan.

## CloudResearch Connect

- Connect supports targeting through participant-profile qualifications, quotas,
  and platform targeting for past participation or IDs.
- When a needed qualification is missing, Connect guidance describes requesting a
  demographic/qualification, running a separate pre-study screen, or adding
  within-survey screening with branch-specific partial payment.
- Within-study screening should use early branching, clear exit messaging, and
  partial payment for the time spent on the screener.

## MTurk

- MTurk eligibility is controlled with qualification requirements on HITs or HIT
  types. Qualifications can be system-provided or requester-defined.
- Requester-defined qualifications can represent previous performance, custom
  qualification tests, inclusion lists, or exclusion from repeated participation.
- When using MTurk-style qualifications, keep the external qualification state
  synchronized with PsyNet participant IDs and previous participation records.

## Lab and custom recruiters

- Custom recruiters often receive only status, failure reason, or failure tags.
  Make these tags meaningful and stable, for example `headphone_check`,
  `language_vocabulary`, or `task_comprehension`.
- Deployment folders should include any recruiter/qualification JSON files the
  experiment references. See `deploy-experiment/SKILL.md` for deployment
  readiness checks.

## Patterns observed in lab experiments

- Audio and music studies commonly combine recruiter-side language/country
  targeting with in-experiment headphones, volume, microphone, vocabulary, or
  REPP setup checks.
- Cross-national studies commonly switch consent and recruiter configuration by
  platform and locale; qualification files must follow the same locale choices.
- Prolific studies commonly load local qualification JSON, then adapt exported
  `eligibility_requirements` into the shape expected by the Dallinger/PsyNet
  Prolific client.
- Some studies use platform qualifications only, while others add task-specific
  PsyNet gates. The right split depends on whether the requirement is a stable
  participant attribute or a current task capability.
