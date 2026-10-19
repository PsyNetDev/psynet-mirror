---
name: verify-ai-model-usability
description: Verify AI/LLM provider access, model availability, fallback options, and AI-call reliability for PsyNet experiments or user requests.
---

# Verify AI model usability

## Prerequisites

- Read the target experiment files or user request that names the model.
- Read `references/provider-verification.md` for provider-specific endpoints,
  credential variables, and known caveats.
- Read `references/ai-call-fallbacks.md` when no requested AI model is usable
  or when reviewing experiment code that calls an AI service.
- If helper output is needed, use
  `scripts/check_model.py`; it uses only the Python standard library.

## Workflow

1. Identify the requested provider, API base URL, and model IDs. If the provider
   is not explicit, check the default platforms in this order: OpenRouter,
   OpenAI, Anthropic/Claude, then Google/Gemini.
2. If the request or code mentions another provider such as Qwen/DashScope,
   DeepSeek, a custom OpenAI-compatible endpoint, or a local model server,
   include that platform in the check.
3. Protect credentials first:
   - Do not print, echo, copy, or commit API keys.
   - Do not run broad `grep`, `rg`, `env`, shell history, or config-dump commands
     that might print secret values.
   - Check whether an expected environment variable exists without printing its
     value, for example by using the helper script or a short `os.environ` check.
   - Keep `.env`, `.dallingerconfig`, credential JSON, shell profiles, and
     private config files out of evidence artifacts and commits.
4. Verify provider usability before judging the model name:
   - Confirm the network can reach the provider host.
   - Confirm the provider API responds rather than timing out or returning a
     service outage.
   - Confirm the configured API key is accepted when a key is available.
   - If a key is missing or rejected, report the provider as unverified or
     unusable and continue checking other requested/default providers that have
     usable access.
5. Verify model availability:
   - Prefer the provider's model-list or model-retrieve API.
   - Check for an exact model ID match first.
   - Check common spelling variants: missing provider prefix, `models/` prefix,
     case mismatch, hyphen/underscore/dot differences, dated versus alias IDs,
     and OpenRouter's `provider/model` format.
   - If the requested model is unavailable, suggest the closest available IDs
     from the same provider and explain whether the issue looks like a typo,
     stale/deprecated model, wrong platform, or unsupported endpoint.
6. For PsyNet experiments, inspect where the model is used:
   - Verify the configured provider/base URL matches the model namespace.
   - Check whether the model needs chat, responses, embeddings, image, audio, or
     tool-calling capabilities, and mention when availability alone does not
     prove capability compatibility.
   - Check that AI calls have bounded timeouts, safe retries, and a fallback path
     that preserves the participant flow when the provider is unavailable.
   - Do not change production credentials or add real credentials to the repo.
7. If no requested/default model is usable, ask the user which fallback direction
   to use before editing experiment behavior:
   - Agent-in-the-loop fallback: an AI agent or subagent acts as the participant
     or assistant for local development/evidence when an API or AI call would
     otherwise be required.
   - Deterministic experiment fallback: replace the AI call temporarily with a
     simple experiment-appropriate `bot_response` or feedback response. If the
     experiment expects audio, return a valid local audio response instead of
     text-only feedback.
8. Report results with separate statuses for network, provider, key, model,
   retry safety, and fallback readiness.
   Include suggested replacement model IDs only when they come from a verified
   provider response, official provider docs, or an explicitly marked fallback
   note.

## Helper usage

Run `scripts/check_model.py` from this skill directory (PsyNet source:
`.cursor/skills/experiment/verify-ai-model-usability`; experiment bundle:
`.cursor/skills/psynet/verify-ai-model-usability`):

`uv run python .cursor/skills/experiment/verify-ai-model-usability/scripts/check_model.py --model <model-id>`

Useful options:

- `--providers default` checks OpenRouter, OpenAI, Anthropic, and Google.
- `--providers all` also checks DeepSeek and Qwen/DashScope.
- `--providers openai,anthropic` checks selected platforms.
- `--json` prints machine-readable output without secret values.
- `--strict` exits nonzero when a requested model is not confirmed usable.
- `--allow-paid-probe` permits a minimal generation request for providers that
  do not expose a reliable model-list endpoint. Use it only when the user has
  explicitly accepted possible API cost.

## Rules

- Never reveal, log, or commit credentials. If a key is exposed during work,
  stop and tell the user to revoke it.
- Do not call a model with a paid request unless the user explicitly asked for
  that level of verification.
- Do not replace an AI call with an agent, subagent, mock, `bot_response`, or
  generated audio fallback without asking the user to choose that direction.
- Do not infer that a model is invalid when the provider, network, or key check
  failed first.
- Prefer live provider responses over memory. Model catalogs change frequently.
