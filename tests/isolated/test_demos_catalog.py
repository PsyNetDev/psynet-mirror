import re

from psynet.utils import get_psynet_root


def test_demos_catalog_lists_every_demo():
    """Agents choose demos from ``demos/index``, so every demo needs an entry."""
    root = get_psynet_root()
    catalog = (root / "docs" / "demos" / "index.rst").read_text()
    listed = set(
        re.findall(r"^`((?:experiments|features|pipelines)/[\w/]+) <", catalog, re.M)
    )
    demos = {
        path.parent.relative_to(root / "demos").as_posix()
        for path in (root / "demos").glob("*/**/experiment.py")
    }

    assert sorted(demos - listed) == [], "Demos missing from docs/demos/index.rst"
    assert sorted(listed - demos) == [], "Catalog entries without a demo"
