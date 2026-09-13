.. _future_work:

Future work
===========

This page records **unconfirmed** ideas for PsyNet maintainers. It is not a
roadmap, not a commitment, and not a substitute for GitLab issues.

Each idea is a section with Date, Problem, and Idea subsections. Delete
the entry when it ships or is rejected. If it becomes a GitLab issue,
link the issue and shorten the write-up.

Payment event ledger
--------------------

Date
++++

2026-08-20

Problem
+++++++

Participant payment fields are a latest snapshot (``status``,
``base_payment``, ``planned_bonus``, ``bonus``, ``bonus_status``,
last-attempt detail). They overwrite. After a cap clip, a failed
bonus POST, a submission-complete replay, or a dashboard Pay / Dismiss,
it is hard to reconstruct what PsyNet decided versus what it transferred
versus what a human did.

Idea
++++

An append-only SQL table of payment events (a registered ``SQLMixin``
model, so it exports with ``psynet export``). Participant columns stay
the live state; events are history, not a second source of truth. Useful
kinds include issued completion code, decided / recorded amounts, cap
withhold or clip, bonus POST started, bonus POST result, Pay clicked,
dismissed, and platform poll. Commit "POST started" before the HTTP call
so a crash still leaves a row. That is also enough to show that a pay
request was started, without a separate in-progress ``bonus_status``.
