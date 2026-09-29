---
name: upgrade-to-psynet-14
description: Migrates an existing PsyNet experiment through PsyNet 14 breaking changes by following the human upgrade checklist in the What's new docs.
---

# Upgrade to PsyNet 14

Use this skill when an experiment needs to move onto PsyNet 14, or when PsyNet
raises an in-place timeline / page JavaScript contract error, a recruiter
migration error (``mturk``, ``bots``, ``multi``, ``error_page_content``,
``ad_requirements``), or an ``early_exit`` rename warning.

**Do not use this skill for greenfield custom pages.** Point new authors at the
custom front ends page instead (`code/pages/custom_front_ends`, below).

## Source of truth

Read and follow the full upgrade checklist, which matches the installed PsyNet:

```bash
psynet docs show whats_new/upgrading_to_psynet_14
```

If it reports no local copy, fetch `whats_new/upgrading_to_psynet_14.html`
from the website URL it prints. If the command doesn't exist (PsyNet before
this release), use
https://psynetdev.gitlab.io/PsyNet/whats_new/upgrading_to_psynet_14.html

That checklist owns migration order and search targets. Keep this skill thin;
put checklist edits in the docs, not here.

Related reading (not a second checklist):

| Topic | Page (`psynet docs show <page>`, or `<page>.html` on the website) |
| --- | --- |
| Release highlights | `whats_new/psynet_14` |
| Authoring patterns | `code/pages/custom_front_ends` |
| Maintainer lifecycle | `developer/page_lifecycle` |
| Config knobs | `reference/configuration` |

## Agent notes

- Prefer fixing SPA contract errors page by page over leaving
  ``inplace_timeline_transitions = false`` indefinitely.
- ``psynet test local`` needs a complete experiment directory
  (``experiment.py``, ``test.py``, ``constraints.txt``, ``config.txt``,
  ``requirements.txt``, ``.gitignore``, ``deploy.toml``, and
  ``.python-version``).
- SPA contract failures on static timeline pages should appear directly in
  the pytest failure from ``psynet test local``; PageMaker pages may still
  surface via bot HTTP errors that include the server message.
