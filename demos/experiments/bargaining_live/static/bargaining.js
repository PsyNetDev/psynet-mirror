function drawCoins(container, stake, keep, keeperIsYou) {
  // One coin per unit: the keeper's share first, then the other player's.
  container.replaceChildren();
  for (let coin = 0; coin < stake; coin++) {
    let element = document.createElement("span");
    let keepers = coin < keep;
    let yours = keepers === keeperIsYou;
    element.className = `bargain-coin ${yours ? "bargain-coin-you" : "bargain-coin-partner"}`;
    element.textContent = "¢";
    container.append(element);
  }
}

export function activate({root, psynet}) {
  let live = psynet.liveGame;
  let status = root.querySelector("#bargain-status");
  let timeLeft = root.querySelector("#bargain-time-left");
  let keep = root.querySelector("#bargain-keep");
  let keepValue = root.querySelector("#bargain-keep-value");
  let propose = root.querySelector("#bargain-propose");
  let accept = root.querySelector("#bargain-accept");
  let mineCoins = root.querySelector("#bargain-mine-coins");
  let theirsCoins = root.querySelector("#bargain-theirs-coins");
  let mine = root.querySelector("#bargain-mine");
  let theirs = root.querySelector("#bargain-theirs");
  let theirsCard = root.querySelector("#bargain-theirs-card");
  let deal = root.querySelector("#bargain-deal");
  let rejection = root.querySelector("#bargain-rejection");
  let view = null;
  let lastTheirs = null;

  // render enables Accept, once there's a proposal to accept.
  live.enableWhilePlaying(keep, propose);
  live.predict((predicted, type, message) => {
    if (type === "propose") {
      predicted.mine = message.keep;
    }
  });

  function render() {
    view = live.predictedView();
    if (view === null) {
      // Before the first view.
      return;
    }
    let playing = live.playing;
    drawCoins(mineCoins, view.stake, Number(keep.value), true);
    keepValue.textContent = keep.value;
    mine.textContent =
      view.mine === null
        ? "You haven't proposed anything yet."
        : `Your partner sees: you keep ${view.mine}, they get ${view.stake - view.mine}.`;
    if (view.theirs === null) {
      theirsCoins.replaceChildren();
      theirs.textContent = "Your partner hasn't proposed anything yet.";
    } else {
      drawCoins(theirsCoins, view.stake, view.theirs, false);
      theirs.textContent = `They keep ${view.theirs}, you get ${view.stake - view.theirs}.`;
      if (lastTheirs !== null && lastTheirs !== view.theirs) {
        // Restarts the highlight, so a player sees the proposal has changed.
        theirsCard.classList.remove("bargain-changed");
        void theirsCard.offsetWidth;
        theirsCard.classList.add("bargain-changed");
      }
    }
    lastTheirs = view.theirs;
    if (view.deal !== null) {
      deal.hidden = false;
      deal.textContent = `Deal! You get ${view.deal} coins and your partner gets ${view.stake - view.deal}.`;
    }
    accept.disabled = !playing || view.theirs === null;
  }

  live.onTimeLeft((left) => {
    timeLeft.style.width = `${(left / live.duration) * 100}%`;
  });
  live.onChange(render);
  live.showStatus(status, () => "Propose a split, or accept your partner's.", {
    ended: (final, reason) => {
      if (final.deal !== null) return "You made a deal.";
      if (final.no_show === "you") return "You didn't arrive in time.";
      if (final.no_show === "partner") return "Your partner didn't arrive.";
      if (reason === "players_left") {
        return final.psynet.away.includes(final.psynet.you)
          ? "You left the game: no deal."
          : "Your partner left the game: no deal.";
      }
      return "Time's up: no deal.";
    },
  });
  live.showRejections(rejection);
  keep.addEventListener("input", render);
  propose.addEventListener("click", () => {
    live.send("propose", {keep: Number(keep.value)});
  });
  accept.addEventListener("click", () => {
    live.send("accept", {keep: view.theirs});
  });
}
