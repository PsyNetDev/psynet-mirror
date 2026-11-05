/**
 * GroupPrompt layout: at the edges of each layout (row, table, wrapped rows,
 * list), on a laptop and a phone, with and without answer bubbles, members
 * must be readable and visible. Their icons, names and bubbles stay inside
 * the window, do not overlap each other or the rest of the page, are not
 * clipped, and have enough contrast. The HTML comes from GroupPrompt itself
 * (render_group_prompt.py), with the longest pseudonyms.
 */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { test, expect } = require("./fixtures");

const read = (file) => fs.readFileSync(path.resolve(file), "utf8");
const BOOTSTRAP_CSS = read("psynet/resources/libraries/bootstrap/bootstrap.min.css");
const THEME_CSS = read("psynet/resources/css/participant.css");
const LAYOUT_JS = read("psynet/resources/scripts/psynet.layout.js");

const SIZES = [2, 4, 5, 6, 7, 12, 13];
const VIEWPORTS = [
  { label: "laptop", width: 1280, height: 720 },
  { label: "phone", width: 375, height: 780 },
];
const CASES = SIZES.flatMap((size) => [
  { size, answers: false },
  { size, answers: true, note: "1 was picked twice" },
]);

function renderCases(cases) {
  const result = spawnSync(
    process.env.PYTHON || "python",
    ["tests/playwright/render_group_prompt.py"],
    { input: JSON.stringify(cases), encoding: "utf8" }
  );
  if (result.status !== 0) throw new Error(result.stderr || String(result.error));
  return JSON.parse(result.stdout);
}

const RENDERED = renderCases(CASES);

async function renderPage(page, viewport, { text, group_html, css }, answers) {
  await page.setViewportSize(viewport);
  const control = answers
    ? '<button id="next-button" class="btn btn-primary btn-lg">Next</button>'
    : [1, 2, 3, 4, 5]
        .map((n) => `<button class="btn btn-primary response push-button">${n}</button>`)
        .join("");
  const direction = answers ? "flex-column" : "flex-row";
  await page.setContent(`<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>${BOOTSTRAP_CSS}${THEME_CSS}${css} body { margin: 0; }</style>
</head><body>
<div id="main-body" class="container psynet-surface" data-expect-scrolling="false">
  <div id="prompt-text">${text}</div>
  ${group_html}
  <div id="control" class="d-flex ${direction} justify-content-center align-items-center gap-2">${control}</div>
</div>
</body></html>`);
  await page.addScriptTag({ content: LAYOUT_JS });
  // Let the staggered bubble animation finish before measuring.
  await page.evaluate(() =>
    Promise.all(document.getAnimations().map((animation) => animation.finished))
  );
}

/** Return readability and visibility problems of the group display. */
function groupLayoutProblems() {
  const problems = [];
  const visible = (el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0;
  };
  const describe = (el) => {
    const member = el.closest(".psynet-group-member");
    const seat = member ? ` (seat ${member.dataset.seat})` : "";
    return `${el.className || el.id}${seat}`;
  };

  const members = [...document.querySelectorAll(".psynet-group-member")];
  const boxes = [];
  for (const member of members) {
    for (const part of member.querySelectorAll(
      ".psynet-pseudonym-icon, .psynet-group-name, .psynet-group-bubble"
    )) {
      if (visible(part)) boxes.push({ el: part, member });
    }
  }
  const page = ["#prompt-text", "#control", ".psynet-group-note"]
    .map((selector) => document.querySelector(selector))
    .filter((el) => el && visible(el));

  // Every part is fully inside the window, so nothing needs scrolling to see.
  for (const { el } of boxes) {
    const r = el.getBoundingClientRect();
    if (r.left < 0 || r.top < 0 || r.right > innerWidth || r.bottom > innerHeight) {
      problems.push(`${describe(el)} is outside the window`);
    }
  }

  // Parts of different members, and parts of one member other than its tick,
  // never overlap; nor do they overlap the text, controls or note.
  const overlap = (a, b) => {
    const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return x > 1 && y > 1;
  };
  for (let i = 0; i < boxes.length; i++) {
    const a = boxes[i].el.getBoundingClientRect();
    for (let j = i + 1; j < boxes.length; j++) {
      if (overlap(a, boxes[j].el.getBoundingClientRect())) {
        problems.push(`${describe(boxes[i].el)} overlaps ${describe(boxes[j].el)}`);
      }
    }
    for (const other of page) {
      if (overlap(a, other.getBoundingClientRect())) {
        problems.push(`${describe(boxes[i].el)} overlaps ${describe(other)}`);
      }
    }
  }

  // Text is not cut off, not too small, and contrasts with its background.
  const rgb = (color) => color.match(/[\d.]+/g).map(Number);
  const luminance = ([r, g, b]) => {
    const channel = (c) => {
      c /= 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };
  const background = (el) => {
    for (let node = el; node; node = node.parentElement) {
      const [r, g, b, a = 1] = rgb(getComputedStyle(node).backgroundColor);
      if (a > 0.5) return [r, g, b];
    }
    return [255, 255, 255];
  };
  const textParts = [
    ...document.querySelectorAll(".psynet-group-name, .psynet-group-bubble, .psynet-group-note"),
  ].filter(visible);
  const inside = (a, b) =>
    a.left >= b.left - 1 && a.top >= b.top - 1 && a.right <= b.right + 1 && a.bottom <= b.bottom + 1;
  for (const el of textParts) {
    const style = getComputedStyle(el);
    const range = document.createRange();
    range.selectNodeContents(el);
    const text = range.getBoundingClientRect();
    if (!inside(text, el.getBoundingClientRect())) {
      problems.push(`${describe(el)} spills its text`);
    }
    for (let node = el.parentElement; node; node = node.parentElement) {
      if (getComputedStyle(node).overflow !== "visible" && node !== document.documentElement && node !== document.body) {
        if (!inside(text, node.getBoundingClientRect())) {
          problems.push(`${describe(el)} is cut off by ${describe(node)}`);
        }
      }
    }
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      for (const match of node.textContent.matchAll(/\S+/g)) {
        const word = document.createRange();
        word.setStart(node, match.index);
        word.setEnd(node, match.index + match[0].length);
        const lines = new Set([...word.getClientRects()].map((r) => Math.round(r.top)));
        if (lines.size > 1) problems.push(`${describe(el)} breaks "${match[0]}" across lines`);
      }
    }
    if (parseFloat(style.fontSize) < 12) {
      problems.push(`${describe(el)} has ${style.fontSize} text`);
    }
    const [fg, bg] = [luminance(rgb(style.color)), luminance(background(el))];
    const contrast = (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
    if (contrast < 4.5) {
      problems.push(`${describe(el)} has contrast ${contrast.toFixed(2)}`);
    }
  }
  return problems;
}

for (const viewport of VIEWPORTS) {
  CASES.forEach((groupCase, index) => {
    const label = `${groupCase.size} members${groupCase.answers ? " with answers" : ""}`;
    test(
      `GroupPrompt with ${label} is readable on a ${viewport.label}`,
      { tag: "@both" },
      async ({ page }) => {
        await renderPage(page, viewport, RENDERED[index], groupCase.answers);
        await page.locator(".psynet-group-member").first().waitFor();
        expect(await page.locator(".psynet-group-member").count()).toBe(groupCase.size);
        expect(await page.evaluate(groupLayoutProblems), label).toEqual([]);
        // A results page for a full group may scroll to its Next button on a
        // phone (see GroupPrompt); the group itself must still be visible.
        if (viewport.label === "phone" && groupCase.size > 9 && groupCase.answers) return;
        expect(await page.evaluate(() => window.psynetLayout.check()), label).toEqual([]);
      }
    );
  });
}
