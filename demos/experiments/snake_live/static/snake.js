const KEYS = {
  arrowup: "up",
  arrowdown: "down",
  arrowleft: "left",
  arrowright: "right",
  w: "up",
  s: "down",
  a: "left",
  d: "right",
};

function drawSquare(context, rules, square, color, inset) {
  let size = rules.square;
  context.fillStyle = color;
  context.fillRect(
    square[0] * size + inset,
    square[1] * size + inset,
    size - 2 * inset,
    size - 2 * inset
  );
}

function draw(context, rules, view) {
  let size = rules.size * rules.square;
  context.fillStyle = "#f8fbff";
  context.fillRect(0, 0, size, size);
  for (let square of view.food) {
    drawSquare(context, rules, square, "#f4c430", 4);
  }
  for (let [id, player] of Object.entries(view.players)) {
    let color = rules.colors[player.number - 1];
    for (let square of player.body) {
      drawSquare(context, rules, square, color, 1);
    }
    let head = player.body[0];
    if (head) {
      // The heads are darker, and the player's own has a white center.
      drawSquare(context, rules, head, "#111827", 1);
      drawSquare(context, rules, head, id === view.me ? "#ffffff" : color, 5);
    }
  }
}

export function activate({ root, vars, psynet }) {
  let status = root.querySelector("#snake-status");
  let live = psynet.liveSession;
  if (!live.hasSession) {
    return;
  }
  let rules = vars.snake_rules;
  let context = root.querySelector("#snake-board").getContext("2d");
  let timer = root.querySelector("#snake-timer");
  let scores = root.querySelector("#snake-scores");
  let shownScores = null;
  let latest = null;

  psynet.addPageEventListener(window, "keydown", (event) => {
    // Leave shortcuts such as Cmd+S alone.
    if (event.metaKey || event.ctrlKey || event.altKey) {
      return;
    }
    // Chrome's autofill sends keydown events without a key.
    let direction = KEYS[(event.key || "").toLowerCase()];
    if (direction) {
      event.preventDefault();
      // The page doesn't show the reasons the game rejects a turn, such as a
      // turn back into the snake's neck: the key press just has no effect.
      let crashed = latest !== null && latest.players[latest.me].body.length === 0;
      if (!event.repeat && live.started && !live.ended && !crashed) {
        live.send("turn", { direction: direction });
      }
    }
  });

  function showScores(view) {
    let players = Object.entries(view.players).sort(([, a], [, b]) => a.number - b.number);
    let key = players.map(([, player]) => [player.food, player.crashes]).join();
    if (key === shownScores) {
      return;
    }
    shownScores = key;
    scores.replaceChildren(
      ...players.map(([id, player]) => {
        let item = document.createElement("li");
        let swatch = document.createElement("span");
        swatch.className = "snake-swatch";
        swatch.style.background = rules.colors[player.number - 1];
        let name = id === view.me ? "You" : `Player ${player.number}`;
        let crashes = player.crashes === 1 ? "1 crash" : `${player.crashes} crashes`;
        item.append(swatch, `${name}: ${player.food} food, ${crashes}`);
        return item;
      })
    );
  }

  function showStatus(view) {
    let time = live.socket.sessionTime();
    let me = view.players[view.me];
    if (live.ended) {
      status.textContent = "The game is over.";
    } else if (!live.started) {
      status.textContent = "Waiting for the other players to open the game";
    } else if (me.back_at !== null && time !== null) {
      let seconds = Math.max(1, Math.ceil(me.back_at - time));
      status.textContent = `You crashed! Your snake will be back in ${seconds} s.`;
    } else {
      status.textContent = "Eat the food!";
    }
    if (view.ends_at !== null && time !== null) {
      timer.textContent = Math.ceil(Math.max(0, view.ends_at - time));
    }
  }

  // The game moves every snake on its ticks, and each tick's view shows the
  // whole board, so the page draws each view as it arrives.
  live.onView((view) => {
    if (view === null) {
      // The final view of a session that failed.
      status.textContent = "The game is over.";
      return;
    }
    latest = view;
    draw(context, rules, view);
    showScores(view);
    showStatus(view);
  });
}
