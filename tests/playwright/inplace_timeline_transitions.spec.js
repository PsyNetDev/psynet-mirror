const path = require("path");
const { test, expect } = require("./fixtures");

const {
  assertNoBackendError,
  assertInplaceTimelinePathActive,
  clickNextAndWait,
  completeInitialGateway,
  waitForPageChange,
  waitForMainBodyContains,
  waitForTimelinePageReady,
  withExperiment
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;

function deferredPromise() {
  let resolve;
  const promise = new Promise((innerResolve) => {
    resolve = innerResolve;
  });
  return { promise, resolve };
}

function hasManagedStylesheet(page, stylesheetPath) {
  return page.evaluate((pathSuffix) => {
    return Array.from(
      document.head.querySelectorAll("link[data-psynet-fragment-stylesheet]")
    ).some((link) => link.href.endsWith(pathSuffix));
  }, stylesheetPath);
}

function makeSilentWav(durationSeconds) {
  const sampleRate = 8000;
  const samples = Math.max(1, Math.round(sampleRate * durationSeconds));
  const buffer = Buffer.alloc(44 + samples * 2);
  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(36 + samples * 2, 4);
  buffer.write("WAVE", 8);
  buffer.write("fmt ", 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36);
  buffer.writeUInt32LE(samples * 2, 40);
  return buffer;
}

test("in-place timeline transitions replay embedded scripts and manage page assets", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve(
    "tests/playwright/experiments/deferred_page_scripts"
  );

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);

    await expect(experimentPage.locator("#main-body")).toContainText("First page", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(
      experimentPage.locator("#managed-javascript-marker")
    ).toHaveAttribute("data-first-active", "true");
    await expect(
      experimentPage.locator("#managed-javascript-marker")
    ).toHaveAttribute("data-second-active", "true");
    await expect
      .poll(
        () =>
          experimentPage.evaluate(() => window.__psynetManagedJavascript || null),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toMatchObject({
        dependencyLoads: 1,
        events: ["activate:first", "activate:second"]
      });
    expect(
      await experimentPage.evaluate(
        () =>
          window.__psynetManagedJavascript.pageUuids.at(-1) === window.pageUuid
      )
    ).toBe(true);
    expect(
      await experimentPage.evaluate(
        () => window.__psynetManagedDependencyAvailableInBody
      )
    ).toBe(true);
    expect(
      await experimentPage.evaluate(() => window.__pageCodeLifecycle)
    ).toEqual(["activate:first"]);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    await expect(
      experimentPage.locator("#managed-javascript-marker")
    ).toContainText("Managed JavaScript activated");
    await expect
      .poll(
        () =>
          experimentPage.evaluate(() => window.__psynetManagedJavascript || null),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toMatchObject({
        dependencyLoads: 1,
        events: [
          "activate:first",
          "activate:second",
          "cleanup:second",
          "cleanup:first",
          "activate:first",
          "activate:second"
        ]
      });
    expect(
      await experimentPage.evaluate(
        () =>
          window.__psynetManagedJavascript.pageUuids.length === 2 &&
          window.__psynetManagedJavascript.pageUuids.at(-1) === window.pageUuid
      )
    ).toBe(true);
    expect(
      await experimentPage.evaluate(
        () => window.__psynetManagedDependencyAvailableInBody
      )
    ).toBe(true);
    expect(
      await experimentPage.evaluate(() => window.__pageCodeLifecycle)
    ).toEqual(["activate:first", "cleanup:first", "activate:second"]);
    await expect(
      experimentPage.locator("#body-library-load-count-marker")
    ).toHaveAttribute("data-load-count", "1", { timeout: STEP_TIMEOUT_MS });

    const deferredMarker = experimentPage.locator(
      "#deferred-trial-construct-marker"
    );
    await expect(deferredMarker).toHaveAttribute(
      "data-trial-construct-handler-ran",
      "true",
      { timeout: STEP_TIMEOUT_MS }
    );
    await expect(deferredMarker).toContainText("trialConstruct handler ran");

    await expect(experimentPage.locator("#deferred-css-marker")).toHaveCSS(
      "color",
      "rgb(12, 34, 56)"
    );

    await expect
      .poll(
        () =>
          experimentPage.evaluate(
            () =>
              window.__psynetDeferredPageScript?.scriptExecutions === 1 &&
              window.__psynetDeferredPageScript?.trialConstructRuns === 1
          ),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe(true);

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    const stylesheetMarker = experimentPage.locator("#custom-stylesheet-marker");
    await expect(stylesheetMarker).toContainText("Styled custom template page", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(stylesheetMarker).toHaveCSS("color", "rgb(12, 34, 56)");
    await expect(stylesheetMarker).toHaveCSS("border-left-width", "7px");
    await expect(stylesheetMarker).toHaveCSS("padding-left", "13px");
    await expect
      .poll(
        () =>
          hasManagedStylesheet(
            experimentPage,
            "/static/custom-stylesheet-page.css"
          ),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe(true);

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    await waitForMainBodyContains(
      experimentPage,
      "Repeated linked page module lifecycle page",
      STEP_TIMEOUT_MS
    );
    await expect(deferredMarker).toHaveAttribute(
      "data-trial-construct-handler-ran",
      "true",
      { timeout: STEP_TIMEOUT_MS }
    );
    await expect
      .poll(
        () =>
          experimentPage.evaluate(
            () =>
              window.__psynetDeferredPageScript?.scriptExecutions === 2 &&
              window.__psynetDeferredPageScript?.trialConstructRuns === 2
          ),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe(true);

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    await waitForMainBodyContains(experimentPage, "Cleanup page", STEP_TIMEOUT_MS);
    await expect(stylesheetMarker).toContainText("Unstyled cleanup marker", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect
      .poll(
        () =>
          hasManagedStylesheet(
            experimentPage,
            "/static/custom-stylesheet-page.css"
          ),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe(false);
    await expect(stylesheetMarker).not.toHaveCSS("color", "rgb(12, 34, 56)");
    await expect(stylesheetMarker).not.toHaveCSS("border-left-width", "7px");
  });
});
test("in-place timeline transitions preload linked CSS before swapping DOM", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve(
    "tests/playwright/experiments/deferred_page_scripts"
  );

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);
    await expect(experimentPage.locator("#main-body")).toContainText("First page", {
      timeout: STEP_TIMEOUT_MS
    });

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await expect(experimentPage.locator("#main-body")).toContainText(
      "Embedded script lifecycle page",
      { timeout: STEP_TIMEOUT_MS }
    );

    const stylesheetGate = deferredPromise();
    let stylesheetRequested = false;
    await experimentPage.route("**/static/custom-stylesheet-page.css", async (route) => {
      stylesheetRequested = true;
      await stylesheetGate.promise;
      await route.continue();
    });

    const transitionPromise = clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    await expect
      .poll(() => stylesheetRequested, { timeout: STEP_TIMEOUT_MS })
      .toBe(true);
    await expect(experimentPage.locator("#main-body")).toContainText(
      "Embedded script lifecycle page",
      { timeout: STEP_TIMEOUT_MS }
    );
    await expect(experimentPage.locator("#main-body")).not.toContainText(
      "Styled custom template page"
    );

    stylesheetGate.resolve();
    await transitionPromise;

    const stylesheetMarker = experimentPage.locator("#custom-stylesheet-marker");
    await expect(stylesheetMarker).toContainText("Styled custom template page", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(stylesheetMarker).toHaveCSS("border-left-width", "7px");
  });
});

test("in-place timeline transitions manage stylesheets that target shell elements", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve(
    "tests/playwright/experiments/deferred_page_scripts"
  );

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);
    await waitForMainBodyContains(experimentPage, "First page", STEP_TIMEOUT_MS);

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(
      experimentPage,
      "Embedded script lifecycle page",
      STEP_TIMEOUT_MS
    );
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(
      experimentPage,
      "Styled custom template page",
      STEP_TIMEOUT_MS
    );
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(
      experimentPage,
      "Repeated linked page module lifecycle page",
      STEP_TIMEOUT_MS
    );
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(experimentPage, "Cleanup page", STEP_TIMEOUT_MS);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    await waitForMainBodyContains(
      experimentPage,
      "Shell stylesheet page",
      STEP_TIMEOUT_MS
    );
    await expect
      .poll(
        () =>
          hasManagedStylesheet(
            experimentPage,
            "/static/shell-stylesheet-page.css"
          ),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe(true);
    await expect(experimentPage.locator("#timeline-progress-bar")).toHaveCSS(
      "border-bottom-width",
      "9px"
    );

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(
      experimentPage,
      "Shell stylesheet cleanup page",
      STEP_TIMEOUT_MS
    );
    await expect
      .poll(
        () =>
          hasManagedStylesheet(
            experimentPage,
            "/static/shell-stylesheet-page.css"
          ),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe(false);
    await expect(experimentPage.locator("#timeline-progress-bar")).toHaveCSS(
      "border-bottom-width",
      "0px"
    );
  });
});

test("in-place media cleanup ignores late audio loads from previous pages", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve(
    "tests/playwright/experiments/deferred_page_scripts"
  );
  const staleResponseGate = deferredPromise();
  const staleAudio = makeSilentWav(0.1);
  const currentAudio = makeSilentWav(0.6);
  let staleRequests = 0;

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);

    await experimentPage.route("**/stale-audio.wav", async (route) => {
      staleRequests += 1;
      await staleResponseGate.promise;
      await route.fulfill({
        status: 200,
        contentType: "audio/wav",
        body: staleAudio
      }).catch(() => {});
    });
    await experimentPage.route("**/current-audio.wav", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "audio/wav",
        body: currentAudio
      });
    });

    await experimentPage.evaluate(() => {
      window.psynet.media.requests = {
        audio: { prompt: "/stale-audio.wav" },
        image: {},
        html: {},
        video: {}
      };
      window.__staleAudioInit = window.psynet.media.init();
    });
    await expect.poll(() => staleRequests, { timeout: 10000 }).toBe(1);

    // Declared page media normally blocks page readiness, so a normal page
    // transition cannot leave that media request pending. This forces the
    // stale-load edge case directly and verifies the cleanup generation guard.
    await experimentPage.evaluate(() => window.psynet.cleanupPageResources());

    const currentDuration = await experimentPage.evaluate(async () => {
      window.psynet.media.requests = {
        audio: { prompt: "/current-audio.wav" },
        image: {},
        html: {},
        video: {}
      };
      await window.psynet.media.init();
      return window.psynet.audio.prompt.buffer.duration;
    });
    expect(currentDuration).toBeGreaterThan(0.5);

    staleResponseGate.resolve();
    await experimentPage.evaluate(async () => {
      await window.__staleAudioInit.catch(() => false);
    });
    await experimentPage.waitForTimeout(250);

    const result = await experimentPage.evaluate(() => ({
      duration: window.psynet.audio.prompt.buffer.duration,
      activeRequests: window.psynet.media.activeRequests.size
    }));
    expect(result.duration).toBeGreaterThan(0.5);
    expect(result.activeRequests).toBe(0);
    await assertNoBackendError(experimentPage);
  });
});

test("legacy response handler errors do not use SPA fragment failure UI", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve(
    "tests/playwright/experiments/deferred_page_scripts"
  );

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);

    await experimentPage.route("**/response", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ submission: "approved" })
      });
    });

    const result = await experimentPage.evaluate(async () => {
      window.__fragmentFailureCalls = 0;
      window.psynetTemplateData.flags.inplaceTimelineTransitions = false;
      window.psynet.handleTimelineTransitionFailure = async function () {
        window.__fragmentFailureCalls += 1;
      };
      return {
        passedValidation: await window.psynet.nextPage("malformed-response"),
        fragmentFailureCalls: window.__fragmentFailureCalls
      };
    });

    expect(result).toEqual({
      passedValidation: false,
      fragmentFailureCalls: 0
    });
  });
});

test("in-place timeline transitions ignore duplicate nextPage while response is pending", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve(
    "tests/playwright/experiments/deferred_page_scripts"
  );

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);
    await expect(experimentPage.locator("#main-body")).toContainText("First page", {
      timeout: STEP_TIMEOUT_MS
    });

    const firstResponseGate = deferredPromise();
    let responseRequests = 0;
    await experimentPage.route("**/response", async (route) => {
      responseRequests += 1;
      if (responseRequests === 1) {
        await firstResponseGate.promise;
      }
      await route.continue();
    });

    const oldUuid = await experimentPage.evaluate(() => window.pageUuid || null);
    const submitResultsPromise = experimentPage.evaluate(async () => {
      const firstSubmit = window.psynet.nextPage("first-submit");
      const duplicateSubmit = window.psynet.nextPage("duplicate-submit");
      return {
        firstSubmit: await firstSubmit,
        duplicateSubmit: await duplicateSubmit
      };
    });

    await expect.poll(() => responseRequests, { timeout: 10000 }).toBe(1);
    await expect
      .poll(
        () =>
          experimentPage.evaluate(() => ({
            nextPagePending: window.psynet.nextPagePending,
            pageReady: window.psynet.pageReady
          })),
        { timeout: 10000 }
      )
      .toEqual({
        nextPagePending: true,
        pageReady: true
      });

    firstResponseGate.resolve();
    await expect(submitResultsPromise).resolves.toEqual({
      firstSubmit: true,
      duplicateSubmit: false
    });
    await waitForPageChange(experimentPage, oldUuid, STEP_TIMEOUT_MS);
    await waitForTimelinePageReady(experimentPage, STEP_TIMEOUT_MS);
    await expect.poll(() => responseRequests, { timeout: 5000 }).toBe(1);
    await assertNoBackendError(experimentPage);
  });
});

test("in-place timeline transition failures show refresh prompt and keep controls disabled", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve(
    "tests/playwright/experiments/deferred_page_scripts"
  );

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);
    await expect(experimentPage.locator("#main-body")).toContainText("First page", {
      timeout: STEP_TIMEOUT_MS
    });

    await experimentPage.route("**/response", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ submission: "approved", page: { attributes: {} } })
      });
    });

    const resultPromise = experimentPage.evaluate(() =>
      window.psynet.nextPage("malformed-response")
    );

    await expect(experimentPage.locator("#alert-message")).toContainText(
      "The next timeline page could not be loaded. Please refresh the page and try again.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await expect
      .poll(
        () =>
          experimentPage.evaluate(() => ({
            nextPagePending: window.psynet.nextPagePending,
            transitionBusy: document.body.classList.contains(
              "timeline-transition-pending"
            ),
            nextDisabled: document
              .getElementById("next-button")
              ?.hasAttribute("disabled")
          })),
        { timeout: 10000 }
      )
      .toEqual({
        nextPagePending: false,
        transitionBusy: false,
        nextDisabled: true
      });

    await experimentPage.locator("#alert-button").click();
    await expect(resultPromise).resolves.toBe(false);
    await assertNoBackendError(experimentPage);
  });
});

test("post-deactivation transition failures are handled once", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve(
    "tests/playwright/experiments/deferred_page_scripts"
  );

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);
    await expect(experimentPage.locator("#main-body")).toContainText("First page", {
      timeout: STEP_TIMEOUT_MS
    });

    await experimentPage.evaluate(() => {
      window.__transitionFailureCalls = 0;
      window.psynet.handleTimelineTransitionFailure = async function () {
        window.__transitionFailureCalls += 1;
      };
    });
    await experimentPage.route("**/response", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          submission: "approved",
          page: { attributes: {} },
          timeline_fragment: {
            html: "<div>Malformed post-deactivation fragment</div>",
            page_uuid: "malformed"
          }
        })
      });
    });

    await expect(
      experimentPage.evaluate(() =>
        window.psynet.nextPage("post-deactivation-failure")
      )
    ).resolves.toBe(false);
    expect(
      await experimentPage.evaluate(() => window.__transitionFailureCalls)
    ).toBe(1);
  });
});

test("post-commit activation failures clean up managed page modules", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve(
    "tests/playwright/experiments/deferred_page_scripts"
  );

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);
    await expect(experimentPage.locator("#main-body")).toContainText("First page", {
      timeout: STEP_TIMEOUT_MS
    });

    await experimentPage.evaluate(() => {
      window.psynet.handleTimelineTransitionFailure = async function () {};
      window.psynet.initPage = async function () {
        throw new Error("Intentional post-commit activation failure");
      };
    });

    await expect(
      experimentPage.evaluate(() =>
        window.psynet.nextPage("post-commit-activation-failure")
      )
    ).resolves.toBe(false);
    await expect
      .poll(
        () =>
          experimentPage.evaluate(
            () => window.__psynetManagedJavascript?.events || []
          ),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toEqual([
        "activate:first",
        "activate:second",
        "cleanup:second",
        "cleanup:first",
        "activate:first",
        "activate:second",
        "cleanup:second",
        "cleanup:first"
      ]);
  });
});
