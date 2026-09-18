.. _developer:
.. highlight:: shell

================
Making a release
================

PsyNet releases are made periodically by the core developers. There is no real rule about how often these releases are made; it comes down to a balance between making new features available early and avoiding spamming PsyNet users with too many updates to keep track of.

The step-by-step release process is maintained as a Cursor skill at
``.cursor/skills/release/SKILL.md``. It currently covers patch and minor releases,
and can be invoked in Cursor via the ``/release`` slash command (skills are
auto-discovered and exposed as slash commands under their skill name).
Pass the release type as an argument to select the corresponding path in
the skill, e.g. ``/release minor`` or ``/release patch``.
The Slack announcement step is documented in a separate Cursor skill at
``.cursor/skills/announce-release/SKILL.md`` (``/announce-release``).

The release skill is written to be followed by a human working with
an AI agent, but it works equally well as a plain checklist read directly.

Overview
--------

1. Decide on a version number following `semantic versioning guidelines
   <https://semver.org/>`_:

   * **Major** (breaking changes)
   * **Minor** (backwards-compatible features and/or bugfixes) — released
     from ``master`` via a new ``release-MAJOR.MINOR`` branch.
   * **Patch** (bugfixes only) — released from the existing
     ``release-MAJOR.MINOR`` branch.

2. Prepare the release commits on the release branch:

   * Fold the changelog fragments into a release section with
     ``psynet dev changelog release X.Y.Z YYYY-MM-DD``.
   * Bump the version in ``psynet/version.py`` and ``pyproject.toml``.
   * Update :doc:`/whats_new/index` when the release includes experimenter-facing
     highlights or breaking changes. Add or revise the matching version page
     (for example ``docs/whats_new/psynet_14.rst``) so authors get a short,
     readable summary and a clear upgrade pointer. Skip this only for
     patch-only releases with nothing meaningful to say there.

3. Publish: tag ``vX.Y.Z`` on the release branch, wait for CI, build and
   upload to PyPI, create the GitLab release, and announce on Slack with
   ``psynet dev release announce X.Y.Z --summary-file highlights.md``
   (preview first with ``--dry-run``). The summary file contains the
   release manager's experimenter-facing highlights in Slack mrkdwn; see the
   release skill for writing guidance. Posting to Slack requires
   ``SLACK_BOT_TOKEN`` in the process environment;
   see ``.cursor/skills/announce-release/SKILL.md`` for setup, token-loading,
   and test-channel instructions. For a one-off test-channel preview, either
   pass the token inline:
   ``SLACK_BOT_TOKEN=<slack-bot-token> psynet dev release announce X.Y.Z --summary-file highlights.md --channel psynet-release-test --dry-run``.
   Or export it first:
   ``export SLACK_BOT_TOKEN=<slack-bot-token>`` followed by
   ``psynet dev release announce X.Y.Z --summary-file highlights.md --channel psynet-release-test --dry-run``.

4. For minor releases, merge the release branch back into ``master`` (merge
   commit, no squash) and bump ``master`` to the next alpha version.

Externally visible or irreversible steps (pushing tags, PyPI uploads, GitLab
releases, Slack posts) require explicit approval from the human release
manager; the skill marks each of these with a **Human checkpoint** callout.

Minor releases go through a release-candidate flow (``X.Y.Zrc1``,
``rc2``, …) by default before the final tag: RCs are tagged, uploaded to
PyPI as pre-releases, and announced on Slack, but get no GitLab release
entry (GitLab has no pre-release flag, so an RC entry would displace the
"latest release" permalink). Skip the RC stage only when the release
manager explicitly decides to release directly.

.. attention::

    If the release upgrades the Dallinger dependency, also update
    ``recommended_dallinger_major_minor`` in ``psynet/version.py`` and refresh
    the vendored Dallinger CI constraints snapshot with
    ``psynet dev ci update-dallinger-constraints``.
