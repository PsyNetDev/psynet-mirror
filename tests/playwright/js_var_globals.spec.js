const path = require("path");
const { test, expect } = require("./fixtures");

const {
  assertInplaceTimelinePathActive,
  assertNoBackendError,
  clickNextAndWait,
  completeInitialGateway,
  waitForMainBodyContains,
  withExperiment
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;

test("legacy js_var globals warn, error, and restore across pages", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve("tests/playwright/experiments/js_var_globals");

  await withExperiment(page, context, absDir, async (experimentPage) => {
    const warnings = [];
    experimentPage.on("console", (message) => {
      if (message.type() === "warning") {
        warnings.push(message.text());
      }
    });

    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);
    await waitForMainBodyContains(experimentPage, "Alpha page", STEP_TIMEOUT_MS);

    const alphaState = await experimentPage.evaluate(() => {
      window.unrelated_existing = 9;
      const descriptor = Object.getOwnPropertyDescriptor(
        window,
        "legacy_alpha"
      );
      const explicitValue = window.legacy_alpha;
      const bareValue = Function("return legacy_alpha")();
      window.legacy_alpha = 7;
      return {
        hasGetter: typeof descriptor?.get === "function",
        explicitValue,
        bareValue,
        assignedValue: window.legacy_alpha,
        canonicalValue: psynet.var.legacy_alpha,
        mode: psynetTemplateData.flags.legacyJsVarGlobals,
        missingType: Function("return typeof unrelated_missing")(),
        unrelatedValue: window.unrelated_existing
      };
    });
    expect(alphaState).toEqual({
      hasGetter: true,
      explicitValue: 1,
      bareValue: 1,
      assignedValue: 7,
      canonicalValue: 1,
      mode: "warn",
      missingType: "undefined",
      unrelatedValue: 9
    });
    await expect
      .poll(
        () =>
          warnings.filter((message) => message.includes('"legacy_alpha"')).length,
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe(1);

    expect(
      await experimentPage.evaluate(() => {
        delete window.legacy_alpha;
        psynet.refreshTemplateData();
        return {
          hasGetter:
            typeof Object.getOwnPropertyDescriptor(window, "legacy_alpha")?.get ===
            "function",
          legacyValue: window.legacy_alpha,
          canonicalValue: psynet.var.legacy_alpha
        };
      })
    ).toEqual({
      hasGetter: true,
      legacyValue: 1,
      canonicalValue: 1
    });

    // External redefine on the same page should be cleared and the accessor
    // reinstalled so the mirrored value tracks the current page js_vars again.
    const redefinedReinstallState = await experimentPage.evaluate(() => {
      Object.defineProperty(window, "legacy_alpha", {
        configurable: true,
        enumerable: true,
        value: "hijacked",
        writable: true
      });
      psynet.refreshTemplateData();
      const descriptor = Object.getOwnPropertyDescriptor(window, "legacy_alpha");
      return {
        hasGetter: typeof descriptor?.get === "function",
        legacyValue: window.legacy_alpha,
        canonicalValue: psynet.var.legacy_alpha
      };
    });
    expect(redefinedReinstallState).toEqual({
      hasGetter: true,
      legacyValue: 1,
      canonicalValue: 1
    });
    await expect
      .poll(
        () =>
          warnings.filter((message) =>
            message.includes(
              "cleared a redefined window.legacy_alpha property and reinstalled"
            )
          ).length,
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe(1);

    // External redefine before navigation must not leak the foreign value to
    // the next page; uninstall restores the pre-accessor window state.
    await experimentPage.evaluate(() => {
      Object.defineProperty(window, "legacy_alpha", {
        configurable: true,
        enumerable: true,
        value: "hijacked-across-pages",
        writable: true
      });
    });

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(experimentPage, "Beta page", STEP_TIMEOUT_MS);
    expect(
      await experimentPage.evaluate(() => ({
        alphaDescriptor: Object.getOwnPropertyDescriptor(
          window,
          "legacy_alpha"
        ),
        alphaValue: window.legacy_alpha
      }))
    ).toEqual({
      alphaDescriptor: undefined,
      alphaValue: undefined
    });
    await expect
      .poll(
        () =>
          warnings.filter((message) =>
            message.includes(
              "cleared a redefined window.legacy_alpha property while uninstalling"
            )
          ).length,
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe(1);

    const betaState = await experimentPage.evaluate(() => {
      psynetTemplateData.flags.legacyJsVarGlobals = "error";
      let error;
      try {
        Function("return legacy_beta")();
      } catch (caught) {
        error = {
          name: caught.name,
          message: caught.message
        };
      }
      let assignmentError;
      try {
        window.legacy_beta = 5;
      } catch (caught) {
        assignmentError = caught.message;
      }
      let typeofError;
      try {
        Function("return typeof legacy_beta")();
      } catch (caught) {
        typeofError = caught.message;
      }
      return {
        alphaDescriptor: Object.getOwnPropertyDescriptor(
          window,
          "legacy_alpha"
        ),
        assignmentError,
        canonicalValue: psynet.var.legacy_beta,
        error,
        globalPresent: "legacy_beta" in window,
        typeofError,
        unrelatedValue: window.unrelated_existing
      };
    });
    expect(betaState).toEqual({
      alphaDescriptor: undefined,
      assignmentError:
        'Legacy global js_vars access "legacy_beta" is disabled. ' +
        'Use psynet.var["legacy_beta"] instead.',
      canonicalValue: 2,
      error: {
        name: "ReferenceError",
        message:
          'Legacy global js_vars access "legacy_beta" is disabled. ' +
          'Use psynet.var["legacy_beta"] instead.'
      },
      globalPresent: true,
      typeofError:
        'Legacy global js_vars access "legacy_beta" is disabled. ' +
        'Use psynet.var["legacy_beta"] instead.',
      unrelatedValue: 9
    });

    await experimentPage.evaluate(() => {
      Object.defineProperty(window, "restored_global", {
        configurable: true,
        enumerable: false,
        value: 42,
        writable: true
      });
      Object.defineProperty(window, "nonconfigurable_global", {
        configurable: false,
        enumerable: true,
        value: 99,
        writable: true
      });
    });
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(
      experimentPage,
      "Descriptor page",
      STEP_TIMEOUT_MS
    );
    const descriptorState = await experimentPage.evaluate(() => {
      const descriptor = Object.getOwnPropertyDescriptor(
        window,
        "restored_global"
      );
      return {
        hasGetter: typeof descriptor?.get === "function",
        legacyValue: window.restored_global,
        canonicalValue: psynet.var.restored_global,
        nonconfigurableValue: window.nonconfigurable_global,
        nonconfigurableCanonicalValue: psynet.var.nonconfigurable_global
      };
    });
    expect(descriptorState).toEqual({
      hasGetter: false,
      legacyValue: 42,
      canonicalValue: 3,
      nonconfigurableValue: 99,
      nonconfigurableCanonicalValue: 4
    });
    for (const key of ["restored_global", "nonconfigurable_global"]) {
      await expect
        .poll(
          () =>
            warnings.filter((message) =>
              message.includes(
                `did not install the legacy js_vars accessor for "${key}" because window.${key} already exists`
              )
            ).length,
          { timeout: STEP_TIMEOUT_MS }
        )
        .toBe(1);
    }
    await experimentPage.evaluate(() => psynet.refreshTemplateData());
    for (const key of ["restored_global", "nonconfigurable_global"]) {
      expect(
        warnings.filter((message) =>
          message.includes(
            `did not install the legacy js_vars accessor for "${key}" because window.${key} already exists`
          )
        )
      ).toHaveLength(1);
    }

    const offState = await experimentPage.evaluate(() => {
      const templateDataElement = document.getElementById(
        "psynet-template-data"
      );
      const templateData = JSON.parse(templateDataElement.textContent);
      templateData.flags.legacyJsVarGlobals = "off";
      templateDataElement.textContent = JSON.stringify(templateData);
      psynet.refreshTemplateData();

      const descriptor = Object.getOwnPropertyDescriptor(
        window,
        "restored_global"
      );
      return {
        hasGetter: typeof descriptor?.get === "function",
        restoredValue: window.restored_global,
        enumerable: descriptor?.enumerable,
        canonicalValue: psynet.var.restored_global
      };
    });
    expect(offState).toEqual({
      hasGetter: false,
      restoredValue: 42,
      enumerable: false,
      canonicalValue: 3
    });

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(experimentPage, "Cleanup page", STEP_TIMEOUT_MS);
    expect(
      await experimentPage.evaluate(() => ({
        restoredValue: window.restored_global,
        unrelatedValue: window.unrelated_existing
      }))
    ).toEqual({
      restoredValue: 42,
      unrelatedValue: 9
    });
    await assertNoBackendError(experimentPage);
  });
});

test("locked legacy global does not block a page transition", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve("tests/playwright/experiments/js_var_globals");

  await withExperiment(page, context, absDir, async (experimentPage) => {
    const warnings = [];
    experimentPage.on("console", (message) => {
      if (message.type() === "warning") {
        warnings.push(message.text());
      }
    });

    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);
    await waitForMainBodyContains(experimentPage, "Alpha page", STEP_TIMEOUT_MS);

    await experimentPage.evaluate(() => {
      Object.defineProperty(window, "legacy_alpha", {
        configurable: false,
        enumerable: true,
        value: "locked by another script",
        writable: false
      });
    });

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(experimentPage, "Beta page", STEP_TIMEOUT_MS);

    expect(
      await experimentPage.evaluate(() => ({
        canonicalValue: psynet.var.legacy_beta,
        lockedValue: window.legacy_alpha,
        oldCanonicalKeyPresent: "legacy_alpha" in psynet.var
      }))
    ).toEqual({
      canonicalValue: 2,
      lockedValue: "locked by another script",
      oldCanonicalKeyPresent: false
    });
    await expect
      .poll(
        () =>
          warnings.filter((message) =>
            message.includes(
              "could not restore window.legacy_alpha because another script made it non-configurable"
            )
          ).length,
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe(1);
    await assertNoBackendError(experimentPage);
  });
});
