---
name: create-skill
description: Create or update a PsyNet Agent Skill and validate its package.
---

# Create a skill

PsyNet repository skills live under `.cursor/skills/`. Experiment-development
skills live under `.cursor/skills/experiment/` and are copied into experiment
checkouts by `psynet scripts update`. Edit the PsyNet source skill rather than a
generated experiment copy.

Each skill is a directory containing `SKILL.md`. The file begins with YAML
frontmatter containing `name` and `description`; `compatibility` is optional.

Run the repository validator after making changes:

```bash
python scripts/validate_agent_skills.py
```

The validator checks that:

- `name` matches the directory name, uses lowercase hyphen-case, and is no more
  than 64 characters;
- `description` is present and is no more than 1,024 characters;
- `compatibility`, when present, is a non-empty string of no more than 500
  characters;
- experiment skill names do not have a redundant `psynet-` prefix;
- cited files under `references/` exist and every reference file is reachable
  from `SKILL.md` or another cited reference;
- `SKILL.md` files over 500 lines produce a warning;
- each skill passes `skills-ref validate` when `skills-ref` is installed.

After changing experiment skills, run `psynet scripts update` in any experiment
checkout that should receive the new version.
