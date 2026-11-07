/**
 * GroupPrompt layout: for rows and zigzags, subgroups and shown names, on a
 * laptop and a phone, with and without answer bubbles, members must be
 * readable and visible. Animals, labels and bubbles stay inside the window
 * and off the rest of the page; animals and labels never overlap each
 * other. Rows of up to three members fit on one line; in a row, animals on
 * a line are level and bubbles side by side however text wraps; in a zigzag a bubble
 * may overlap a neighbour, but hovering over its member brings it to the
 * front. Text is not clipped and has enough contrast. The HTML comes from
 * GroupPrompt itself (render_group_prompt.py), with the longest pseudonyms.
 */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { test, expect } = require("./fixtures");

const read = (file) => fs.readFileSync(path.resolve(file), "utf8");
const BOOTSTRAP_CSS = read("psynet/resources/libraries/bootstrap/bootstrap.min.css");
const THEME_CSS = read("psynet/resources/css/participant.css");
const LAYOUT_JS = read("psynet/resources/scripts/psynet.layout.js");
const ORIGIN = "http://psynet.test";
const STATIC_PREFIX = "/static/packages/psynet/";

const VIEWPORTS = [
  { label: "laptop", width: 1280, height: 720 },
  { label: "phone", width: 375, height: 780 },
];
const SHAPES = [
  { size: 2 },
  { size: 2, answer: "I accept 4 or more" },
  { size: 3, names: "shown" },
  { size: 4 },
  { size: 5 },
  { size: 8 },
  { size: 12 },
  { size: 8, subgroup_size: 2 },
  { size: 12, subgroup_size: 6 },
  { size: 6, names: "shown" },
  { size: 2, names: "anonymous" },
];
const CASES = SHAPES.flatMap((shape) => [
  ...(shape.answer ? [] : [{ ...shape, answers: false }]),
  { ...shape, answers: true, note: "1 was picked twice" },
]);
const describeCase = (c) =>
  [
    `${c.size} members`,
    c.subgroup_size && `in subgroups of ${c.subgroup_size}`,
    c.names === "anonymous" && "anonymous",
    c.names === "shown" && "with names",
    c.answer && "with a wrapping answer",
    c.answers && "with answers",
  ]
    .filter(Boolean)
    .join(" ");

function renderCases(cases) {
  const result = spawnSync(
    process.env.PYTHON || "python3",
    ["tests/playwright/render_group_prompt.py"],
    { input: JSON.stringify(cases), encoding: "utf8" }
  );
  if (result.status !== 0) throw new Error(result.stderr || String(result.error));
  return JSON.parse(result.stdout);
}

// Rendered on first use, so that listing tests does not need Python.
let rendered;
const renderedCase = (index) => (rendered ??= renderCases(CASES))[index];

async function renderPage(page, viewport, { text, group_html, css }, answers) {
  await page.setViewportSize(viewport);
  const control = answers
    ? '<button id="next-button" class="btn btn-primary btn-lg">Next</button>'
    : [1, 2, 3, 4, 5]
        .map((n) => `<button class="btn btn-primary response push-button">${n}</button>`)
        .join("");
  const direction = answers ? "flex-column" : "flex-row";
  // Served from an origin so that static URLs such as the animal artwork load.
  await page.route(`${ORIGIN}/**`, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith(STATIC_PREFIX)) {
      const file = path.join("psynet/static", url.pathname.slice(STATIC_PREFIX.length));
      return route.fulfill({ path: file });
    }
    return route.fulfill({ contentType: "text/html; charset=utf-8", body: html });
  });
  const html = `<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>${BOOTSTRAP_CSS}${THEME_CSS}${css} body { margin: 0; }</style>
</head><body>
<div id="main-body" class="container psynet-surface" data-expect-scrolling="false">
  <div id="prompt-text">${text}</div>
  ${group_html}
  <div id="control" class="d-flex ${direction} justify-content-center align-items-center gap-2">${control}</div>
</div>
</body></html>`;
  await page.goto(`${ORIGIN}/`);
  await page.waitForFunction(() => [...document.images].every((img) => img.complete));
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
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 1;
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
      ".psynet-pseudonym-sticker, .psynet-group-name, .psynet-group-bubble"
    )) {
      if (visible(part)) boxes.push({ el: part, member });
    }
  }
  // Whether two boxes overlap, or only their vertical extents for "y".
  const overlap = (a, b, axis) => {
    const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return y > 1 && (axis === "y" || x > 1);
  };

  // Rows of up to three members fit on one line. Animals sharing a line are
  // level, and bubbles sit side by side.
  for (const row of document.querySelectorAll(".psynet-group-members--row")) {
    const stickers = [...row.querySelectorAll(".psynet-pseudonym-sticker")].map((sticker) =>
      sticker.getBoundingClientRect()
    );
    const lines = stickers.filter((a, i) => !stickers.slice(0, i).some((b) => overlap(a, b, "y")));
    if (stickers.length <= 3 && lines.length > 1) {
      problems.push(`a row of ${stickers.length} members wraps`);
    }
    for (const [i, a] of stickers.entries()) {
      for (const b of stickers.slice(i + 1)) {
        if (overlap(a, b, "y") && Math.abs(a.top - b.top) > 1) {
          problems.push(`row animals are not level (tops ${a.top}, ${b.top})`);
        }
      }
    }
    const bubbles = [...row.querySelectorAll(".psynet-group-bubble")].filter(visible);
    for (const [i, a] of bubbles.entries()) {
      for (const b of bubbles.slice(i + 1)) {
        if (overlap(a.getBoundingClientRect(), b.getBoundingClientRect())) {
          problems.push(`${describe(a)} overlaps ${describe(b)}`);
        }
      }
    }
  }

  // Bubbles may overlap other members (hovering brings them to the front).
  const isBubble = (el) => el.classList.contains("psynet-group-bubble");
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
  for (let i = 0; i < boxes.length; i++) {
    const a = boxes[i].el.getBoundingClientRect();
    for (let j = i + 1; j < boxes.length; j++) {
      if (isBubble(boxes[i].el) || isBubble(boxes[j].el)) continue;
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

/** Return the seats whose bubble is not on top while their member is hovered. */
async function hiddenBubbles(page) {
  const hidden = [];
  for (const member of await page.locator(".psynet-group-member").all()) {
    const bubble = member.locator(".psynet-group-bubble:not(.psynet-group-bubble--none)");
    if ((await bubble.count()) === 0) continue;
    await member.hover();
    const onTop = await bubble.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const [x, y] = [(r.left + r.right) / 2, (r.top + r.bottom) / 2];
      // Edge midpoints, as hit testing follows the rounded corners.
      const points = [
        [r.left + 3, y],
        [r.right - 3, y],
        [x, r.top + 3],
        [x, r.bottom - 3],
      ];
      return points.every(([x, y]) => el.contains(document.elementFromPoint(x, y)));
    });
    if (!onTop) hidden.push(await member.getAttribute("data-seat"));
  }
  await page.mouse.move(0, 0);
  return hidden;
}

for (const viewport of VIEWPORTS) {
  CASES.forEach((groupCase, index) => {
    const label = describeCase(groupCase);
    test(
      `GroupPrompt with ${label} is readable on a ${viewport.label}`,
      { tag: "@both" },
      async ({ page }) => {
        await renderPage(page, viewport, renderedCase(index), groupCase.answers);
        await page.locator(".psynet-group-member").first().waitFor();
        expect(await page.locator(".psynet-group-member").count()).toBe(groupCase.size);
        expect(await page.evaluate(groupLayoutProblems), label).toEqual([]);
        expect(await hiddenBubbles(page), `${label}: bubbles behind others on hover`).toEqual([]);
        expect(await page.evaluate(() => window.psynetLayout.check()), label).toEqual([]);
      }
    );
  });
}
