/**
 * The audio meter used to sit in a 500px table, which pushed the coloured
 * status text off the edge of a phone. This check renders the theme markup
 * at a phone viewport so a regression does not need a microphone or a
 * full experiment. It also guards the CSS-bar restyle: the track is a
 * short themed trough, not a 50px canvas brick.
 */
const fs = require("fs");
const path = require("path");
const { test, expect } = require("./fixtures");

const PHONE_VIEWPORT = { width: 375, height: 780 };

const METER_MARKUP = `
  <div class="psynet-surface">
    <div class="audio-meter-block">
      <div class="audio-meter">
        <div id="audio-meter" class="audio-meter__track" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="60" style="--audio-meter-fill: var(--psynet-success);">
          <div class="audio-meter__fill" style="width: 60%;"></div>
        </div>
        <p id="audio-meter-text" class="audio-meter__text" style="display: block; color: var(--psynet-success);">Just right.</p>
        <p id="audio-meter-device-name" class="audio-meter__device">Microphone: Built-in Microphone</p>
      </div>
    </div>
  </div>
`;

test(
  "audio meter status text stays inside a phone viewport",
  { tag: "@both" },
  async ({ page }) => {
    const css = fs.readFileSync(
      path.resolve("psynet/resources/css/participant.css"),
      "utf8"
    );

    await page.setViewportSize(PHONE_VIEWPORT);
    await page.setContent(`<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
${css}
body { margin: 0; }
</style>
</head>
<body>
${METER_MARKUP}
</body>
</html>`);

    const metrics = await page.evaluate(() => {
      const text = document.getElementById("audio-meter-text");
      const meter = document.querySelector(".audio-meter");
      const track = document.getElementById("audio-meter");
      const textRect = text.getBoundingClientRect();
      const meterRect = meter.getBoundingClientRect();
      const trackRect = track.getBoundingClientRect();
      return {
        textRight: textRect.right,
        textLeft: textRect.left,
        meterRight: meterRect.right,
        trackHeight: trackRect.height,
        viewport: window.innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        hasCanvas: Boolean(document.querySelector("canvas"))
      };
    });

    expect(metrics.hasCanvas).toBe(false);
    expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.viewport + 1);
    expect(metrics.textRight).toBeLessThanOrEqual(metrics.viewport);
    expect(metrics.textLeft).toBeGreaterThanOrEqual(0);
    expect(metrics.meterRight).toBeLessThanOrEqual(metrics.viewport);
    expect(metrics.trackHeight).toBeLessThan(24);
  }
);
