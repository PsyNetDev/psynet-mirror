import os
import re
import shlex
import sys
import tempfile
import time
from typing import OrderedDict

import pexpect
import polib
from yaspin import yaspin

from psynet.log import bold

# Keep this as the single source of truth for Jinja extraction keyword rules.
# - gettext:1 means "extract the first argument as the message"
# - pgettext:1c,2 means "first argument is context, second is the message"
# - _:1 means "extract the first argument from _(...)"
# - _p:1c,2 covers the PsyNet context-aware alias for pgettext
_BABEL_JINJA_CONFIG = """[jinja2: **.html]
encoding = utf-8
keywords = _:1 _p:1c,2 pgettext:1c,2 gettext:1
"""
# ``docs_text`` holds the release docs bundle, including copies of the demos,
# whose strings belong to the demos rather than to the PsyNet catalog.
_BUNDLED_DOCS_DIRNAME = "docs_text"
# pybabel's defaults (".* ._") plus the docs bundle.
_PYBABEL_IGNORE_DIRS = f".* ._ {_BUNDLED_DOCS_DIRNAME}"


def new_pot(fpath):
    """Returns an empty pot file."""
    pot = polib.POFile()
    pot.metadata = {
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
    }
    pot.encoding = "utf-8"
    pot.metadata_is_fuzzy = ["fuzzy"]
    pot.fpath = fpath
    return pot


def load_po(po_path):
    """Load a pot or po from file."""
    assert po_path.endswith((".po", ".pot")), "po_path must end with .po or .pot"
    assert os.path.exists(po_path), f"File {po_path} does not exist"
    return polib.pofile(po_path)


def get_pot_from_command(cmd, tmp_pot_file, sp):
    """Create a pot file from a command and open."""
    timeout = 60
    p = pexpect.spawn(cmd, timeout=timeout)
    while not p.eof():
        line = p.readline().decode("utf-8")
        sp.text = line
    p.close()
    if p.exitstatus > 0:
        sys.exit(p.exitstatus)
    if os.path.exists(tmp_pot_file):
        pot = load_po(tmp_pot_file)
        os.remove(tmp_pot_file)
        return list(pot)
    else:
        return []


def _build_pybabel_extract_command(cfg_file, pot_file, input_path):
    """Build the pybabel extract command using shell-safe quoted paths.

    Keywords are passed explicitly to keep behavior stable across Babel versions.
    """
    return (
        "pybabel extract "
        "-k gettext:1 -k pgettext:1c,2 -k _:1 -k _p:1c,2 "
        f"--ignore-dirs {shlex.quote(_PYBABEL_IGNORE_DIRS)} "
        f"-F {shlex.quote(cfg_file)} "
        f"-o {shlex.quote(pot_file)} "
        f"{shlex.quote(input_path)}"
    )


def create_translation_template_with_pybabel(input, sp):
    """Extract translations from a file or multiple files using pybabel."""
    with tempfile.TemporaryDirectory() as tempdir:
        tmp_cfg_file = os.path.join(tempdir, "babel.cfg")
        tmp_pot_file = os.path.join(tempdir, "babel.pot")
        with open(tmp_cfg_file, "w") as f:
            f.write(_BABEL_JINJA_CONFIG)
        return get_pot_from_command(
            _build_pybabel_extract_command(tmp_cfg_file, tmp_pot_file, input),
            tmp_pot_file,
            sp,
        )


def create_translation_template_with_xgettext(input_file, sp):
    """Extract translations from a file using xgettext."""
    with tempfile.TemporaryDirectory() as tempdir:
        tmp_pot_file = os.path.join(tempdir, "xgettext.pot")
        return get_pot_from_command(
            "xgettext "
            f"-o {shlex.quote(tmp_pot_file)} "
            f"{shlex.quote(input_file)} "
            '-L Python --keyword="_p:1c,2"',
            tmp_pot_file,
            sp,
        )


# def clean_po(po):
#     po = sort_po(po)
#     po = clean_code_occurence_paths_in_po(po)

#     return po


def sort_po(po: polib.POFile) -> polib.POFile:
    """
    Sorts the entries in the po file.

    Each entry might have multiple occurrences, but we sort by the first occurrence
    (i.e. the first time the string appears in the code).
    In particular, we sort first by the file name, then by the line number.
    Note that the file name strings might be absolute paths, which might vary by machine;
    this doesn't matter for the sorting though, as a given po file will only contain paths
    from the same top-level directory.
    """
    po.sort(key=_po_sort_key)
    return po


def make_file_paths_relative(po: polib.POFile) -> polib.POFile:
    cwd = os.getcwd()
    for entry in po:
        for i, _ in enumerate(entry.occurrences):
            full_path, line_number = entry.occurrences[i]
            relative_path = os.path.relpath(full_path, cwd)
            entry.occurrences[i] = (relative_path, line_number)
    return po


def _po_sort_key(entry):
    first_occurrence = entry.occurrences[0]
    path = first_occurrence[0]
    line_number = int(first_occurrence[1])
    return path, line_number


def create_pot(input_path: str, pot_path):
    """
    Extract translations from a file or multiple files using pybabel or xgettext.
    Parameters
    ----------
    input_path :
        path pointing to the file or directory to extract translations from

    pot_path :
        path pointing to the pot file to write to

    Returns
    -------
    Returns the generated pot file
    """
    from psynet.translation.check import (
        F_STRING_PATTERN,
        JINJA_PATTERN,
        variable_name_check,
    )

    if not os.path.isabs(input_path):
        input_path = os.path.abspath(input_path)

    entries = []

    with yaspin(text="Extracting translations...") as sp:
        now = time.time()
        if os.path.isdir(input_path):
            entries.extend(_get_entries_from_dir(input_path, sp))
        elif input_path.endswith(".html"):
            entries.extend(_get_html_entries_from_file(input_path, sp))
        elif input_path.endswith(".py"):
            entries.extend(_get_py_entries_from_file(input_path, sp))
        else:
            sp.text = "Input file must be a Python or HTML file."
            sp.fail("💥")
            raise ValueError("Input file must be a Python or HTML file.")

        pot = new_pot(pot_path)
        pot.extend(entries)

        pot = sort_po(pot)
        pot = make_file_paths_relative(pot)

        os.makedirs(os.path.dirname(pot_path), exist_ok=True)
        pot.save(pot_path)
        taken = round(time.time() - now)

        extracted_variables = []
        for entry in entries:
            extracted_variables.extend(re.findall(F_STRING_PATTERN, entry.msgid))
            extracted_variables.extend(re.findall(JINJA_PATTERN, entry.msgid))
        used_variables = list(set(extracted_variables))

        illegal_variable_names = []
        for var_name in used_variables:
            try:
                variable_name_check(var_name)
            except AssertionError:
                illegal_variable_names.append(var_name)
        if len(illegal_variable_names) > 0:
            sp.text = (
                bold("Extracting translations failed") + ": "
                "Some variable names do not comply with the naming convention for variables. "
                f"Search and replace the following variables in your source code: {illegal_variable_names}"
            )
            sp.fail("💥")
            exit(1)

        sp.text = bold("Translations extracted successfully.") + f" ({taken}s)"
        sp.ok("✅")

    return pot


def _get_entries_from_dir(input_path, sp):
    entries = []
    entries.extend(_get_html_entries_from_dir(input_path, sp))
    entries.extend(_get_py_entries_from_dir(input_path, sp))

    return entries


def _get_html_entries_from_dir(input_path, sp):
    # pybabel works recursively, so we can just call it on the directory
    return create_translation_template_with_pybabel(input_path, sp)


def _get_html_entries_from_file(input_path, sp):
    return create_translation_template_with_pybabel(input_path, sp)


def _get_py_entries_from_dir(input_path, sp):
    # xgettext does not work recursively, so we need to walk the directory and call it on each file
    # Skip hidden and common non-hidden directories
    SKIP_DIRS = {
        "venv",
        "env",
        "__pycache__",
        "__pypackages__",
        "node_modules",
        "site-packages",
        "dist-packages",
        _BUNDLED_DOCS_DIRNAME,
    }

    entries = []
    for root, dirs, files in os.walk(input_path):
        # Filter out directories we want to skip
        # Modify dirs in-place to prevent os.walk from descending into these directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]

        for file in files:
            if file.endswith(".py"):
                entries.extend(_get_py_entries_from_file(os.path.join(root, file), sp))
    return entries


def _get_py_entries_from_file(input_path, sp):
    return create_translation_template_with_xgettext(input_path, sp)


def remove_line_numbers(po):
    for entry in po:
        # Get unique occurrence paths without line numbers
        paths = sorted(set([path for path, _ in entry.occurrences]))

        # Store file paths without line numbers
        entry.occurrences = [(path, None) for path in paths]
    return po


def po_to_dict(po):
    """Convert a po file to a dictionary. Keys are (msgid, msgctxt) tuples. Makes sure there are no duplicates."""
    entries_dict = OrderedDict()
    for entry in po:
        key = (entry.msgid, entry.msgctxt)
        if key in entries_dict:
            old_entry = entries_dict[key]
            assert old_entry.msgid == entry.msgid
            assert old_entry.msgctxt == entry.msgctxt
            assert old_entry.msgstr == entry.msgstr
        else:
            entries_dict[key] = entry
    return entries_dict


def get_po_path(locale, locales_dir, namespace):
    return os.path.join(locales_dir, locale, "LC_MESSAGES", namespace + ".po")


def compile_mo(po_path):
    """Compile a po file to a mo file and remove fuzzy entries so the translation is recognized properly."""
    po = load_po(po_path)
    mo_path = po_path.replace(".po", ".mo")
    for entry in po:
        entry.flags = []  # Make sure fuzzy entries are excluded, this will lead to the translation not being recognized
    po.save_as_mofile(mo_path)
