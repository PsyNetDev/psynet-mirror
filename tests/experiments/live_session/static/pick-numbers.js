export function activate({root, psynet}) {
  let status = root.querySelector("#game-status");
  if (!psynet.liveSession.hasSession) {
    return;
  }
  let pick = root.querySelector("#pick");
  psynet.liveSession.disableUntilStarted(pick);
  psynet.liveSession.onView((view) => {
    if (view === null) {
      return;
    }
    if (!psynet.liveSession.started) {
      status.textContent = "Waiting for your partner";
    } else {
      status.textContent = view.picked ? "Picked" : "Pick a number";
    }
  });
  psynet.liveSession.onRejected((number, reason) => {
    root.querySelector("#game-error").textContent = reason;
  });
  pick.addEventListener("click", () => {
    psynet.liveSession.send("pick", {
      number: Number(root.querySelector("#pick-number").value),
    });
  });
}
