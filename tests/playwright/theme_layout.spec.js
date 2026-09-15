/**
 * Layout contracts from the default-theme review that can be checked without
 * a running experiment: graphic size on a short landscape phone, vertical
 * push-button columns, in-flow footer placement, caption
 * contrast for color "white", audio-meter setLevel/applyColor, and the
 * in-page `psynetLayout.check()` API.
 */
const fs = require("fs");
const path = require("path");
const { test, expect } = require("./fixtures");

const THEME_CSS = fs.readFileSync(
  path.resolve("psynet/resources/css/participant.css"),
  "utf8"
);
const PSYNET_JS = fs.readFileSync(
  path.resolve("psynet/resources/scripts/psynet.js"),
  "utf8"
);
const AUDIO_METER_JS = fs.readFileSync(
  path.resolve("psynet/templates/macros/control/audio_meter.js"),
  "utf8"
);
const BOOTSTRAP_CSS = fs.readFileSync(
  path.resolve("psynet/resources/libraries/bootstrap/bootstrap.min.css"),
  "utf8"
);
const LAYOUT_JS = fs.readFileSync(
  path.resolve("psynet/resources/scripts/psynet.layout.js"),
  "utf8"
);
const WAIT_PAGE_TEMPLATE = fs.readFileSync(
  path.resolve("psynet/templates/wait-page.html"),
  "utf8"
);
const WAIT_PAGE_CSS = WAIT_PAGE_TEMPLATE.match(
  /<style[^>]*>([\s\S]*?)<\/style>/
)[1];

async function renderTheme(
  page,
  {
    html,
    extraCss = "",
    viewport,
    scripts = [],
    htmlAttrs = "",
    // Load Bootstrap before the theme, as participant pages do, for rules the
    // theme only adjusts rather than defines.
    includeBootstrap = false
  }
) {
  await page.setViewportSize(viewport);
  await page.setContent(`<!doctype html>
<html ${htmlAttrs}>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
${includeBootstrap ? BOOTSTRAP_CSS : ""}
${THEME_CSS}
body { margin: 0; }
${extraCss}
</style>
</head>
<body>
${html}
</body>
</html>`);
  for (const script of scripts) {
    await page.addScriptTag({ content: script });
  }
}

test(
  "landscape graphics stay visible on a short phone",
  { tag: "@both" },
  async ({ page }) => {
    const aspect = (16 / 9).toFixed(6);
    await renderTheme(page, {
      viewport: { width: 780, height: 375 },
      html: `
        <div class="psynet-surface">
          <div id="graphic-prompt" style="
            width: min(90.0000vw, 100%, calc(60.0000vh * ${aspect}),
              max(var(--psynet-graphic-min-size),
              calc((100vh - var(--psynet-graphic-vertical-chrome)) * ${aspect})));
            aspect-ratio: 16 / 9;
            height: auto;
            background: #dfe5ee;
          "></div>
        </div>`
    });

    const box = await page.locator("#graphic-prompt").boundingBox();
    expect(box).not.toBeNull();
    expect(box.width).toBeGreaterThan(80);
    expect(box.height).toBeGreaterThan(40);
    expect(box.width / box.height).toBeCloseTo(16 / 9, 2);
  }
);

test(
  "vertical push-button lists stay in one column and grow the page",
  { tag: "@both" },
  async ({ page }) => {
    const buttons = Array.from(
      { length: 20 },
      (_, i) => `<button type="button" class="push-button">Option ${i + 1}</button>`
    ).join("");
    await renderTheme(page, {
      viewport: { width: 1280, height: 720 },
      extraCss: `.push-button { min-height: 40px; min-width: 220px; }`,
      html: `<div class="push-button-container push-button-container--vertical">${buttons}</div>`
    });

    const metrics = await page.evaluate(() => {
      const container = document.querySelector(".push-button-container");
      const buttons = [...document.querySelectorAll(".push-button")];
      const lefts = buttons.map((button) =>
        Math.round(button.getBoundingClientRect().left)
      );
      const last = buttons[buttons.length - 1].getBoundingClientRect();
      return {
        uniqueLefts: [...new Set(lefts)].length,
        containerScroll: container.scrollHeight - container.clientHeight,
        pageScroll: document.documentElement.scrollHeight - window.innerHeight,
        lastBottom: last.bottom,
        count: buttons.length
      };
    });

    expect(metrics.count).toBe(20);
    expect(metrics.uniqueLefts).toBe(1);
    expect(metrics.containerScroll).toBeLessThanOrEqual(1);
    expect(metrics.pageScroll).toBeGreaterThan(1);
    expect(metrics.lastBottom).toBeGreaterThan(720);
  }
);

test(
  "long option lists grow their panel and scroll the page",
  { tag: "@both" },
  async ({ page }) => {
    const options = Array.from(
      { length: 16 },
      (_, i) =>
        `<label class="psynet-option">
           <input type="radio" name="opt" class="response">
           <span class="psynet-option-label">Option ${i + 1}</span>
         </label>`
    ).join("");
    await renderTheme(page, {
      viewport: { width: 1280, height: 720 },
      html: `<div class="control-container psynet-options">${options}</div>`
    });

    const metrics = await page.evaluate(() => {
      const panel = document.querySelector(".psynet-options");
      const style = getComputedStyle(panel);
      return {
        panelScroll: panel.scrollHeight - panel.clientHeight,
        pageScroll: document.documentElement.scrollHeight - window.innerHeight,
        background: style.backgroundColor,
        borderWidth: style.borderTopWidth
      };
    });

    // The panel behind the rows stays, but it no longer scrolls internally.
    expect(metrics.panelScroll).toBeLessThanOrEqual(1);
    expect(metrics.pageScroll).toBeGreaterThan(1);
    expect(metrics.background).not.toBe("rgba(0, 0, 0, 0)");
    expect(parseFloat(metrics.borderWidth)).toBeGreaterThan(0);
  }
);

test(
  "the footer needs no body clearance",
  { tag: "@both" },
  async ({ page }) => {
    await renderTheme(page, {
      viewport: { width: 1280, height: 720 },
      html: `
        <div class="container d-flex align-items-center justify-content-center" style="min-height: 90vh">
          <div class="psynet-surface">
            <h3>To proceed, click the button below.</h3>
            <button type="button" class="btn btn-primary">Next</button>
          </div>
        </div>`
    });

    const noFooter = await page.evaluate(() => ({
      paddingBottom: getComputedStyle(document.body).paddingBottom,
      scrollHeight: document.documentElement.scrollHeight,
      viewport: window.innerHeight
    }));
    expect(parseFloat(noFooter.paddingBottom)).toBe(0);
    expect(noFooter.scrollHeight).toBeLessThanOrEqual(noFooter.viewport + 1);

    await renderTheme(page, {
      viewport: { width: 1280, height: 720 },
      html: `
        <div id="timeline-root">
          <div id="main-body" class="psynet-surface"><p>Timeline content</p></div>
          <nav id="footer" class="navbar">Reward</nav>
        </div>`
    });
    const withFooter = await page.evaluate(() => {
      const footer = document.getElementById("footer").getBoundingClientRect();
      return {
        paddingBottom: getComputedStyle(document.body).paddingBottom,
        footerBottom: footer.bottom,
        viewport: window.innerHeight
      };
    });
    expect(parseFloat(withFooter.paddingBottom)).toBe(0);
    expect(withFooter.footerBottom).toBeCloseTo(withFooter.viewport, 0);
  }
);

for (const viewport of [
  { width: 1280, height: 720, label: "desktop" },
  { width: 390, height: 844, label: "phone" }
]) {
  for (const withFooter of [false, true]) {
    test(
      `wait page fits ${viewport.label} viewport ${
        withFooter ? "with" : "without"
      } footer`,
      { tag: "@both" },
      async ({ page }) => {
        const mediaBar =
          '<div id="media-download-progress-bar" style="width: 40%"></div>';
        const footer = withFooter
          ? `<nav id="footer" class="navbar">${mediaBar}
               <div class="container py-2">Reward</div>
             </nav>`
          : mediaBar;
        await renderTheme(page, {
          viewport,
          includeBootstrap: true,
          scripts: [LAYOUT_JS],
          extraCss: WAIT_PAGE_CSS,
          html: `
            <div id="timeline-root">
              <div id="timeline-header" class="header">
                <div class="progress"></div>
              </div>
              <div id="main-body" class="container psynet-surface"
                   data-expect-scrolling="false">
                <div id="wait-page"><p>Please wait for the next participant.</p></div>
              </div>
              ${footer}
            </div>`
        });

        const result = await page.evaluate(async () => ({
          scrollHeight: document.documentElement.scrollHeight,
          viewportHeight: window.innerHeight,
          violations: (await window.psynetLayout.check()).map(
            (violation) => violation.check
          )
        }));
        expect(result.scrollHeight).toBeLessThanOrEqual(
          result.viewportHeight + 1
        );
        expect(result.violations).not.toContain("no_vertical_overflow");
      }
    );
  }
}

test(
  "Prolific exit control is usable on a phone",
  { tag: "@both" },
  async ({ page }) => {
    await renderTheme(page, {
      viewport: { width: 390, height: 844 },
      includeBootstrap: true,
      scripts: [LAYOUT_JS],
      html: `
          <main class="container my-5 psynet-surface">
            <h1>Submit your Prolific task</h1>
            <p>Use the button below to complete the task.</p>
            <button id="js-exit-button" class="btn btn-primary btn-lg">Submit study</button>
          </main>`
    });

    const result = await page.evaluate(async () => {
      const control = document.querySelector("button");
      const box = control.getBoundingClientRect();
      return {
        box: { left: box.left, right: box.right, top: box.top, bottom: box.bottom },
        viewport: { width: window.innerWidth, height: window.innerHeight },
        violations: (await window.psynetLayout.check()).map(
          (violation) => violation.check
        )
      };
    });
    expect(result.box.left).toBeGreaterThanOrEqual(0);
    expect(result.box.right).toBeLessThanOrEqual(result.viewport.width);
    expect(result.box.top).toBeGreaterThanOrEqual(0);
    expect(result.box.bottom).toBeLessThanOrEqual(result.viewport.height);
    expect(result.violations).toEqual([]);
  }
);

test(
  "transient pages show a spinner immediately",
  { tag: "@both" },
  async ({ page }) => {
    await renderTheme(page, {
      viewport: { width: 1280, height: 720 },
      includeBootstrap: true,
      html: `<div id="main-body" class="psynet-surface">
               <div class="psynet-activity" role="status">
                 <span class="spinner-border" aria-hidden="true"></span>
                 <span class="visually-hidden">Working...</span>
               </div>
             </div>`
    });

    const spinner = page.locator(".psynet-activity .spinner-border");
    await expect(spinner).toBeVisible();

    const state = await spinner.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        opacity: parseFloat(style.opacity),
        animationDelay: style.animationDelay,
        animationName: style.animationName,
        color: style.color,
        // Layout size, not getBoundingClientRect: the spinner is rotating, and
        // a rotated square reports a bounding box up to 1.41x its own size.
        width: style.width,
        height: style.height
      };
    });

    // No delayed reveal: the spinner is there from the first frame.
    expect(state.opacity).toBe(1);
    expect(state.animationDelay).toBe("0s");
    expect(state.animationName).toBe("spinner-border");
    // The theme's sizing and accent colour win over Bootstrap's defaults.
    expect(state.width).toBe("40px");
    expect(state.height).toBe("40px");
    expect(state.color).toBe("rgb(48, 112, 200)");
  }
);

test(
  "reduced motion only stills theme chrome, not experiment stimuli",
  { tag: "@both" },
  async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await renderTheme(page, {
      viewport: { width: 800, height: 600 },
      extraCss: `
        @keyframes stimulus-pulse {
          from { opacity: 0.25; }
          to { opacity: 1; }
        }
        #stimulus { animation: stimulus-pulse 2s infinite; }`,
      html: `
        <div class="colorfadeanim" id="theme-chrome">Waiting</div>
        <div id="stimulus">Animated experiment stimulus</div>`
    });

    const animations = await page.evaluate(() => ({
      chrome: getComputedStyle(document.getElementById("theme-chrome")).animationName,
      stimulus: getComputedStyle(document.getElementById("stimulus")).animationName
    }));
    expect(animations.chrome).toBe("none");
    expect(animations.stimulus).toBe("stimulus-pulse");
  }
);

test(
  "progress percentage sits on a grey pill matching the track",
  { tag: "@both" },
  async ({ page }) => {
    await renderTheme(page, {
      viewport: { width: 1280, height: 200 },
      extraCss: `.progress { display: flex; overflow: hidden; }`,
      html: `
        <div id="timeline-header" class="header">
          <div class="progress">
            <div id="timeline-progress-bar" class="progress-bar" style="width:12%"></div>
            <span id="timeline-progress-label" aria-hidden="true" data-progress="12%"></span>
          </div>
        </div>`
    });

    const colors = await page.evaluate(() => {
      const rail = document.querySelector("#timeline-header .progress");
      const label = document.getElementById("timeline-progress-label");
      return {
        rail: getComputedStyle(rail).backgroundColor,
        pill: getComputedStyle(label, "::before").backgroundColor,
        border: getComputedStyle(document.documentElement)
          .getPropertyValue("--psynet-border")
          .trim()
      };
    });

    expect(colors.rail).toBe(colors.pill);
    expect(colors.border).toBe("#dfe5ee");
  }
);

test(
  "media progress mirrors the timeline bar and follows the footer",
  { tag: "@both" },
  async ({ page }) => {
    const header = `
      <div id="timeline-header" class="header">
        <div class="progress">
          <div id="timeline-progress-bar" class="progress-bar" style="width:12%"></div>
        </div>
      </div>`;
    const bar = `<div id="media-download-progress-bar" style="width: 40%"></div>`;
    const bootstrapNavbar = `
      .navbar { --bs-navbar-padding-y: 0.5rem; --bs-navbar-padding-x: 0;
                position: relative; display: flex; flex-wrap: wrap;
                align-items: center;
                padding: var(--bs-navbar-padding-y) var(--bs-navbar-padding-x); }
      .container { width: 100%; padding-inline: 0.75rem; margin-inline: auto; }
      .py-2 { padding-top: 0.5rem; padding-bottom: 0.5rem; }
      .progress { display: flex; overflow: hidden; }`;

    // No footer: the bar takes the bottom edge, like the top bar takes the top.
    await renderTheme(page, {
      viewport: { width: 1280, height: 720 },
      extraCss: bootstrapNavbar,
      html: `<div id="timeline-root">${header}
               <div id="main-body" class="psynet-surface"><p>Trial</p></div>
               ${bar}
             </div>`
    });

    let geometry = await page.evaluate(() => {
      const media = document.getElementById("media-download-progress-bar");
      const top = document.querySelector("#timeline-header .progress");
      const mediaRect = media.getBoundingClientRect();
      return {
        topHeight: getComputedStyle(top).height,
        mediaHeight: getComputedStyle(media).height,
        mediaBottom: Math.round(mediaRect.bottom),
        mediaWidth: Math.round(mediaRect.width),
        viewport: window.innerHeight,
        bodyPaddingBottom: getComputedStyle(document.body).paddingBottom
      };
    });

    // A thinner rail than the labelled bar at the top of the page.
    expect(parseFloat(geometry.mediaHeight)).toBeGreaterThan(0);
    expect(parseFloat(geometry.mediaHeight)).toBeLessThan(
      parseFloat(geometry.topHeight)
    );
    expect(geometry.mediaBottom).toBe(geometry.viewport);
    // Width still tracks progress rather than filling the page.
    expect(geometry.mediaWidth).toBe(512);
    // Room reserved so scrolled content cannot hide under it.
    expect(geometry.bodyPaddingBottom).toBe(geometry.mediaHeight);

    // With a footer it rides the footer's top edge instead.
    await renderTheme(page, {
      viewport: { width: 1280, height: 720 },
      extraCss: bootstrapNavbar,
      html: `${header}<div id="main-body" class="psynet-surface"><p>Trial</p></div>
             <nav id="footer" class="navbar">${bar}
               <div class="container py-2"><div class="footer-text">Reward: $0.42</div></div>
             </nav>`
    });

    geometry = await page.evaluate(() => {
      const media = document.getElementById("media-download-progress-bar");
      const footer = document.getElementById("footer");
      return {
        mediaTop: Math.round(media.getBoundingClientRect().top),
        footerTop: Math.round(footer.getBoundingClientRect().top),
        footerBorderTop: getComputedStyle(footer).borderTopWidth,
        mediaHeight: getComputedStyle(media).height,
        mediaToken: getComputedStyle(document.documentElement)
          .getPropertyValue("--psynet-media-progress-height")
          .trim()
      };
    });

    // The bar sits just inside the footer's top border, not over it.
    expect(geometry.mediaTop - geometry.footerTop).toBe(
      parseFloat(geometry.footerBorderTop)
    );
    // Still its own token height, whatever the theme sets it to.
    expect(geometry.mediaHeight).toBe(geometry.mediaToken);
  }
);

test(
  "standalone media progress disappears when loading completes",
  { tag: "@both" },
  async ({ page }) => {
    await renderTheme(page, {
      viewport: { width: 1280, height: 720 },
      html: `<div id="timeline-root">
               <div id="media-download-progress-bar" style="width: 40%"></div>
             </div>`,
      scripts: [mediaProgressRuntime()]
    });

    await page.evaluate(() => {
      psynet.media.downloadProgress.set("audio", "stimulus", 40);
    });
    await expect(page.locator("#media-download-progress-bar")).toBeVisible();

    await page.evaluate(() => {
      psynet.media.downloadProgress.set("audio", "stimulus", 100);
    });
    await expect(page.locator("#media-download-progress-bar")).toBeHidden();
    expect(
      await page.evaluate(() => getComputedStyle(document.body).paddingBottom)
    ).toBe("0px");

    await renderTheme(page, {
      viewport: { width: 1280, height: 720 },
      html: `<nav id="footer">
               <div id="media-download-progress-bar" style="width: 40%"></div>
             </nav>`,
      scripts: [mediaProgressRuntime()]
    });
    await page.evaluate(() => {
      psynet.media.downloadProgress.set("audio", "stimulus", 100);
    });
    await expect(page.locator("#media-download-progress-bar")).toBeVisible();
  }
);

test(
  "footer text is centred below the progress bar",
  { tag: "@both" },
  async ({ page }) => {
    await renderTheme(page, {
      viewport: { width: 1280, height: 720 },
      // Same markup as timeline-page.html's footer macro, with the progress bar
      // full width as it is on a page with no media to download.
      html: `
        <nav id="footer" class="navbar">
          <div id="media-download-progress-bar" style="width: 100%"></div>
          <div class="container py-2 d-flex flex-wrap align-items-center gap-2">
            <div class="footer-text">Reward: <strong>$0.00</strong></div>
          </div>
        </nav>`,
      // The theme relies on Bootstrap for .navbar padding.
      extraCss: `
        .navbar { --bs-navbar-padding-y: 0.5rem; --bs-navbar-padding-x: 0;
                  position: relative; display: flex; flex-wrap: wrap;
                  align-items: center;
                  padding: var(--bs-navbar-padding-y) var(--bs-navbar-padding-x); }
        .container { width: 100%; padding-inline: 0.75rem; margin-inline: auto; }
        .py-2 { padding-top: 0.5rem; padding-bottom: 0.5rem; }
        .d-flex { display: flex; }
        .align-items-center { align-items: center; }`
    });

    const offset = await page.evaluate(() => {
      const footer = document.getElementById("footer");
      const bar = document.getElementById("media-download-progress-bar");
      const text = footer.querySelector(".footer-text");
      const footerRect = footer.getBoundingClientRect();
      const barRect = bar.getBoundingClientRect();
      const textRect = text.getBoundingClientRect();
      // The strip participants see starts below the progress bar.
      const stripTop = barRect.bottom;
      return (
        textRect.top - stripTop - (footerRect.bottom - textRect.bottom)
      );
    });

    // Positive means the text sits low, negative means it sits high.
    expect(Math.abs(offset)).toBeLessThanOrEqual(1);
  }
);

test(
  "a wrapped footer stays after the last control",
  { tag: "@both" },
  async ({ page }) => {
    await renderTheme(page, {
      viewport: { width: 520, height: 568 },
      includeBootstrap: true,
      scripts: [LAYOUT_JS],
      html: `
        <div id="timeline-root">
          <div id="main-body" class="psynet-surface">
            <p>A short experiment page.</p>
            <div class="psynet-actions">
              <button id="next-button" class="btn btn-primary btn-lg">Next</button>
            </div>
          </div>
          <nav id="footer" class="navbar">
            <div id="media-download-progress-bar" style="width: 100%"></div>
            <div class="container py-2 d-flex flex-wrap align-items-center gap-2">
              <span class="psynet-tooltip">
                <span id="reward-summary" class="psynet-tooltip__trigger"
                      tabindex="0" aria-describedby="reward-tooltip">
                  <strong>$0.42</strong>
                </span>
                <span id="reward-tooltip" class="psynet-tooltip__content"
                      role="tooltip">
                  Reward earned so far: $0.30 for time + $0.12 for performance.
                </span>
              </span>
              <button class="btn btn-light">Comment</button>
              <span class="psynet-tooltip psynet-tooltip--end">
                <button id="early-exit-button" class="btn btn-danger"
                        aria-describedby="exit-tooltip">Leave</button>
                <span id="exit-tooltip" class="psynet-tooltip__content"
                      role="tooltip">Leave without finishing.</span>
              </span>
            </div>
          </nav>
        </div>`
    });

    // The reward breakdown moved into a tooltip, so the footer should now fit
    // on one row even here. Force the wrapped case as well, since a longer
    // translation or a larger font size produces it.
    for (const label of ["Leave", "Leave without finishing right now"]) {
      await page.locator("#early-exit-button").evaluate((button, text) => {
        button.textContent = text;
      }, label);
      const geometry = await page.evaluate(async () => {
        const footer = document.getElementById("footer");
        const next = document.getElementById("next-button");
        return {
          footerPosition: getComputedStyle(footer).position,
          footerTop: footer.getBoundingClientRect().top,
          nextBottom: next.getBoundingClientRect().bottom,
          clearance: getComputedStyle(document.body).paddingBottom,
          violations: (await window.psynetLayout.check()).map((v) => v.check)
        };
      });

      expect(geometry.footerPosition).toBe("relative");
      expect(geometry.clearance).toBe("0px");
      expect(geometry.footerTop).toBeGreaterThanOrEqual(geometry.nextBottom);
      expect(geometry.violations).not.toContain("nothing_permanently_occluded");
    }

    const tooltip = page.locator("#reward-tooltip");
    await page.locator("#reward-summary").focus();
    await expect(tooltip).toBeVisible();
    await expect(tooltip).toContainText("$0.30 for time + $0.12 for performance");

    await page.locator("#early-exit-button").focus();
    await expect(page.locator("#exit-tooltip")).toBeVisible();
    await expect(page.locator("#exit-tooltip")).toContainText(
      "Leave without finishing."
    );
  }
);

test(
  "white captions stay distinct from the dark-mode surface",
  { tag: "@both" },
  async ({ page }) => {
    await renderTheme(page, {
      viewport: { width: 800, height: 600 },
      htmlAttrs: 'data-bs-theme="dark"',
      html: `
        <div class="psynet-surface" id="surface">
          <p id="caption" style="color: white">Get ready</p>
        </div>`
    });

    const colors = await page.evaluate(() => ({
      caption: getComputedStyle(document.getElementById("caption")).color,
      surface: getComputedStyle(document.getElementById("surface")).backgroundColor
    }));
    expect(colors.caption).not.toBe(colors.surface);
  }
);

test(
  "audio meter setLevel and applyColor update the CSS bar",
  { tag: "@both" },
  async ({ page }) => {
    await renderTheme(page, {
      viewport: { width: 800, height: 600 },
      html: `
        <div class="audio-meter">
          <div id="audio-meter" class="audio-meter__track" role="meter"
               aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
            <div class="audio-meter__fill" style="width: 0%;"></div>
          </div>
          <p id="audio-meter-text" class="audio-meter__text">Just right.</p>
        </div>`,
      scripts: [
        `window.psynet = {
           page: { control: {} },
           theme: {
             namedColors: {
               red: "var(--psynet-danger)",
               green: "var(--psynet-success)"
             },
             resolveColor: function (color) {
               if (color == null || color === "") return color;
               return this.namedColors[String(color).trim().toLowerCase()] || color;
             }
           }
         };`,
        AUDIO_METER_JS
      ]
    });

    const result = await page.evaluate(() => {
      const control = psynet.page.control.audioMeter;
      control.track = document.getElementById("audio-meter");
      control.fill = control.track.querySelector(".audio-meter__fill");
      control.audioMeterText = document.getElementById("audio-meter-text");
      control.setLevel(0.4);
      control.applyColor("red");
      return {
        fillWidth: control.fill.style.width,
        ariaNow: control.track.getAttribute("aria-valuenow"),
        fillToken: control.track.style.getPropertyValue("--audio-meter-fill"),
        textColor: control.audioMeterText.style.color
      };
    });

    expect(result.fillWidth).toBe("40%");
    expect(result.ariaNow).toBe("40");
    expect(result.fillToken).toBe("var(--psynet-danger)");
    expect(result.textColor).toBe("var(--psynet-danger)");
  }
);

const LAYOUT_JS_PATH = path.resolve("psynet/resources/scripts/psynet.layout.js");

// WCAG 1.4.11 asks for 3:1 between a control's boundary and its background.
// The footer sits on its own tint, so the ratio has to be measured against
// that rather than against the content surface.
function contrastHelpers() {
  return `
    window.__contrast = function (a, b) {
      const channel = (v) => {
        v = v / 255;
        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
      };
      const lum = (rgb) => {
        const [r, g, b] = rgb.match(/\\d+(\\.\\d+)?/g).map(Number);
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
      };
      const la = lum(a);
      const lb = lum(b);
      return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    };
  `;
}

const FOOTER_MARKUP = `
  <div id="main-body" class="container psynet-surface"><p>Trial</p>
    <div class="psynet-actions">
      <button id="next-button" class="btn btn-primary btn-lg">Next</button>
    </div>
  </div>
  <nav id="footer" class="navbar">
    <div id="media-download-progress-bar" style="width: 100%"></div>
    <div class="container py-2 d-flex flex-wrap align-items-center gap-2">
      <span class="psynet-tooltip">
      <span id="reward-summary" class="psynet-tooltip__trigger"
            tabindex="0" aria-describedby="reward-tooltip">
          <span class="visually-hidden">Reward: </span><strong>$0.42</strong>
          <svg class="psynet-info" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14Z"/></svg>
        </span>
        <span id="reward-tooltip" class="psynet-tooltip__content" role="tooltip">
          Reward earned so far: $0.30 for time + $0.12 for performance.
        </span>
      </span>
      <button type="button" class="btn btn-light" id="comment-button">Comment</button>
      <span class="psynet-tooltip psynet-tooltip--end">
        <button id="early-exit-button" class="btn btn-danger psynet-tooltip__trigger"
                aria-describedby="exit-tooltip">Leave</button>
        <span id="exit-tooltip" class="psynet-tooltip__content" role="tooltip">
          Leave without finishing.
        </span>
      </span>
    </div>
  </nav>`;

for (const scheme of ["light", "dark"]) {
  test(
    `footer row is one family with visible boundaries (${scheme})`,
    { tag: "@both" },
    async ({ page }) => {
      await renderTheme(page, {
        viewport: { width: 1600, height: 620 },
        includeBootstrap: true,
        htmlAttrs: `data-bs-theme="${scheme}"`,
        scripts: [contrastHelpers()],
        html: FOOTER_MARKUP
      });

      const footer = await page.evaluate(() => {
        const el = (s) => document.querySelector(s);
        const box = (s) => el(s).getBoundingClientRect();
        const styles = (s) => getComputedStyle(el(s));
        const footerBg = styles("#footer").backgroundColor;
        return {
          heights: {
            reward: Math.round(box("#reward-summary").height),
            comment: Math.round(box("#comment-button").height),
            exit: Math.round(box("#early-exit-button").height)
          },
          radii: {
            reward: styles("#reward-summary").borderTopLeftRadius,
            comment: styles("#comment-button").borderTopLeftRadius,
            next: styles("#next-button").borderTopLeftRadius
          },
          // A readout set smaller and bolder than the controls beside it read as
          // a different kind of object.
          fonts: {
            rewardSize: styles("#reward-summary").fontSize,
            commentSize: styles("#comment-button").fontSize,
            rewardFamily: styles("#reward-summary").fontFamily,
            commentFamily: styles("#comment-button").fontFamily
          },
          // The glyph belongs to the figure, so it takes the same colour.
          glyphColor: styles("#reward-summary .psynet-info").color,
          rewardColor: styles("#reward-summary").color,
          // Grouped right: the reward is left of both controls, and the two
          // controls sit next to each other rather than spread across the bar.
          gaps: {
            rewardToComment: Math.round(
              box("#comment-button").left - box("#reward-summary").right
            ),
            commentToExit: Math.round(
              box("#early-exit-button").left - box("#comment-button").right
            )
          },
          contrast: {
            comment: window.__contrast(
              styles("#comment-button").borderTopColor,
              footerBg
            ),
            exit: window.__contrast(
              styles("#early-exit-button").borderTopColor,
              footerBg
            ),
            // The controls are surface-filled. The footer is tinted deeper than
            // the page so that fill is visible in its own right, rather than
            // leaving the border to draw the whole control.
            commentFill: window.__contrast(
              styles("#comment-button").backgroundColor,
              footerBg
            ),
            // The footer must not dissolve into the page it sits against.
            footerAgainstPage: window.__contrast(
              footerBg,
              getComputedStyle(document.body).backgroundColor
            )
          },
          // The readout must not look like a third button.
          rewardBorder: styles("#reward-summary").borderTopColor,
          // The label reads on its own fill, not on the bar behind it.
          commentLabelContrast: window.__contrast(
            styles("#comment-button").color,
            styles("#comment-button").backgroundColor
          ),
          exitLabelContrast: window.__contrast(
            styles("#early-exit-button").color,
            styles("#early-exit-button").backgroundColor
          ),
          footerAlignedToContent:
            Math.round(box("#footer > .container").width) <=
            Math.round(box("#main-body").width) + 1
        };
      });

      // One box for all three items, matching the theme's .btn radius rather
      // than introducing a pill.
      expect(footer.heights.comment).toBe(footer.heights.reward);
      expect(footer.heights.exit).toBe(footer.heights.reward);
      expect(footer.radii.reward).toBe(footer.radii.comment);
      expect(footer.radii.reward).toBe(footer.radii.next);

      // Boundaries participants can actually see.
      expect(footer.contrast.comment).toBeGreaterThanOrEqual(3);
      expect(footer.contrast.exit).toBeGreaterThanOrEqual(3);
      expect(footer.rewardBorder).toBe("rgba(0, 0, 0, 0)");

      // A control fill barely distinguishable from the bar left the buttons
      // looking washed out, and the footer needs its own identity against the
      // page it abuts.
      expect(footer.contrast.commentFill).toBeGreaterThan(1.1);
      expect(footer.contrast.footerAgainstPage).toBeGreaterThan(1.03);

      // Coloured labels still have to be readable on the control's own fill.
      expect(footer.commentLabelContrast).toBeGreaterThanOrEqual(4.5);
      expect(footer.exitLabelContrast).toBeGreaterThanOrEqual(4.5);

      // The readout is set like the controls beside it, and its glyph belongs to
      // it rather than being a separately coloured fragment.
      expect(footer.fonts.rewardSize).toBe(footer.fonts.commentSize);
      expect(footer.fonts.rewardFamily).toBe(footer.fonts.commentFamily);
      expect(footer.glyphColor).toBe(footer.rewardColor);

      expect(footer.footerAlignedToContent).toBe(true);
      expect(footer.gaps.commentToExit).toBeLessThan(footer.gaps.rewardToComment);

      // Exit must still read as the red control when focused. The shared 3px
      // accent ring around a small red outline reads as a blue button.
      await page.locator("#comment-button").focus();
      await page.keyboard.press("Tab");
      const focused = await page.evaluate(() => {
        const el = document.getElementById("early-exit-button");
        const cs = getComputedStyle(el);
        return {
          focusVisible: el.matches(":focus-visible"),
          outline: cs.outlineColor,
          border: cs.borderTopColor
        };
      });
      expect(focused.focusVisible).toBe(true);
      expect(focused.outline).toBe(focused.border);
    }
  );
}

for (const scheme of ["light", "dark"]) {
  test(
    `the progress rail reads against the page before it is filled (${scheme})`,
    { tag: "@both" },
    async ({ page }) => {
      await renderTheme(page, {
        viewport: { width: 1280, height: 480 },
        includeBootstrap: true,
        htmlAttrs: `data-bs-theme="${scheme}"`,
        scripts: [contrastHelpers()],
        html: `
          <div id="timeline-header" class="header">
            <div class="progress">
              <div id="timeline-progress-bar" class="progress-bar" style="width:0%"></div>
              <span id="timeline-progress-label" aria-hidden="true" data-progress="0%"></span>
            </div>
          </div>
          <div id="main-body" class="container psynet-surface"><p>Trial</p></div>
          <nav id="footer" class="navbar">
            <div class="container py-2"><span class="footer-text">Reward</span></div>
          </nav>`
      });

      const rail = await page.evaluate(() => {
        const cs = (s) => getComputedStyle(document.querySelector(s));
        const railBg = cs("#timeline-header .progress").backgroundColor;
        return {
          railBg,
          // An empty rail is pure background, so if it matches the page there is
          // nothing to see until progress starts.
          againstPage: window.__contrast(railBg, cs("body").backgroundColor),
          // And the fill has to stand out from the rail once it does.
          fillAgainstRail: window.__contrast(
            cs("#timeline-progress-bar").backgroundColor,
            railBg
          ),
          // The rail and footer are one family.
          matchesFooter: railBg === cs("#footer").backgroundColor
        };
      });

      expect(rail.againstPage).toBeGreaterThanOrEqual(1.1);
      expect(rail.fillAgainstRail).toBeGreaterThanOrEqual(3);
      expect(rail.matchesFooter).toBe(true);
    }
  );
}

test(
  "the footer follows content at every window width",
  { tag: "@both" },
  async ({ page }) => {
    const tallPage = (paragraphs) => `
      <div id="timeline-root">
        <div id="main-body" class="psynet-surface" data-expect-scrolling="true">
          ${"<p>A long experiment page.</p>".repeat(paragraphs)}
          <div class="psynet-actions">
            <button id="next-button" class="btn btn-primary btn-lg">Next</button>
          </div>
        </div>
        <nav id="footer" class="navbar" style="height: 60px">
          <div id="media-download-progress-bar" style="width: 50%"></div>
          Reward
        </nav>
      </div>`;

    const geometry = async () =>
      await page.evaluate(() => {
        const footer = document.getElementById("footer");
        const next = document.getElementById("next-button");
        const bar = document.getElementById("media-download-progress-bar");
        const footerBox = footer.getBoundingClientRect();
        const barBox = bar.getBoundingClientRect();
        return {
          position: getComputedStyle(footer).position,
          clearance: getComputedStyle(document.body).paddingBottom,
          footerTop: footerBox.top,
          footerBottom: footerBox.bottom,
          viewportHeight: window.innerHeight,
          footerBelowNext: footerBox.top >= next.getBoundingClientRect().bottom,
          // An in-flow footer that is not a containing block lets the absolutely
          // positioned media bar escape to the top of the page.
          barInsideFooter:
            barBox.top >= footerBox.top - 1 && barBox.bottom <= footerBox.bottom + 1
        };
      });

    // Narrow page overflows: the footer follows the content past the fold, so
    // the window belongs to the page and nothing is reserved.
    await renderTheme(page, {
      viewport: { width: 375, height: 600 },
      includeBootstrap: true,
      scripts: [LAYOUT_JS],
      html: tallPage(60)
    });
    let g = await geometry();
    expect(g.position).toBe("relative");
    expect(g.clearance).toBe("0px");
    expect(g.footerTop).toBeGreaterThan(g.viewportHeight);
    expect(g.footerBelowNext).toBe(true);
    expect(g.barInsideFooter).toBe(true);
    expect(
      (await page.evaluate(async () => await window.psynetLayout.check())).map(
        (v) => v.check
      )
    ).not.toContain("nothing_permanently_occluded");

    // Narrow page fits: the footer stops at the bottom edge of the window
    // instead of floating up under the content it follows.
    await renderTheme(page, {
      viewport: { width: 375, height: 600 },
      includeBootstrap: true,
      scripts: [LAYOUT_JS],
      html: tallPage(1)
    });
    g = await geometry();
    expect(g.position).toBe("relative");
    expect(g.footerBottom).toBeCloseTo(g.viewportHeight, 0);
    expect(g.footerTop).toBeGreaterThan(
      await page.evaluate(
        () => document.getElementById("next-button").getBoundingClientRect().bottom
      )
    );

    // The same holds with no JavaScript at all: were this decided by
    // measurement, the participant would watch the footer jump after the first
    // paint.
    await renderTheme(page, {
      viewport: { width: 375, height: 600 },
      includeBootstrap: true,
      html: tallPage(60)
    });
    g = await geometry();
    expect(g.position).toBe("relative");
    expect(g.clearance).toBe("0px");
    expect(g.footerTop).toBeGreaterThan(g.viewportHeight);

    // Wide windows use the same in-flow behavior.
    await renderTheme(page, {
      viewport: { width: 1280, height: 600 },
      includeBootstrap: true,
      scripts: [LAYOUT_JS],
      html: tallPage(60)
    });
    g = await geometry();
    expect(g.position).toBe("relative");
    expect(g.clearance).toBe("0px");
    expect(g.footerTop).toBeGreaterThan(g.viewportHeight);
    expect(g.footerBelowNext).toBe(true);

    // Resizing never changes the footer positioning model.
    await page.setViewportSize({ width: 375, height: 600 });
    expect((await geometry()).position).toBe("relative");
    await page.setViewportSize({ width: 900, height: 600 });
    expect((await geometry()).position).toBe("relative");
  }
);

test(
  "inplace footer replacement needs no layout bookkeeping",
  { tag: "@both" },
  async ({ page }) => {
    await renderTheme(page, {
      viewport: { width: 1280, height: 720 },
      scripts: [LAYOUT_JS],
      html: `
        <div id="timeline-root">
          <div id="main-body" class="psynet-surface"><p>Trial</p></div>
          <nav id="footer" class="navbar" style="height: 60px">Reward</nav>
        </div>`
    });

    await page.evaluate(() => {
      const footer = document.createElement("nav");
      footer.id = "footer";
      footer.className = "navbar";
      footer.style.height = "150px";
      footer.textContent = "Updated reward";
      document.getElementById("footer").replaceWith(footer);
    });

    const geometry = await page.evaluate(() => {
      const footer = document.getElementById("footer");
      return {
        position: getComputedStyle(footer).position,
        height: footer.getBoundingClientRect().height,
        bottom: footer.getBoundingClientRect().bottom,
        viewport: window.innerHeight,
        bodyPadding: getComputedStyle(document.body).paddingBottom
      };
    });
    expect(geometry.position).toBe("relative");
    // CSS height describes the content box; the footer also has a 1px border.
    expect(geometry.height).toBeGreaterThanOrEqual(150);
    expect(geometry.height).toBeLessThanOrEqual(151);
    expect(geometry.bottom).toBeCloseTo(geometry.viewport, 0);
    expect(geometry.bodyPadding).toBe("0px");
  }
);

async function renderLayoutFixture(page, html, viewport = { width: 1280, height: 720 }) {
  await page.setViewportSize(viewport);
  await page.setContent(`<!doctype html>
<html>
<body>
${html}
</body>
</html>`);
  await page.addScriptTag({ path: LAYOUT_JS_PATH });
}

test(
  "layout check reports overflow on a tall page that does not expect scrolling",
  { tag: "@both" },
  async ({ page }) => {
    await renderLayoutFixture(
      page,
      `<div id="main-body" style="height: 2000px">tall</div>`
    );
    const violations = await page.evaluate(async () => window.psynetLayout.check());
    expect(violations.map((item) => item.check)).toContain("no_vertical_overflow");
  }
);

test(
  "layout check skips overflow when expect_scrolling is set",
  { tag: "@both" },
  async ({ page }) => {
    await renderLayoutFixture(
      page,
      `<div id="main-body" data-expect-scrolling="true" style="height: 2000px">tall</div>`
    );
    const violations = await page.evaluate(async () => window.psynetLayout.check());
    expect(violations.map((item) => item.check)).not.toContain("no_vertical_overflow");
    expect(violations.map((item) => item.check)).not.toContain(
      "controls_reachable_without_scrolling"
    );
  }
);

test(
  "layout check is empty on a short page",
  { tag: "@both" },
  async ({ page }) => {
    await renderLayoutFixture(page, `<div id="main-body"><p>short</p></div>`);
    const violations = await page.evaluate(async () => window.psynetLayout.check());
    expect(violations).toEqual([]);
  }
);

test(
  "layout API attaches to an existing psynet object",
  { tag: "@both" },
  async ({ page }) => {
    await page.setContent("<!doctype html><body></body>");
    await page.addScriptTag({ content: "window.psynet = {};" });
    await page.addScriptTag({ path: LAYOUT_JS_PATH });
    const attached = await page.evaluate(
      () => window.psynet.layout === window.psynetLayout
    );
    expect(attached).toBe(true);
  }
);

test(
  "layout helper fails when the page API is missing",
  { tag: "@both" },
  async ({ page }) => {
    const { assertPageInvariants } = require("./participantPageInvariants");
    await page.setContent("<!doctype html><p>bare</p>");
    await expect(assertPageInvariants(page, "bare page")).rejects.toThrow(
      /psynetLayout/
    );
  }
);

function fragmentRuntime() {
  const start = PSYNET_JS.indexOf("psynet.prepareTimelineFragment = function");
  const end = PSYNET_JS.indexOf("psynet.deactivateTimelineFragmentLifecycle");
  if (start < 0 || end < 0) {
    throw new Error("Could not extract timeline fragment functions");
  }
  return `
    window.psynet = window.psynet || {};
    psynet.getPageCssLinks = function () { return []; };
    psynet.ensureStylesheetLinks = function () {};
    psynet.applyInlinePageStyles = function () {};
    ${PSYNET_JS.slice(start, end)}
  `;
}

function mediaProgressRuntime() {
  const start = PSYNET_JS.indexOf(
    "psynet.media.downloadProgress = {"
  );
  const end = PSYNET_JS.indexOf("\n    psynet.media.requests =", start);
  if (start < 0 || end < 0) {
    throw new Error("Could not extract media progress functions");
  }
  return `
    window.psynet = window.psynet || {};
    psynet.utils = {
      mean(values) {
        return values.reduce((sum, value) => sum + value, 0) / values.length;
      }
    };
    psynet.media = { types: ["audio"] };
    ${PSYNET_JS.slice(start, end)}
  `;
}

function timelineMarkup({ footer, media = true }) {
  const bar = `<div id="media-download-progress-bar" data-nest="${
    footer ? "nested" : "standalone"
  }" style="width:40%"></div>`;
  const chrome = footer
    ? `<nav id="footer">${bar}<div class="footer-text">Reward</div></nav>`
    : media
      ? bar
      : "";
  return `
    <div id="timeline-header"></div>
    <div id="main-body">body</div>
    ${chrome}
    <script id="psynet-template-data" type="application/json">{}</script>
  `;
}

async function swapTimeline(page, html) {
  return page.evaluate((nextHtml) => {
    const fragment = window.psynet.prepareTimelineFragment({ html: nextHtml });
    window.psynet.commitTimelineFragment(fragment);
    const bars = [...document.querySelectorAll("#media-download-progress-bar")];
    return {
      count: bars.length,
      nested: bars.length === 1 && bars[0].closest("#footer") !== null,
      hasFooter: document.getElementById("footer") !== null
    };
  }, html);
}

test(
  "inplace swaps keep a single media bar when footer presence changes",
  { tag: "@both" },
  async ({ page }) => {
    await page.setContent(`<!doctype html>
<html><body>
  <div id="timeline-root">${timelineMarkup({ footer: false })}</div>
</body></html>`);
    await page.addScriptTag({ content: fragmentRuntime() });

    let state = await swapTimeline(page, timelineMarkup({ footer: true }));
    expect(state).toEqual({ count: 1, nested: true, hasFooter: true });

    state = await swapTimeline(page, timelineMarkup({ footer: false }));
    expect(state).toEqual({ count: 1, nested: false, hasFooter: false });

    state = await swapTimeline(page, timelineMarkup({ footer: false }));
    expect(state).toEqual({ count: 1, nested: false, hasFooter: false });

    state = await swapTimeline(
      page,
      timelineMarkup({ footer: false, media: false })
    );
    expect(state).toEqual({ count: 0, nested: false, hasFooter: false });

    state = await swapTimeline(page, timelineMarkup({ footer: true }));
    expect(state).toEqual({ count: 1, nested: true, hasFooter: true });
  }
);

test(
  "jsPsych stage fits a laptop window with a footer",
  { tag: "@both" },
  async ({ page }) => {
    await renderTheme(page, {
      viewport: { width: 1280, height: 720 },
      extraCss: `
        .navbar { --bs-navbar-padding-y: 0.5rem; --bs-navbar-padding-x: 0;
                  position: relative; display: flex; flex-wrap: wrap;
                  align-items: center;
                  padding: var(--bs-navbar-padding-y) var(--bs-navbar-padding-x); }
        .container { width: 100%; padding-inline: 0.75rem; margin-inline: auto; }
        .py-2 { padding-top: 0.5rem; padding-bottom: 0.5rem; }`,
      html: `
        <div id="timeline-root">
          <div id="timeline-header" class="header">
            <div class="progress" style="height: 1rem"></div>
          </div>
          <div id="main-body" class="psynet-surface">
            <div id="js-psych"></div>
          </div>
          <nav id="footer" class="navbar">
            <div class="container py-2"><div class="footer-text">Reward: $0.42</div></div>
          </nav>
        </div>
        `
    });

    const overflow = await page.evaluate(() => {
      const scrollHeight = Math.max(
        document.documentElement.scrollHeight,
        document.body.scrollHeight
      );
      return {
        overflow: scrollHeight - window.innerHeight,
        stageMinHeight: getComputedStyle(document.getElementById("js-psych"))
          .minHeight
      };
    });
    expect(overflow.overflow).toBeLessThanOrEqual(1);
    expect(overflow.stageMinHeight).not.toBe("70vh");
  }
);

test(
  "layout check reports a control left behind the footer",
  { tag: "@both" },
  async ({ page }) => {
    await renderLayoutFixture(
      page,
      `<div id="main-body" data-expect-scrolling="true">
         <div style="height: 2000px">tall</div>
         <button id="next-button">Next</button>
       </div>
       <nav id="footer" style="position:fixed; bottom:0; left:0; right:0; height:80px; background:#ccc">footer</nav>`
    );
    const violations = await page.evaluate(async () => window.psynetLayout.check());
    expect(violations.map((item) => item.check)).toContain(
      "nothing_permanently_occluded"
    );
  }
);

for (const responseMarkup of [
  '<input class="response" id="text-input">',
  '<textarea class="response" id="long-text"></textarea>',
  '<select class="response" id="choice"><option>Choice</option></select>',
  '<div class="response" id="custom-control" tabindex="0">Custom control</div>'
]) {
  test(
    `layout check reports an occluded ${responseMarkup.match(/^<(\w+)/)[1]} response`,
    { tag: "@both" },
    async ({ page }) => {
      await renderLayoutFixture(
        page,
        `<div id="main-body" data-expect-scrolling="true">
           <div style="height: 2000px">tall</div>
           ${responseMarkup}
         </div>
         <nav id="footer" style="position:fixed; bottom:0; left:0; right:0; height:80px; background:#ccc">footer</nav>`
      );
      const violations = await page.evaluate(async () => window.psynetLayout.check());
      expect(violations.map((item) => item.check)).toContain(
        "nothing_permanently_occluded"
      );
    }
  );
}

test(
  "percentage-height probe restores inline value and priority",
  { tag: "@both" },
  async ({ page }) => {
    await renderLayoutFixture(
      page,
      `<div><div id="percentage-height" style="height: 50% !important">content</div></div>`
    );

    const style = await page.evaluate(() => {
      window.psynetLayout.collectViolations();
      const element = document.getElementById("percentage-height");
      return {
        value: element.style.getPropertyValue("height"),
        priority: element.style.getPropertyPriority("height")
      };
    });
    expect(style).toEqual({ value: "50%", priority: "important" });
  }
);

test(
  "layout check accepts a fixed custom footer when content clears it",
  { tag: "@both" },
  async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.setContent(`<!doctype html>
<html>
<head><style>body { margin: 0; padding-bottom: 5rem; }</style></head>
<body>
  <div id="main-body" data-expect-scrolling="true">
    <div style="height: 2000px">tall</div>
    <button id="next-button">Next</button>
  </div>
  <nav id="footer" style="position:fixed; bottom:0; left:0; right:0; height:80px; background:#ccc">footer</nav>
</body>
</html>`);
    await page.addScriptTag({ path: LAYOUT_JS_PATH });
    const violations = await page.evaluate(async () => window.psynetLayout.check());
    expect(violations.map((item) => item.check)).not.toContain(
      "nothing_permanently_occluded"
    );
  }
);

const CSS_ROOT = path.resolve("psynet/resources/css");
const THEME_ORIGIN = "https://psynet-theme.test";
const SAMPLE_TITLE = "Thanks for your interest in this experiment.";
const SAMPLE_BODY =
  "To proceed, click the button below. Your responses so far will still be saved.";

// Served from a routed origin rather than through setContent so that
// participant.css can fetch its own font files, which is what makes the
// before-and-after comparison below meaningful.
async function renderThemedText(page) {
  await page.route(`${THEME_ORIGIN}/**`, (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname.endsWith(".woff2")) {
      return route.fulfill({
        contentType: "font/woff2",
        body: fs.readFileSync(path.join(CSS_ROOT, pathname))
      });
    }
    if (pathname === "/participant.css") {
      return route.fulfill({ contentType: "text/css", body: THEME_CSS });
    }
    return route.fulfill({
      contentType: "text/html",
      body: `<!doctype html>
<html><head>
<link rel="stylesheet" href="/participant.css">
<style>
  .surface { width: 640px; }
  /* Inline-block so the box tracks the text rather than the column. */
  .nowrap { white-space: nowrap; display: inline-block; }
  .medium { font-weight: 500; }
</style>
</head><body>
<div class="surface" id="themed">
  <h1 class="title">${SAMPLE_TITLE}</h1>
  <p class="body">${SAMPLE_BODY}</p>
  <span class="medium nowrap">Continue to the next page</span>
  <h1 class="title nowrap">${SAMPLE_TITLE}</h1>
  <p class="body nowrap">${SAMPLE_BODY}</p>
</div>
<div class="surface" id="pre-swap"></div>
</body></html>`
    });
  });
  await page.goto(`${THEME_ORIGIN}/`);
}

test(
  "text does not resize when Inter replaces the fallback font",
  { tag: "@both" },
  async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await renderThemedText(page);

    const measurements = await page.evaluate(async () => {
      await document.fonts.ready;
      const families = getComputedStyle(document.documentElement)
        .getPropertyValue("--psynet-font-sans")
        .split(",")
        .map((family) => family.trim().replace(/^["']|["']$/g, ""));
      // The family the browser reaches for while Inter is still downloading.
      const [interFamily, fallbackFamily] = families;

      // The metric-matched fallback can only be exercised where the machine
      // has an Arial-metric font for it to scale.
      let arialMetricFont = true;
      try {
        await new FontFace(
          "MetricProbe",
          'local("Arial"), local("Liberation Sans"), local("Arimo")'
        ).load();
      } catch {
        arialMetricFont = false;
      }

      const preSwap = document.getElementById("pre-swap");
      preSwap.innerHTML = document.getElementById("themed").innerHTML;
      preSwap.style.fontFamily = `"${fallbackFamily}"`;

      const boxes = (id) =>
        [...document.querySelectorAll(`#${id} > *`)].map((element) => {
          const rect = element.getBoundingClientRect();
          return { width: rect.width, height: rect.height };
        });
      const declared = (family) =>
        [...document.fonts].filter((face) => face.family === family);
      return {
        interFamily,
        fallbackFamily,
        interLoaded: declared(interFamily).some(
          (face) => face.status === "loaded"
        ),
        fallbackIsDeclared: declared(fallbackFamily).length > 0,
        arialMetricFont,
        themed: boxes("themed"),
        preSwap: boxes("pre-swap")
      };
    });

    expect(measurements.interFamily).toBe("Inter");
    expect(measurements.interLoaded).toBe(true);
    // Leaving the pre-swap font to the machine makes the swap unpredictable:
    // the theme has to name a face of its own that Inter can replace without
    // resizing anything.
    expect(measurements.fallbackIsDeclared).toBe(true);
    test.skip(
      !measurements.arialMetricFont,
      "No Arial-metric font is installed, so the metric-matched fallback " +
        "cannot be exercised here."
    );

    const [
      themedTitle,
      themedBody,
      themedButton,
      themedTitleWidth,
      themedBodyWidth
    ] =
      measurements.themed;
    const [preTitle, preBody, preButton, preTitleWidth, preBodyWidth] =
      measurements.preSwap;

    // Wrapped text must keep its line count, or the page reflows under the
    // participant when the webfont lands.
    expect(preTitle.height).toBe(themedTitle.height);
    expect(preBody.height).toBe(themedBody.height);
    expect(preButton.height).toBe(themedButton.height);

    // Heading text is the most visible: an unmatched fallback sets it several
    // percent narrower, which reads as the title changing size mid-load.
    // These sub-pixel comparisons use Playwright's deterministic font-rendering
    // flags; production hinting can alter raster bounds without changing the
    // fallback metrics or wrapped line count.
    const shift = (before, after) => Math.abs(before.width / after.width - 1);
    expect(shift(preTitleWidth, themedTitleWidth)).toBeLessThan(0.01);
    expect(shift(preBodyWidth, themedBodyWidth)).toBeLessThan(0.01);
    expect(shift(preButton, themedButton)).toBeLessThan(0.01);
  }
);
