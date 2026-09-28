Branch review in Cursor
=======================

Before a PsyNet merge request is finalized, run ``/branch-review`` from Cursor
chat on the feature branch. The review compares that branch to the open merge
request's **target** (not always ``master``).

Using ``/branch-review``
++++++++++++++++++++++++

#. Open Cursor chat in the PsyNet repository, on the feature branch.
#. Type ``/branch-review``.
#. Stay off the merge-request target. If you are already on that branch
   (often ``master``), switch to the feature branch first.

What ``/branch-review`` does
++++++++++++++++++++++++++++

``/branch-review`` first runs ``/update-onto-target``, then reviews
``origin/<target>...HEAD`` and updates the GitLab title and description.
To merge without reviewing, run ``/update-onto-target`` on its own.

Just before the merge request is merged into its target, run
``/reorganize-onto-target``. When that rewrite is allowed, and why it
must not fetch a newer target, is in
``.cursor/skills/reorganize-onto-target/SKILL.md`` (When to run).

Reference workflow
++++++++++++++++++

The detailed steps live in these skills:

* ``.cursor/skills/update-onto-target/SKILL.md`` (``/update-onto-target``)
* ``.cursor/skills/branch-review/SKILL.md`` (``/branch-review``)
* ``.cursor/skills/reorganize-onto-target/SKILL.md`` (``/reorganize-onto-target``)

The matching command files are under ``.cursor/commands/``.
