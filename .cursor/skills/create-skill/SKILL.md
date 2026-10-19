---
name: create-skill
description: Create or update a PsyNet Agent Skill, validate its package, and reread the result for writing problems.
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

## Placing new knowledge

Write each new piece of knowledge in one place. Choose that place by asking
which skill the reader will already have open at the moment they need it, and
put it under the heading they will look for. The same rule copied into several
skills becomes several rules that drift apart, and a reader who finds one copy
cannot tell whether it is current.

Link to that section from elsewhere by skill path and heading, but only where a
reader working in the other skill genuinely needs it. A useful pointer carries
something local: which gate the rule belongs to, or where it falls in that
skill's sequence. Do not restate the rule, repeat its code example, or add a
link only because the topic is adjacent.

## After writing

Read the edited skill as a finished page. Show the correct pattern with a
short code example. Check that each rule still lives in a single place, as
described under "Placing new knowledge". Headings should match how someone
will look up the next step.

Watch for verbosity, LLM-style jargon, bullet lists of vague constructs
instead of prose, missing concrete examples, long explanations of bad
practice, duplicated content, a reader who cannot find the next step from
the title and first heading, shapeless structure, and files that have grown
too long to read. Use the same pass when you edit Sphinx docs in the same
change.
