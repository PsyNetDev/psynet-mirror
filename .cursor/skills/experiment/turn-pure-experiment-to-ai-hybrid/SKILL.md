---
name: turn-pure-experiment-to-ai-hybrid
description: Convert a pure-human PsyNet experiment into an AI or hybrid human-AI experiment with active scheduling, prompt parity, and local mock testing.
---

# Turn a pure-human experiment into an AI hybrid

## Workflow

- For local mock or stochastic participant profiles before live hybrid launch,
  read `simulate-participants/SKILL.md`.
- Start from the pure-human experiment and identify the participant-facing task,
  stimuli, instructions, response format, trial maker, recruitment target, and
  trial capacity.
- Add configuration for AI proportion, total participant target, credential
  environment variable name, model/base URL, timeout, retry policy, and local
  mock behavior.
- Validate AI proportion bounds and all scheduler/API settings before launch.
- Keep credential indirection keys non-sensitive when they only name an
  environment variable; mark only real token-bearing config keys as sensitive.
- Build shared stimulus construction so the human UI and AI prompt use the same
  stimulus representation.
- Write AI prompts that mirror the participant-facing instructions without
  revealing extra information.
- Implement a bot-response path that calls the model, parses and validates
  output, and returns the same response format as a human participant.
- Implement active hybrid scheduling instead of bulk-launching all AI
  participants.
- During live mixed sessions, repeatedly compare human count, AI count, total
  participant count, remaining trial capacity, and the target AI-human
  proportion.
- Launch only enough bots to restore the desired current proportion, then
  re-check after human arrivals and bot completions.
- Stop recruitment and AI launches once the configured participant target or
  trial capacity has been reached.

## Tests

- Test pure-human, mixed human-AI, and all-AI settings.
- Test AI proportion bounds and other config validation failures.
- Test that human display stimuli and AI prompt stimuli are built from the same
  representation.
- Test prompt text for parity with participant-facing instructions.
- Test active scheduler behavior for human arrivals, bot completions, exhausted
  trial capacity, and reached participant targets.
- Mock model/API calls in local tests; do not require real service credentials.

## Common failures

- Do not launch the full AI quota when the first human arrives; fast bots can
  consume all trials before humans receive any trials.
- Do not let AI prompts drift from participant-facing instructions.
- Do not construct human stimuli and AI prompt stimuli through separate logic.
- Do not skip local mock behavior; it is required for reliable testing without
  real credentials.
- Do not let recruitment continue after the participant target or trial capacity
  is reached.
