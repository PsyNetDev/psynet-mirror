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

function drawFood(context, board, square) {
  let size = board.square;
  context.font = `${size - 2}px sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText("🍎", (square[0] + 0.5) * size, (square[1] + 0.5) * size + 1);
}

// Each snake is drawn in its player's pseudonym colour, as their sticker in
// the scores shows it. The game's own colours are used instead when two
// players share a colour, or when the page doesn't know a player's, as on
// an anonymous page.
function snakeColors(board, players, count) {
  let colors = Array.from({ length: count }, (_, player) => players[player]?.css_color);
  if (colors.every(Boolean) && new Set(colors).size === count) {
    return { colors, pseudonyms: true };
  }
  return { colors: board.colors.slice(0, count), pseudonyms: false };
}

function draw(context, board, view, me, colors) {
  let size = board.size * board.square;
  context.fillStyle = "#f8fbff";
  context.fillRect(0, 0, size, size);
  for (let square of view.food) {
    drawFood(context, board, square);
  }
  view.snakes.forEach((snake, player) => {
    let color = colors[player];
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

  function showScores(view, { colors, pseudonyms }) {
    let key = JSON.stringify([view.snakes.map((snake) => [snake.food, snake.crashes]), colors]);
    if (key === shownScores) {
      return;
    }
    shownScores = key;
    scores.replaceChildren(
      ...view.snakes.map((snake, player) => {
        let item = document.createElement("li");
        let shown = live.players[player];
        // The sticker shows the snake's colour, unless the snakes have the
        // game's own colours, which a swatch then shows.
        if (shown?.sticker_html) {
          let sticker = document.createElement("span");
          sticker.className = "snake-sticker";
          sticker.innerHTML = shown.sticker_html;
          item.append(sticker);
        }
        if (!pseudonyms) {
          let swatch = document.createElement("span");
          swatch.className = "snake-swatch";
          swatch.style.background = colors[player];
          item.append(swatch);
        }
        // The stickers show who's who, so only the player's own row says so
        // ("You"). The others' pseudonyms are there for screen readers.
        let name = shown?.label ?? `Player ${player + 1}`;
        let crashes = snake.crashes === 1 ? "1 crash" : `${snake.crashes} crashes`;
        let label = document.createElement("span");
        label.textContent = `${name}: `;
        if (!shown?.you) {
          label.className = "visually-hidden";
        }
        let text = document.createElement("span");
        text.append(label, `${snake.food} food, ${crashes}`);
        item.append(text);
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
    root.querySelector("#snake-game").style.setProperty("--snake-players", view.snakes.length);
    let colors = snakeColors(board, live.players, view.snakes.length);
    draw(context, board, view, live.player, colors.colors);
    showScores(view, colors);
  });
}
