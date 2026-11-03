export function activate({root, psynet}) {
  let status = root.querySelector("#game-status");
  if (!psynet.liveSession.hasSession) {
    status.textContent = "Your group couldn't start the game.";
    return;
  }
  psynet.websocket.onConnect(() => {
    root.querySelector("#page-socket-status").textContent = "Connected";
  });
  psynet.liveSession.onView((view) => {
    status.textContent = view.picked ? "Picked" : "Pick a number";
  });
  psynet.liveSession.onRejected((number, reason) => {
    root.querySelector("#game-error").textContent = reason;
  });
  root.querySelector("#pick").addEventListener("click", () => {
    psynet.liveSession.send("pick", {
      number: Number(root.querySelector("#pick-number").value),
    });
  });
}
