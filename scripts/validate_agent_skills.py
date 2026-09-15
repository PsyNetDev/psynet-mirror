#!/usr/bin/env python3
"""Validate PsyNet Agent Skills under .cursor/skills/."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKILL_REFERENCE_RE = re.compile(
    r"(?<![\w./-])((?:(?P<skill>[a-z0-9-]+)/)?references/[A-Za-z0-9_.-]+\.(?:md|ya?ml|py))"
)
SKILL_NAME_MAX_LENGTH = 64
SKILL_DESCRIPTION_MAX_LENGTH = 1024
SKILL_COMPATIBILITY_MAX_LENGTH = 500
SKILL_LINE_COUNT_WARNING = 500


def read_frontmatter(skill_file: Path) -> tuple[dict[str, str], list[str]]:
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, [f"{skill_file}: missing YAML frontmatter"]
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return {}, [f"{skill_file}: malformed YAML frontmatter"]
    import yaml

    loaded = yaml.safe_load(parts[1])
    if not isinstance(loaded, dict):
        return {}, [f"{skill_file}: frontmatter must be a mapping"]
    frontmatter = {str(key): value for key, value in loaded.items()}
    return frontmatter, []


def resolve_reference_path(
    reference: Path, skill_name: str | None, skills_root: Path, skill_dir: Path
) -> Path:
    if skill_name:
        candidates = (
            skills_root / "experiment" / reference,
            skills_root / reference,
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]
    return skill_dir / reference


def referenced_paths(text: str, *, skill_dir: Path, skills_root: Path) -> set[Path]:
    paths: set[Path] = set()
    for match in SKILL_REFERENCE_RE.finditer(text):
        reference = Path(match.group(1))
        skill_name = match.group("skill")
        paths.add(resolve_reference_path(reference, skill_name, skills_root, skill_dir))
    return paths


def validate_skill_dir(
    skill_dir: Path, skills_root: Path
) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return [f"{skill_dir}: missing SKILL.md"], warnings

    frontmatter, frontmatter_problems = read_frontmatter(skill_file)
    problems.extend(frontmatter_problems)

    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")
    if not isinstance(name, str) or not name:
        problems.append(f"{skill_file}: missing name")
    elif name != skill_dir.name:
        problems.append(f"{skill_file}: name must match folder {skill_dir.name!r}")
    elif not SKILL_NAME_RE.fullmatch(name):
        problems.append(f"{skill_file}: invalid skill name {name!r}")
    elif len(name) > SKILL_NAME_MAX_LENGTH:
        problems.append(
            f"{skill_file}: name exceeds {SKILL_NAME_MAX_LENGTH} characters"
        )
    else:
        try:
            relative_parts = skill_dir.relative_to(skills_root).parts
        except ValueError:
            relative_parts = ()
        if relative_parts[:1] == ("experiment",) and name.startswith("psynet-"):
            problems.append(
                f"{skill_file}: experiment skills must not use a redundant "
                "'psynet-' prefix; the experiment/ tree already namespaces them"
            )

    if not isinstance(description, str) or not description.strip():
        problems.append(f"{skill_file}: missing description")
    elif len(description) > SKILL_DESCRIPTION_MAX_LENGTH:
        problems.append(
            f"{skill_file}: description exceeds {SKILL_DESCRIPTION_MAX_LENGTH} characters"
        )

    compatibility = frontmatter.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, str) or not compatibility.strip():
            problems.append(f"{skill_file}: compatibility must be a non-empty string")
        elif len(compatibility) > SKILL_COMPATIBILITY_MAX_LENGTH:
            problems.append(
                f"{skill_file}: compatibility exceeds {SKILL_COMPATIBILITY_MAX_LENGTH} characters"
            )

    line_count = len(skill_file.read_text(encoding="utf-8").splitlines())
    if line_count > SKILL_LINE_COUNT_WARNING:
        warnings.append(
            f"{skill_file}: SKILL.md has {line_count} lines; "
            f"consider splitting detail into references/ "
            f"(warns above {SKILL_LINE_COUNT_WARNING})"
        )

    references_dir = skill_dir / "references"
    reference_files = (
        sorted(
            path
            for path in references_dir.iterdir()
            if path.is_file() and path.suffix in {".md", ".yaml", ".yml", ".py"}
        )
        if references_dir.exists()
        else []
    )
    known_references = set(reference_files)
    reachable = {skill_file}
    queue = [skill_file]
    while queue:
        current = queue.pop(0)
        text = current.read_text(encoding="utf-8")
        for cited in sorted(
            referenced_paths(text, skill_dir=skill_dir, skills_root=skills_root)
        ):
            if not cited.exists():
                problems.append(f"{current}: cited reference does not exist: {cited}")
            elif cited.parent == references_dir and cited in known_references:
                if cited not in reachable:
                    reachable.add(cited)
                    queue.append(cited)

    for reference_file in sorted(known_references):
        if reference_file not in reachable:
            problems.append(
                f"{reference_file}: reference file is not cited from {skill_file} "
                "or another cited reference"
            )

    return problems, warnings


def run_skills_ref(skill_dir: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["skills-ref", "validate", str(skill_dir)],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    if completed.returncode == 0:
        return []
    output = (completed.stdout + completed.stderr).strip()
    return [f"{skill_dir}: skills-ref validate failed: {output or 'non-zero exit'}"]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    skills_root = root / ".cursor" / "skills"
    if not skills_root.exists():
        print(f"{skills_root}: missing skills directory", file=sys.stderr)
        return 1

    problems: list[str] = []
    warnings: list[str] = []
    skill_dirs = sorted({path.parent for path in skills_root.rglob("SKILL.md")})
    for skill_dir in skill_dirs:
        skill_problems, skill_warnings = validate_skill_dir(skill_dir, skills_root)
        problems.extend(skill_problems)
        warnings.extend(skill_warnings)
        problems.extend(run_skills_ref(skill_dir))

    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
