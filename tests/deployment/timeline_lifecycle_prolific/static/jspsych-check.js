// One auto-advancing trial, so the page also works on phones without a
// keyboard. The document ID shows whether jsPsych got its own document.
export function buildTimeline() {
  return [
    {
      type: jsPsychHtmlKeyboardResponse,
      stimulus: "<p>Short jsPsych check. This screen continues automatically.</p>",
      choices: "NO_KEYS",
      trial_duration: 2500,
      data: {
        lifecycle_document_id: window.lifecycleDocument
          ? window.lifecycleDocument.id
          : null,
      },
    },
  ];
}
