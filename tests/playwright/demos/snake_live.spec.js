const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  startExperiment,
  startParticipantsTogether,
  stopExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;
// The game's SIZE.
const SIZE = 30;
const KEYS = { up: "ArrowUp", down: "ArrowDown", left: "ArrowLeft", right: "ArrowRight" };
const STEPS = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
const OPPOSITE = { up: "down", down: "up", left: "right", right: "left" };

// Keeps the latest view the page has drawn in window.latestView, once the
// next view arrives.
function watchViews(page) {
  return page.evaluate(
    () =>
      new Promise((resolve) => {
        psynet.liveSession.onView((view) => {
          window.latestView = view;
          resolve();
        });
      })
  );
}

function latestView(page) {
  return page.evaluate(() => window.latestView);
}

async function snakeOf(page, id) {
  const view = await latestView(page);
  return view.players[id ?? view.me];
}

// Steers the player's snake toward the nearest food, onto empty squares
// only, until it has eaten a piece.
async function eatAPiece(page) {
  const deadline = Date.now() + 20000;
  let pressed = null;
  while (Date.now() < deadline) {
    const view = await latestView(page);
    const me = view.players[view.me];
    if (me.food > 0) {
      return;
    }
    const head = me.body[0];
    if (head && view.food.length) {
      const taken = new Set(
        Object.values(view.players).flatMap((player) => player.body.map((square) => square.join()))
      );
      const food = view.food.reduce((a, b) =>
        Math.abs(a[0] - head[0]) + Math.abs(a[1] - head[1]) <=
        Math.abs(b[0] - head[0]) + Math.abs(b[1] - head[1])
          ? a
          : b
      );
      const options = Object.keys(STEPS)
        .filter((direction) => direction !== OPPOSITE[me.direction])
        .map((direction) => {
          const next = [head[0] + STEPS[direction][0], head[1] + STEPS[direction][1]];
          return { direction, next };
        })
        .filter(({ next }) => next.every((n) => n >= 0 && n < SIZE) && !taken.has(next.join()));
      if (options.length) {
        const distance = ({ next }) => Math.abs(next[0] - food[0]) + Math.abs(next[1] - food[1]);
        const best = options.reduce((a, b) => (distance(b) < distance(a) ? b : a));
        if (best.direction !== me.direction && best.direction !== pressed) {
          await page.keyboard.press(KEYS[best.direction]);
          pressed = best.direction;
        } else if (best.direction === me.direction) {
          pressed = null;
        }
      }
    }
    await page.waitForTimeout(40);
  }
  throw new Error("The snake didn't eat a piece of food in time.");
}

test("players steer snakes in snake_live, eat food, crash and come back, and finish the round", { tag: "@both" }, async ({
  browser
}) => {
  const experiment = startExperiment(path.resolve("demos/experiments/snake_live"));
  const contexts = [await browser.newContext(), await browser.newContext()];

  try {
    const participants = await startParticipantsTogether(
      contexts,
      await experiment.urlPromise,
      "snake_live"
    );
    await Promise.all(
      participants.map(async (participant) => {
        await expect(participant.locator("#snake-status")).toHaveText("Eat the food!", {
          timeout: STEP_TIMEOUT_MS
        });
        await watchViews(participant);
      })
    );
    const [first, second] = participants;
    await expect(first.locator("#next-button")).toBeHidden();
    const id = (await latestView(first)).me;

    // A turn on one page shows on the other, since the game moves every
    // snake and sends both pages the board.
    await expect
      .poll(
        async () => {
          const { direction } = await snakeOf(second, id);
          if (direction !== "down") {
            await first.keyboard.press("ArrowDown");
          }
          return direction;
        },
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe("down");

    await eatAPiece(first);
    const eater = await snakeOf(first);
    await expect(first.locator("#snake-scores")).toContainText(`You: ${eater.food} food`);
    await expect(second.locator("#snake-scores")).toContainText(
      `Player ${eater.number}: ${eater.food} food`,
      { timeout: STEP_TIMEOUT_MS }
    );

    // A reloaded page draws the game as it stands.
    await first.reload();
    await expect(first.locator("#snake-status")).toHaveText("Eat the food!", {
      timeout: STEP_TIMEOUT_MS
    });
    await watchViews(first);

    // Left to go straight on, the snake hits a wall, or a snake, and comes
    // back, as the other player's page shows.
    await expect
      .poll(async () => {
        const { crashes, body } = await snakeOf(second, id);
        return crashes > eater.crashes && body.length > 0;
      }, { timeout: STEP_TIMEOUT_MS })
      .toBe(true);

    // The page moves on by itself once the round is over and the result is
    // saved.
    await expect(first.locator("#main-body")).toContainText("Your snake ate", {
      timeout: STEP_TIMEOUT_MS
    });
    await assertNoBackendError(first);
  } finally {
    for (const context of contexts) {
      await context.close();
    }
    await stopExperiment(experiment.proc);
  }
});
