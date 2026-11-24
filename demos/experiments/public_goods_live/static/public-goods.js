function tokenRow(name, tokens, endowment, you, absent) {
  let row = document.createElement("div");
  row.className = `pg-row${you ? " pg-row-you" : ""}${absent ? " pg-row-absent" : ""}`;
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
  count.textContent = absent ? "Not here" : `${tokens} in the pot`;
  row.append(label, slots, count);
  return row;
}

export function activate({root, vars, psynet}) {
  let live = psynet.liveGame;
  let rules = vars.public_goods_rules;
  let status = root.querySelector("#pg-status");
  let timeLeft = root.querySelector("#pg-time-left");
  let slider = root.querySelector("#pg-tokens");
  let rows = root.querySelector("#pg-rows");
  let pot = root.querySelector("#pg-pot");
  let earn = root.querySelector("#pg-earn");
  let instructions = root.querySelector("#pg-instructions");
  let rejection = root.querySelector("#pg-rejection");

  live.enableWhilePlaying(slider);
  live.predict((predicted, type, message) => {
    if (type === "contribute") {
      predicted.contributions[live.player] = message.tokens;
    }
  });

  function render(view) {
    let contributions = view.contributions;
    let mine = contributions[live.player];
    if (document.activeElement !== slider) {
      slider.value = mine;
    }
    // Before the round starts, every player who isn't ready yet is a no-show.
    let noShows = live.started ? view.no_shows : [];
    rows.replaceChildren(
      ...contributions.map((tokens, player) =>
        tokenRow(
          // "You", or the player's pseudonym, as the group's other pages show them.
          live.players[player]?.label ?? `Player ${player + 1}`,
          tokens,
          rules.endowment,
          player === live.player,
          noShows.includes(player)
        )
      )
    );
    let total = contributions.reduce((a, b) => a + b, 0);
    let share = (rules.multiplier * total) / (contributions.length - noShows.length);
    pot.textContent = `Pot: ${total} tokens × ${rules.multiplier} = ${+(rules.multiplier * total).toFixed(2)}`;
    let shareText = +share.toFixed(2);
    let earned = +(rules.endowment - mine + share).toFixed(2);
    instructions.hidden = live.ended;
    earn.textContent = live.ended
      ? `Each player gets ${shareText} tokens from the pot, and you earn ${earned} tokens.`
      : `If the round ended now, each player would get ${shareText} tokens ` +
        `from the pot, and you would earn ${earned} tokens.`;
  }

  live.onTimeLeft((left) => {
    timeLeft.style.width = `${(left / live.duration) * 100}%`;
  });
  live.onChange(render);
  // The rows show what's happening, so the status says nothing while the
  // round is played.
  live.showStatus(status, null, { ended: "Time's up." });
  live.showRejections(rejection);
  slider.addEventListener("input", () => {
    live.send("contribute", {tokens: Number(slider.value)});
  });
}
