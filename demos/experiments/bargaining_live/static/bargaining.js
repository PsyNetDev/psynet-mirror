export function activate({root, psynet}) {
  if (!psynet.liveSession.hasSession) {
    // PsyNet's notice says why, and the Next button moves on.
    root.querySelector("#bargain-game").hidden = true;
    return;
  }
  let status = root.querySelector("#bargain-status");
  let clock = root.querySelector("#bargain-clock");
  let keep = root.querySelector("#bargain-keep");
  let propose = root.querySelector("#bargain-propose");
  let accept = root.querySelector("#bargain-accept");
  let mine = root.querySelector("#bargain-mine");
  let theirs = root.querySelector("#bargain-theirs");
  let rejection = root.querySelector("#bargain-rejection");
  let view = null;

  psynet.liveSession.disableUntilStarted(keep, propose, accept);
  psynet.liveSession.predict((predicted, type, message) => {
    if (type === "propose") {
      predicted.mine = message.keep;
    }
  });

  function render() {
    view = psynet.liveSession.predictedView();
    if (view === null) {
      status.textContent = "The game is over.";
      return;
    }
    let playing = psynet.liveSession.started && !psynet.liveSession.ended;
    if (view.deal !== null) {
      status.textContent = `Deal! You get ${view.deal} coins.`;
    } else if (psynet.liveSession.ended) {
      status.textContent = "Time's up: no deal.";
    } else if (!psynet.liveSession.started) {
      status.textContent = "Waiting for your partner to open the game";
    } else {
      status.textContent = "Propose a split, or accept your partner's.";
    }
    mine.textContent =
      view.mine === null ? "" : `You propose to keep ${view.mine} of ${view.endowment}.`;
    theirs.textContent =
      view.theirs === null
        ? "Your partner hasn't proposed anything yet."
        : `Your partner proposes to keep ${view.theirs}, giving you ${view.endowment - view.theirs}.`;
    propose.disabled = !playing;
    keep.disabled = !playing;
    accept.disabled = !playing || view.theirs === null;
  }

  function tick() {
    let socket = psynet.liveSession.socket;
    if (view && view.ends_at !== null && !psynet.liveSession.ended) {
      let left = Math.max(0, Math.ceil(view.ends_at - socket.sessionTime()));
      clock.textContent = `${left} s left`;
    } else {
      clock.textContent = "";
    }
  }
  let timer = setInterval(tick, 250);

  psynet.liveSession.onView(() => {
    render();
    tick();
  });
  psynet.liveSession.onRejected((number, reason) => {
    rejection.textContent = reason;
  });
  propose.addEventListener("click", () => {
    rejection.textContent = "";
    psynet.liveSession.send("propose", {keep: Number(keep.value)});
    render();
  });
  accept.addEventListener("click", () => {
    rejection.textContent = "";
    psynet.liveSession.send("accept", {keep: view.theirs});
  });
  return () => clearInterval(timer);
}
