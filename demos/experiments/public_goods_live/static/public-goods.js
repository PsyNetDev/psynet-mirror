export function activate({root, psynet}) {
  if (!psynet.liveSession.hasSession) {
    root.querySelector("#pg-game").hidden = true;
    return;
  }
  let status = root.querySelector("#pg-status");
  let clock = root.querySelector("#pg-clock");
  let slider = root.querySelector("#pg-tokens");
  let mine = root.querySelector("#pg-mine");
  let others = root.querySelector("#pg-others");
  let pot = root.querySelector("#pg-pot");
  let rejection = root.querySelector("#pg-rejection");
  let view = null;

  psynet.liveSession.disableUntilStarted(slider);
  psynet.liveSession.predict((predicted, type, message) => {
    if (type === "contribute") {
      predicted.mine = message.tokens;
    }
  });

  function render() {
    view = psynet.liveSession.predictedView();
    if (view === null) {
      status.textContent = "The round is over.";
      return;
    }
    if (psynet.liveSession.ended) {
      status.textContent = "Time's up.";
    } else if (!psynet.liveSession.started) {
      status.textContent = "Waiting for the other players to open the game";
    } else {
      status.textContent = "";
    }
    if (document.activeElement !== slider) {
      slider.value = view.mine;
    }
    mine.textContent = ` You put in ${view.mine} tokens.`;
    others.textContent = `The others put in: ${view.others.join(", ")} tokens.`;
    let total = view.mine + view.others.reduce((a, b) => a + b, 0);
    pot.textContent = `The pot so far: ${total} tokens.`;
    slider.disabled = !psynet.liveSession.started || psynet.liveSession.ended;
  }

  function tick() {
    if (view && view.ends_at !== null && !psynet.liveSession.ended) {
      let left = view.ends_at - psynet.liveSession.socket.sessionTime();
      clock.textContent = `${Math.max(0, Math.ceil(left))} s left`;
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
  slider.addEventListener("input", () => {
    rejection.textContent = "";
    psynet.liveSession.send("contribute", {tokens: Number(slider.value)});
    render();
  });
  return () => clearInterval(timer);
}
