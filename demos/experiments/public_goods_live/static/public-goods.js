const NAMES = ["Player B", "Player C", "Player D"];

function tokenRow(name, tokens, endowment, you) {
  let row = document.createElement("div");
  row.className = `pg-row${you ? " pg-row-you" : ""}`;
  let label = document.createElement("span");
  label.className = "pg-name";
  label.textContent = name;
  let slots = document.createElement("span");
  slots.className = "pg-slots";
  for (let slot = 0; slot < endowment; slot++) {
    let token = document.createElement("span");
    token.className = `pg-token${slot < tokens ? " pg-token-in" : ""}`;
    slots.append(token);
  }
  let count = document.createElement("span");
  count.className = "pg-count";
  count.textContent = `${tokens} in the pot`;
  row.append(label, slots, count);
  return row;
}

export function activate({root, psynet}) {
  let live = psynet.liveSession;
  if (!live.hasSession) {
    root.querySelector("#pg-game").hidden = true;
    return;
  }
  let status = root.querySelector("#pg-status");
  let timeLeft = root.querySelector("#pg-time-left");
  let slider = root.querySelector("#pg-tokens");
  let rows = root.querySelector("#pg-rows");
  let pot = root.querySelector("#pg-pot");
  let earn = root.querySelector("#pg-earn");
  let rejection = root.querySelector("#pg-rejection");
  let view = null;

  live.disableUntilStarted(slider);
  live.predict((predicted, type, message) => {
    if (type === "contribute") {
      predicted.mine = message.tokens;
    }
  });

  function render() {
    view = live.predictedView();
    if (view === null) {
      status.textContent = "The round is over.";
      return;
    }
    if (live.ended) {
      status.textContent = "Time's up.";
    } else if (!live.started) {
      status.textContent = "Waiting for the other players to open the game";
    } else {
      status.textContent = "";
    }
    if (document.activeElement !== slider) {
      slider.value = view.mine;
    }
    rows.replaceChildren(
      tokenRow("You", view.mine, view.endowment, true),
      ...view.others.map((tokens, i) => tokenRow(NAMES[i], tokens, view.endowment, false))
    );
    let total = view.mine + view.others.reduce((a, b) => a + b, 0);
    let players = view.others.length + 1;
    let share = (view.multiplier * total) / players;
    pot.textContent = `Pot: ${total} tokens × ${view.multiplier} = ${+(view.multiplier * total).toFixed(2)}`;
    earn.textContent =
      `If the round ended now, each player would get ${+share.toFixed(2)} tokens ` +
      `from the pot, and you would earn ${+(view.endowment - view.mine + share).toFixed(2)} tokens.`;
    slider.disabled = !live.started || live.ended;
  }

  function tick() {
    if (view && view.ends_at !== null && !live.ended) {
      let left = view.ends_at - (live.socket.sessionTime() ?? 0);
      timeLeft.style.width = `${Math.max(0, Math.min(1, left / view.seconds)) * 100}%`;
    }
  }
  let timer = setInterval(tick, 250);

  live.onView(() => {
    render();
    tick();
  });
  live.onRejected((number, reason) => {
    rejection.textContent = reason;
  });
  slider.addEventListener("input", () => {
    rejection.textContent = "";
    live.send("contribute", {tokens: Number(slider.value)});
    render();
  });
  return () => clearInterval(timer);
}
