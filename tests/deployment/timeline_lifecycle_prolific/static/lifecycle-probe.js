// Page module attached to every probed page. It records how the page was
// reached and what it inherited from earlier pages, and submits that record
// as ``metadata.lifecycle`` on the page's response. analyze.py checks the
// records against the transitions the timeline is supposed to produce.

// Module scripts are evaluated once per document, so this changes only when
// the browser loads a new document.
const moduleInstance = Math.random().toString(36).slice(2, 10);

function countPlayingMediaElements() {
  return Array.from(document.querySelectorAll("audio, video")).filter(
    (element) => !element.paused && !element.ended,
  ).length;
}

export function activate({ root, vars, psynet }) {
  const doc = window.lifecycleDocument;
  const pageUuid = vars.pageUuid;
  doc.activationsByPage[pageUuid] = (doc.activationsByPage[pageUuid] || 0) + 1;

  // lifecycle-page.css colours this element; only the page that links the
  // stylesheet should see that colour.
  const sentinel = document.createElement("span");
  sentinel.className = "lifecycle-sentinel";
  sentinel.hidden = true;
  root.appendChild(sentinel);

  const atActivation = {
    step: vars.lifecycle_step,
    document_id: doc.id,
    document_load_index: doc.loadIndex,
    navigation_type: doc.navigationType,
    module_instance: moduleInstance,
    page_style_applied: getComputedStyle(sentinel).color === "rgb(1, 2, 3)",
    component_token: vars.lifecycle_component_token ?? null,
    sounds_at_activation: psynet.media.sounds.length,
    media_elements_playing_at_activation: countPlayingMediaElements(),
  };

  // A getter defers the rest until submission, when the page has settled.
  Object.defineProperty(psynet.response.staged.metadata, "lifecycle", {
    configurable: true,
    enumerable: true,
    get() {
      const layout = window.psynetLayout;
      return {
        ...atActivation,
        dependency_executions: doc.dependencyExecutions,
        activations_of_this_page: doc.activationsByPage[pageUuid],
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
    sentinel.remove();
  };
}
