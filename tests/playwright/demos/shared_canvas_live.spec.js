const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  checkLayoutAndScreenshot,
  startExperiment,
  startParticipantsTogether,
  stopExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

const SIZE = 640;
// The game seconds the leaving player's check needs: AWAY_DELAY_MS in
// live-game.js, the game's COAST_AFTER and time for the views to arrive.
const SECONDS_TO_LEAVE = 12;
const DRAG = 4;

// The player's own piece as the page predicts it.
function ownPlayer(page) {
  return page.evaluate(() => {
    const view = psynet.liveGame.predictedView();
    return { id: view.psynet.you, ...view.players[view.psynet.you] };
  });
}

// Another player's piece as the page draws it, or null before the page has
// tick views to draw from, as just after it loads.
function drawnPlayer(page, id) {
  return page.evaluate((id) => psynet.liveGame.interpolatedView()?.players[id] ?? null, id);
}

function towardCenter(player) {
  return player.x < SIZE / 2 ? "ArrowRight" : "ArrowLeft";
}

// Records the x of each player in every view the page receives, so that a
// drawn position can be told apart from one the game sent.
function recordViewPositions(page) {
  return page.evaluate(() => {
    window.viewXs = {};
    psynet.liveGame.onReceive((view) => {
      view.players.forEach((player, id) => {
        (window.viewXs[id] ??= new Set()).add(player.x);
      });
    });
  });
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
      const view = psynet.liveGame.predictedView();
      return view && view.players[view.psynet.you];
    };
    const record = () => {
      before = own();
      requestAnimationFrame(record);
    };
    requestAnimationFrame(record);
    psynet.liveGame.onReceive(() => {
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
      const view = psynet.liveGame.predictedView();
      return { me: view.players[view.psynet.you], coins: view.coins };
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
  // The game ticks, so it runs on gunicorn, as a deployed experiment does.
  const experiment = startExperiment(path.resolve("demos/experiments/shared_canvas_live"), { legacy: true });
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
    const [first, second] = participants;
    await recordViewPositions(second);
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

    // The other player's page draws the first player between the game's
    // tick views, at positions no view had, rather than jumping from one to
    // the next. The frames are counted for at most a second, so the player
    // is still well away from the wall, however slowly frames come. A tick
    // view that arrives late holds the drawing at its position for a few
    // frames, and under load few frames come at all, so one frame between
    // tick positions is enough to show the page interpolates.
    await expect
      .poll(async () => Math.abs((await drawnPlayer(second, start.id)).x - start.x), {
        intervals: [20],
        timeout: STEP_TIMEOUT_MS
      })
      .toBeGreaterThan(0);
    const drawn = await second.evaluate(
      (id) =>
        new Promise((resolve) => {
          const counts = { frames: 0, between: 0 };
          const end = performance.now() + 1000;
          const frame = () => {
            const x = psynet.liveGame.interpolatedView().players[id].x;
            counts.frames += 1;
            counts.between += window.viewXs[id].has(x) ? 0 : 1;
            if (counts.frames < 30 && performance.now() < end) {
              requestAnimationFrame(frame);
            } else {
              resolve(counts);
            }
          };
          requestAnimationFrame(frame);
        }),
      start.id
    );
    expect(drawn.frames).toBeGreaterThan(2);
    expect(drawn.between, JSON.stringify(drawn)).toBeGreaterThan(0);

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

    // A move is cut short if it would take the player past the game's clock.
    // Standing still for the game's SAVED_MOVEMENT, 0.5 seconds, and more,
    // saves up enough movement time that uneven delivery of the moves below
    // never does that, so the page's predictions should be exact.
    await first.waitForTimeout(1000);
    await checkPredictions(first);
    await collectACoin(first);
    await waitUntilStill(first);
    const collector = await ownPlayer(first);
    expect(collector.coins).toBeGreaterThan(0);
    await expect(first.locator("#canvas-scores")).toContainText(`You: ${collector.coins}`);
    // The other page shows the collector by their pseudonym.
    const label = await second.evaluate(
      (player) => psynet.liveGame.players[player].label,
      collector.id
    );
    expect(label).not.toBe("You");
    await expect(second.locator("#canvas-scores")).toContainText(
      `${label}: ${collector.coins}`,
      { timeout: STEP_TIMEOUT_MS }
    );
    await checkLayoutAndScreenshot(second, "shared_canvas_live_board");

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
    // This needs a few seconds of the round, which a slow machine may
    // already have used up; tests/isolated/test_shared_canvas_live.py
    // checks the coasting itself.
    const secondsLeft = await first.evaluate(() => psynet.liveGame.secondsLeft());
    if (secondsLeft < SECONDS_TO_LEAVE) {
      test.info().annotations.push({
        type: "skipped check",
        description: `Only ${secondsLeft} s of the round were left for the leaving player.`
      });
    } else {
      const leaver = await ownPlayer(second);
      await second.keyboard.down(towardCenter(leaver));
      // The game, and not only the leaver's own page, has them moving.
      await expect
        .poll(async () => Math.abs((await drawnPlayer(first, leaver.id))?.vx ?? 0), {
          timeout: STEP_TIMEOUT_MS
        })
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
    }


    // The page moves on by itself once the round is over and the result is
    // saved.
    await expect(first.locator("#main-body")).toContainText(
      `You collected ${collector.coins} ${collector.coins === 1 ? "coin" : "coins"}`,
      { timeout: STEP_TIMEOUT_MS }
    );
    await checkLayoutAndScreenshot(first, "shared_canvas_live_result");
    await assertNoBackendError(first);
  } finally {
    for (const context of contexts) {
      await context.close();
    }
    await stopExperiment(experiment.proc);
  }
});
