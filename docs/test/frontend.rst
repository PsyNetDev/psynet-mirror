=======================
Testing front-end logic
=======================

The front end is what runs in the participant's browser: how pages are laid
out, how controls behave, and how media play and record. :doc:`Bots
<backend>` don't display pages, so front-end behavior needs testing in a
real browser.

Taking the experiment yourself
------------------------------

Run ``psynet debug local`` and take the experiment as a participant would,
on a laptop and, unless the experiment excludes them, on a phone. Read
every instruction, try each kind of response, and check that the time
estimate is realistic.

Automated browser tests
-----------------------

A browser test drives a real browser through the experiment with
`Playwright <https://playwright.dev/>`_. It is stored with the experiment as
``tests/participant-flow.spec.js`` and runs against a local server started
with ``psynet debug local``. A useful test checks what the participant
experiences, not only that each page can be passed: controls that should be
enabled or disabled, feedback and validation messages, transitions between
trials, and the saved responses.

Coding agents write these tests using the ``playwright-testing`` skill,
which ``psynet setup`` installs in the experiment directory.

To install Playwright in the experiment directory:

.. code-block:: shell

    npm init -y
    npm install --save-dev @playwright/test
    npx playwright install chromium

Then start ``psynet debug local`` in one terminal and run
``npx playwright test`` in another.

Waiting for the next page
-------------------------

When a timeline page is ready for the participant, PsyNet sets
``data-page-ready="true"`` on its ``#main-body`` element. After a click on
*Next*, the old page keeps that attribute until the server replies, so a
test also waits for ``window.pageUuid``, which differs on every timeline
page, to change:

.. code-block:: js

    const oldUuid = await page.evaluate(() => window.pageUuid);
    await page.locator("#next-button").click();
    await page.waitForFunction(
      (uuid) =>
        window.pageUuid !== uuid &&
        document.getElementById("main-body")?.dataset.pageReady === "true",
      oldUuid,
    );

Layout checks
-------------

Every participant page provides ``psynetLayout.check()``, which returns a
list of layout problems on the page as displayed. It detects:

- pages rendered in quirks mode instead of standards mode;
- percentage heights declared against auto-height parents, which don't
  take effect;
- content wider than the window;
- response controls that can only be reached by scrolling, or that overlap
  the footer;
- pages that scroll although they are meant to fit the window.

A browser test calls it on each page once the page is ready, and expects an
empty list:

.. code-block:: js

    const violations = await page.evaluate(() => window.psynetLayout.check());
    expect(violations).toEqual([]);

Run the checks at a laptop size (1280×720) and, if the experiment allows
phones, at a phone size (375×780). Bots don't render a layout, so only a
browser test runs these checks.

Pages that are meant to be taller than the window should declare
``expect_scrolling``; otherwise a scrollbar counts as a problem. Pass it to
the page constructor:

.. code-block:: python

    InfoPage(long_briefing_text, time_estimate=60, expect_scrolling=True)

or set it on a custom page class:

.. code-block:: python

    class MyLongPage(Page):
        expect_scrolling = True

Passing ``expect_scrolling=False`` to the constructor overrides a class-level
``True``, for example when a normally long page is created in a short
variant. The bundled consent pages already declare it. The attribute only
affects these checks; it doesn't change what participants see.

Screenshots and video
---------------------

The same browser tests can take screenshots and record a video of a
participant's session (the ``record-participant-video`` skill). An
:doc:`audit <audits>` includes them in its Screenshots and Participant video
sections, so that a reviewer can see the experiment without running it.

.. seealso::

   The :doc:`/skills/playwright-testing` and :doc:`/skills/record-participant-video` skills.
