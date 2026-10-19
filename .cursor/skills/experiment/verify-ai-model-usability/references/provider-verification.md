# Provider verification reference

Use this reference while applying the `verify-ai-model-usability` skill. Provider
APIs and model catalogs change often, so prefer live API responses or current
official documentation over stale model lists.

## Credential handling

- Check only whether a credential is present; never print its value.
- Do not search secret files or environment dumps for key names.
- Safe examples:
  - `uv run python -c "import os; print('OPENAI_API_KEY present:', bool(os.getenv('OPENAI_API_KEY')))"`
  - `uv run python .cursor/skills/experiment/verify-ai-model-usability/scripts/check_model.py --providers openai --model gpt-4o`
- Unsafe examples:
  - `echo $OPENAI_API_KEY`
  - `env | grep KEY`
  - `rg OPENAI_API_KEY ~/.bashrc .env .dallingerconfig`
  - copying credential JSON or `.env` files into evidence artifacts.

## Default provider order

When no provider is specified, check:

1. OpenRouter
2. OpenAI
3. Anthropic/Claude
4. Google/Gemini

If a model is not available on the first usable provider, keep checking the
remaining default providers before concluding that the requested model is not
usable.

## Provider details

| Provider | Environment variables | Model-list endpoint | Notes |
| --- | --- | --- | --- |
| OpenRouter | `OPENROUTER_API_KEY` | `GET https://openrouter.ai/api/v1/models` | Model IDs usually use `provider/model`, for example `openai/gpt-4o` or `anthropic/claude-sonnet-4-5`. Some public model-list calls may work without a key, but key usability still requires an authenticated request. |
| OpenAI | `OPENAI_API_KEY` | `GET https://api.openai.com/v1/models` | The endpoint confirms availability for the authenticated project, but not every listed model supports every API surface. Check chat/responses/embedding needs separately. |
| Anthropic/Claude | `ANTHROPIC_API_KEY` | `GET https://api.anthropic.com/v1/models` | Requires `anthropic-version: 2023-06-01`. Claude IDs can be aliases or pinned snapshots; verify the exact ID or alias returned by the API. |
| Google/Gemini | `GEMINI_API_KEY`, fallback `GOOGLE_API_KEY` | `GET https://generativelanguage.googleapis.com/v1beta/models` | API responses often use names such as `models/gemini-2.5-flash`; treat both the full name and suffix as candidates. |
| DeepSeek | `DEEPSEEK_API_KEY` | `GET https://api.deepseek.com/models` | OpenAI-compatible. Use the provider response for current IDs because legacy model names may be deprecated. |
| Qwen/DashScope | `DASHSCOPE_API_KEY`, fallback `QWEN_API_KEY` | Often unavailable or endpoint-dependent | DashScope commonly supports OpenAI-compatible chat/completions endpoints but may not expose `/models`. Do not mark a Qwen model invalid solely because model-list probing returns 404. Use current Qwen/DashScope docs or an explicitly approved minimal paid probe. |

## Status interpretation

- `network_error`: DNS, TLS, timeout, or connection failure. Model validity is
  unverified.
- `provider_error`: Provider responded with service-side failure or unexpected
  status. Try another provider or retry later before judging the model name.
- `missing_key`: The needed environment variable is not present. Do not ask the
  user to paste the key into chat; ask them to configure it securely.
- `auth_error`: The provider rejected the key. Do not reveal any part of the key.
- `endpoint_unsupported`: The provider is reachable but does not support the
  model-list endpoint used for validation.
- `model_available`: The requested model exactly matches an available provider
  model ID or accepted alias.
- `model_not_found`: The provider and key are usable, but no exact model match
  was found. Provide closest suggestions from the verified list.

## Suggested-model rules

Only suggest replacements that are traceable to one of these sources:

1. A live provider model-list response.
2. A live model-retrieve response.
3. Current official provider documentation read during the task.
4. A clearly labeled fallback note for providers without list endpoints.

Prefer suggestions from the same provider and same capability family. For
example, suggest a Claude chat model for a missing Claude chat model, not a
Google embedding model. Mention when a replacement may require code changes such
as switching the provider, base URL, SDK, or API route.
