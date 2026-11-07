// Exercise the real UnityPage loader boundary without shipping a compiled game.
window.createUnityInstance = async function () {
  const button = document.createElement("button");
  button.id = "unity-test-action";
  let step;
  const update = contents => {
    step = contents.step;
    button.textContent = `Complete Unity step ${step}`;
    button.disabled = false;
  };
  update(psynet.page.contents);
  button.onclick = async () => {
    button.disabled = true;
    if (!await psynet.nextPage({step})) button.disabled = false;
  };
  document.querySelector("#unity-container").append(button);
  return {
    SendMessage(objectName, methodName, payload) { update(JSON.parse(payload).contents); },
    SetFullscreen() {},
  };
};
