const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  startExperiment,
  startParticipantsTogether,
  stopExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;
// The game's ROUND_SECONDS. Every step until the player who leaves has
// stopped has to happen within it.
const ROUND_SECONDS = 30;
const SIZE = 640;
const DRAG = 4;

// The player's own piece as the page predicts it.
function ownPlayer(page) {
  return page.evaluate(() => {
    const view = psynet.liveSession.predictedView();
    return { id: view.me, ...view.players[view.me] };
  });
}

// Another player's piece as the page draws it.
function drawnPlayer(page, id) {
  return page.evaluate((id) => psynet.liveSession.interpolatedView().players[id], id);
}

function towardCenter(player) {
  return player.x < SIZE / 2 ? "ArrowRight" : "ArrowLeft";
}

// Records, each frame after the page has sent its moves, where the page
// predicts its player is. When a view arrives, the prediction from the new
// view should be the same, since the page works out each move exactly as
// the game does.
function checkPredictions(page) {
  return page.evaluate(() => {
    const check = (window.predictionCheck = { checks: 0, largestError: 0 });
    let before = null;
    const own = () => {
      const view = psynet.liveSession.predictedView();
      return view && view.players[view.me];
    };
    const record = () => {
      before = own();
      requestAnimationFrame(record);
    };
    requestAnimationFrame(record);
    psynet.liveSession.onView(() => {
      const after = own();
      if (before && after) {
        check.checks += 1;
        for (const key of ["x", "y", "vx", "vy"]) {
          check.largestError = Math.max(check.largestError, Math.abs(after[key] - before[key]));
        }
      }
    });
  });
}

// Holds down the arrow keys that steer the player toward the nearest coin,
// aiming short by the distance they'd coast, until they've collected one.
async function collectACoin(page) {
  const held = new Set();
  const press = async (key, down) => {
    if (down && !held.has(key)) {
      held.add(key);
      await page.keyboard.down(key);
    } else if (!down && held.has(key)) {
      held.delete(key);
      await page.keyboard.up(key);
    }
  };
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const { me, coins } = await page.evaluate(() => {
      const view = psynet.liveSession.predictedView();
      return { me: view.players[view.me], coins: view.coins };
    });
    if (me.coins > 0) {
      break;
    }
    const nearest = coins.reduce((a, b) =>
      Math.hypot(a.x - me.x, a.y - me.y) <= Math.hypot(b.x - me.x, b.y - me.y) ? a : b
    );
    const gapX = nearest.x - me.vx / DRAG - me.x;
    const gapY = nearest.y - me.vy / DRAG - me.y;
    await press("ArrowRight", gapX > 5);
    await press("ArrowLeft", gapX < -5);
    await press("ArrowDown", gapY > 5);
    await press("ArrowUp", gapY < -5);
    await page.waitForTimeout(30);
  }
  for (const key of [...held]) {
    await press(key, false);
  }
}

async function waitUntilStill(page) {
  await expect
    .poll(async () => {
      const me = await ownPlayer(page);
      return [me.vx, me.vy];
    }, { timeout: STEP_TIMEOUT_MS })
    .toEqual([0, 0]);
}

test("players move around shared_canvas_live with prediction and interpolation, collect a coin, coast after leaving, and finish the round", { tag: "@both" }, async ({
  browser
}) => {
  const experiment = startExperiment(path.resolve("demos/experiments/shared_canvas_live"));
  const contexts = [await browser.newContext(), await browser.newContext()];
  // While this is set, the first player's moves are held back from the
  // server, to be sent later.
  let holdMoves = false;
  const heldMoves = [];
  await contexts[0].routeWebSocket(/\/experiment-socket/, (route) => {
    const server = route.connectToServer();
    route.onMessage((message) => {
      if (holdMoves && String(message).includes('"move"')) {
        heldMoves.push(() => server.send(message));
      } else {
        server.send(message);
      }
    });
  });

  try {
    const participants = await startParticipantsTogether(
      contexts,
      await experiment.urlPromise,
      "shared_canvas_live"
    );
    await Promise.all(
      participants.map(async (participant) => {
        await expect(participant.locator("#canvas-status")).toHaveText("Collect the coins!", {
          timeout: STEP_TIMEOUT_MS
        });
      })
    );
    const roundStart = Date.now();
    const [first, second] = participants;
    // The page moves on by itself when the game ends, so its Next button is hidden.
    await expect(first.locator("#next-button")).toBeHidden();

    // With its moves held back, the first player's piece still moves on
    // their own page, but not yet on the other player's.
    const start = await ownPlayer(first);
    const key = towardCenter(start);
    holdMoves = true;
    await first.keyboard.down(key);
    await expect
      .poll(async () => Math.abs((await ownPlayer(first)).x - start.x), {
        intervals: [20],
        timeout: STEP_TIMEOUT_MS
      })
      .toBeGreaterThan(10);
    expect(heldMoves.length).toBeGreaterThan(0);
    expect((await drawnPlayer(second, start.id)).x).toBe(start.x);
    holdMoves = false;
    heldMoves.splice(0).forEach((send) => send());

    // The other player's page draws the first player in many small steps
    // between the game's 20 ticks a second. Without interpolation, 30 frames
    // at 60 a second would show about 10 positions. A tick view that arrives
    // late holds the drawing for a few frames, so the check leaves room for
    // one.
    await expect
      .poll(async () => Math.abs((await drawnPlayer(second, start.id)).x - start.x), {
        timeout: STEP_TIMEOUT_MS
      })
      .toBeGreaterThan(0);
    const drawn = await second.evaluate(
      (id) =>
        new Promise((resolve) => {
          const xs = [];
          const frame = () => {
            xs.push(psynet.liveSession.interpolatedView().players[id].x);
            if (xs.length < 30) {
              requestAnimationFrame(frame);
            } else {
              resolve(xs);
            }
          };
          requestAnimationFrame(frame);
        }),
      start.id
    );
    expect(new Set(drawn).size).toBeGreaterThan(15);

    // Once the key is released, the player slows down and stops, and the
    // other page draws them where they stopped.
    await first.keyboard.up(key);
    const moving = await ownPlayer(first);
    expect(Math.hypot(moving.vx, moving.vy)).toBeGreaterThan(50);
    await waitUntilStill(first);
    const stopped = await ownPlayer(first);
    expect(Math.abs(stopped.x - moving.x)).toBeGreaterThan(5);
    // The game accepts at most SAVED_MOVEMENT of moves that arrive at once,
    // so the held moves may have counted for less than the page predicted.
    // The page is then put right by the game's views, so its own position is
    // read again each time.
    await expect
      .poll(async () => {
        const seen = await drawnPlayer(second, start.id);
        const own = await ownPlayer(first);
        return [seen.x - own.x, seen.y - own.y, own.vx, own.vy];
      }, { timeout: STEP_TIMEOUT_MS })
      .toEqual([0, 0, 0, 0]);

    await checkPredictions(first);
    await collectACoin(first);
    await waitUntilStill(first);
    const collector = await ownPlayer(first);
    expect(collector.coins).toBeGreaterThan(0);
    await expect(first.locator("#canvas-scores")).toContainText(`You: ${collector.coins}`);
    await expect(second.locator("#canvas-scores")).toContainText(
      `Player ${collector.number}: ${collector.coins}`,
      { timeout: STEP_TIMEOUT_MS }
    );

    // The views that arrived while the first player went for the coin and
    // coasted never moved their piece from where the page predicted it.
    const check = await first.evaluate(() => window.predictionCheck);
    expect(check.checks).toBeGreaterThan(0);
    expect(check.largestError).toBe(0);

    // A reloaded page draws the player where they are.
    await first.reload();
    await expect(first.locator("#canvas-status")).toHaveText("Collect the coins!", {
      timeout: STEP_TIMEOUT_MS
    });
    const reloaded = await ownPlayer(first);
    expect([reloaded.x, reloaded.y, reloaded.coins]).toEqual([
      collector.x,
      collector.y,
      collector.coins
    ]);

    // A player whose page closes while they're moving coasts to a stop.
    const leaver = await ownPlayer(second);
    const leaverKey = towardCenter(leaver);
    await second.keyboard.down(leaverKey);
    await expect
      .poll(async () => Math.abs((await ownPlayer(second)).vx), { timeout: STEP_TIMEOUT_MS })
      .toBeGreaterThan(100);
    await second.close();
    await expect(first.locator("#psynet-player-away-notice")).toHaveText(
      "Another player has left the game.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await expect
      .poll(async () => {
        const seen = await drawnPlayer(first, leaver.id);
        return [seen.vx, seen.vy];
      }, { timeout: STEP_TIMEOUT_MS })
      .toEqual([0, 0]);
    expect(Date.now() - roundStart, "the steps ran past the end of the round").toBeLessThan(
      ROUND_SECONDS * 1000
    );


    // The page moves on by itself once the round is over and the result is
    // saved.
    await expect(first.locator("#main-body")).toContainText(
      `You collected ${collector.coins} ${collector.coins === 1 ? "coin" : "coins"}`,
      { timeout: STEP_TIMEOUT_MS }
    );
    await assertNoBackendError(first);
  } finally {
    for (const context of contexts) {
      await context.close();
    }
    await stopExperiment(experiment.proc);
  }
});
