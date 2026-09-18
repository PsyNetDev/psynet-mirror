---
name: upgrade-to-psynet-14
description: Migrates an existing PsyNet experiment through PsyNet 14 breaking changes by following the human upgrade checklist (published What's new docs, or local RST in a PsyNet source checkout).
---

# Upgrade to PsyNet 14

Use this skill when an experiment needs to move onto PsyNet 14, or when PsyNet
raises an in-place timeline / page JavaScript contract error.

**Do not use this skill for greenfield custom pages.** Point new authors at the
custom-frontends tutorial instead (published URL below).

## Source of truth

Read and follow the full upgrade checklist. **Prefer the published HTML**, which
is available even when PsyNet is installed from PyPI/Git without a source tree:

https://psynetdev.gitlab.io/PsyNet/whats_new/upgrading_to_psynet_14.html

Fetch that page (for example with WebFetch) and follow it. Pip wheels do not
ship the ``docs/`` RST tree, so do not assume
``docs/whats_new/upgrading_to_psynet_14.rst`` exists on disk.

**Source-checkout shortcut:** if this workspace is a PsyNet repository (or
otherwise has the docs tree), you may read the same checklist at
``docs/whats_new/upgrading_to_psynet_14.rst`` instead of fetching HTML.

That checklist owns migration order and search targets. Keep this skill thin;
put checklist edits in the docs, not here.

Related reading (not a second checklist):

| Topic | Published | Source checkout |
| --- | --- | --- |
| Release highlights | https://psynetdev.gitlab.io/PsyNet/whats_new/psynet_14.html | ``docs/whats_new/psynet_14.rst`` |
| Authoring patterns | https://psynetdev.gitlab.io/PsyNet/tutorials/writing_custom_frontends.html | ``docs/tutorials/writing_custom_frontends.rst`` |
| Maintainer lifecycle | https://psynetdev.gitlab.io/PsyNet/developer/page_lifecycle.html | ``docs/developer/page_lifecycle.rst`` |
| Config knobs | https://psynetdev.gitlab.io/PsyNet/experiment_development/configuration.html | ``docs/experiment_development/configuration.rst`` |

## Agent notes

- Prefer fixing SPA contract errors page by page over leaving
  ``inplace_timeline_transitions = false`` indefinitely.
- ``psynet test local`` needs a complete experiment directory
  (``experiment.py``, ``test.py``, ``constraints.txt``, ``config.txt``,
  ``requirements.txt``, ``.gitignore``, and ``.python-version``).
- SPA contract failures on static timeline pages should appear directly in
  the pytest failure from ``psynet test local``; PageMaker pages may still
  surface via bot HTTP errors that include the server message.
