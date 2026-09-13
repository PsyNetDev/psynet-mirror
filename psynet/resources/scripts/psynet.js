(function () {
  "use strict";

  const templateDataElement = document.getElementById("psynet-template-data");
  if (!templateDataElement) {
    console.error(
      "[psynet] Missing #psynet-template-data bootstrap element; skipping timeline initialization.",
    );
    return;
  }

  const psynetTemplateData = JSON.parse(templateDataElement.textContent);
  window.psynetTemplateData = psynetTemplateData;

  // `psynet.var` is the canonical page-scoped JavaScript variable namespace.
  // Legacy globals remain available through configurable accessors while
  // experiments migrate, allowing accesses to warn or fail with useful errors.
  const LEGACY_JS_VAR_GLOBAL_MODES = new Set(["warn", "error", "off"]);
  const RESERVED_JS_VAR_GLOBALS = new Set(["pageUuid"]);
  let legacyJsVarGlobalStates = new Map();
  let warnedLegacyJsVarGlobalCollisionKeys = new Set();
  let warnedLegacyJsVarGlobalLockedKeys = new Set();
  let warnedLegacyJsVarGlobalKeys = new Set();

  let getLegacyJsVarGlobalMode = function () {
    let mode = psynetTemplateData.flags?.legacyJsVarGlobals || "warn";
    if (!LEGACY_JS_VAR_GLOBAL_MODES.has(mode)) {
      throw new Error(`Unknown legacy js_vars global mode: ${mode}.`);
    }
    return mode;
  };

  let legacyJsVarGlobalError = function (key) {
    return new ReferenceError(
      `Legacy global js_vars access "${key}" is disabled. ` +
        `Use psynet.var[${JSON.stringify(key)}] instead.`,
    );
  };

  let warnLegacyJsVarGlobalAccess = function (key) {
    if (warnedLegacyJsVarGlobalKeys.has(key)) {
      return;
    }
    warnedLegacyJsVarGlobalKeys.add(key);
    console.warn(
      `Legacy global js_vars access "${key}" is deprecated. ` +
        `Use psynet.var[${JSON.stringify(key)}] instead.`,
    );
  };

  let clearLegacyJsVarGlobalProperty = function (key) {
    let descriptor = Object.getOwnPropertyDescriptor(window, key);
    if (!descriptor) {
      return true;
    }

    if (!descriptor.configurable) {
      if (!warnedLegacyJsVarGlobalLockedKeys.has(key)) {
        warnedLegacyJsVarGlobalLockedKeys.add(key);
        warnedLegacyJsVarGlobalCollisionKeys.add(key);
        console.warn(
          `PsyNet could not restore window.${key} because another script ` +
            "made it non-configurable. The legacy global will remain in place; " +
            `use psynet.var[${JSON.stringify(key)}] for page-scoped data.`,
        );
      }
      return false;
    }

    delete window[key];
    return true;
  };

  let uninstallLegacyJsVarGlobal = function (key) {
    let state = legacyJsVarGlobalStates.get(key);
    if (!state) {
      return;
    }
    legacyJsVarGlobalStates.delete(key);

    let currentDescriptor = Object.getOwnPropertyDescriptor(window, key);
    let stillInstalled =
      currentDescriptor &&
      currentDescriptor.get === state.get &&
      currentDescriptor.set === state.set;
    if (currentDescriptor && !stillInstalled) {
      // Another script redefined the property. Clear it so the foreign value
      // cannot leak across SPA page transitions. If the other script locked
      // the property, relinquish ownership rather than aborting navigation.
      if (!clearLegacyJsVarGlobalProperty(key)) {
        return;
      }
      console.warn(
        `PsyNet cleared a redefined window.${key} property while uninstalling ` +
          "the legacy js_vars accessor.",
      );
      return;
    }

    clearLegacyJsVarGlobalProperty(key);
  };

  let installLegacyJsVarGlobal = function (key, value) {
    let state = legacyJsVarGlobalStates.get(key);
    if (state) {
      let currentDescriptor = Object.getOwnPropertyDescriptor(window, key);
      let stillInstalled =
        currentDescriptor &&
        currentDescriptor.get === state.get &&
        currentDescriptor.set === state.set;
      if (stillInstalled) {
        state.value = value;
        return;
      }

      // The accessor was replaced or removed while we still tracked it. Drop
      // the stale map entry, clear any foreign redefine, and fall through to a
      // fresh install so `psynet.var` and the legacy mirror stay in sync.
      legacyJsVarGlobalStates.delete(key);
      if (currentDescriptor) {
        if (!clearLegacyJsVarGlobalProperty(key)) {
          return;
        }
        console.warn(
          `PsyNet cleared a redefined window.${key} property and reinstalled ` +
            "the legacy js_vars accessor.",
        );
      }
    }

    // Legacy compatibility must never shadow browser, framework, or third-party
    // state. Authors can always access the page value through `psynet.var`.
    if (key in window) {
      if (!warnedLegacyJsVarGlobalCollisionKeys.has(key)) {
        warnedLegacyJsVarGlobalCollisionKeys.add(key);
        console.warn(
          `PsyNet did not install the legacy js_vars accessor for "${key}" ` +
            `because window.${key} already exists. ` +
            `Use psynet.var[${JSON.stringify(key)}] instead.`,
        );
      }
      return;
    }
    warnedLegacyJsVarGlobalCollisionKeys.delete(key);

    state = {
      get: undefined,
      set: undefined,
      value,
    };
    state.get = function () {
      let mode = getLegacyJsVarGlobalMode();
      if (mode !== "warn") {
        throw legacyJsVarGlobalError(key);
      }
      warnLegacyJsVarGlobalAccess(key);
      return state.value;
    };
    state.set = function (nextValue) {
      let mode = getLegacyJsVarGlobalMode();
      if (mode !== "warn") {
        throw legacyJsVarGlobalError(key);
      }
      warnLegacyJsVarGlobalAccess(key);
      // Preserve the historical behavior: assigning the global changes its
      // mirrored value without mutating the canonical `psynet.var` object.
      state.value = nextValue;
    };

    Object.defineProperty(window, key, {
      configurable: true,
      enumerable: true,
      get: state.get,
      set: state.set,
    });
    legacyJsVarGlobalStates.set(key, state);
  };

  let syncJsVars = function () {
    let jsVars = psynetTemplateData.jsVars || {};
    let mode = getLegacyJsVarGlobalMode();

    legacyJsVarGlobalStates.forEach((_, key) => {
      if (mode === "off" || !(key in jsVars)) {
        uninstallLegacyJsVarGlobal(key);
      }
    });

    if ("pageUuid" in jsVars) {
      // `window.pageUuid` remains an intentional framework lifecycle property,
      // rather than a deprecated author js_vars mirror.
      window.pageUuid = jsVars.pageUuid;
    }

    if (mode !== "off") {
      Object.entries(jsVars).forEach(([key, value]) => {
        if (!RESERVED_JS_VAR_GLOBALS.has(key)) {
          installLegacyJsVarGlobal(key, value);
        }
      });
    }
  };

  syncJsVars();

  $(document).on("change", "#iso-language", function () {
    const locale = $(this).val();
    $.get(
      `${psynetTemplateData.routes.setLocaleParticipant}?locale=${locale}`,
      function () {
        location.reload();
      },
    );
  });

  let beforeunloadFunction = function () {};
  var psynet = (function () {
    /**
     * @namespace
     * @alias psynet
     */

    var psynet = {
      media: {},
      page: {
        ...(psynetTemplateData.page || {}),
        prompt: {},
        control: {},
      },
      utils: {},
      comments: [],
      var: psynetTemplateData.jsVars,
    };
    psynet.SUBMISSION_HANDLED = Symbol("psynet.SUBMISSION_HANDLED");

    // Named CSS colours (red, green, blue, ...) resolve to theme tokens so
    // trial progress, event captions, and the audio meter follow the
    // participant palette instead of the browser's primary colours.
    // Keep in sync with _PARTICIPANT_NAMED_COLORS in psynet/timeline.py.
    // "white" is omitted so it remains CSS white.
    psynet.theme = {
      namedColors: {
        red: "var(--psynet-danger)",
        green: "var(--psynet-success)",
        blue: "var(--psynet-accent)",
        orange: "var(--psynet-warning)",
        grey: "var(--psynet-text-muted)",
        gray: "var(--psynet-text-muted)",
        black: "var(--psynet-text)",
      },
      resolveColor: function (color) {
        if (color == null || color === "") {
          return color;
        }
        let mapped = this.namedColors[String(color).trim().toLowerCase()];
        return mapped || color;
      },
    };

    psynet.utils.shallowCopy = function (x) {
      return Object.assign({}, x);
    };

    psynet.utils.deepCopy = function (x) {
      return JSON.parse(JSON.stringify(x));
    };

    // check if it is a function
    psynet.utils.isFunction = function (functionToCheck) {
      return (
        functionToCheck !== null &&
        functionToCheck &&
        {}.toString.call(functionToCheck) === "[object Function]"
      );
    };

    // Checks which value in the haystack is closest to the needle
    psynet.utils.closest = function (needle, haystack) {
      var bestValue;
      var bestDist;
      var bestI;
      for (var i = 0; i < haystack.length; i++) {
        var proposal = haystack[i];
        var dist = Math.abs(proposal - needle);
        if (bestDist == undefined || dist < bestDist) {
          bestValue = proposal;
          bestDist = dist;
          bestI = i;
        }
      }
      return {
        value: bestValue,
        dist: bestDist,
        index: bestI,
      };
    };

    // check if it is a dictionary
    psynet.utils.isDict = function (dictToCheck) {
      return (
        typeof dictToCheck === "object" &&
        dictToCheck !== null &&
        !(dictToCheck instanceof Array) &&
        !(dictToCheck instanceof Date)
      );
    };

    // check if a key exists in an array
    psynet.utils.keyExistsInArray = function (key, arr) {
      return arr.indexOf(key) > -1;
    };

    // compute a mean; this is not build-in into Javascript XD
    psynet.utils.mean = function (numbers) {
      var total = 0,
        i;
      for (i = 0; i < numbers.length; i += 1) {
        total += numbers[i];
      }
      return total / numbers.length;
    };

    psynet.removeBeforeUnloadEventListener = function () {
      window.removeEventListener("beforeunload", beforeunloadFunction);
    };

    // ---- Template data bootstrap / refresh ---------------------------------
    // In inplace mode we keep one persistent document and replace only the
    // timeline fragment. After each swap we must refresh the bootstrap payload
    // explicitly, because a browser reload is no longer doing that for us.
    psynet.refreshTemplateData = function () {
      const refreshedTemplateDataElement = document.getElementById(
        "psynet-template-data",
      );
      if (!refreshedTemplateDataElement) {
        throw new Error("Missing refreshed psynet template data.");
      }
      const refreshedTemplateData = JSON.parse(
        refreshedTemplateDataElement.textContent,
      );
      Object.keys(psynetTemplateData).forEach((key) => {
        delete psynetTemplateData[key];
      });
      Object.assign(psynetTemplateData, refreshedTemplateData);
      window.psynetTemplateData = psynetTemplateData;
      psynet.var = psynetTemplateData.jsVars || {};
      psynet.page = {
        ...(psynetTemplateData.page || {}),
        prompt: {},
        control: {},
        response: {
          retrieveResponse: undefined,
          stageResponse: null,
        },
      };
      syncJsVars();
      psynet.media.requests = psynetTemplateData.mediaRequests || {};
    };

    psynet.pageReady = false;

    // ---- Page readiness -----------------------------------------------------
    psynet.updatePageReadyMarker = function () {
      let mainBody = document.getElementById("main-body");
      if (!mainBody) {
        return;
      }
      mainBody.setAttribute(
        "data-page-ready",
        psynet.pageReady ? "true" : "false",
      );
    };

    psynet.setPageReady = function (isReady) {
      psynet.pageReady = isReady;
      psynet.updatePageReadyMarker();
      if (isReady) {
        window.dispatchEvent(new CustomEvent("timelinePageReady"));
      }
    };

    psynet.runWhenDocumentReady = function (callback) {
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", callback, { once: true });
        return;
      }
      callback();
    };

    psynet.getJsSynthState = function () {
      if (!psynet.page.prompt.jsSynth) {
        psynet.page.prompt.jsSynth = {
          defaultParams: undefined,
          loadedInstruments: {},
          activeNodes: undefined,
        };
      }
      return psynet.page.prompt.jsSynth;
    };

    psynet.page.response = {
      retrieveResponse: undefined,
      stageResponse: null,
    };

    // ---- Response handler registration -------------------------------------
    psynet.setRetrieveResponseHandler = function (handler) {
      psynet.page.response.retrieveResponse = handler;
    };

    psynet.getRetrieveResponseHandler = function () {
      return psynet.page.response.retrieveResponse;
    };

    psynet.clearRetrieveResponseHandler = function () {
      psynet.page.response.retrieveResponse = undefined;
    };

    psynet.setStageResponseHandler = function (handler) {
      psynet.page.response.stageResponse = handler;
      psynet.stageResponse = handler;
    };

    psynet.getStageResponseHandler = function () {
      return psynet.page.response.stageResponse || psynet.stageResponse;
    };

    psynet.clearStageResponseHandler = function () {
      psynet.page.response.stageResponse = null;
      psynet.stageResponse = null;
    };

    Object.defineProperty(window, "retrieveResponse", {
      configurable: true,
      get() {
        return psynet.getRetrieveResponseHandler();
      },
      set(handler) {
        psynet.setRetrieveResponseHandler(handler);
      },
    });

    Object.defineProperty(window, "DEFAULT_PARAMS", {
      configurable: true,
      get() {
        return psynet.getJsSynthState().defaultParams;
      },
      set(value) {
        psynet.getJsSynthState().defaultParams = value;
      },
    });

    Object.defineProperty(window, "LOADED_INSTRUMENTS", {
      configurable: true,
      get() {
        return psynet.getJsSynthState().loadedInstruments;
      },
      set(value) {
        psynet.getJsSynthState().loadedInstruments = value;
      },
    });

    Object.defineProperty(window, "ACTIVE_NODES", {
      configurable: true,
      get() {
        return psynet.getJsSynthState().activeNodes;
      },
      set(value) {
        psynet.getJsSynthState().activeNodes = value;
      },
    });

    // ---- Page-scoped listeners / resources ---------------------------------
    psynet.pageEventListeners = [];
    psynet.pageCleanupCallbacks = [];

    psynet.addPageEventListener = function (
      target,
      eventName,
      handler,
      options,
    ) {
      target.addEventListener(eventName, handler, options);
      psynet.pageEventListeners.push({
        target: target,
        eventName: eventName,
        handler: handler,
        options: options,
      });
    };

    psynet.addPageCleanupCallback = function (callback) {
      psynet.pageCleanupCallbacks.push(callback);
    };

    psynet.runPageCleanupCallbacks = function () {
      psynet.pageCleanupCallbacks.forEach(function (callback) {
        try {
          callback();
        } catch (error) {
          psynet.log.warn(
            "Page cleanup callback failed: " +
              (error && error.message ? error.message : String(error)),
          );
        }
      });
      psynet.pageCleanupCallbacks = [];
    };

    psynet.clearPageEventListeners = function () {
      psynet.pageEventListeners.forEach(function (listener) {
        listener.target.removeEventListener(
          listener.eventName,
          listener.handler,
          listener.options,
        );
      });
      psynet.pageEventListeners = [];
    };

    psynet.resetPageState = function () {
      psynet.runPageCleanupCallbacks();
      psynet.clearPageEventListeners();
      psynet.comments = [];
      psynet.page = {
        prompt: {},
        control: {},
        response: {
          retrieveResponse: undefined,
          stageResponse: null,
        },
      };
      psynet.setPageReady(false);
      psynet.pageLoaded = false;
      psynet.nextPagePending = false;
      psynet.clearStageResponseHandler();
      psynet.response.staged = {
        rawAnswer: null,
        metadata: {},
        blobs: {},
      };
      psynet.clearRetrieveResponseHandler();
    };

    psynet.executeInlineScript = function (code) {
      let script = document.createElement("script");
      script.textContent = code;
      document.body.appendChild(script);
      script.remove();
    };

    psynet.loadedDocumentScripts = new Set();

    psynet.rememberLoadedDocumentScripts = function () {
      document
        .querySelectorAll(
          'script[src]:not([type="text/psynet-script"]):not([data-psynet-load-failed])',
        )
        .forEach((script) => {
          psynet.loadedDocumentScripts.add(
            new URL(script.src, window.location.href).href,
          );
        });
    };

    psynet.executeExternalScript = function (src) {
      let normalizedSrc = new URL(src, window.location.href).href;

      if (psynet.loadedDocumentScripts.has(normalizedSrc)) {
        return Promise.resolve();
      }

      return new Promise((resolve, reject) => {
        let script = document.createElement("script");
        script.src = normalizedSrc;
        script.async = false;
        script.onload = () => {
          psynet.loadedDocumentScripts.add(normalizedSrc);
          script.remove();
          resolve();
        };
        script.onerror = () => {
          script.remove();
          reject(new Error("Could not load script " + normalizedSrc + "."));
        };
        document.head.appendChild(script);
      });
    };

    // Dependencies load once per document. Page code and page modules share
    // one activation/cleanup lifecycle and run for every hosting page.
    psynet.activeJSPageBehaviors = [];
    psynet.AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

    psynet.loadJSDependencies = async function () {
      psynet.rememberLoadedDocumentScripts();
      for (let src of psynetTemplateData.jsDependencies || []) {
        await psynet.executeExternalScript(src);
      }
    };

    psynet.getPageActivationContext = function () {
      let root = document.getElementById("main-body");
      if (!root) {
        throw new Error("Cannot activate page JavaScript without #main-body.");
      }
      return {
        root,
        trial: psynet.trial,
        vars: psynet.var,
        page: psynet.page,
        psynet,
      };
    };

    psynet.validatePageCleanup = function (cleanup, source) {
      if (cleanup !== undefined && typeof cleanup !== "function") {
        throw new Error(
          `${source} returned a cleanup value that is not a function.`,
        );
      }
    };

    psynet.activatePageJavascript = async function () {
      let activated = [];
      let context = psynet.getPageActivationContext();
      try {
        for (let src of psynetTemplateData.legacyJsLinks || []) {
          // Legacy js_links force a full reload, so a clean document load uses
          // the same once-per-document loader as js_dependencies.
          await psynet.executeExternalScript(src);
        }
        for (let code of psynetTemplateData.legacyScripts || []) {
          // Classic global script semantics for deprecated ``scripts``.
          psynet.executeInlineScript(code);
        }
        for (let [index, code] of (
          psynetTemplateData.jsPageCode || []
        ).entries()) {
          let activate = new psynet.AsyncFunction(
            "root",
            "trial",
            "vars",
            "page",
            "psynet",
            `"use strict";\n${code}`,
          );
          let cleanup = await activate(
            context.root,
            context.trial,
            context.vars,
            context.page,
            context.psynet,
          );
          let source = `js_page_code[${index}]`;
          psynet.validatePageCleanup(cleanup, source);
          activated.push({ source, cleanup });
        }
        for (let src of psynetTemplateData.jsPageModules || []) {
          let normalizedSrc = new URL(src, window.location.href).href;
          let module = await import(normalizedSrc);
          if (typeof module.activate !== "function") {
            throw new Error(
              `JS page module ${normalizedSrc} must export activate(context).`,
            );
          }
          let cleanup = await module.activate(context);
          psynet.validatePageCleanup(cleanup, `JS page module ${normalizedSrc}`);
          activated.push({ source: normalizedSrc, cleanup });
        }
      } catch (error) {
        await psynet.deactivatePageJavascript(activated);
        throw error;
      }
      psynet.activeJSPageBehaviors = activated;
    };

    psynet.deactivatePageJavascript = async function (
      activations = psynet.activeJSPageBehaviors,
    ) {
      if (activations === psynet.activeJSPageBehaviors) {
        psynet.activeJSPageBehaviors = [];
      }
      for (let activation of [...activations].reverse()) {
        if (!activation.cleanup) continue;
        try {
          await activation.cleanup();
        } catch (error) {
          psynet.log.warn(
            `Cleanup failed for ${activation.source}: ` +
              (error && error.message ? error.message : String(error)),
          );
        }
      }
    };

    // Shared by full-page and in-place activation. The guarded loader skips
    // js_dependencies already present as blocking head scripts, then replays
    // inert embedded scripts (in-place pages) before page code and modules.
    psynet.activateManagedPageJavascript = async function () {
      await psynet.loadJSDependencies();
      await psynet.executeScriptSequence(psynet.getEmbeddedScripts());
      await psynet.activatePageJavascript();
    };

    psynet.executeScriptSequence = async function (scriptElements) {
      let inlineBuffer = [];

      let flushInlineBuffer = async function () {
        if (inlineBuffer.length === 0) {
          return;
        }
        // Keep grouped inline scripts in a page-local scope. This prevents
        // var/function declarations from one SPA fragment leaking into later
        // fragments while preserving parser order within each inline group.
        psynet.executeInlineScript(
          "(function(){\n" + inlineBuffer.join("\n") + "\n})();",
        );
        inlineBuffer = [];
      };

      for (let script of scriptElements) {
        if (script.type === "application/json") {
          continue;
        }
        // Preserve HTML parser ordering: inline scripts before a linked script
        // run first, then the linked script, then subsequent inline scripts.
        if (script.src) {
          await flushInlineBuffer();
          await psynet.executeExternalScript(script.src);
        } else if (script.textContent.trim() !== "") {
          inlineBuffer.push(script.textContent);
        }
      }

      await flushInlineBuffer();
    };

    // Framework templates and supported page markup may still contain internal
    // scripts. In-place rendering makes them inert; replay them in DOM order
    // after js_dependencies load, skipping duplicate linked libraries.
    psynet.getEmbeddedScripts = function () {
      let mainBody = document.getElementById("main-body");
      if (!mainBody) {
        return [];
      }

      return Array.from(
        mainBody.querySelectorAll('script[type="text/psynet-script"]'),
      );
    };

    psynet.getElementById = function (root, id) {
      if (typeof root.getElementById === "function") {
        return root.getElementById(id);
      }
      return root.querySelector("#" + id);
    };

    psynet.getPageCssLinks = function (root = document) {
      let cssTemplate = psynet.getElementById(root, "psynet-page-css-links");
      if (!cssTemplate) {
        return [];
      }
      if (cssTemplate.content) {
        return Array.from(
          cssTemplate.content.querySelectorAll("link[rel='stylesheet']"),
        );
      }
      return Array.from(cssTemplate.querySelectorAll("link[rel='stylesheet']"));
    };

    psynet.getPageStyles = function (root = document) {
      let cssTemplate = psynet.getElementById(root, "psynet-page-css");
      if (!cssTemplate) {
        return [];
      }
      if (cssTemplate.content) {
        return Array.from(cssTemplate.content.querySelectorAll("style"));
      }
      return Array.from(cssTemplate.querySelectorAll("style"));
    };

    psynet.removePageStylesheetLinks = function () {
      document
        .querySelectorAll("link[data-psynet-fragment-stylesheet]")
        .forEach((link) => link.remove());
    };

    psynet.ensureStylesheetLinks = function (root = document) {
      psynet.removePageStylesheetLinks();

      for (let link of psynet.getPageCssLinks(root)) {
        let href = new URL(link.href, window.location.href).href;
        let alreadyPresent = Array.from(
          document.head.querySelectorAll("link[rel='stylesheet']"),
        ).some((existingLink) => existingLink.href === href);
        if (!alreadyPresent) {
          let newLink = link.cloneNode(false);
          newLink.rel = "stylesheet";
          newLink.href = href;
          newLink.setAttribute("data-psynet-fragment-stylesheet", "true");
          document.head.appendChild(newLink);
        }
      }
    };

    psynet.applyInlinePageStyles = function (root = document) {
      document
        .querySelectorAll("style[data-psynet-fragment-style]")
        .forEach((style) => style.remove());

      // Inline page CSS is page-scoped in SPA mode, so it must be replaced
      // rather than accumulated across fragment swaps.
      for (let style of psynet.getPageStyles(root)) {
        let newStyle = document.createElement("style");
        newStyle.setAttribute("data-psynet-fragment-style", "true");
        newStyle.textContent = style.textContent;
        document.head.appendChild(newStyle);
      }
    };

    psynet.preloadStylesheetLinks = async function (links) {
      let uniqueHrefs = Array.from(
        new Set(
          links.map((link) => new URL(link.href, window.location.href).href),
        ),
      );

      await Promise.all(
        uniqueHrefs.map(
          (href) =>
            new Promise((resolve, reject) => {
              let alreadyLoaded = Array.from(
                document.head.querySelectorAll("link[rel='stylesheet']"),
              ).some((existingLink) => existingLink.href === href);
              if (alreadyLoaded) {
                resolve();
                return;
              }

              let preload = document.createElement("link");
              preload.rel = "preload";
              preload.as = "style";
              preload.href = href;
              preload.setAttribute(
                "data-psynet-fragment-stylesheet-preload",
                "true",
              );
              preload.onload = () => {
                preload.remove();
                resolve();
              };
              preload.onerror = () => {
                preload.remove();
                reject(new Error("Could not preload stylesheet " + href + "."));
              };
              document.head.appendChild(preload);
            }),
        ),
      );
    };

    // ---- Timeline fragment transitions -------------------------------------
    psynet.setTimelineTransitionBusy = function (isBusy) {
      document.body.classList.toggle("timeline-transition-pending", isBusy);
      let mainBody = document.getElementById("main-body");
      if (mainBody) {
        mainBody.setAttribute("aria-busy", isBusy ? "true" : "false");
      }
    };

    psynet.finalizePageReady = async function () {
      await new Promise((resolve) => setTimeout(resolve, 0));
      psynet.setPageReady(true);
      await psynet.trial.registerEvent("pageReady");
    };

    psynet.prepareTimelineFragment = function (payload) {
      if (!payload || typeof payload.html !== "string" || payload.html === "") {
        throw new Error("Missing timeline fragment HTML payload.");
      }

      let template = document.createElement("template");
      template.innerHTML = payload.html.trim();

      let requiredIds = ["timeline-header", "main-body", "psynet-template-data"];

      let replacements = requiredIds.map((id) => {
        let nextElement = template.content.querySelector("#" + id);
        let currentElement = document.getElementById(id);
        if (!nextElement || !currentElement) {
          throw new Error(
            "Failed to apply timeline fragment payload: missing element #" + id + ".",
          );
        }
        return { currentElement, nextElement };
      });

      // The footer is optional and can differ between pages: show_footer =
      // false omits it, and so does a footer that would have nothing in it.
      // Insert, remove, or replace it rather than demanding that it exists.
      // The media-download bar is reconciled after the footer swap: it is
      // nested in the footer on some pages and a sibling on others, so it
      // cannot share this insert/remove/replace loop.
      let optionalIds = ["footer", "early-exit-modal"];
      let optionalChanges = optionalIds.map((id) => ({
        id,
        nextElement: template.content.querySelector("#" + id),
        currentElement: document.getElementById(id),
      }));

      return {
        payload,
        template,
        replacements,
        optionalChanges,
        stylesheetLinks: psynet.getPageCssLinks(template.content),
      };
    };

    psynet.reconcileMediaDownloadBar = function (template, root) {
      // After the footer has been swapped, a nested next bar is already in
      // the document (it travelled with the footer) and a standalone next bar
      // is still in the template. Mixed pages (Lucid screening without a
      // terminate button, then a later page with one) used to skip the bar
      // entirely and leave either two rails or none.
      const nextStandalone = template.content.querySelector(
        "#media-download-progress-bar",
      );
      const liveBars = Array.from(
        document.querySelectorAll("#media-download-progress-bar"),
      );
      if (nextStandalone !== null) {
        liveBars.forEach((bar) => {
          if (bar !== nextStandalone) bar.remove();
        });
        if (root !== null && nextStandalone.parentNode !== root) {
          root.appendChild(nextStandalone);
        }
      } else {
        liveBars.forEach((bar) => {
          if (bar.closest("#footer") === null) bar.remove();
        });
      }
    };

    psynet.preloadTimelineFragmentAssets = async function (fragment) {
      await psynet.preloadStylesheetLinks(fragment.stylesheetLinks);
    };

    psynet.commitTimelineFragment = function (fragment) {
      psynet.ensureStylesheetLinks(fragment.template.content);
      psynet.applyInlinePageStyles(fragment.template.content);

      fragment.replacements.forEach(({ currentElement, nextElement }) => {
        currentElement.replaceWith(nextElement);
      });

      let root = document.getElementById("timeline-root");
      (fragment.optionalChanges || []).forEach(({ currentElement, nextElement }) => {
        if (currentElement !== null && nextElement !== null) {
          currentElement.replaceWith(nextElement);
        } else if (currentElement !== null) {
          currentElement.remove();
        } else if (nextElement !== null && root !== null) {
          root.appendChild(nextElement);
        }
      });
      psynet.reconcileMediaDownloadBar(fragment.template, root);

      if (fragment.payload.page_uuid !== undefined) {
        window.pageUuid = fragment.payload.page_uuid;
      }
    };

    psynet.deactivateTimelineFragmentLifecycle = async function () {
      if (psynet.trial) {
        await psynet.trial.stop({ force: true });
      }
      await psynet.deactivatePageJavascript();
      await psynet.cleanupPageResources();
      psynet.clearLucidTermination();
      psynet.resetPageState();
    };

    psynet.activateTimelineFragmentLifecycle = async function () {
      // Architecture: docs/developer/page_lifecycle.rst
      // A full page reload used to clear old handlers, globals, and transient
      // page state automatically. In inplace mode we must recreate that
      // lifecycle explicitly before we can mark the new page as ready.
      psynet.refreshTemplateData();
      await psynet.rebuildTrial();
      await psynet.activateManagedPageJavascript();
      psynet.trialProgress = createTrialProgress();
      psynet.initLucidTermination();
      psynet.initEarlyExitButton();
      await psynet.initPage();
      await psynet.finalizePageReady();
      psynet.nextPagePending = false;
      psynet.setTimelineTransitionBusy(false);
      psynet.log.info("Timeline fragment activation complete.");
    };

    psynet.loadNextTimelinePageFromResponse = async function (payload) {
      psynet.log.info("Applying next timeline fragment directly from /response.");
      psynet.setPageReady(false);
      psynet.setTimelineTransitionBusy(true);
      // Failure presentation belongs to the response boundary, which catches
      // errors from this function and invokes handleTimelineTransitionFailure
      // exactly once.
      await psynet.deactivateTimelineFragmentLifecycle();
      let fragment = psynet.prepareTimelineFragment(payload);
      await psynet.preloadTimelineFragmentAssets(fragment);
      psynet.commitTimelineFragment(fragment);
      try {
        await psynet.activateTimelineFragmentLifecycle();
      } catch (error) {
        // The new DOM is already committed. Unwind any trial, managed scripts,
        // legacy cleanup callbacks, and media initialized before activation
        // failed; the response boundary will present the refresh message.
        try {
          await psynet.deactivateTimelineFragmentLifecycle();
        } catch (cleanupError) {
          psynet.log.warn(
            "Failed to clean up an incomplete page activation: " +
              (cleanupError && cleanupError.message
                ? cleanupError.message
                : String(cleanupError)),
          );
        }
        throw error;
      }
    };

    psynet.handleTimelineTransitionFailure = async function (error, message) {
      psynet.setPageReady(false);
      psynet.nextPagePending = false;
      psynet.setTimelineTransitionBusy(false);
      psynet.response.disable();
      psynet.submit.disable();
      psynet.log.error(error.stack || String(error));
      await psynet.alert(
        message ||
          "The next timeline page could not be loaded. Please refresh the page and try again.",
      );
    };

    psynet.waitForEventListener = async function (target, type) {
      await new Promise((resolve) => {
        target.addEventListener(type, () => resolve(), { once: true });
      });
    };

    class PsyNetError extends Error {
      constructor(message) {
        super(message);
        this.name = "PsyNetError"; // (2)
      }
    }

    psynet.log = {};

    psynet.log.max = 100;
    psynet.log.counter = 0;

    psynet.log.generic = function (msg, level) {
      if (
        level !== "error" &&
        level !== "warning" &&
        level !== "info" &&
        level !== "debug"
      ) {
        throw new Error("Invalid log level: " + level);
      }

      let time = new Date();
      console.log(
        "LOG (" +
          level.toUpperCase() +
          ") at " +
          time.toLocaleTimeString() +
          ": " +
          msg,
      );

      if (level != "debug" && psynet.log.counter < psynet.log.max) {
        psynet.log.counter += 1;
        const route = "/log/" + level + "/" + psynetTemplateData.uniqueId;

        dallinger.post(route, { message: msg });
      }
    };

    psynet.log.error = function (msg) {
      var msgWithBrowserInfo =
        msg + "\n    " + "Platform: " + platform.toString();
      psynet.log.generic(msgWithBrowserInfo, "error");
    };

    psynet.log.warning = function (msg) {
      psynet.log.generic(msg, "warning");
    };

    psynet.log.warn = psynet.log.warning;

    psynet.log.info = function (msg) {
      psynet.log.generic(msg, "info");
    };

    psynet.log.debug = function (msg) {
      psynet.log.generic(msg, "debug");
    };

    let Trial = function () {
      let trial = {
        state: null,
        events: {},
        timers: [],
        intervals: [],
        eventLog: [],
        inProgress: false,
        stopping: false,
        stopped: false,
      };

      trial.reset = function () {
        trial.state = null;
        trial.inProgress = false;
        trial.stopped = false;
        trial.startTime = null;
        Object.values(trial.events).forEach((e) => e.reset());
      };

      let Event = function (id, spec) {
        let event = {
          id: id,
          toBeTriggered: [],
          triggerCondition: spec.trigger_condition,
          delay: spec.delay,
          once: spec.once,
          handlers: [],
          happened: false,
          message: spec.message,
          messageColor: spec.message_color,
          js: spec.js,
        };
        event.isTriggeredBy = spec.is_triggered_by.map((t) => {
          let trigger = {
            delay: t.delay,
            triggeringEvent: t.triggering_event,
            fired: false,
            triggeredEvent: event,
          };
          trigger.fire = function (info) {
            trigger.fired = true;
            trigger.triggeredEvent.checkTriggers(info);
          };
          return trigger;
        });

        event.checkTriggers = function (info) {
          if ((trial.stopping || trial.stopped) && id !== "trialStopped") {
            return;
          }
          let allTriggersFired = event.isTriggeredBy.every(
            (trigger) => trigger.fired,
          );
          if (
            (event.triggerCondition == "any" || allTriggersFired) &&
            !(event.once && event.happened)
          ) {
            trial.setTimer(
              () => trial.registerEvent(id, { info: info }),
              event.delay * 1000,
            );
          }
        };

        event.propagateTriggers = function () {
          event.isTriggeredBy.forEach((trigger) => {
            let triggeringEvent = trial.events[trigger.triggeringEvent];
            if (!triggeringEvent) {
              triggeringEvent = genericEvent(trigger.triggeringEvent);
              trial.events[trigger.triggeringEvent] = triggeringEvent;
            }

            triggeringEvent.toBeTriggered.push(trigger);
          });
        };

        event.resetTriggers = function () {
          event.isTriggeredBy.forEach((trigger) => {
            trigger.fired = false;
          });
        };

        event.reset = function () {
          event.happened = false;
          event.resetTriggers();
        };

        event.showMessage = function () {
          if (event.message !== null) {
            psynet.trialProgress.setText(event.message, event.messageColor);
          }
        };

        event.runJS = function (info) {
          if (event.js !== null) {
            Function("info", unescape(event.js))(info);
          }
        };

        event.runHandlers = async function (info) {
          let handlers = event.handlers;

          // Sort in order of decreasing priority
          handlers.sort((a, b) => -(a.priority - b.priority));

          for (const handler of handlers) {
            trial.pendingEventHandlers.add(id);
            try {
              await handler.func(info);
            } catch (error) {
              psynet.log.error(
                "Error in trial handler for event " +
                  id +
                  ": " +
                  (error && error.stack ? error.stack : String(error)),
              );
              throw error;
            } finally {
              trial.pendingEventHandlers.remove(id);
            }
          }
        };

        event.hitTriggers = function (info) {
          if ((trial.stopping || trial.stopped) && id !== "trialStop") {
            return;
          }
          for (const target of event.toBeTriggered) {
            trial.setTimer(() => target.fire(info), target.delay * 1000);
          }
        };

        return event;
      };

      let genericEvent = function (id) {
        // We use snake_case here to mirror the specification format
        // that comes from the Python back-end
        return Event(id, {
          is_triggered_by: [],
          trigger_condition: "all",
          delay: 0.0,
          once: false,
        });
      };

      trial.initEvents = function () {
        let rawEvents = psynetTemplateData.events;
        Object.entries(rawEvents).forEach(
          ([id, spec]) => (trial.events[id] = Event(id, spec)),
        );
        Object.values(trial.events).forEach((event) =>
          event.propagateTriggers(),
        );
      };

      trial.initEvents();

      // TODO: Distinguish page-scoped timers from trial-cycle timers. Some
      // pages use delayed trial events for page-level gating across prompt
      // loops, so normal trial restarts must not clear all timers blindly.
      trial.setTimer = function (handler, timeout) {
        let timer = setTimeout(handler, timeout);
        trial.timers.push(timer);
        return timer;
      };

      trial.setRepeatingTimer = function (handler, interval) {
        let timer = setInterval(handler, interval);
        trial.intervals.push(timer);
        return timer;
      };

      trial.clearTimers = function () {
        trial.timers.forEach((timer) => clearTimeout(timer));
        trial.intervals.forEach((interval) => clearInterval(interval));
        trial.timers = [];
        trial.intervals = [];
      };

      trial.pendingEventHandlers = (() => {
        let data = {};
        return {
          data: data,

          add: function (id) {
            let time = new Date();
            data[id] = {
              timeStarted: time,
            };
          },

          remove: function (id) {
            delete data[id];
          },

          waitFor: async function (providedOptions) {
            let options = {
              pollInterval: 0.005,
              timeOut: 10,
              ignore: [],
            };

            Object.assign(options, providedOptions);

            let timer = 0;

            function queueIsEmpty() {
              let pendingHandlers = Object.keys(data);
              let filteredHandlers = pendingHandlers.filter(
                (id) => !options.ignore.includes(id),
              );
              return filteredHandlers.length == 0;
            }

            function checkQueue() {
              return new Promise((resolve, reject) => {
                let poller = setInterval(() => {
                  if (queueIsEmpty()) {
                    clearInterval(poller);
                    resolve();
                  } else {
                    timer += options.pollInterval;
                    if (timer >= options.timeOut) {
                      let pendingHandlers = Object.keys(data);
                      reject();
                      clearInterval(poller);
                      throw new Error(
                        "Timed out when waiting for event handlers to complete. Pending handlers: " +
                          pendingHandlers.join(", "),
                      );
                    }
                  }
                }, options.pollInterval);
              });
            }

            await checkQueue();
          },
        };
      })();

      trial.logEvent = function (id, info) {
        let time = new Date();
        trial.eventLog.push({
          eventType: id,
          localTime: time,
          info: info,
        });
        psynet.log.debug(id);
      };

      trial.registerEvent = async function (id, providedOptions) {
        if (
          (trial.stopping || trial.stopped) &&
          !["trialStop", "trialStopped"].includes(id)
        ) {
          return;
        }
        let options = {
          info: null,
          once: false,
        };
        Object.assign(options, providedOptions);

        let event = trial.events[id];
        if (event !== undefined && event.happened && options.once) {
          return;
        }

        trial.state = id;
        trial.logEvent(id, options.info);
        if (
          [
            "trialPrepare",
            "trialStart",
            "promptStart",
            "promptEnd",
            "trialFinish",
            "trialStop",
            "trialStopped",
            "responseEnable",
            "submitEnable",
          ].includes(id)
        ) {
          psynet.log.info("Registered trial event: " + id + ".");
        }

        if (event !== undefined) {
          event.happened = true;
          event.showMessage();
          event.runJS(options.info);
          await event.runHandlers(options.info);
          if (
            (trial.stopping || trial.stopped) &&
            !["trialStop", "trialStopped"].includes(id)
          ) {
            return;
          }
          event.hitTriggers(options.info);
        }
      };

      trial.onEvent = function (id, handler, providedOptions) {
        if (typeof handler !== "function") {
          throw new Error("Handler must be a function in trial.onEvent");
        }
        // Higher priority values are executed first
        let options = {
          priority: 0.0,
        };
        Object.assign(options, providedOptions);

        let event = trial.events[id];
        if (event === undefined) {
          event = genericEvent(id);
          trial.events[id] = event;
        }
        event.handlers.push({
          func: handler,
          priority: options.priority,
        });
      };

      trial.getGlobalTime = function () {
        return psynet.media.audioContext.currentTime;
      };

      trial.listEvents = function () {
        return Object.keys(trial.events);
      };

      trial.init = async function () {
        // Should only be called once, on page load
        await trial.registerEvent("trialConstruct");
        $("#buttonStart").attr("disabled", false);
      };

      trial.stop = async function (providedOptions) {
        /**
         * Can be called manually to stop the trial.
         * Is idempotent (you can call it multiple times
         * with no bad side effects).
         */
        let options = {
          force: false,
        };
        Object.assign(options, providedOptions);

        if (trial.stopping || trial.stopped) {
          return;
        }
        if (!options.force && !trial.inProgress) {
          return;
        }
        trial.stopping = true;
        trial.clearTimers();
        trial.inProgress = false;
        try {
          await this.pendingEventHandlers.waitFor();
          await trial.registerEvent("trialStop");
          trial.reset();
          trial.stopped = true;
        } finally {
          trial.stopping = false;
        }
      };

      trial.restart = async function (providedOptions) {
        // Can be called manually at an arbitrary point to restart the trial
        let options = {
          from: "trialPrepare",
        };
        Object.assign(options, providedOptions);

        await trial.stop();
        trial.reset();
        trial.inProgress = true;
        await trial.registerEvent(options.from);
      };

      return trial;
    };

    let registerCoreTrialHandlers = function (trial) {
      trial.onEvent("trialConstruct", async function () {
        await psynet.media.init();
        $(".wait-for-media-load").removeAttr("disabled");
      });

      trial.onEvent("trialPrepare", function () {
        trial.inProgress = true;
      });

      trial.onEvent("trialFinished", function () {
        trial.inProgress = false;
      });

      trial.onEvent("trialStopped", function () {
        trial.inProgress = false;
      });

      trial.onEvent("responseEnable", psynet.response.enable);
      trial.onEvent("submitEnable", psynet.submit.enable);
    };

    psynet.submit = {
      // .sd-navigation__complete-btn is the complete button in SurveyJS
      enable: () =>
        $(".submit, .sd-navigation__complete-btn").removeAttr("disabled"),
      disable: () =>
        $(".submit, .sd-navigation__complete-btn").attr("disabled", "disabled"),
    };

    psynet.response = {
      staged: {
        rawAnswer: null,
        metadata: {},
        blobs: {},
      },
      enable: () => $(".response").removeAttr("disabled"),
      disable: () => $(".response").attr("disabled", "disabled"),
    };

    psynet.rebuildTrial = async function () {
      if (psynet.trial) {
        await psynet.trial.stop({ force: true });
      }
      psynet.trial = Trial();
      registerCoreTrialHandlers(psynet.trial);
    };

    psynet.trial = Trial();
    registerCoreTrialHandlers(psynet.trial);

    psynet.media.types = ["audio", "image", "html", "video"];
    psynet.media.data = {};

    psynet.media.sounds = [];

    psynet.media.loaded = false;

    psynet.media.objectUrls = new Set();

    psynet.media.activeRequests = new Set();
    psynet.media.loadGeneration = 0;

    psynet.media.downloadProgress = {
      byFile: {},
    };

    psynet.media.types.forEach(function (mediaType) {
      psynet.media.downloadProgress.byFile[mediaType] = {};
    });

    psynet.media.downloadProgress.set = function (mediaType, fileId, value) {
      psynet.media.downloadProgress.byFile[mediaType][fileId] = value;
      psynet.media.downloadProgress.updateDisplay();
    };

    psynet.media.downloadProgress.getTotal = function () {
      let res = [];
      Object.values(psynet.media.downloadProgress.byFile).forEach(
        function (processes) {
          Object.values(processes).forEach(function (i) {
            res.push(i);
          });
        },
      );
      return psynet.utils.mean(res);
    };

    psynet.media.downloadProgress.bar = function () {
      return document.getElementById("media-download-progress-bar");
    };

    psynet.media.downloadProgress.updateDisplay = function () {
      let bar = psynet.media.downloadProgress.bar();
      if (bar !== null) {
        const total = Math.round(psynet.media.downloadProgress.getTotal());
        bar.style.width = total + "%";
        if (bar.parentElement?.id !== "footer") {
          bar.hidden = total >= 100;
        }
      }
    };

    psynet.media.downloadProgress.reset = function () {
      psynet.media.types.forEach(function (mediaType) {
        psynet.media.downloadProgress.byFile[mediaType] = {};
      });
      let bar = psynet.media.downloadProgress.bar();
      if (bar !== null) {
        bar.style.width = "0%";
        if (bar.parentElement?.id !== "footer") {
          bar.hidden = false;
        }
      }
    };

    // The last thing we expect of the user is that the resources, that need to be loaded, are dumped as a json:
    // For example here, we request a batch file that contains three files and we request a single file
    // As we can see each file has a ID and a url where the file is stored
    psynet.media.requests = psynetTemplateData.mediaRequests;

    // psynet.media.requests = {
    //     "audio": {
    //         "batch": {
    //             "url": "file_concatenated.mp3",
    //             "ids": ["funk_game_loop", "honey_bee", "there_it_is"],
    //             "type": "batch"
    //         },
    //         "bier": "bier.wav"
    //     }
    // };

    psynet.media.stopAllAudio = function (options) {
      if (typeof stop_all_tonejs_audio === "function") {
        stop_all_tonejs_audio();
      }
      return Promise.all(
        psynet.media.sounds.slice().map(function (sound) {
          return sound.stop(options);
        }),
      );
    };

    psynet.media.isCurrentLoadGeneration = function (loadGeneration) {
      return (
        loadGeneration === undefined ||
        loadGeneration === psynet.media.loadGeneration
      );
    };

    psynet.media.invalidateActiveLoads = function () {
      psynet.media.loadGeneration += 1;
      Array.from(psynet.media.activeRequests).forEach(function (request) {
        try {
          request.abort();
        } catch (error) {
          psynet.log.warn(
            "Failed to abort media request: " +
              (error && error.message ? error.message : String(error)),
          );
        }
      });
      psynet.media.activeRequests.clear();
    };

    psynet.media.registerObjectUrl = function (url) {
      if (typeof url === "string" && url.startsWith("blob:")) {
        psynet.media.objectUrls.add(url);
      }
      return url;
    };

    psynet.media.revokeObjectUrl = function (url) {
      if (!(typeof url === "string" && url.startsWith("blob:"))) {
        return;
      }
      try {
        URL.revokeObjectURL(url);
      } catch (error) {
        psynet.log.warn(
          "Failed to revoke object URL: " + (error && error.message ? error.message : String(error)),
        );
      } finally {
        psynet.media.objectUrls.delete(url);
      }
    };

    psynet.media.stopStream = function (stream) {
      if (!stream || typeof stream.getTracks !== "function") {
        return;
      }
      stream.getTracks().forEach(function (track) {
        if (track && typeof track.stop === "function") {
          track.stop();
        }
      });
    };

    psynet.cleanupPageResources = async function () {
      psynet.log.info("Cleaning page resources before swapped-page activation.");
      psynet.media.invalidateActiveLoads();
      await psynet.media.stopAllAudio({ fadeOut: 0 });

      let clearPlayer = function (player) {
        if (!player) {
          return;
        }
        if (player.tagName === "VIDEO") {
          try {
            player.pause();
          } catch (error) {}
          player.removeAttribute("src");
          if (typeof player.load === "function") {
            player.load();
          }
        } else if (player.tagName === "IMG") {
          player.removeAttribute("src");
        }
      };

      Object.values(psynet.media.data).forEach(function (entries) {
        Object.values(entries || {}).forEach(function (entry) {
          if (!entry) {
            return;
          }
          if (entry.objectUrl) {
            psynet.media.revokeObjectUrl(entry.objectUrl);
          }
          if (entry.url) {
            psynet.media.revokeObjectUrl(entry.url);
          }
          clearPlayer(entry.player);
        });
      });

      Array.from(psynet.media.objectUrls).forEach(function (url) {
        psynet.media.revokeObjectUrl(url);
      });

      psynet.media.types.forEach(function (mediaType) {
        psynet.media.data[mediaType] = {};
        psynet[mediaType] = psynet.media.data[mediaType];
      });
      psynet.media.sounds = [];
      psynet.media.loaded = false;
      psynet.media.downloadProgress.reset();
    };

    psynet.media.getMicrophoneMetadataFromAudioStream = function (stream) {
      var audioTracks = stream.getAudioTracks();
      if (audioTracks.length === 0) {
        psynet.log.error("No tracks found");
        return {};
      } else if (audioTracks.length > 1) {
        psynet.log.warn(
          "Expected exactly one audio track, but got " +
            audioTracks.length +
            " tracks. " +
            "Recording the first track.",
        );
      }

      var audioTrack = audioTracks[0];
      const audioTrackSettings = audioTrack.getSettings();
      return {
        microphone: {
          label: audioTrack.label,
          enabled: audioTrack.enabled,
          muted: audioTrack.muted,
          channelCount: audioTrackSettings.channelCount,
          autoGainControl: audioTrackSettings.autoGainControl,
          echoCancellation: audioTrackSettings.echoCancellation,
          noiseSuppression: audioTrackSettings.noiseSuppression,
          latency: audioTrackSettings.latency,
          sampleRate: audioTrackSettings.sampleRate,
          sampleSize: audioTrackSettings.sampleSize,
        },
      };
    };

    psynet.media.initAudioContext = function () {
      if (
        psynet.media.audioContext &&
        psynet.media.audioContext.state !== "closed"
      ) {
        if (psynet.media.audioContext.state === "suspended") {
          psynet.media.audioContext.resume();
        }
        return;
      }

      let context = null;
      if ("webkitAudioContext" in window) context = new webkitAudioContext();
      if ("AudioContext" in window) context = new AudioContext();
      if (!context) {
        throw Error(
          "ERROR: No AudioContext available. Try Chrome, Safari or Firefox Nightly.",
        );
      }
      if (context.state == "suspended") {
        context.resume();
      }
      psynet.media.audioContext = context;
    };

    let askUserToResume = function () {
      return new Promise((resolve) => {
        let resumeModal = $("#resume-modal");
        let resumeButton = $("#resume-button");
        resumeModal.css("display", "block");
        resumeButton.click(async function () {
          resumeModal.css("display", "none");
          $("#js-psych").trigger("focus");
          await psynet.media.init();
          resolve();
        });
      });
    };

    psynet.media.init = async function () {
      psynet.media.initAudioContext();

      if (psynet.media.audioContext.state == "suspended") {
        psynet.log.info(
          "Audio context is suspended, and can only be resumed " +
            "after a user interaction. Waiting for the participant to click 'Resume'.",
        );
        await askUserToResume();
        psynet.media.initAudioContext();
      }
      let requests = psynet.media.requests;
      let mediaTypes = Object.keys(requests);
      // Nothing here touches the progress bar: it may not exist (show_footer =
      // false omits it), and its appearance belongs to participant.css, which
      // keeps it a solid accent rather than animating a gradient.
      await Promise.all(mediaTypes.map((x) => processRequests(x, requests[x])));
    };

    let initMediaType = function (mediaType) {
      let x = {};
      psynet.media.data[mediaType] = x;
      psynet[mediaType] = x;
    };

    let initStimulus = function (id, mediaType) {
      psynet.media.data[mediaType][id] = {
        loaded: false,
      };
    };

    let processRequests = function (mediaType, requests) {
      initMediaType(mediaType);
      checkRequests(requests);

      return Promise.all(
        Object.keys(requests).map(function (id) {
          let value = requests[id];
          if (isBatch(value)) {
            return preloadBatch(id, value, mediaType);
          } else {
            let url = value;
            return preloadStimulus(id, url, mediaType);
          }
        }),
      );
    };

    let isBatch = function (x) {
      return psynet.utils.isDict(x);
    };

    async function unzipBatch(url) {
      console.log("Zip file: " + url);
      let batchdata = fetch(url)
        .then((response) => response.arrayBuffer())
        .then((data) => JSZip.loadAsync(data))
        .then((zip) => {
          return zip.file("stim.batch").async("uint8array");
        })
        .then((data) => {
          return data;
        });
      return batchdata;
    }

    let preloadBatch = async function (batchId, batch, mediaType) {
      let url = batch.url;

      let args = {
        batchId: batchId,
        stimulusIds: batch.ids,
        mediaType: mediaType,
        fileId: batchId,
        loadGeneration: psynet.media.loadGeneration,
      };
      args.stimulusIds.forEach(function (id) {
        initStimulus(id, mediaType);
      });

      let unzip = batch.unzip;
      if (unzip) {
        let data = await unzipBatch(batch.url);
        return processMediaBatch[mediaType](data.buffer, args);
      } else {
        return createRequest(
          url,
          mediaType,
          processMediaBatch[mediaType],
          args,
        );
      }
    };

    let preloadStimulus = function (stimulusId, url, mediaType) {
      let args = {
        stimulusId: stimulusId,
        mediaType: mediaType,
        fileId: stimulusId,
        loadGeneration: psynet.media.loadGeneration,
      };
      initStimulus(stimulusId, mediaType);
      return createRequest(
        url,
        mediaType,
        createMediaFromBuffer[mediaType],
        args,
      );
    };

    function reportRequestError(url, status) {
      let msg;
      if (status === 404) {
        msg =
          "Failed to load media asset at " + url + " (404, file not found).";
      } else {
        msg =
          "Failed to load media asset at " +
          url +
          " (error code = " +
          status +
          ").";
      }
      throw Error(msg);
    }

    async function createRequest(url, mediaType, callbackFunction, args) {
      let request = new XMLHttpRequest();
      request.open("GET", url, true);
      let loadGeneration = args.loadGeneration;

      if (mediaType == "audio" || mediaType == "html") {
        request.responseType = "arraybuffer";
      } else if (mediaType == "image" || mediaType == "video") {
        request.responseType = "blob";
      } else {
        throw Error("Unsupported media type: " + mediaType);
      }

      // Make sure all batches are processed as arraybuffers
      if (args["batchId"]) {
        request.responseType = "arraybuffer";
      }

      request.onprogress = function (e) {
        if (!psynet.media.isCurrentLoadGeneration(loadGeneration)) {
          return;
        }
        psynet.media.downloadProgress.set(
          args["mediaType"],
          args["fileId"],
          (e.loaded * 100) / e.total,
        );
      };

      return new Promise((resolve, reject) => {
        let finishRequest = function () {
          psynet.media.activeRequests.delete(request);
        };

        request.onload = async function () {
          finishRequest();
          if (!psynet.media.isCurrentLoadGeneration(loadGeneration)) {
            resolve(false);
            return;
          }
          try {
            if (request.status === 200) {
              await callbackFunction(request.response, args);
              resolve(true);
            } else {
              reportRequestError(url, request.status);
            }
          } catch (error) {
            reject(error);
          }
        };

        request.onerror = function () {
          finishRequest();
          reject(
            Error(
              "Failed to load media asset at " +
                url +
                " (network error).",
            ),
          );
        };

        request.onabort = function () {
          finishRequest();
          resolve(false);
        };

        psynet.media.activeRequests.add(request);
        request.send();
      });
    }

    let checkRequests = function (requests) {
      // - Checks for missing URLs in batches.
      // - Checks for duplicated IDs
      let ids = [];

      let log = function (id) {
        var value = requests[id];
        if (psynet.utils.isDict(value)) {
          logBatch(value);
        } else {
          logStimulus(id);
        }
      };

      let logStimulus = function (id) {
        if (psynet.utils.keyExistsInArray(id, ids)) {
          throw Error(
            "The ID you specified `" +
              id +
              "` already exists! IDs must be unique!",
          );
        }
        ids.push(id);
      };

      let logBatch = function (batch) {
        if (!("url" in batch)) {
          throw Error('Each batch object must contain a "url" attribute.');
        }
        if (!("ids" in batch)) {
          throw Error(
            'Each batch object must contain an "ids" attribute specifying its constituent stimuli.',
          );
        }
        let stimulusIds = batch["ids"];
        stimulusIds.forEach(logStimulus);
      };

      Object.keys(requests).forEach(log);
    };

    let createAudioStimulus = function (data, stimulusId, loadGeneration) {
      psynet.log.debug("Decoding sound " + stimulusId + "...");

      return new Promise((resolve) => {
        psynet.media.audioContext.decodeAudioData(data, function (buffer) {
          if (!psynet.media.isCurrentLoadGeneration(loadGeneration)) {
            resolve(false);
            return;
          }
          psynet.log.debug("Sound " + stimulusId + " decoded.");

          let out = psynet.media.data.audio[stimulusId];
          if (!out) {
            resolve(false);
            return;
          }
          out.buffer = buffer;

          out.play = function (providedOptions) {
            let options = {
              fadeIn: 0.0,
              fadeOut: 0.0,
              startDelay: 0.01,
              gain: 1,
              loop: false,
              start: null,
              end: null,
            };

            Object.assign(options, providedOptions);

            const start = options.start === null ? 0.0 : options.start;
            const duration =
              options.end === null ? undefined : options.end - options.start;

            let sound = {
              source: psynet.media.audioContext.createBufferSource(),
              gainNode: psynet.media.audioContext.createGain(),
              startTime:
                psynet.media.audioContext.currentTime + options.startDelay,
              options: options,
              manuallyStopped: false,
              duration: duration === undefined ? buffer.duration : duration,
              stimulusId: stimulusId,
              onEnd: null,
            };

            const soundTrial = psynet.trial;
            const soundPageUuid = window.pageUuid;
            let stopTimer = null;
            let completionTimer = null;
            let stopCompletionTimer = null;
            let stopPromise = null;
            let resolveStopPromise = null;
            let completed = false;

            let clearSoundTimers = function () {
              if (stopTimer !== null) {
                clearTimeout(stopTimer);
                stopTimer = null;
              }
              if (completionTimer !== null) {
                clearTimeout(completionTimer);
                completionTimer = null;
              }
              if (stopCompletionTimer !== null) {
                clearTimeout(stopCompletionTimer);
                stopCompletionTimer = null;
              }
            };

            let settleStopPromise = function () {
              if (resolveStopPromise !== null) {
                resolveStopPromise();
                resolveStopPromise = null;
              }
              stopPromise = null;
            };

            let isSoundTrialActive = function () {
              return (
                psynet.trial === soundTrial &&
                window.pageUuid === soundPageUuid &&
                !soundTrial.stopping &&
                !soundTrial.stopped
              );
            };

            let stopSource = function () {
              try {
                sound.source.stop();
              } catch (error) {
                if (!error || error.name !== "InvalidStateError") {
                  psynet.log.warn(
                    "Failed to stop audio " +
                      sound.stimulusId +
                      ": " +
                      (error && error.message ? error.message : String(error)),
                  );
                }
              }
              completeSound();
            };

            let completeSound = function () {
              if (completed) {
                return;
              }
              completed = true;
              clearSoundTimers();
              settleStopPromise();
              psynet.log.debug("Finished sound with ID = " + sound.stimulusId);
              psynet.media.sounds = psynet.media.sounds.filter(
                (s) => s !== sound,
              );
              if (!isSoundTrialActive()) {
                return;
              }
              soundTrial.registerEvent("audioFinished: " + sound.stimulusId);
              if (sound.options.loop && !sound.manuallyStopped) {
                psynet.log.debug("Looping sound with ID = " + out.stimulusId);
                out.play(sound.options);
              }
            };

            sound.source.buffer = buffer;

            sound.source.connect(sound.gainNode);
            sound.gainNode.connect(psynet.media.audioContext.destination);

            sound.gainNode.gain.setValueAtTime(0.001, sound.startTime);

            sound.source.start(sound.startTime, start, duration);

            if (options.gain > 1e-10) {
              sound.gainNode.gain.exponentialRampToValueAtTime(
                options.gain,
                psynet.media.audioContext.currentTime +
                  options.startDelay +
                  options.fadeIn,
              );
            }

            if (sound.options.fadeOut > 0.0) {
              stopTimer = psynet.trial.setTimer(
                () => sound.stop({ fadeOut: options.fadeOut, manual: false }),
                1000 * (options.startDelay + sound.duration - options.fadeOut),
              );
            }

            completionTimer = psynet.trial.setTimer(() => {
              psynet.log.warn(
                "Audio ended event did not fire for " +
                  sound.stimulusId +
                  "; using timed fallback completion.",
              );
              completeSound();
            }, 1000 * (options.startDelay + sound.duration + 0.1));

            sound.stop = function (providedOptions) {
              let options = {
                fadeOut: sound.options.fadeOut,
                manual: true,
              };

              Object.assign(options, providedOptions);

              if (completed) {
                return Promise.resolve();
              }
              if (stopPromise !== null) {
                sound.manuallyStopped = sound.manuallyStopped || options.manual;
                return stopPromise;
              }

              clearSoundTimers();

              psynet.log.debug("Stopping audio " + sound.stimulusId + ".");

              sound.manuallyStopped = options.manual;

              if (stopPromise === null) {
                stopPromise = new Promise((resolve) => {
                  resolveStopPromise = resolve;
                });
              }

              let gainNow = sound.gainNode.gain.value;
              let timeNow = psynet.media.audioContext.currentTime;

              if (sound.gainNode.gain.value > 0.001) {
                sound.gainNode.gain.setValueAtTime(gainNow, timeNow);
                sound.gainNode.gain.exponentialRampToValueAtTime(
                  0.001,
                  timeNow + options.fadeOut,
                );
              }

              const finishStop = () => {
                stopCompletionTimer = null;
                stopSource();
              };

              if (options.fadeOut <= 0) {
                queueMicrotask(finishStop);
              } else {
                stopCompletionTimer = soundTrial.setTimer(
                  finishStop,
                  options.fadeOut * 1000,
                );
              }
              return stopPromise;
            };

            sound.source.addEventListener("ended", function () {
              completeSound();
            });

            psynet.media.sounds.push(sound);
            return sound;
          };

          out.stop = function (options) {
            return Promise.all(
              psynet.media.sounds
                .filter((s) => s.stimulusId == stimulusId)
                .map((s) => s.stop(options)),
            );
          };

          out.loaded = true;

          resolve(true);
        });
      });
    };

    psynet.media.blobToArrayBuffer = async function (blob) {
      let buffer = await new Response(blob).arrayBuffer();
      return buffer;
    };

    // Used to add extra stimuli that aren't loaded as part of the initial media load
    // (needs refactoring in a general cross-media way)
    psynet.media.addExtraAudioStimulus = async function (buffer, stimulusId) {
      initStimulus(stimulusId, "audio");
      await createAudioStimulus(
        buffer,
        stimulusId,
        psynet.media.loadGeneration,
      );
    };

    let createMediaFromBuffer = {};
    createMediaFromBuffer.audio = function (data, args) {
      if (!psynet.media.isCurrentLoadGeneration(args.loadGeneration)) {
        return false;
      }
      psynet.media.downloadProgress.set(args.mediaType, args.fileId, 100);
      return createAudioStimulus(data, args.stimulusId, args.loadGeneration);
    };

    let getImageMetadataFromURL = function (url) {
      return new Promise((resolve, reject) => {
        let img = new Image();
        img.onload = () =>
          resolve({
            width: img.width,
            height: img.height,
          });
        img.onerror = () => reject();
        img.src = url;
      });
    };

    function getMimeTypeFromArrayBuffer(arrayBuffer) {
      const uint8arr = new Uint8Array(arrayBuffer);
      var dec = new TextDecoder();
      var text = dec.decode(uint8arr).toLowerCase().replace(" ", "");

      if (text.includes("<svg")) {
        return "image/svg+xml";
      } else {
        return null;
      }
    }

    createMediaFromBuffer.html = async function (data, args) {
      let stimulusId = args["stimulusId"];
      let mediaType = args["mediaType"];
      let fileId = args["fileId"];

      if (!psynet.media.isCurrentLoadGeneration(args.loadGeneration)) {
        return false;
      }
      let player = document.getElementById(stimulusId);
      if (player != null) {
        psynet.log.debug(
          "Associating " +
            mediaType +
            " '" +
            stimulusId +
            "' with the player of the same name.'",
        );
        const uint8arr = new Uint8Array(data);
        var dec = new TextDecoder();
        player.innerHTML = dec.decode(uint8arr);
      }
      let out = psynet.media.data[mediaType][stimulusId];
      if (!out) {
        return false;
      }
      out.player = player;
      out.innerHTML = player.innerHTML;
      // let metadata = await getSvgMetadataFromData(player.innerHTML);
      // {#out.url = url;#}
      // {#out.width = metadata.width;#}
      // {#out.height = metadata.height;#}
      // {#out.aspectRatio = out.width / out.height;#}
      out.loaded = true;

      psynet.media.downloadProgress.set(mediaType, fileId, 100);
      return true;
    };

    createMediaFromBuffer.image = async function (data, args) {
      let stimulusId = args["stimulusId"];
      let mediaType = args["mediaType"];
      let fileId = args["fileId"];

      if (!psynet.media.isCurrentLoadGeneration(args.loadGeneration)) {
        return false;
      }
      let player = document.getElementById(stimulusId);

      if (player) {
        psynet.log.debug(
          "Associating " +
            mediaType +
            " '" +
            stimulusId +
            "' with the player of the same name.'",
        );
      } else {
        player = document.createElement("div");
      }

      if (!data.type) {
        let mimeType = getMimeTypeFromArrayBuffer(data);
        data = new Blob([data], { type: mimeType });
      }

      player.src = psynet.media.registerObjectUrl(URL.createObjectURL(data));

      let out = psynet.media.data[mediaType][stimulusId];
      if (!out) {
        return false;
      }
      out.player = player;
      out.objectUrl = player.src;

      let url = player.src;
      let metadata = await getImageMetadataFromURL(url);
      if (!psynet.media.isCurrentLoadGeneration(args.loadGeneration)) {
        return false;
      }
      out.url = url;
      out.width = metadata.width;
      out.height = metadata.height;
      out.aspectRatio = out.width / out.height;
      out.loaded = true;

      psynet.media.downloadProgress.set(mediaType, fileId, 100);
      return true;
    };

    createMediaFromBuffer.video = async function (data, args) {
      let stimulusId = args["stimulusId"];
      let mediaType = args["mediaType"];
      let fileId = args["fileId"];

      if (!psynet.media.isCurrentLoadGeneration(args.loadGeneration)) {
        return false;
      }
      let player = document.getElementById(stimulusId);
      if (player != null) {
        psynet.log.debug(
          "Associating " +
            mediaType +
            " '" +
            stimulusId +
            "' with the player of the same name.'",
        );
        data = new Blob([data]); // convert to blob
        player.src = psynet.media.registerObjectUrl(URL.createObjectURL(data));
        player.classList.remove("loader");
        player.load();
        await psynet.waitForEventListener(player, "canplaythrough");
      }

      if (!psynet.media.isCurrentLoadGeneration(args.loadGeneration)) {
        return false;
      }
      let out = psynet.media.data[mediaType][stimulusId];
      if (!out) {
        return false;
      }
      out.player = player;
      if (player != null && player.src) {
        out.objectUrl = player.src;
      }
      out.loaded = true;

      psynet.media.downloadProgress.set(mediaType, fileId, 100);
      return true;
    };

    let processMediaBatch = {};

    processMediaBatch.extract_stimuli = function (data, args) {
      let stimulusIds = args["stimulusIds"];
      let mediaType = args["mediaType"];
      let fileId = args["fileId"];
      let loadGeneration = args["loadGeneration"];

      if (!psynet.media.isCurrentLoadGeneration(loadGeneration)) {
        return false;
      }

      function extractBuffer(src, start, length) {
        // This function is used to find the start and end of each file
        let dstU8 = new Uint8Array(length);
        let srcU8 = new Uint8Array(src, start, length);
        dstU8.set(srcU8);
        return dstU8;
      }

      let numFiles = 0;
      psynet.log.debug(
        "Unpacking the " + mediaType + ' batch "' + fileId + '".',
      );
      let bb = new DataView(data);
      let offset = 0;
      let promises = [];

      while (offset < bb.byteLength) {
        let stimulusId = stimulusIds[numFiles];
        let length = bb.getUint32(offset, true);
        offset += 4;
        let media = extractBuffer(data, offset, length);
        offset += length;
        numFiles++;

        if (numFiles > stimulusIds.length) {
          throw Error(
            "Too many stimuli found in batch file (" +
              "expected " +
              stimulusIds.length +
              ", got at least" +
              numFiles +
              ").",
          );
        }

        args = {
          stimulusId: stimulusId,
          mediaType: mediaType,
          fileId: fileId,
          loadGeneration: loadGeneration,
        };

        // In contrast to audio, video, and image are not loaded into the DOM, so we need to create a player
        if (mediaType === "html") {
          $("#media-container").prepend(
            '<div style="display: none" class="html" id="' +
              stimulusId +
              '"></div>',
          );
        }

        if (mediaType === "image") {
          $("#media-container").prepend(
            '<img style="display: none" class="image" id="' +
              stimulusId +
              '"></img>',
          );
        } else if (mediaType === "video") {
          $("#media-container").prepend(
            '<video style="display: none" class="video" id="' +
              stimulusId +
              '"></video>',
          );
        }

        promises.push(createMediaFromBuffer[mediaType](media.buffer, args));
      }
      if (numFiles < stimulusIds.length) {
        throw Error(
          "Too few stimuli found in batch file (" +
            "expected " +
            stimulusIds.length +
            ", got " +
            numFiles +
            ").",
        );
      }
      return Promise.all(promises);
    };

    const SUPPORTED_MODALITIES = ["audio", "image", "html", "video"];
    SUPPORTED_MODALITIES.forEach(function (modality) {
      processMediaBatch[modality] = function (data, args) {
        //, ids,) {
        return processMediaBatch.extract_stimuli(data, args);
      };
    });

    let initModal = function (modalId, buttonId, closeClass = "close") {
      let modal = document.getElementById(modalId);
      let commentBtn = document.getElementById(buttonId);
      let span = document.getElementsByClassName(closeClass)[0];

      if (modal !== null && commentBtn !== null) {
        commentBtn.onclick = function () {
          modal.style.display = "block";
        };

        span.onclick = function () {
          modal.style.display = "none";
        };

        window.onclick = function (event) {
          if (event.target === modal) {
            modal.style.display = "none";
          }
        };
      }

      $("#send-comment")
        .off("click.psynetComment")
        .on("click.psynetComment", function () {
        var text = $("#comment-text");
        var textValue = text.val();

        if (textValue !== "") {
          psynet.comments.push(textValue);
          text.val("");
          psynet.alert(psynetTemplateData.strings.commentStored);
        }
        });
    };

    psynet.estimateDownloadSpeed = function () {
      // Returns estimated download speed in megabits/second
      // (at the time of writing, this is capped at 10).
      let connection =
        navigator.connection ||
        navigator.mozConnection ||
        navigator.webkitConnection;
      if (connection) {
        return connection.downlink;
      } else {
        return null;
      }
    };

    psynet.pageLoaded = false;

    let waitForDocumentReady = function () {
      return new Promise((resolve) => {
        psynet.runWhenDocumentReady(resolve);
      });
    };

    let waitForBrowserCheck = async function () {
      return await browser.validate();
    };

    psynet.initPage = async function () {
      console.log("Initialising page...");

      psynet.registerErrorHandler();
      initModal("comment-modal", "comment-button");

      psynet.response.disable();
      psynet.submit.disable();
      $(".wait-for-media-load").attr("disabled", "disabled");

      await waitForDocumentReady();
      psynet.rememberLoadedDocumentScripts();

      psynet.pageLoadTime = new Date();
      psynet.pageLoaded = true;
      psynet.assignmentId = psynetTemplateData.assignmentId;
      psynet.participantId = psynetTemplateData.participantId;
      psynet.uniqueId = psynetTemplateData.uniqueId;

      let correctBrowser = await waitForBrowserCheck();

      updateProgressAndReward();

      if (correctBrowser) {
        await new Promise((resolve) => setTimeout(resolve, 25));
        await psynet.trial.init();
      }
    };

    psynet.registerErrorHandler = function () {
      if (psynet._errorHandlerRegistered) {
        return;
      }
      psynet._errorHandlerRegistered = true;
      window.onerror = function (msg, url, line, col, error) {
        if (error) {
          psynet.log.error(error.stack);
        }
      };
      window.addEventListener("unhandledrejection", function (event) {
        let reason = event.reason;
        psynet.log.error((reason && reason.stack) || String(reason));
      });
    };

    psynet.nextPagePending = false;

    psynet.submitResponse = async function (onRejection) {
      let response;

      try {
        response = await psynet.compileResponse();
      } catch (error) {
        onRejection();
        throw error;
      }
      if (response === psynet.SUBMISSION_HANDLED) {
        return;
      }

      await psynet.nextPage(
        response.rawAnswer,
        response.metadata,
        response.blobs,
        onRejection,
      );
    };

    psynet.compileResponse = async function () {
      let response = {};
      let retrieveResponseHandler = psynet.getRetrieveResponseHandler();
      let stageResponseHandler = psynet.getStageResponseHandler();

      if (typeof retrieveResponseHandler == "undefined") {
        if (stageResponseHandler) {
          let stagedResponse = await stageResponseHandler();
          if (stagedResponse === psynet.SUBMISSION_HANDLED) {
            return stagedResponse;
          }
        }
        response = psynet.response.staged;
      } else {
        response = retrieveResponseHandler();
      }

      return response;
    };

    // ---- Response submission / handling ------------------------------------
    psynet.nextPage = async function (rawAnswer, metadata, blobs, onRejection) {
      if (!psynet.pageReady) {
        psynet.log.info("Blocked nextPage because pageReady is false.");
        psynet.alert(psynetTemplateData.strings.pageLoadNotReady);
        return false;
      }
      if (psynet.nextPagePending) {
        psynet.log.info("Blocked nextPage because nextPagePending is true.");
        psynet.log.debug(
          "Skipping nextPage request as nextPage is already pending.",
        );
        return false;
      }
      psynet.log.info("Submitting response via nextPage.");
      psynet.nextPagePending = true;
      // rawAnswer, metadata, and blobs default to psynet.response.staged if they
      // are not provided explicitly.
      //
      // Returns true if the answer passes validation checks.
      if (rawAnswer === undefined) {
        rawAnswer = psynet.response.staged.rawAnswer;
      }
      if (metadata === undefined) {
        metadata = psynet.response.staged.metadata;
      }
      metadata.comments = psynet.comments;
      if (blobs === undefined) {
        blobs = psynet.response.staged.blobs;
      }
      if (psynetTemplateData.flags.lucidRecruitment) {
        psynet.removeBeforeUnloadEventListener();
      }
      let passedValidation = await submitGenericResponse(
        rawAnswer,
        metadata,
        blobs,
        onSuccessResponse,
        onErrorResponse,
        onRejection,
      );
      if (!passedValidation) {
        psynet.nextPagePending = false;
      }
      return passedValidation;
    };

    psynet.alert = function (text) {
      return new Promise((resolve) => {
        let alertModal = $("#alert-modal");
        let alertButton = $("#alert-button");
        let alertText = $("#alert-message");
        alertText.text(text);
        alertModal.css("display", "block");
        alertButton.click(async function () {
          alertModal.css("display", "none");
          resolve();
        });
      });
    };

    psynet.requireTimelineFragmentPayload = function (response) {
      if (response && response.timeline_fragment) {
        return response.timeline_fragment;
      }
      throw new Error(
        "Missing timeline_fragment in approved /response while inplace timeline transitions are enabled.",
      );
    };

    psynet.isSameSessionPageUpdate = function (response) {
      let nextSessionId = response.page.attributes?.session_id;
      let currentSessionId = psynet.page.attributes?.session_id;
      return (
        nextSessionId !== undefined &&
        nextSessionId !== null &&
        currentSessionId !== undefined &&
        currentSessionId !== null &&
        nextSessionId === currentSessionId
      );
    };

    psynet.requiresFullPageReloadTransition = function (response) {
      return Boolean(
        psynet.page.attributes?.requires_full_page_reload ||
          response.page.attributes?.requires_full_page_reload,
      );
    };

    psynet.loadNextTimelinePageWithReload = function () {
      window.location = "/timeline?unique_id=" + psynet.uniqueId;
    };

    // Finish the assignment and go to the exit page without leaving the
    // completed timeline in history. Using location.replace (instead of
    // Dallinger's window.location assignment) means Back from exit cannot
    // revive a finished session; the server also redirects finished
    // /timeline visits as a backstop.
    psynet.finishAndGoToExit = function () {
      const participantId = dallinger.identity.participantId;
      const exitRoute = "/recruiter-exit?participant_id=" + participantId;
      return dallinger
        .post("/worker_complete", { participant_id: participantId })
        .done(function () {
          dallinger.allowExit();
          let openedFromDashboard = false;
          try {
            openedFromDashboard =
              window.opener &&
              window.opener.location.pathname.startsWith("/dashboard");
          } catch (error) {
            openedFromDashboard = false;
          }
          if (window.opener && !openedFromDashboard) {
            window.opener.location.replace(exitRoute);
            window.close();
          } else {
            window.location.replace(exitRoute);
          }
        })
        .fail(function () {
          psynetErrorPage.go({
            uniqueId: psynet.uniqueId,
            participantId: participantId,
          });
        });
    };

    // If the browser restores a timeline page from the back/forward cache
    // (for example after Back from exit), force a reload so the server can
    // redirect finished participants.
    window.addEventListener("pageshow", function (event) {
      if (event.persisted) {
        window.location.reload();
      }
    });

    psynet.handleApprovedResponse = async function (response) {
      psynet.log.debug("Response received successfully.");

      if (psynet.isSameSessionPageUpdate(response)) {
        psynet.page = response.page;
        psynet.trial.registerEvent("pageUpdated");
        psynet.nextPagePending = false;
        return true;
      }

      if (psynet.requiresFullPageReloadTransition(response)) {
        psynet.loadNextTimelinePageWithReload();
        return true;
      }

      if (psynetTemplateData.flags.inplaceTimelineTransitions) {
        await psynet.loadNextTimelinePageFromResponse(
          psynet.requireTimelineFragmentPayload(response),
        );
      } else {
        psynet.loadNextTimelinePageWithReload();
      }

      return true;
    };

    psynet.handleRejectedResponse = async function (response, onRejection) {
      psynet.log.debug("Response rejected.");
      psynet.alert(response.message);
      psynet.response.enable();
      psynet.submit.enable();
      if (onRejection) {
        onRejection(response);
      }
      return false;
    };

    let onSuccessResponse = async function (request, onRejection) {
      let response = JSON.parse(request.response);
      if (response.submission === "approved") {
        return await psynet.handleApprovedResponse(response);
      }
      if (response.submission === "rejected") {
        return await psynet.handleRejectedResponse(response, onRejection);
      }
      throw Error("Received a malformed response.");
    };

    let onPageUpdated = function (event) {
      console.log(
        "Dispatched 'onPageUpdated' event. Sending data to Unity:\nattributes:" +
          psynet.page.attributes +
          "\ncontents:" +
          psynet.page.contents,
      );
      unityInstance.SendMessage(
        "PsynetObj",
        "GetData",
        JSON.stringify({
          attributes: psynet.page.attributes,
          contents: psynet.page.contents,
        }),
      );
    };

    let onErrorResponse = function () {
      psynetErrorPage.go({
        uniqueId: psynet.uniqueId,
        participantId: psynetTemplateData.participantId,
      });
    };

    let addBlobs = function (formData, blobs) {
      for (let [key, value] of Object.entries(blobs)) {
        if (key === "json") {
          throw Error("Blobs may not be named 'json'.");
        }
        formData.append(key, value);
      }
    };

    let prepareJsonSubmission = function (rawAnswer, metadata) {
      var currentTime = new Date();

      var allMetadata = {
        time_taken: (currentTime - psynet.pageLoadTime) / 1000,
        platform: platform.toString(),
        download_speed_megabits_per_sec: psynet.estimateDownloadSpeed(),
        event_log: psynet.trial.eventLog,
      };

      if (metadata !== undefined) {
        for (var x in metadata) {
          allMetadata[x] = metadata[x];
        }
      }

      return JSON.stringify({
        participant_id: psynet.participantId,
        page_uuid: psynet.var.pageUuid,
        assignment_id: psynet.assignmentId,
        unique_id: psynet.uniqueId,
        raw_answer: rawAnswer,
        metadata: allMetadata,
        include_timeline_fragment: !psynet.page.attributes
          ?.requires_full_page_reload,
      });
    };

    let submitGenericResponse = function (
      rawAnswer,
      metadata,
      blobs,
      onSuccessResponse,
      onErrorResponse,
      onRejection,
    ) {
      // rawAnswer - an arbitrary Javascript object (not necessarily an Object) to be sent to JSON
      // blobs - optional Object, each attribute should be a blob to upload.
      //       - Note that 'json' is not a permitted name for an attribute
      //
      // Returns true if the answer passed validation checks, false otherwise.
      $(" .response, .submit ").prop("disabled", true);

      const json = prepareJsonSubmission(rawAnswer, metadata);

      var formData = new FormData();
      formData.append("json", json);

      if (blobs !== undefined) {
        addBlobs(formData, blobs);
      }

      return new Promise((resolve) => {
        let request = new XMLHttpRequest();
        request.onreadystatechange = async function () {
          if (request.readyState === 4) {
            let passedValidation;
            try {
              if (request.status === 200) {
                psynet.log.debug("Response was successfully received.");
                passedValidation = await onSuccessResponse(request, onRejection);
              } else {
                psynet.log.debug("Something went wrong.");
                onErrorResponse(request);
                passedValidation = false;
              }
            } catch (error) {
              if (psynetTemplateData.flags.inplaceTimelineTransitions) {
                await psynet.handleTimelineTransitionFailure(error);
              } else {
                psynet.log.error(error.stack || String(error));
                onErrorResponse(request);
              }
              passedValidation = false;
            } finally {
              resolve(passedValidation);
            }
          }
        };
        request.open("POST", "/response");
        request.send(formData);
      });
    };

    let createTrialProgress = function () {
      let config = psynetTemplateData.trialProgressDisplayConfig;
      let opacities = { light: 0.25, medium: 0.6, dark: 1.0 };

      let init = function () {
        config.stages.forEach((stage) => (stage.html = {}));
        config.stages.forEach((stage) => {
          stage.html.past = addBarSegment(stage.color, opacities.dark);
        });
        config.stages.forEach((stage) => {
          stage.html.future = addBarSegment(stage.color, opacities.light);
        });
        config.stages.forEach((stage) => {
          stage.update = function (elapsed) {
            let proportionOfStageComplete = bound(
              (elapsed - stage.time[0]) / stage.duration,
              0,
              1,
            );
            let proportionOfBarComplete =
              (proportionOfStageComplete * stage.duration) / config.duration;
            stage.html.past.setWidth(100 * proportionOfBarComplete);
            let proportionOfStageIncomplete = 1 - proportionOfStageComplete;
            let proportionOfBarIncomplete =
              (proportionOfStageIncomplete * stage.duration) / config.duration;
            stage.html.future.setWidth(100 * proportionOfBarIncomplete);
            if (proportionOfStageComplete > 0) {
              if (stage.persistent || proportionOfStageComplete < 1) {
                activeStage = stage;
              } else {
                activeStage = null;
              }
            }
          };
        });
        if (psynet.trialProgressIntervalId) {
          clearInterval(psynet.trialProgressIntervalId);
        }
        psynet.trialProgressIntervalId = psynet.trial.setRepeatingTimer(
          update,
          5,
        );
      };

      let bound = function (x, min, max) {
        return Math.max(min, Math.min(x, max));
      };

      let addBarSegment = function (color, opacity) {
        let bar = $("#trial-progress-bar");
        let segment = $("<div/>", {
          class: "progress-bar trial-progress-bar-segment",
          role: "progressbar",
          style:
            "width: 0%; opacity: " +
            opacity +
            "; background-color: " +
            psynet.theme.resolveColor(color) +
            ";",
          "aria-valuenow": "0",
          "aria-valuemin": "0",
          "aria-valuemax": "100",
        });
        bar.append(segment);
        segment.setWidth = function (percent) {
          segment.css("width", percent + "%");
          segment.attr("aria-valuenow", percent);
        };
        return segment;
      };

      let activeStage = null;
      let startTime = null;

      let start = function () {
        startTime = psynet.trial.getGlobalTime();
      };

      let stop = function () {
        startTime = null;
        activeStage = null;
      };

      let setText = function (content, color) {
        if (content == "") {
          resetText();
        } else {
          let text = $("#trial-progress-caption-contents");
          text.text(content);
          if (color) {
            text.css("color", psynet.theme.resolveColor(color));
          }
        }
      };

      let resetText = function () {
        let text = $("#trial-progress-caption-contents");
        text.html("&nbsp;");
      };

      let update = function () {
        let elapsed =
          startTime !== null ? psynet.trial.getGlobalTime() - startTime : 0.0;
        config.stages.forEach((s) => s.update(elapsed));
        if (config.stages.length > 0) {
          if (activeStage) {
            setText(activeStage.caption, activeStage.color);
          } else {
            resetText();
          }
        }
      };

      psynet.trial.onEvent("trialConstruct", init, { priority: -1000 });
      psynet.trial.onEvent(config.start, start);
      psynet.trial.onEvent("trialStopped", stop);
      psynet.trial.onEvent("pageUpdated", onPageUpdated);

      return {
        stages: config.stages,
        setText: setText,
        start: start,
        stop: stop,
      };
    };

    psynet.trialProgress = createTrialProgress();

    psynet.audio = psynet.media.data.audio;
    psynet.image = psynet.media.data.image;
    psynet.html = psynet.media.data.html;
    psynet.video = psynet.media.data.video;

    return psynet;
  })();

  let updateProgressAndReward = function () {
    if (psynet.participantId !== undefined) {
      $.get("/timeline/progress_and_reward", {
        participantId: psynet.participantId,
      }).done(function (data) {
        let progressPercentage = data["progressPercentage"];
        let progressPercentageStr = progressPercentage + "%";
        // The bar carries the width and the accessible value; the visible
        // percentage is drawn from the label's data attribute.
        $("#timeline-progress-bar").css("width", progressPercentageStr);
        $("#timeline-progress-bar").attr("aria-valuenow", progressPercentage);
        $("#timeline-progress-label").attr("data-progress", progressPercentageStr);

        if (data["reward"] !== undefined) {
          $("#time-reward").text(data["reward"]["time"].toFixed(2));
          $("#performance-reward").text(
            data["reward"]["performance"].toFixed(2),
          );
          $("#total-reward").text(data["reward"]["total"].toFixed(2));
        }
      });
    }
  };

  if (psynetTemplateData.flags.dynamicallyUpdateProgressBarAndReward) {
    setInterval(updateProgressAndReward, 1000);
  }

  function alertParticipantOpenedDevtools() {
    console.warn(
      "You have opened the developer tools. " +
        "The experimenter is informed about this possible misconduct. " +
        "You might be excluded from the experiment.",
    );
  }

  function writeToDbParticipantOpenedDevtools() {
    dallinger.post(psynetTemplateData.routes.participantOpenedDevtools);
  }

  function logParticipantOpenedDevtools() {
    psynet.log.warning(
      "Participant " +
        psynet.participantId +
        " opened the browser's developer tools.",
    );
  }

  function isConsoleOpen() {
    let consoleOpen = false;
    let f = function () {};
    f.toString = function () {
      consoleOpen = true;
    };
    console.profile(f);
    console.profileEnd(f);
    return consoleOpen;
  }

  if (psynetTemplateData.flags.checkParticipantOpenedDevtools) {
    let warnedDevtools = false;
    setInterval(() => {
      if (!warnedDevtools && isConsoleOpen()) {
        logParticipantOpenedDevtools();
        writeToDbParticipantOpenedDevtools();
        alertParticipantOpenedDevtools();
        warnedDevtools = true;
      }
    }, 1000);
  }

  window.psynet = psynet;
  if (window.psynetLayout) {
    psynet.layout = window.psynetLayout;
  }

  psynet.clearLucidTermination = function () {
    psynet.removeBeforeUnloadEventListener();
    $(document).off(".psynetLucidTermination");

    if (psynet.lucidTerminationIntervalIds) {
      psynet.lucidTerminationIntervalIds.forEach((id) => clearInterval(id));
    }
    psynet.lucidTerminationIntervalIds = [];

    if (psynet.lucidTerminationEvents && psynet.lucidTerminationResetHandler) {
      psynet.lucidTerminationEvents.forEach((eventName) => {
        window.removeEventListener(eventName, psynet.lucidTerminationResetHandler);
      });
    }
    psynet.lucidTerminationEvents = [];
    psynet.lucidTerminationResetHandler = null;
  };

  psynet.initEarlyExitButton = function () {
    // Keep a failed script load local to the Leave button rather than
    // failing the whole page bootstrap.
    if (!window.psynetEarlyExit) {
      psynet.log.error("The early-exit script did not load.");
      return;
    }
    window.psynetEarlyExit.init();
  };

  psynet.initLucidTermination = function () {
    psynet.clearLucidTermination();

    if (!psynetTemplateData.flags.lucidRecruitment) {
      return;
    }

    const NO_FOCUS_TIMEOUT = psynetTemplateData.lucid.noFocusTimeoutMs;
    const NO_FOCUS_TIMEOUT_REASON =
      psynetTemplateData.lucid.noFocusTimeoutReason;
    const OVERALL_TIMEOUT = psynetTemplateData.lucid.overallTimeoutS;
    const POLLING_INTERVAL = 1000;

    let triedToLeave = false;
    let noFocusSince = 0;
    let noActivitySince = 0;
    let secondsLeft = psynetTemplateData.lucid.secondsLeft;

    function terminateParticipant(reason) {
      psynet.removeBeforeUnloadEventListener();
      clearInterval(checkTriedToLeaveIntervalID);
      clearInterval(clockIntervalID);
      return window.location.replace(
        `/terminate_participant?participant_id=${psynetTemplateData.participantId}&reason=${reason}`,
      );
    }

    function checkTriedToLeave() {
      if (triedToLeave) {
        terminateParticipant("user-tried-to-leave");
      }
    }

    function updateClocks() {
      let msg = "";

      if (document.hasFocus()) {
        noFocusSince = 0;
      } else {
        noFocusSince += POLLING_INTERVAL;
        if (noFocusSince > NO_FOCUS_TIMEOUT) {
          terminateParticipant(
            NO_FOCUS_TIMEOUT_REASON + NO_FOCUS_TIMEOUT / 1000 + "s",
          );
        } else {
          msg =
            "No focus: " +
            noFocusSince / 1000 +
            "/" +
            NO_FOCUS_TIMEOUT / 1000 +
            "s";
        }
      }

      noActivitySince += POLLING_INTERVAL;
      const noActivityTimeout = psynetTemplateData.lucid.inactivityTimeoutMs;
      if (noActivitySince > noActivityTimeout) {
        terminateParticipant(
          "inactivity-timeout-" +
            psynetTemplateData.lucid.inactivityTimeoutS +
            "s",
        );
      }
      msg +=
        " No activity: " +
        noActivitySince / 1000 +
        "/" +
        noActivityTimeout / 1000 +
        "s";

      if (secondsLeft <= 0) {
        psynet.removeBeforeUnloadEventListener();
        terminateParticipant("overall-timeout-" + OVERALL_TIMEOUT + "s");
      }
      secondsLeft -= POLLING_INTERVAL / 1000;
      msg += " Overall timeout: " + secondsLeft + "/" + OVERALL_TIMEOUT + "s";
    }

    beforeunloadFunction = function (event) {
      if (psynetTemplateData.lucid.shouldWarnOnBeforeUnload) {
        event.returnValue = "Are you sure you want to leave?";
        triedToLeave = true;
      }
    };

    window.addEventListener("beforeunload", beforeunloadFunction);
    window.beforeunloadFunction = beforeunloadFunction;

    const checkTriedToLeaveIntervalID = setInterval(
      checkTriedToLeave,
      POLLING_INTERVAL,
    );
    const clockIntervalID = setInterval(updateClocks, POLLING_INTERVAL);

    psynet.lucidTerminationIntervalIds = [
      checkTriedToLeaveIntervalID,
      clockIntervalID,
    ];

    $(document).on(
      "click.psynetLucidTermination",
      ".btn:not(#early-exit-button):not(#early-exit-cancel), .sd-btn",
      function () {
        psynet.removeBeforeUnloadEventListener();
      },
    );

    const events = [
      "click",
      "keypress",
      "load",
      "mousedown",
      "mousemove",
      "touchstart",
    ];
    psynet.lucidTerminationEvents = events;
    psynet.lucidTerminationResetHandler = function () {
      noActivitySince = 0;
    };
    events.forEach((eventName) => {
      window.addEventListener(eventName, psynet.lucidTerminationResetHandler);
    });
  };
})();
