export function activate({root, psynet}) {
  let status = root.querySelector("#game-status");
  if (!psynet.liveGame.hasGame) {
    return;
  }
  let pick = root.querySelector("#pick");
  psynet.liveGame.enableWhilePlaying(pick);
  psynet.liveGame.onChange((view) => {
    if (view === null) {
      return;
    }
    if (!psynet.liveGame.started) {
      status.textContent = "Waiting for your partner";
    } else {
      status.textContent = view.picked ? "Picked" : "Pick a number";
    }
  });
  psynet.liveGame.onRejected((number, reason) => {
    root.querySelector("#game-error").textContent = reason;
  });
  pick.addEventListener("click", () => {
    psynet.liveGame.send("pick", {
      number: Number(root.querySelector("#pick-number").value),
    });
  });
}
