# AI-call fallbacks and stability

Use this reference when a PsyNet experiment calls an AI service, or when no
requested AI model is usable after provider and key checks.

## Ask before substituting AI behavior

Before replacing a real AI/API call, summarize what is unavailable and ask the
user to choose one of these directions:

1. **Agent-in-the-loop fallback**: use the current AI agent or a subagent as the
   participant, assistant, judge, or content generator during local development
   and evidence collection.
2. **Deterministic experiment fallback**: replace the AI call temporarily with a
   simple response shaped for the experiment, such as `bot_response`, static
   feedback, a rule-based response, or a local audio response.

Record the user's choice in the work summary or audit notes. Do not present
either fallback as proof that the real provider works.

## Agent-in-the-loop fallback

Use only for local development, demos, or local evidence when the experiment
itself was developed by an AI agent and the task logic allows a synthetic
assistant/participant.

- Keep the agent's role explicit: participant, assistant, evaluator, or content
  generator.
- Route the interaction through the same experiment path the real participant or
  assistant would use whenever feasible.
- Do not use this fallback for production deployment, payment decisions, or
  claims about provider availability.
- Label evidence clearly so reviewers know an agent/subagent supplied the AI
  behavior.

## Deterministic fallback

Use when the experiment can continue safely without a live model.

- Match the production response shape exactly enough for downstream code to run:
  keys, types, text fields, score fields, metadata, file paths, and errors.
- Prefer experiment-appropriate feedback over generic filler. For example, a
  tutoring task can return a brief hint, while a classifier can return a stable
  category with confidence metadata.
- If the experiment expects `bot_response`, return or set `bot_response` through
  the same interface the real AI call uses.
- If the experiment expects audio, return a valid local audio artifact in the
  expected format. Use committed/generated local assets or deterministic audio
  generation; do not require external TTS credentials.
- Put temporary fallbacks behind explicit local/test configuration and document
  what remains unverified.

## Stability checklist for real AI calls

When reviewing or implementing an AI call, verify that the code includes:

- A bounded request timeout.
- Bounded retries with exponential backoff and jitter.
- Retry only for transient failures such as timeouts, connection errors, 429,
  and 5xx responses; do not retry invalid credentials or invalid model names.
- A fallback path that keeps the PsyNet participant flow from crashing when the
  provider is unavailable.
- Structured error handling that preserves useful status without logging secret
  headers, prompts containing private data, or raw provider credentials.
- Capability checks for the required modality: chat, responses, embeddings,
  images, audio, tool use, JSON/schema output, or streaming.
- Tests or manual evidence for success, timeout/retry, auth failure, model-not-
  found, and fallback behavior when the AI call is central to the experiment.

## PsyNet-specific guidance

- Keep fallback behavior local/test scoped unless the user explicitly asks for a
  production fallback.
- Preserve participant-visible timing and page flow as much as possible.
- If AI output affects payment, scoring, grouping, or trial generation, make the
  fallback deterministic and mark resulting data as fallback-generated.
- Store provider status and fallback metadata in experiment logs or trial data
  when useful for later analysis, but never store API keys.
