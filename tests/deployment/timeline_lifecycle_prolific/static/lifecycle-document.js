// Loaded through js_dependencies, which PsyNet promises to run once per
// browser document. A second execution in the same document is a bug that
// lifecycle-probe.js reports as dependency_executions > 1.
(function () {
  "use strict";

  if (window.lifecycleDocument) {
    window.lifecycleDocument.dependencyExecutions += 1;
    return;
  }

  let loadIndex = null;
  try {
    loadIndex = Number(sessionStorage.getItem("lifecycleDocumentLoads") || "0") + 1;
    sessionStorage.setItem("lifecycleDocumentLoads", String(loadIndex));
  } catch (error) {
    // Some privacy modes block sessionStorage; the document ID still works.
  }

  const navigation = performance.getEntriesByType("navigation")[0];

  window.lifecycleDocument = {
    id: Math.random().toString(36).slice(2, 10) + Date.now().toString(36),
    loadIndex: loadIndex,
    navigationType: navigation ? navigation.type : null,
    dependencyExecutions: 1,
    activationsByPage: {},
  };
})();
