---
name: develop-experiment-front-end
description: Choose and build participant-facing PsyNet pages, from built-in ModularPage prompts and controls through Native Graphics to custom JavaScript, and check them in the browser. Use when building pages, controls, stimulus displays, or custom prompts.
---

# Develop experiment front end

## Read first

Read these pages before acting. Get the docs folder once with `psynet docs path`, then read `<folder>/<page>.txt` (or `.rst` in a source checkout) and search with `rg -n -i --no-ignore "<term>" <folder>`. If there is no local copy, fetch the pages from the website URL that `psynet docs path` prints.

- `code/writing_pages`: pages, prompts, controls, validation, and timing within a page
- `code/pages/control_gallery`: built-in controls
- `code/pages/graphics`: Native Graphics
- `code/pages/event_management`: page events and the event log
- `code/pages/custom_front_ends`: custom prompts, controls, and pages, and their JavaScript lifecycle
- `code/pages/theming`: colors and layout tokens
- `test/backend`: how bots answer pages

## Choose the lowest level that works

Work down this list and stop at the first level that can express the design:

1. A `ModularPage` with built-in prompts and controls.
2. Native Graphics (`GraphicPrompt`, `GraphicControl`) for shapes, images,
   timed frame sequences, and clicks on objects.
3. A custom `Prompt` or `Control` on a `ModularPage`.
4. A custom `Page` subclass with a template fragment.

For visual tasks (images, shapes, spatial clicks), record a Native Graphics
feasibility check in the plan before choosing custom JavaScript: name the
graphics objects and events you will use, or the concrete requirement they
cannot meet. Familiarity is not a reason to write custom JavaScript.

Drive within-trial changes, such as enabling responses after a sound, through
page events rather than timers in custom code.

Find a demo to start from with `explore-psynet-repository/SKILL.md`.
`demos/features/modular_page` shows custom prompts and controls, and
`demos/experiments/graphics` shows Native Graphics.

## Bots on custom components

A custom `Page` or `Control` needs `get_bot_response`. A plain return value
is stored as the final answer and skips `format_answer` (see "How bots
answer" in `test/backend`). Return `BotResponse(raw_answer=...)` so bot data
has the same shape as browser data:

```python
from psynet.bot import BotResponse


class ColorText(Control):
    def format_answer(self, raw_answer, **kwargs):
        return raw_answer.capitalize()

    def get_bot_response(self, experiment, bot, page, prompt):
        return BotResponse(raw_answer="hello")
```

Leave `session_id` at its default (`None`) on repeated interactive pages.
Consecutive pages that share a `session_id` update in place and fire
`pageUpdated` instead of activating the page's JavaScript again.

## Check custom components in the browser

For each custom component, build a minimal timeline and a Playwright test
(`playwright-testing/SKILL.md`). Take screenshots at key moments and run the
layout check before each one. Confirm that stimuli display as intended, all
text is visible, button layouts are intuitive, and styling is consistent.
Record video (`record-participant-video/SKILL.md`) only when screenshots
cannot show the behavior, because it is slow to review.

## Rules

- Use `KeyboardPushButtonControl` for keyboard responses rather than custom
  key handlers.
- Do not show non-participant-facing terms, such as calling display items
  "stimuli".
- Do not measure reaction time unless asked. When it is required, follow
  "Reaction time" in `psychophysics/SKILL.md`.
