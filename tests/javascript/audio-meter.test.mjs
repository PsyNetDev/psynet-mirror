import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { it } from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SOURCE = fs.readFileSync(
  path.join(ROOT, "psynet/templates/macros/control/audio_meter.js"),
  "utf8"
);

function element() {
  return {
    innerHTML: "",
    style: { setProperty() {} },
    setAttribute() {},
    querySelector: () => element(),
  };
}

function loadMeter(config, sliders = {}) {
  const timeouts = [];
  let resetMessage = null;
  const text = element();
  const context = {
    psynet: {
      media: { requireAudio() {} },
      page: { control: {} },
      trial: {
        onEvent() {},
        setTimer(handler, timeout) {
          timeouts.push(timeout);
          resetMessage = handler;
          return timeouts.length;
        },
      },
    },
    document: { getElementById: (id) => (id === "audio-meter-text" ? text : element()) },
    window: { requestAnimationFrame() {} },
    $: (selector) => ({ get: () => ({ value: sliders[selector.slice(1)] }) }),
    clearTimeout() {},
  };
  vm.runInNewContext(SOURCE, context);
  const meter = context.psynet.page.control.audioMeter;
  meter.init(
    JSON.stringify({
      display_range: { min: -60, max: 0 },
      decay: { display: 0.1, high: 0.1, low: 0.1 },
      threshold: { high: -2, low: -20 },
      grace: { high: 0.0, low: 1.5 },
      warn_on_clip: true,
      msg_duration: { high: 0.25, low: 0.25 },
      ...config,
    })
  );
  const level = { db: -10, clipping: false };
  meter.audioMeter = {
    get volume() {
      return level.db === null ? null : { display: level.db, high: level.db, low: level.db };
    },
    checkClipping: () => level.clipping,
  };
  const at = (time) => {
    meter.onLevelChange(time);
    return text.innerHTML;
  };
  const fireReset = () => {
    resetMessage();
    return text.innerHTML;
  };
  return { meter, text, level, at, timeouts, fireReset };
}

it("warns about quiet input only after the low grace period", () => {
  const { level, at, timeouts, fireReset } = loadMeter({
    grace: { high: 0.0, low: 4 },
    msg_duration: { high: 0.25, low: 0.5 },
  });
  level.db = -40;
  assert.equal(at(1000), "Just right.");
  assert.equal(at(4900), "Just right.");
  assert.equal(at(5100), "Too quiet!");
  assert.deepEqual(timeouts, [500]);
  assert.equal(fireReset(), "Just right.");
});

it("warns about loud input only after the high grace period", () => {
  const { level, at, timeouts } = loadMeter({
    grace: { high: 0.2, low: 1.5 },
    msg_duration: { high: 0.75, low: 0.25 },
  });
  level.db = 0;
  assert.equal(at(1000), "Just right.");
  assert.equal(at(1150), "Just right.");
  assert.equal(at(1250), "Too loud!");
  assert.deepEqual(timeouts, [750]);
});

it("keeps the starting message until the first level reading", () => {
  const { meter, text, level, at, timeouts } = loadMeter({});
  meter.showMessage("Starting audio meter...", "blue", null);
  level.db = null;
  assert.equal(at(0), "Starting audio meter...");
  assert.equal(at(1000), "Starting audio meter...");
  level.db = -40;
  assert.equal(at(1100), "Just right.");
  assert.equal(at(2500), "Just right.");
  assert.equal(at(2700), "Too quiet!");
  assert.equal(text.innerHTML, "Too quiet!");
  assert.deepEqual(timeouts, [250]);
});

it("ignores clipping when warn_on_clip is off", () => {
  const quiet = loadMeter({ warn_on_clip: false });
  quiet.level.clipping = true;
  assert.equal(quiet.at(0), "Just right.");

  const warns = loadMeter({ warn_on_clip: true });
  warns.level.clipping = true;
  assert.equal(warns.at(0), "Too loud!");
});

it("reads calibration sliders as numbers", () => {
  const { meter } = loadMeter(
    {},
    {
      "decay-display": "0.1",
      "decay-high": "0.2",
      "decay-low": "0.3",
      "threshold-high": "-5",
      "threshold-low": "-30",
      "grace-high": "0.4",
      "grace-low": "2",
      "warn-on-clip": "0",
      "msg-duration-high": "1",
      "msg-duration-low": "1.5",
    }
  );
  meter.updateFromSliders();
  assert.equal(meter.warnOnClip, false);
  assert.equal(meter.grace.low, 2);
  assert.equal(meter.threshold.low, -30);
  assert.equal(meter.msgDuration.low, 1.5);
});
