"""Publish PsyNet's Agent Skills as documentation pages.

Skills are the canonical source for recommended workflows. At build time this
extension copies each skill's ``SKILL.md`` and ``references/*.md`` into the
documentation tree as MyST pages, so the website shows exactly what agents
read. The generated files are ignored by Git; edit the skills in
``.cursor/skills/`` instead.

- Experiment skills (``.cursor/skills/experiment/<name>``) become
  ``skills/<name>`` pages, listed on ``skills/index``.
- Maintainer skills (other folders in ``.cursor/skills/``) become
  ``developer/skills/<name>`` pages, listed on ``developer/skills/index``.

Each page gains a note saying that it is written for coding agents, and the
backticked page names in a skill's "Read first" list become links.
"""

import re
from pathlib import Path

EXPERIMENT_NOTE = """```{{note}}
This is an Agent Skill: a workflow written mainly for coding agents, and also
useful as a checklist for people. PsyNet installs it into experiments at
``.cursor/skills/psynet/{name}/SKILL.md``; in Cursor, run ``/{name}``. Edit
it in the PsyNet repository at ``.cursor/skills/experiment/{name}/``.
```
"""

MAINTAINER_NOTE = """```{{note}}
This is an Agent Skill for PsyNet maintainers, written mainly for coding
agents working on the PsyNet repository. In Cursor, run ``/{name}``. Edit it
at ``.cursor/skills/{name}/``.
```
"""

_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
_READ_FIRST_ITEM = re.compile(r"^(\s*[-*] )`([a-z0-9_]+(?:/[a-z0-9_]+)*)`", re.M)


def _read_first_links(text):
    """Turn backticked docs pages in the "Read first" section into links."""
    match = re.search(r"^## Read first\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        return text
    section = _READ_FIRST_ITEM.sub(r"\1{doc}`/\2`", match.group(1))
    return text[: match.start(1)] + section + text[match.end(1) :]


def _skill_markdown(skill_md, name, note, references):
    text = _FRONTMATTER.sub("", skill_md.read_text(encoding="utf-8"), count=1)
    text = _read_first_links(text)
    # Source layout is <skills>/<name>/SKILL.md; pages are <out>/<name>.md.
    text = re.sub(r"\]\(references/", f"]({name}/references/", text)
    text = re.sub(r"\]\(\.\./", "](", text)
    text = _skill_md_links(text)
    lines = text.splitlines()
    title_index = next(
        (i for i, line in enumerate(lines) if line.startswith("# ")), None
    )
    note_block = note.format(name=name)
    if title_index is None:
        lines[0:0] = [f"# {name}", "", note_block]
    else:
        lines.insert(title_index + 1, "\n" + note_block)
    body = "\n".join(lines).rstrip() + "\n"
    if references:
        entries = "\n".join(f"{name}/references/{ref.stem}" for ref in references)
        body += f"\n```{{toctree}}\n:hidden:\n\n{entries}\n```\n"
    return body


def _skill_md_links(text):
    """Point links to another skill's ``SKILL.md`` at that skill's page."""
    return re.sub(r"([a-z0-9-]+)/SKILL\.md(#[^)]*)?\)", r"\1.md\2)", text)


def _reference_markdown(path, name):
    text = _FRONTMATTER.sub("", path.read_text(encoding="utf-8"), count=1)
    # References keep their depth (<out>/<name>/references/), except links to
    # their own skill's SKILL.md.
    text = re.sub(r"\]\(\.\./SKILL\.md(#[^)]*)?\)", rf"](../../{name}.md\1)", text)
    text = _skill_md_links(text)
    if not re.search(r"^# ", text, re.M):
        text = f"# {path.stem.replace('-', ' ').capitalize()}\n\n" + text
    return text


def _write_skills(source_dirs, out_dir, note):
    pages = {}
    for skill_dir in source_dirs:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        name = skill_dir.name
        references = sorted((skill_dir / "references").glob("*.md"))
        pages[out_dir / f"{name}.md"] = _skill_markdown(
            skill_md, name, note, references
        )
        for ref in references:
            pages[out_dir / name / "references" / ref.name] = _reference_markdown(
                ref, name
            )

    # Rewrite only changed pages, so incremental and live-preview builds don't
    # see every skill page as modified on each run.
    for path, text in pages.items():
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if out_dir.exists():
        for path in sorted(out_dir.rglob("*"), reverse=True):
            if path.is_file() and path.name != "index.rst" and path not in pages:
                path.unlink()
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    return [path.stem for path in pages if path.parent == out_dir]


def generate_skill_pages(app):
    """Write the skill pages before Sphinx reads the source tree."""
    docs_dir = Path(app.srcdir)
    skills_root = docs_dir.parent / ".cursor" / "skills"
    experiment_dirs = sorted(
        p for p in (skills_root / "experiment").iterdir() if p.is_dir()
    )
    maintainer_dirs = sorted(
        p for p in skills_root.iterdir() if p.is_dir() and p.name != "experiment"
    )
    _write_skills(experiment_dirs, docs_dir / "skills", EXPERIMENT_NOTE)
    _write_skills(maintainer_dirs, docs_dir / "developer" / "skills", MAINTAINER_NOTE)


def setup(app):
    app.connect("builder-inited", generate_skill_pages)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
