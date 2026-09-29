---
name: psychophysics
description: Design-discipline checklist for PsyNet psychophysics experiments; exact visual displays with nothing extra on screen, neutral UI chrome, faithful stimulus sizes from papers, and reaction time only when asked. Use alongside implement-experiment when a task depends on precise visual stimuli, timing, or response latency.
---

# Psychophysics experiments

## Read first

Read these pages before acting. In a PsyNet source checkout read `docs/<page>.rst`; otherwise fetch `https://psynetdev.gitlab.io/PsyNet/<page>.html`.

- `code/pages/graphics`: Native Graphics displays, frame sequences, and gating the control from a frame
- `code/pages/event_management`: page events, the event log, and "Measuring reaction time"
- `code/pages/control_gallery`: built-in response controls
- `code/pages/theming`: color tokens for buttons, progress, and page chrome
- `code/writing_a_trial_maker`: trials, scoring, and performance checks

Follow the overall workflow in `implement-experiment/SKILL.md`, and choose
the page technology as in `develop-experiment-front-end/SKILL.md`.

## What appears on screen

- Show exactly the specified display elements, with correct timing. Do not
  add fixation crosses, labels, borders, or other elements that the design
  does not specify, and remove each element when the design says it ends.
- Keep decision wording such as "same or different?" out of the stimulus
  area during presentation frames unless the design puts it there. Put it in
  the instructions or on the response controls.
- Do not remove all trial-level guidance if the task would become ambiguous.
  Put a short reminder outside the visual field, for example as the
  `GraphicPrompt` text above the graphic.
- Do not add frames, panels, or contrasting backgrounds around white
  stimuli. They change the apparent context; white stimuli should blend into
  the white content surface.
- Center response buttons and questions on the stimulus.
- Do not show terms that are not meant for participants, such as calling
  display items "stimuli".

## Neutral UI chrome

For color-related or color-sensitive experiments, make buttons, the progress
rail, and selected states neutral (for example gray) by redefining the accent
and chrome tokens described in `code/pages/theming`, not by styling buttons
alone. Check the final participant screenshot to confirm that the progress
indicator changed as well as the buttons.

## Sizes from papers

Use explicit size specifications from the paper when it gives them.
Schematic figures often exaggerate dots and stimuli, especially when the
display is one panel of a larger figure, so be cautious about estimating
sizes from them. A screenshot or a clear single-display schematic is a more
reliable guide to relative sizes.

## Reaction time

Do not measure reaction time unless the user asks for it. When it is
required:

- Use the pattern in "Measuring reaction time" in
  `code/pages/event_management`: a `GraphicPrompt` that gates the response
  until the stimulus frame, `KeyboardPushButtonControl`, and a
  `format_answer` that computes the latency from the event log. Store the
  latency in each trial's answer.
- Write custom timing JavaScript only if that pattern cannot express the
  design, keep it isolated, and trigger it from PsyNet events.
- Give bots a synthetic event log as that section describes, so simulated
  data contains real latencies.
