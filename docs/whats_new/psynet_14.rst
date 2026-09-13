=========
PsyNet 14
=========

PsyNet 14 makes timeline navigation feel like a modern web app.

Instead of reloading the whole browser page every time a participant moves
on, PsyNet keeps the experiment open and swaps in the next step in place.
That means smoother transitions, less waiting on repeated page loads, and a
better chance of preserving useful browser state — audio, video, and custom
frontends included — as people move through the timeline.

Under the hood this is powered by clearer page lifecycle APIs for templates,
styles, and JavaScript, so custom pages can take part in that fluent
navigation instead of fighting a full reload on every step.

What authors need to know
-------------------------

* Prefer **fragment templates** plus explicit assets
  (``css_links``, ``js_dependencies``, ``js_page_code``, ``js_page_modules``).
* Read page data from ``psynet.var``, not ``window``.
* Put page setup in a module ``activate()`` function — do not rely on
  ``DOMContentLoaded``.
* Temporary opt-out while migrating:
  ``inplace_timeline_transitions = false``.
* Recruiter ``mturk``, ``bots``, and ``multi`` are rejected.
* Leave uses ``show_early_exit_button``; ``error_page_content`` is
  replaced by ``error_page_presentation``.
* Phones are allowed by default; the browser floor is Chrome 105.

MTurk recruitment has been removed
----------------------------------

PsyNet no longer provides an MTurk recruiter, submission page, payment flow, or
MTurk-specific deployment commands. Configuring ``recruiter = mturk`` now
raises a clear error instead of falling back to Dallinger's transitive
integration. Amazon is `closing MTurk on September 30, 2026
<https://docs.aws.amazon.com/sagemaker/latest/dg/sms-workforce-management-public.html>`_.
Move active experiments to another recruiter before upgrading to PsyNet 14.

Upgrading
---------

PsyNet 14 is a breaking release for some custom frontends, recruiter
configs, and leave/error-page APIs.

* Human checklist: :doc:`/whats_new/upgrading_to_psynet_14`.
* Patterns and examples: :doc:`/tutorials/writing_custom_frontends`.
* In Cursor, ``/upgrade-to-psynet-14`` can walk the same checklist.
