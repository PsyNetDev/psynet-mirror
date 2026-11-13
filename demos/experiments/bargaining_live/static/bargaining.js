function drawCoins(container, endowment, keep, keeperIsYou) {
  // One coin per unit: the keeper's share first, then the other player's.
  container.replaceChildren();
  for (let coin = 0; coin < endowment; coin++) {
    let element = document.createElement("span");
    let keepers = coin < keep;
    let yours = keepers === keeperIsYou;
    element.className = `bargain-coin ${yours ? "bargain-coin-you" : "bargain-coin-partner"}`;
    element.textContent = "¢";
    container.append(element);
  }
}

export function activate({root, psynet}) {
  let live = psynet.liveSession;
  if (!live.hasSession) {
    root.querySelector("#bargain-game").hidden = true;
    return;
  }
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

  live.disableUntilStarted(keep, propose, accept);
  live.predict((predicted, type, message) => {
    if (type === "propose") {
      predicted.mine = message.keep;
    }
  });

  function render() {
    view = live.predictedView();
    if (view === null) {
      status.textContent = "The game is over.";
      return;
    }
    let playing = live.started && !live.ended;
    if (view.deal !== null) {
      status.textContent = "You made a deal.";
    } else if (live.ended) {
      status.textContent = "Time's up: no deal.";
    } else if (!live.started) {
      status.textContent = "Waiting for your partner to open the game";
    } else {
      status.textContent = "Propose a split, or accept your partner's.";
    }
    drawCoins(mineCoins, view.endowment, Number(keep.value), true);
    keepValue.textContent = keep.value;
    mine.textContent =
      view.mine === null
        ? "You haven't proposed anything yet."
        : `Your partner sees: you keep ${view.mine}, they get ${view.endowment - view.mine}.`;
    if (view.theirs === null) {
      theirsCoins.replaceChildren();
      theirs.textContent = "Your partner hasn't proposed anything yet.";
    } else {
      drawCoins(theirsCoins, view.endowment, view.theirs, false);
      theirs.textContent = `They keep ${view.theirs}, you get ${view.endowment - view.theirs}.`;
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
      deal.textContent = `Deal! You get ${view.deal} coins and your partner gets ${view.endowment - view.deal}.`;
    }
    propose.disabled = !playing;
    keep.disabled = !playing;
    accept.disabled = !playing || view.theirs === null;
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
  keep.addEventListener("input", render);
  propose.addEventListener("click", () => {
    rejection.textContent = "";
    live.send("propose", {keep: Number(keep.value)});
    render();
  });
  accept.addEventListener("click", () => {
    rejection.textContent = "";
    live.send("accept", {keep: view.theirs});
  });
  return () => clearInterval(timer);
}
