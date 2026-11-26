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

function drawSquare(context, board, square, color, inset) {
  let size = board.square;
  context.fillStyle = color;
  context.fillRect(
    square[0] * size + inset,
    square[1] * size + inset,
    size - 2 * inset,
    size - 2 * inset
  );
}

function draw(context, board, view, me) {
  let size = board.size * board.square;
  context.fillStyle = "#f8fbff";
  context.fillRect(0, 0, size, size);
  for (let square of view.food) {
    drawSquare(context, board, square, "#f4c430", 4);
  }
  view.snakes.forEach((snake, player) => {
    let color = board.colors[player];
    for (let square of snake.body) {
      drawSquare(context, board, square, color, 1);
    }
    let head = snake.body[0];
    if (head) {
      // The heads are darker, and the player's own has a white center.
      drawSquare(context, board, head, "#111827", 1);
      drawSquare(context, board, head, player === me ? "#ffffff" : color, 5);
    }
  });
}

export function activate({ root, config, psynet }) {
  let status = root.querySelector("#snake-status");
  let live = psynet.liveGame;
  let board = config.snake_board;
  let context = root.querySelector("#snake-board").getContext("2d");
  let timer = root.querySelector("#snake-timer");
  let scores = root.querySelector("#snake-scores");
  let shownScores = null;

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
      let view = live.predictedView();
      let crashed = view !== null && view.snakes[live.player].body.length === 0;
      if (!event.repeat && live.playing && !crashed) {
        live.send("turn", { direction: direction });
      }
    }
  });

  function showScores(view) {
    let key = view.snakes.map((snake) => [snake.food, snake.crashes]).join();
    if (key === shownScores) {
      return;
    }
    shownScores = key;
    scores.replaceChildren(
      ...view.snakes.map((snake, player) => {
        let item = document.createElement("li");
        let swatch = document.createElement("span");
        swatch.className = "snake-swatch";
        swatch.style.background = board.colors[player];
        // "You", or the player's pseudonym, as the group's other pages show them.
        let name = live.players[player]?.label ?? `Player ${player + 1}`;
        let crashes = snake.crashes === 1 ? "1 crash" : `${snake.crashes} crashes`;
        item.append(swatch, `${name}: ${snake.food} food, ${crashes}`);
        return item;
      })
    );
  }

  live.showStatus(status, (view) => {
    let time = live.gameTime();
    let me = view.snakes[live.player];
    if (me.back_at !== null && time !== null) {
      let seconds = Math.max(1, Math.ceil(me.back_at - time));
      return `You crashed! Your snake will be back in ${seconds} s.`;
    }
    return "Eat the food!";
  });

  live.onTimeLeft((left) => {
    timer.textContent = Math.ceil(left);
  });

  // The game moves every snake on its ticks, and each tick's view shows the
  // whole board, so the page draws each view as it arrives.
  live.onChange((view) => {
    draw(context, board, view, live.player);
    showScores(view);
  });
}
