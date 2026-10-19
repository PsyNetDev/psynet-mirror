/**
 * Participant-page layout checks.
 *
 * Loaded on every participant page (ad, consent, timeline, abort, error).
 *
 * `psynetLayout.check()`, which Playwright or the console calls after the page
 * is ready, asserts layout invariants. The checks do not run on their own.
 *
 * These are assertions about how a page is built, not judgements about how it
 * looks. Each check corresponds to a defect that reached the default theme at
 * least once:
 *
 *   standards_mode                        Template output emitted before
 *                                         `<!doctype html>` put every
 *                                         participant page into quirks mode.
 *   percentage_height_ineffective         Layouts declared percentage heights
 *                                         against auto-height parents, which
 *                                         only resolved because of quirks mode.
 *   controls_reachable_without_scrolling  A stimulus grew large enough to push
 *                                         the response control off screen on a
 *                                         page that was meant to fit.
 *   no_vertical_overflow                  A page that was meant to fit can
 *                                         still scroll, even if the control
 *                                         happens to peek above the footer.
 *   nothing_permanently_occluded          Content overlaps the footer even at
 *                                         the end of the scroll.
 *   no_horizontal_overflow                Content wider than the viewport.
 *
 * Pages that are genuinely meant to scroll declare it with
 * `expect_scrolling=True` (see `Page` in psynet/timeline.py). Ad pages have no
 * `#main-body`, so the fit / no-scroll checks do not apply; standards mode,
 * percentage heights, horizontal overflow, and footer occlusion still do.
 *
 * Public API: `window.psynetLayout` (`collectViolations`,
 * `collectScrollViolations`, `check`). When `window.psynet` already exists,
 * the same object is also assigned to `psynet.layout`.
 */
(function (global) {
  "use strict";

  const CONTROL_SELECTORS = [
    "#next-button",
    "#reset-button",
    ".response",
    "#consent",
  ];

  function collectViolations() {
    const violations = [];
    const round = (n) => Math.round(n);

    // A missing or displaced doctype silently changes the box model and how
    // percentage heights resolve.
    if (document.compatMode !== "CSS1Compat") {
      violations.push({
        check: "standards_mode",
        detail: `document.compatMode is ${document.compatMode}, expected CSS1Compat`,
      });
    }

    // Unless the page declares that it expects scrolling, its response controls
    // must be reachable without scrolling. Declaring intent is the only reliable
    // way to tell a stimulus page that has outgrown the window from a consent
    // form that is meant to be long: the geometry looks identical.
    const mainBody = document.querySelector("#main-body");
    const expectsScrolling = mainBody
      ? mainBody.dataset.expectScrolling === "true"
      : false;

    const footer = document.querySelector("#footer");
    const footerVisible = footer && getComputedStyle(footer).display !== "none";
    const footerRect = footerVisible ? footer.getBoundingClientRect() : null;
    const usableBottom = footerRect ? footerRect.top : window.innerHeight;

    if (mainBody && !expectsScrolling) {
      for (const selector of CONTROL_SELECTORS) {
        for (const element of document.querySelectorAll(selector)) {
          const style = getComputedStyle(element);
          if (style.display === "none" || style.visibility === "hidden") continue;
          const rect = element.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) continue;
          if (rect.top >= 0 && rect.bottom <= usableBottom) continue;
          violations.push({
            check: "controls_reachable_without_scrolling",
            detail:
              `${selector} spans y=${round(rect.top)}-${round(rect.bottom)} but the ` +
              `usable area is 0-${round(usableBottom)} ` +
              `(viewport ${window.innerHeight}px, document ` +
              `${round(document.documentElement.scrollHeight)}px). Either make the page ` +
              "fit, or pass expect_scrolling=True to the page if it is meant to scroll",
          });
        }
      }

      // Reachability alone is not enough: a Next button can sit just above the
      // footer while the content surface still extends a few centimetres below
      // the fold, which is the scrollbar participants notice on a laptop.
      const scrollHeight = Math.max(
        document.documentElement.scrollHeight,
        document.body ? document.body.scrollHeight : 0
      );
      if (scrollHeight > window.innerHeight + 1) {
        violations.push({
          check: "no_vertical_overflow",
          detail:
            `document scrollHeight ${round(scrollHeight)} exceeds viewport height ` +
            `${window.innerHeight}px, so the page can scroll. Either make the page ` +
            "fit, or pass expect_scrolling=True to the page if it is meant to scroll",
        });
      }
    }

    // A percentage height resolves only against an ancestor with a definite
    // height. Against an auto-height parent it silently becomes auto in standards
    // mode, and resolves against the viewport in quirks mode, so the same markup
    // behaves differently depending on the document mode.
    //
    // Candidates come from stylesheet rules and from inline style attributes,
    // because either can declare the height.
    const candidates = new Map();
    const addCandidate = (element, height, origin) => {
      if (!candidates.has(element)) candidates.set(element, { height, origin });
    };

    for (const sheet of document.styleSheets) {
      let rules;
      try {
        rules = sheet.cssRules;
      } catch (error) {
        continue; // cross-origin stylesheet
      }
      for (const rule of rules) {
        if (!rule.selectorText || !rule.style) continue;
        const height = rule.style.getPropertyValue("height");
        if (!height || !height.trim().endsWith("%")) continue;
        let matches;
        try {
          matches = document.querySelectorAll(rule.selectorText);
        } catch (error) {
          continue; // selector unsupported by querySelectorAll
        }
        for (const element of matches) {
          addCandidate(element, height.trim(), rule.selectorText);
        }
      }
    }

    for (const element of document.querySelectorAll("[style]")) {
      const height = element.style.height;
      if (height && height.trim().endsWith("%")) {
        addCandidate(element, height.trim(), "inline style");
      }
    }

    for (const [element, { height, origin }] of candidates) {
      if (element === document.documentElement || element === document.body) continue;
      const parent = element.parentElement;
      if (!parent) continue;
      const style = getComputedStyle(element);
      if (
        style.display === "none" ||
        style.position === "absolute" ||
        style.position === "fixed"
      ) {
        continue;
      }

      // Probe: collapse the element. If the parent shrinks with it, the parent's
      // height is derived from its children, so it has no definite height for the
      // percentage to resolve against.
      const parentHeight = parent.getBoundingClientRect().height;
      if (parentHeight === 0) continue;
      const savedHeight = element.style.getPropertyValue("height");
      const savedPriority = element.style.getPropertyPriority("height");
      try {
        element.style.setProperty("height", "0px", "important");
        const collapsedParentHeight = parent.getBoundingClientRect().height;

        if (collapsedParentHeight < parentHeight - 1) {
          const label = element.id ? `#${element.id}` : element.tagName.toLowerCase();
          violations.push({
            check: "percentage_height_ineffective",
            detail:
              `${label} declares height:${height} (${origin}) against an auto-height parent ` +
              `(collapsing it shrank the parent from ${round(parentHeight)}px to ` +
              `${round(collapsedParentHeight)}px), so the declared height depends on ` +
              "quirks-mode behaviour rather than resolving as written",
          });
        }
      } finally {
        if (savedHeight) {
          element.style.setProperty("height", savedHeight, savedPriority);
        } else {
          element.style.removeProperty("height");
        }
      }
    }

    const scrollWidth = document.documentElement.scrollWidth;
    if (scrollWidth > window.innerWidth + 1) {
      violations.push({
        check: "no_horizontal_overflow",
        detail: `document scrollWidth ${scrollWidth} exceeds viewport width ${window.innerWidth}`,
      });
    }

    return violations;
  }

  /**
   * Detect content that overlaps a footer even at the end of the scroll.
   * PsyNet's footer is in flow, but custom experiment CSS can reposition it.
   *
   * Scrolls to the end, restoring the original position afterwards. The scroll is
   * repeated until the position stops changing: a single jump can land short
   * while layout is still settling, which reports occlusion that is not there.
   */
  async function collectScrollViolations() {
    const footer = document.querySelector("#footer");
    if (!footer || getComputedStyle(footer).display === "none") return [];

    const scroller = document.scrollingElement || document.documentElement;
    const originalScrollTop = scroller.scrollTop;

    let previous = -1;
    for (let i = 0; i < 40 && scroller.scrollTop !== previous; i++) {
      previous = scroller.scrollTop;
      scroller.scrollTop = scroller.scrollHeight;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }

    const footerTop = footer.getBoundingClientRect().top;
    const violations = [];
    for (const selector of CONTROL_SELECTORS) {
      for (const element of document.querySelectorAll(selector)) {
        const style = getComputedStyle(element);
        if (style.display === "none" || style.visibility === "hidden") continue;
        if (style.position === "fixed") continue; // pinned on purpose
        const rect = element.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        if (rect.bottom > footerTop && rect.top < footer.getBoundingClientRect().bottom) {
          violations.push({
            check: "nothing_permanently_occluded",
            detail:
              `${selector} still overlaps the footer at the end of the scroll ` +
              `(spans y=${Math.round(rect.top)}-${Math.round(rect.bottom)}, footer starts ` +
              `at y=${Math.round(footerTop)}), so it can never be fully seen`,
          });
        }
      }
    }

    scroller.scrollTop = originalScrollTop;
    return violations;
  }

  async function check() {
    return collectViolations().concat(await collectScrollViolations());
  }

  const api = {
    collectViolations,
    collectScrollViolations,
    check,
  };

  global.psynetLayout = api;
  if (global.psynet) {
    global.psynet.layout = api;
  }
})(window);
