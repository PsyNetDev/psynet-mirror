// The page sends a move about 30 times a second while its player is moving.
const SECONDS_PER_MOVE = 1 / 30;

const KEYS = {
  arrowleft: [-1, 0],
  arrowright: [1, 0],
  arrowup: [0, -1],
  arrowdown: [0, 1],
  a: [-1, 0],
  d: [1, 0],
  w: [0, -1],
  s: [0, 1],
};

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

function passesNear(rules, x1, y1, x2, y2, coin) {
  let sx = x2 - x1;
  let sy = y2 - y1;
  let length = sx * sx + sy * sy;
  let along = length === 0 ? 0 : ((coin.x - x1) * sx + (coin.y - y1) * sy) / length;
  along = clamp(along, 0, 1);
  let px = x1 + along * sx - coin.x;
  let py = y1 + along * sy - coin.y;
  return px * px + py * py <= rules.reach * rules.reach;
}

function isMoving(player) {
  return player.vx !== 0 || player.vy !== 0;
}

// Does to a view what experiment.py's advance does to the state, in the same
// order, so the prediction lands where the game does. rules is experiment.py's
// RULES.
export function advance(rules, view, you, dx, dy, seconds) {
  let player = view.players[you];
  let low = rules.player_radius;
  let high = rules.size - rules.player_radius;
  let scale = dx !== 0 && dy !== 0 ? rules.diagonal : 1;
  let ax = rules.acceleration * dx * scale;
  let ay = rules.acceleration * dy * scale;
  let elapsed = 0;
  while (elapsed < seconds) {
    let dt = Math.min(rules.step, seconds - elapsed);
    elapsed += dt;
    let x = player.x;
    let y = player.y;
    player.vx += (ax - rules.drag * player.vx) * dt;
    player.vy += (ay - rules.drag * player.vy) * dt;
    player.x += player.vx * dt;
    player.y += player.vy * dt;
    if (!(low <= player.x && player.x <= high)) {
      player.x = clamp(player.x, low, high);
      player.vx = 0;
    }
    if (!(low <= player.y && player.y <= high)) {
      player.y = clamp(player.y, low, high);
      player.vy = 0;
    }
    let speedSquared = player.vx * player.vx + player.vy * player.vy;
    if (dx === 0 && dy === 0 && speedSquared < rules.stop_speed * rules.stop_speed) {
      player.vx = player.vy = 0;
    }
    view.coins = view.coins.filter((coin) => {
      if (passesNear(rules, x, y, player.x, player.y, coin)) {
        player.coins += 1;
        return false;
      }
      return true;
    });
  }
}

// Places each player between two tick views.
function interpolate(a, b, fraction) {
  let players = b.players.map((to, player) => {
    let from = a.players[player];
    return {
      ...to,
      x: from.x + (to.x - from.x) * fraction,
      y: from.y + (to.y - from.y) * fraction,
    };
  });
  return { ...b, players: players };
}

function drawCircle(context, x, y, radius, fill, stroke, lineWidth) {
  context.beginPath();
  context.arc(x, y, radius, 0, Math.PI * 2);
  context.fillStyle = fill;
  context.fill();
  context.lineWidth = lineWidth;
  context.strokeStyle = stroke;
  context.stroke();
}

// Draws the coins and the player's own piece from mine, the player's
// predicted view, and the other players from others, the interpolated view,
// which is a little behind it.
function draw(context, rules, you, mine, others) {
  context.fillStyle = "#f8fbff";
  context.fillRect(0, 0, rules.size, rules.size);
  context.strokeStyle = "#d8e2ef";
  context.lineWidth = 1;
  for (let line = 80; line < rules.size; line += 80) {
    context.beginPath();
    context.moveTo(line, 0);
    context.lineTo(line, rules.size);
    context.moveTo(0, line);
    context.lineTo(rules.size, line);
    context.stroke();
  }
  for (let coin of mine.coins) {
    drawCircle(context, coin.x, coin.y, rules.coin_radius, "#f4c430", "#a27400", 2);
  }
  others.players.forEach((player, number) => {
    if (number !== you) {
      let color = rules.colors[number];
      drawCircle(context, player.x, player.y, rules.player_radius, color, "#ffffff", 2);
    }
  });
  let me = mine.players[you];
  drawCircle(context, me.x, me.y, rules.player_radius, rules.colors[you], "#111827", 4);
}

export function activate({ root, vars, psynet }) {
  let status = root.querySelector("#canvas-status");
  let live = psynet.liveGame;
  if (!live.hasGame) {
    // Without a game there's nothing to animate, so the page doesn't start
    // its drawing loop.
    return;
  }
  let rules = vars.canvas_rules;
  let context = root.querySelector("#canvas").getContext("2d");
  let timer = root.querySelector("#canvas-timer");
  let scores = root.querySelector("#canvas-scores");
  let shownScores = null;
  let held = new Set();
  let direction = [0, 0];
  // Seconds the player has moved since the page last sent a move.
  let pending = 0;
  // The view the page last drew.
  let shown = null;
  let lastFrame = null;
  let running = true;

  live.predict((view, type, message) => {
    if (type === "move") {
      advance(rules, view, live.player, message.dx, message.dy, message.seconds);
    }
  });
  live.interpolate(interpolate);

  psynet.addPageEventListener(window, "keydown", (event) => {
    // Leave shortcuts such as Cmd+S alone. Their keyup may never arrive.
    if (event.metaKey || event.ctrlKey || event.altKey) {
      return;
    }
    // Chrome's autofill sends keydown events without a key.
    let key = (event.key || "").toLowerCase();
    if (KEYS[key]) {
      held.add(key);
      event.preventDefault();
    }
  });
  psynet.addPageEventListener(window, "keyup", (event) => {
    held.delete((event.key || "").toLowerCase());
  });
  psynet.addPageEventListener(window, "blur", () => held.clear());

  function heldDirection() {
    let dx = 0;
    let dy = 0;
    for (let key of held) {
      dx += KEYS[key][0];
      dy += KEYS[key][1];
    }
    return [clamp(dx, -1, 1), clamp(dy, -1, 1)];
  }

  function sendMove() {
    if (pending > 0) {
      live.send("move", { dx: direction[0], dy: direction[1], seconds: pending });
    }
    pending = 0;
  }

  // Counts the time the player moves, and sends it as a move about 30 times
  // a second, and once more when they come to rest.
  function move(elapsed) {
    let next = heldDirection();
    if (next[0] !== direction[0] || next[1] !== direction[1]) {
      sendMove();
      direction = next;
    }
    if (!live.playing || shown === null) {
      pending = 0;
      return;
    }
    let keysHeld = direction[0] !== 0 || direction[1] !== 0;
    if (keysHeld || isMoving(shown.players[live.player])) {
      pending = Math.min(rules.longest_move, pending + elapsed);
      if (pending >= SECONDS_PER_MOVE) {
        sendMove();
      }
    } else {
      // The movement that brought the player to rest.
      sendMove();
    }
  }

  // The predicted view, plus the movement the page hasn't sent yet.
  function shownView() {
    let view = live.predictedView();
    if (view === null || pending === 0) {
      return view;
    }
    view = structuredClone(view);
    advance(rules, view, live.player, direction[0], direction[1], pending);
    return view;
  }

  function showScores(view) {
    let key = view.players.map((player) => player.coins).join();
    if (key === shownScores) {
      return;
    }
    shownScores = key;
    scores.replaceChildren(
      ...view.players.map((player, number) => {
        let item = document.createElement("li");
        let swatch = document.createElement("span");
        swatch.className = "canvas-swatch";
        swatch.style.background = rules.colors[number];
        let name = number === live.player ? "You" : `Player ${number + 1}`;
        item.append(swatch, `${name}: ${player.coins}`);
        return item;
      })
    );
  }

  // The page draws about 60 times a second, so it changes text only when the
  // text has changed.
  function setText(element, text) {
    if (element.textContent !== text) {
      element.textContent = text;
    }
  }

  live.showStatus(status, () => "Collect the coins!");

  live.onTimeLeft((left) => setText(timer, String(Math.ceil(left))));

  function frame(now) {
    if (!running) {
      return;
    }
    let elapsed = lastFrame === null ? 0 : (now - lastFrame) / 1000;
    lastFrame = now;
    move(elapsed);
    shown = shownView();
    // The view is null before the first view.
    if (shown !== null) {
      draw(context, rules, live.player, shown, live.interpolatedView() || shown);
      showScores(shown);
    }
    if (live.ended) {
      running = false;
    } else {
      requestAnimationFrame(frame);
    }
  }
  requestAnimationFrame(frame);

  return () => {
    running = false;
  };
}
