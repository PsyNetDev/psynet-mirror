---
name: develop-experiment-front-end
description: Develop and test PsyNet experiment front-end interfaces with ModularPage, Native Graphics, and Playwright checks. Use when building or validating participant-facing pages, controls, custom prompts, or UI evidence screenshots.
---

# Develop experiment front end

## Prerequisites

- For Playwright screenshots or participant-flow video evidence, use
  `record-participant-video/SKILL.md`.

## Modular pages

PsyNet contains a wide range of built-in components for developing user interfaces.
Most of these are accessed via the `ModularPage` component;
these should be prioritized where possible.

## Graphics

PsyNet includes a sophisticated Native Graphics system for displaying
graphics programmatically. Under the hood, it uses the JavaScript library
Raphaël for graphics rendering. PsyNet exposes some Raphaël functionality to
users, for example when defining custom object attributes. Whenever custom
frontend behavior seems necessary, first consider whether the task can be
implemented with PsyNet's Native Graphics system. This is often the
recommended approach for psychological experiments involving simple visual
stimuli such as geometric shapes, fixation crosses, or several relatively
simple objects, shapes, or images presented in a timed sequence within a
single trial. Simple interactions, such as clicking on a shape, can also be
handled with PsyNet Graphics.

For visual experiments involving images, geometric shapes, or simple spatial
interactions, include an explicit PsyNet Graphics feasibility check before
choosing custom JavaScript. Record the result in the implementation plan or
technical notes: either identify the PsyNet Graphics components/events that will
be used, or explain the concrete requirement that makes custom JavaScript
necessary. Do not choose custom JavaScript only because it seems more familiar
or because image presentation appears easier without first checking whether
PsyNet Graphics can handle the same display and interaction.

## Events

Changes that occur within a trial should be controlled using PsyNet's event
management system where possible. PsyNet Graphics can use event management to
coordinate object display with events such as `promptEnd`. For more details,
consult the PsyNet Event Management documentation and the Graphics tutorial.

## Customization

Simple customizations can be achieved by passing custom JS to the `ModularPage`.
Further customization can be achieved by creating custom `Prompt` or `Control` components.
More wholesale customization can be achieved by creating a custom `Page` subclass.

Customizations should be tested robustly.
Construct a minimal experiment timeline to do this,
and construct a Playwright test for each custom component.
Use the Playwright test to create screenshots at key moments, and review these screenshots.
For canonical participant video evidence, follow `record-participant-video/SKILL.md`.
Ensure that:

- Stimuli are displayed as expected
- All text is visible
- Button layouts are intuitive
- Aesthetics are good and consistent

Video review should be used sparingly as it is time-consuming.

When implementing custom `Page` classes, make sure `get_bot_response`
returns the same structured, formatted answer that the browser path records.
PsyNet bots submit the value returned by `get_bot_response` as the formatted
answer, so the bot path can bypass `format_answer` unless you explicitly
call it or otherwise match its output.

When repeating custom `Page` classes with JavaScript event handlers, avoid
reusing the default `session_id` unless the code explicitly handles PsyNet's
`pageUpdated` event. Consecutive pages with the same session can preserve the
browser context and update the DOM without rerunning page scripts. Use distinct
`session_id` values for repeated interactive pages when each trial needs fresh
handler installation.

## Examples

Refer to the explore-psynet-repository skill for examples to work from.

## Rules & gotchas

- Implement keyboard-button responses with `KeyboardPushButtonControl` rather than dedicated JavaScript.
- Do not show technical details that are not participant-facing, such as labeling display items “stimuli”.
- Do not measure reaction time unless explicitly instructed. When RT is required, follow the reaction-time guidance in `psychophysics/SKILL.md`.
