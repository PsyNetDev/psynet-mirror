import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { activate } from "../../psynet/resources/scripts/vocabtest.js";

function vocabPage(decode) {
  const listeners = {};
  globalThis.document = {
    addEventListener: (type, fn) => (listeners[type] = fn),
    removeEventListener() {},
  };
  globalThis.Image = class {
    style = {};
    decode() {
      return decode();
    }
  };
  const target = { shown: null, replaceChildren: (img = null) => (target.shown = img) };
  const root = {
    querySelector: () => target,
    querySelectorAll: () => [],
    addEventListener() {},
    removeEventListener() {},
  };
  const psynet = {
    pageConfig: { vocab: { keyboard: true, trueKey: "KeyA", falseKey: "KeyL", lag: 0, hideAfter: 1000 } },
    log: { warn() {} },
  };
  const answers = [];
  const handle = { answer: (choice) => answers.push(choice), startClock() {} };
  const page = activate({ root, psynet });
  const show = (signal = new AbortController().signal) =>
    page.update({ contents: { image: "/word.png" }, upcomingContents: [], response: handle, signal });
  const press = (code, extra = {}) => listeners.keydown({ code, target: {}, ...extra });
  return { page, target, answers, show, press };
}

describe("vocabulary test page", () => {
  it("doesn't show a word whose update was abandoned while it decoded", async () => {
    const controller = new AbortController();
    const { page, target, answers, show, press } = vocabPage(async () => controller.abort());
    await show(controller.signal);
    assert.equal(target.shown, null);
    press("KeyA");
    assert.deepEqual(answers, []);
    page.cleanup();
  });

  it("answers with the configured keys but not with shortcuts", async () => {
    const { page, answers, show, press } = vocabPage(async () => {});
    await show();
    press("KeyA", { ctrlKey: true });
    press("KeyA");
    assert.deepEqual(answers, ["real"]);
    page.cleanup();
  });

  it("gives up on an image that fails to decode three times", async () => {
    let attempts = 0;
    const { page, show } = vocabPage(async () => {
      attempts++;
      throw new Error("broken");
    });
    await assert.rejects(show(), /Couldn't load \/word.png/);
    assert.equal(attempts, 3);
    page.cleanup();
  });
});
