---
name: refactor
description: Reviews code for readability and maintainability refactor opportunities.
---

# Refactor

## Purpose

To spot, discuss, and potentially implement refactoring opportunities.

## Terminology

- Treat "merge request" and "pull request" as equivalent.
- "Scope" means which code set is being reviewed (whole project, PR diff, or specific file).

## Workflow

1. Determine scope:
   - Default: review only code touched in the current PR diff.
   - If other instructions provided: follow them.
2. Reflect on readability and maintainability:
   - Naming clarity and intent
   - Function/class size and cohesion
   - Duplication and abstraction opportunities
   - Control-flow complexity and nesting
   - Error handling consistency
   - Test clarity and coverage impact
3. Identify concrete proposals:
   - Determine risk and payoff
   - Determine confidence in recommendation
4. Discuss findings with the user before implementing refactors.

## Recommendation threshold

Evaluate and report confidence in the refactoring opportunities.
Skip reporting low-confidence/speculative opportunities.
Include larger restructuring suggestions when risk and payoff are explained.

## Discussion behavior

- Keep discussion freeform and concise.
- Present concrete suggestions tied to changed files and code snippets.
- Number each selection, optionally using grouping where appropriate (e.g. 3a, 3b).
- Mark confidence level for each suggestion (high/medium, and low only when explicitly speculative).
- Explain expected impact (readability, maintainability, or reduced risk).
- Favor high-value, low-risk refactors first.
- If uncertain about intent, ask clarifying questions.
- Ask for confirmation before any implementation work.
  The user should state which of the numbered suggestions to implement.
  Produce a to-do list from this.
- By default, implement one suggestion at a time, proposing a separate commit for each.
- If refactoring code that existed before the MR, add a brief changelog fragment in `changelog.d/`
  (for example via `psynet dev changelog new changed "Refactored export utilities in command_line.py."`).
- Do not edit `CHANGELOG.md` directly in an MR; it is generated from fragments at release time.
