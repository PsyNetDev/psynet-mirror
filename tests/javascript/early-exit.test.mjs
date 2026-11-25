import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SOURCE = fs.readFileSync(
  path.join(ROOT, "psynet/resources/scripts/psynet.early-exit.js"),
  "utf8"
);

function element() {
  const listeners = [];
  return {
    hidden: true,
    style: {},
    dataset: {},
    textContent: "",
    focus() {},
    addEventListener(type, listener, options) {
      listeners.push({ type, listener, signal: options?.signal });
    },
    click() {
      for (const { type, listener, signal } of listeners) {
        if (type === "click" && !signal?.aborted) listener({ target: this });
      }
    },
  };
}

function leavePage() {
  const page = {
    "early-exit-button": element(),
    "early-exit-modal": element(),
    "early-exit-cancel": element(),
    "early-exit-confirm": element(),
    "early-exit-title": element(),
    "early-exit-message": element(),
  };
  page["early-exit-modal"].dataset.assignmentId = "A1";
  return page;
}

describe("the Leave button", () => {
  it("opens the new page's dialog if a reply replaces the page while answers are sent", async () => {
    const first = leavePage();
    const second = leavePage();
    let dom = first;
    const sentFor = [];
    const window = {
      pageUuid: "page-1",
      psynet: { answers: { sending: null } },
      setTimeout,
      clearTimeout,
    };
    const document = {
      getElementById: (id) => dom[id] ?? null,
      addEventListener() {},
    };
    const fetch = async (url, options) => {
      sentFor.push(JSON.parse(options.body).page_uuid);
      return {
        ok: true,
        json: async () => ({
          offer_id: "offer",
          confirmation: { title: "Leave?", message: "", confirm_label: "", cancel_label: "" },
        }),
      };
    };
    new Function("window", "document", "fetch", SOURCE)(window, document, fetch);
    window.psynetEarlyExit.init();

    // The answer's reply replaces the page, as keepPage or a swap does.
    window.psynet.answers.sending = (async () => {
      await null;
      dom = second;
      window.pageUuid = "page-2";
      window.psynetEarlyExit.init();
    })().finally(() => {
      window.psynet.answers.sending = null;
    });
    first["early-exit-button"].click();
    await new Promise((resolve) => setTimeout(resolve, 10));

    assert.deepEqual(sentFor, ["page-2"]);
    assert.equal(first["early-exit-modal"].hidden, true);
    assert.equal(second["early-exit-modal"].hidden, false);
    assert.equal(second["early-exit-modal"].dataset.offerId, "offer");
  });

  it("asks for the hold page's offer while a timeline hold covers the page", async () => {
    const page = leavePage();
    const sentFor = [];
    const window = {
      pageUuid: "page-1",
      psynet: { answers: { sending: null }, submissionPageUuid: "hold-1" },
      setTimeout,
      clearTimeout,
    };
    const document = { getElementById: (id) => page[id] ?? null, addEventListener() {} };
    const fetch = async (url, options) => {
      sentFor.push(JSON.parse(options.body).page_uuid);
      return { ok: false, json: async () => ({}) };
    };
    new Function("window", "document", "fetch", SOURCE)(window, document, fetch);
    window.psynetEarlyExit.init();

    page["early-exit-button"].click();
    await new Promise((resolve) => setTimeout(resolve, 10));

    assert.deepEqual(sentFor, ["hold-1"]);
  });
});
