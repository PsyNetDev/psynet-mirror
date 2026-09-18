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

Upgrading
---------

PsyNet 14 is a breaking release for some custom frontends.

* Human checklist: :doc:`/whats_new/upgrading_to_psynet_14`.
* Patterns and examples: :doc:`/tutorials/writing_custom_frontends`.
* In Cursor, ``/upgrade-to-psynet-14`` can walk the same checklist.
