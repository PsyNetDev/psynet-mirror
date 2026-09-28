Theming
=======

Every participant-facing page (ad, consent, timeline, waiting and error pages)
shares a default theme. Page content sits on a white surface over a lightly
tinted page background. The accent color is used only for the primary action,
the progress indicator and selected options. Below 720px wide the surface
padding tightens so that pages fit a phone without horizontal overflow.

Design tokens
-------------

The theme is defined in a single stylesheet, ``psynet/resources/css/participant.css``,
which is served at ``/static/css/participant.css``. It expresses every color
and size through CSS custom properties, so most restyling means redefining a
few tokens rather than overriding rules.

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Token
     - Default
     - Purpose
   * - ``--psynet-page-bg``
     - ``#eef1f6``
     - Page background behind the content surface.
   * - ``--psynet-surface``
     - ``#ffffff``
     - Content surface that holds page content.
   * - ``--psynet-surface-sunken``
     - ``#f7f9fc``
     - Panels that group response options.
   * - ``--psynet-chrome-bg``
     - ``#d8e3f4``
     - The progress rail above the content and the footer below it.
   * - ``--psynet-footer-bg``
     - ``var(--psynet-chrome-bg)``
     - The footer alone, so it can be retinted without the rail.
   * - ``--psynet-rail-fill``
     - ``var(--psynet-accent)``
     - Filled portion of the timeline progress rail and the media-download
       rail.
   * - ``--psynet-accent-solid``
     - ``var(--psynet-accent)``
     - Fill for solid buttons, with ``--psynet-accent-solid-contrast`` for
       their labels.
   * - ``--psynet-border``
     - ``#dfe5ee``
     - Default border color for surfaces and controls.
   * - ``--psynet-text``
     - ``#1f2733``
     - Body text.
   * - ``--psynet-text-muted``
     - ``#5c6b7f``
     - Secondary text, for example the reward footer.
   * - ``--psynet-accent``
     - ``#3070c8``
     - Primary action, progress fill, selected states, focus ring.
   * - ``--psynet-accent-rgb``
     - ``48, 112, 200``
     - Comma-separated channels of the accent. Bootstrap links and
       utilities such as ``text-primary`` read this, not the hex token.
   * - ``--psynet-accent-hover``
     - ``#275ba4``
     - Hover state for primary actions and links.
   * - ``--psynet-accent-hover-rgb``
     - ``39, 91, 164``
     - Comma-separated channels of the hover color, for Bootstrap.
   * - ``--psynet-accent-contrast``
     - ``#ffffff``
     - Text drawn on the accent, for example primary-button labels.
   * - ``--psynet-danger``
     - ``#c0454c``
     - Recording, warnings, "too loud" audio-meter states, and the footer's
       ``Exit`` control. The named color ``red`` resolves here.
   * - ``--psynet-danger-soft``
     - ``#fbeff0``
     - Quiet danger surface, for example hovering ``Exit``.
   * - ``--psynet-success``
     - ``#2f7d5b``
     - Completed stages and "just right" audio-meter states. The named
       color ``green`` resolves here.
   * - ``--psynet-warning``
     - ``#9a6700``
     - Get-ready stages. The named color ``orange`` resolves here.
   * - ``--psynet-content-width``
     - ``900px``
     - Maximum width of the content surface.
   * - ``--psynet-measure``
     - ``62ch``
     - Maximum width of prose.
   * - ``--psynet-graphic-vertical-chrome``
     - ``25rem``
     - Height reserved around a
       :class:`~psynet.graphics.GraphicPrompt` so the page fits the window.
       Windows below 540px tall use ``10rem``.
   * - ``--psynet-graphic-min-size``
     - ``8rem``
     - Minimum size of a graphic when the reserved height applies.
   * - ``--psynet-audio-meter-height``
     - ``10px``
     - Height of the microphone-level track.

To recolor an experiment, redefine the tokens in your own stylesheet.
Buttons, progress, and focus follow ``--psynet-accent``. Links and Bootstrap
utilities such as ``text-primary`` also need the matching ``-rgb`` tokens,
because Bootstrap composes those colors from RGB triples:

.. code-block:: css

    /* static/theme.css */
    :root {
        --psynet-accent: #7a4fa3;
        --psynet-accent-rgb: 122, 79, 163;
        --psynet-accent-hover: #623e84;
        --psynet-accent-hover-rgb: 98, 62, 132;
        --psynet-page-bg: #f5f2f8;
    }

Register the stylesheet on the experiment class:

.. code-block:: python

    class Exp(psynet.experiment.Experiment):
        css_links = ["static/theme.css"]

PsyNet adds a content version to this local URL when it renders the page, so
the URL changes whenever the file changes and no cache-busting query
parameters are needed. Raw ``<link>`` or ``<script>`` tags written directly in
a custom template are not rewritten; their unversioned ``/static/...`` URLs
still work and are revalidated by the browser instead of cached indefinitely.

``participant.css`` avoids ``!important``, so an ordinary rule in your own
stylesheet overrides a default without extra specificity. The
``demos/features/custom_theme`` demo is a complete example.

.. note::

    Token overrides apply to timeline pages. ``css`` and ``css_links`` are not
    currently injected into the ad and consent pages; to restyle those, provide
    your own ``templates/ad.html`` or ``templates/consent.html``.

Wider stimuli
-------------

If a stimulus needs more room than the default content width, widen the surface
for the whole experiment:

.. code-block:: python

    Exp.css.append(":root { --psynet-content-width: 1140px; }")

Prose remains bounded by ``--psynet-measure``, so widening the surface does not
lengthen lines of text.

Color and stimuli
-----------------

When color is part of the measurement, set the accent to a neutral gray so
that no saturated color appears near the stimuli:

.. code-block:: python

    Exp.css.append(":root { --psynet-accent: #44556b; --psynet-accent-rgb: 68, 85, 107; }")

Named colors on trial progress stages (``red``, ``green``, ``blue``)
follow ``--psynet-danger``, ``--psynet-success``, and ``--psynet-accent``
rather than the browser's primary colors. Override those tokens the same
way, or pass a hex value to :class:`~psynet.timeline.ProgressStage`.
``white`` is left as CSS white so that a caption stays visible in dark mode.

Dark mode
---------

Setting ``color_mode`` to ``dark`` or ``auto`` in ``config.txt`` switches the
tokens to a dark palette (see :doc:`/reference/configuration`). If you
override tokens and support dark mode, define your overrides for both
schemes:

.. code-block:: css

    :root {
        --psynet-accent: #7a4fa3;
        --psynet-accent-rgb: 122, 79, 163;
    }
    [data-bs-theme="dark"] {
        --psynet-accent: #b48ad4;
        --psynet-accent-rgb: 180, 138, 212;
    }

Response options
----------------

:class:`~psynet.modular_page.RadioButtonControl` and
:class:`~psynet.modular_page.CheckboxControl` render each option as a full-width
row with a minimum height of 46px, so the whole row is clickable. The rows sit
in a panel (``.psynet-options``) that grows with them, so a long list scrolls
the page rather than a nested scrollbar inside the control; create such a page
with ``expect_scrolling=True``. The markup is:

.. code-block:: html

    <div class="control-container psynet-options">
        <label class="psynet-option">
            <input type="radio" id="..." name="..." class="response">
            <span class="psynet-option-label">Label</span>
        </label>
    </div>

To restyle options, target ``.psynet-option`` and ``.psynet-option-label``.

:class:`~psynet.modular_page.PushButtonControl` groups choices in
``.push-button-container``. Vertical lists (``arrange_vertically=True``)
stay in a single column. The buttons sit directly on the content surface with
no panel behind them, and the list grows with them in the same way as
``.psynet-options``.

The Next and Reset buttons sit in ``.psynet-actions``.

The selected state is styled with ``:has()``, which is why the default
``min_browser_version`` is Chrome 105 (see :doc:`/reference/configuration`).

Pages that scroll
-----------------

The footer is part of the document at every window width. On a short page it
rests at the bottom edge of the window; on a long page it follows the content,
so it never covers a response control. The document is the only scroll
container.

A page should fit a typical laptop window (1280×720) unless it is created with
``expect_scrolling=True``. That attribute only affects
:doc:`front-end layout checks </test/frontend>`; participants see the same
page either way.
