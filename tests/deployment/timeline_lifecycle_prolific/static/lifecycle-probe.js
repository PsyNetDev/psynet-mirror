// Page module attached to every probed page. It records how the page was
// reached and what it inherited from earlier pages, and submits that record
// as ``metadata.lifecycle`` on the page's response. analyze.py checks the
// records against the transitions the timeline is supposed to produce.

// Module scripts are evaluated once per document, so this changes only when
// the browser loads a new document.
const moduleInstance = Math.random().toString(36).slice(2, 10);

// sessionStorage survives full reloads, so transitions of both kinds are timed.
const LEFT_PAGE_KEY = "lifecycleLeftPage";

function readLeftPage() {
  try {
    return JSON.parse(sessionStorage.getItem(LEFT_PAGE_KEY));
  } catch (error) {
    return null;
  }
}

function writeLeftPage(step) {
  try {
    sessionStorage.setItem(LEFT_PAGE_KEY, JSON.stringify({ step, at: Date.now() }));
  } catch (error) {
    // Without sessionStorage the next page reports no transition time.
  }
}

function countPlayingMediaElements() {
  return Array.from(document.querySelectorAll("audio, video")).filter(
    (element) => !element.paused && !element.ended,
  ).length;
}

export function activate({ root, vars, psynet }) {
  const doc = window.lifecycleDocument;
  const pageUuid = vars.pageUuid;
  doc.activationsByPage[pageUuid] = (doc.activationsByPage[pageUuid] || 0) + 1;

  const leftPage = readLeftPage();

  // lifecycle-page.css colours this element; only the page that links the
  // stylesheet should see that colour.
  const sentinel = document.createElement("span");
  sentinel.className = "lifecycle-sentinel";
  sentinel.hidden = true;
  root.appendChild(sentinel);

  // A stale timer from an earlier page would submit this page without any
  // participant input.
  let userInput = false;
  const onInput = () => {
    userInput = true;
  };
  document.addEventListener("pointerdown", onInput, true);
  document.addEventListener("keydown", onInput, true);

  const atActivation = {
    step: vars.lifecycle_step,
    document_id: doc.id,
    document_load_index: doc.loadIndex,
    navigation_type: doc.navigationType,
    module_instance: moduleInstance,
    transition_from: leftPage ? leftPage.step : null,
    transition_ms: leftPage ? Date.now() - leftPage.at : null,
    page_style_applied: getComputedStyle(sentinel).color === "rgb(1, 2, 3)",
    component_token: vars.lifecycle_component_token ?? null,
    sounds_at_activation: psynet.media.sounds.length,
    media_elements_playing_at_activation: countPlayingMediaElements(),
  };

  // PsyNet reads staged metadata when it serializes the response, so this
  // getter runs at submission, after the page has settled.
  Object.defineProperty(psynet.response.staged.metadata, "lifecycle", {
    configurable: true,
    enumerable: true,
    get() {
      writeLeftPage(vars.lifecycle_step);
      const layout = window.psynetLayout;
      return {
        ...atActivation,
        dependency_executions: doc.dependencyExecutions,
        activations_of_this_page: doc.activationsByPage[pageUuid],
        user_input_before_submit: userInput,
        sounds_at_submit: psynet.media.sounds.length,
        layout_violations: layout
          ? layout.collectViolations().map((violation) => violation.check)
          : null,
        viewport: [window.innerWidth, window.innerHeight],
        touch: navigator.maxTouchPoints > 0,
      };
    },
  });

  return function cleanup() {
    document.removeEventListener("pointerdown", onInput, true);
    document.removeEventListener("keydown", onInput, true);
    sentinel.remove();
  };
}
