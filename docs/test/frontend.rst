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

    await page.waitForSelector("#main-body[data-page-ready='true']");
    const violations = await page.evaluate(() => window.psynetLayout.check());
    expect(violations).toEqual([]);

Run the checks at a laptop size (1280×720) and, if the experiment allows
phones, at a phone size (375×780). Pages that are meant to be taller than the
window should be created with ``expect_scrolling=True``; otherwise a
scrollbar counts as a problem.

Screenshots and video
---------------------

The same browser tests can take screenshots and record a video of a
participant's session (the ``record-participant-video`` skill). An
:doc:`audit <audits>` includes them in its Screenshots and Participant video
sections, so that a reviewer can see the experiment without running it.
