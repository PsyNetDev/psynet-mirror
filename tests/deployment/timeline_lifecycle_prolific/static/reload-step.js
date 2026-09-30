// Page module for lt_reload. Next stays hidden until the participant has
// reloaded this page once, so the response comes from the rebuilt page.
const RELOAD_REQUEST_KEY = "lifecycleReloadRequest";

export function activate({ root, vars }) {
  const nextButton = document.getElementById("next-button");
  const reloadButton = root.querySelector("#lifecycle-reload");
  const done = root.querySelector("#lifecycle-reload-done");
  const documentId = window.lifecycleDocument.id;

  let request;
  try {
    request = JSON.parse(sessionStorage.getItem(RELOAD_REQUEST_KEY));
  } catch (error) {
    // Without sessionStorage a reload cannot be confirmed; let them continue.
    reloadButton.style.display = "none";
    return;
  }

  if (request && request.step === vars.lifecycle_step && request.documentId !== documentId) {
    reloadButton.style.display = "none";
    done.style.display = "";
    return;
  }

  nextButton.style.display = "none";
  const onClick = () => {
    sessionStorage.setItem(
      RELOAD_REQUEST_KEY,
      JSON.stringify({ step: vars.lifecycle_step, documentId }),
    );
    window.location.reload();
  };
  reloadButton.addEventListener("click", onClick);
  return function cleanup() {
    reloadButton.removeEventListener("click", onClick);
  };
}
