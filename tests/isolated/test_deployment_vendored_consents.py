"""Guard against drift between the vendored consents_cococo copies.

The deployment-test experiments each carry their own byte-identical copy of
the shared consents_cococo package (from
https://gitlab.com/computational-audition-lab/cococo-shared), because a
deployment packages only the experiment directory. This test fails loudly if
someone updates one copy but not the other.
"""

import sys
from pathlib import Path

from psynet.utils import get_psynet_root

VENDORED_DIRS = [
    Path("tests/deployment/audio_gibbs/consents_cococo"),
    Path("tests/deployment/payment_flows_prolific/consents_cococo"),
]


def _vendored_files(directory: Path) -> dict:
    """Map relative paths to file contents, ignoring caches."""
    return {
        path.relative_to(directory): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def test_cultural_foundation_consent_opts_out_of_spa_contract():
    """The paid consent page must not raise under in-place timeline transitions."""
    exp_dir = get_psynet_root() / "tests/deployment/payment_flows_prolific"
    sys.path.insert(0, str(exp_dir))
    try:
        from consents_cococo.consent_cultural_foundation import _make_consent_page

        page = _make_consent_page("cf_main_consent", "<p>ok</p>", time_estimate=60)
        assert page.requires_full_page_reload
        page._check_spa_template_contract(inplace_timeline_transitions=True)
    finally:
        sys.path.remove(str(exp_dir))


def test_vendored_consents_copies_are_identical():
    root = get_psynet_root()
    reference_dir, *other_dirs = VENDORED_DIRS
    reference = _vendored_files(root / reference_dir)
    assert reference, f"No files found in {reference_dir}"

    for other_dir in other_dirs:
        other = _vendored_files(root / other_dir)
        assert set(other) == set(reference), (
            f"{other_dir} and {reference_dir} contain different files; "
            "keep the vendored consents_cococo copies byte-identical."
        )
        for rel_path, content in reference.items():
            assert other[rel_path] == content, (
                f"{other_dir / rel_path} differs from {reference_dir / rel_path}; "
                "keep the vendored consents_cococo copies byte-identical."
            )
