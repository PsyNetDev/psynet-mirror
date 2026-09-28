import importlib.util
import warnings
from pathlib import Path

import pytest

pytest.importorskip("citeproc", reason="citeproc-py is a docs-only dependency")

ROOT = Path(__file__).resolve().parents[2]


def _load_research_list():
    path = ROOT / "docs" / "_ext" / "research_list.py"
    spec = importlib.util.spec_from_file_location("research_list", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BIB = """
@article{old,
  author = {Smith, Ann and Jones, Bob and Lee, Cy}, title = {Old}, year = {2020},
  doi = {10.1000/old}, keywords = {rating},
}
@article{new,
  author = {{van Rijn}, Pol and Smith, Ann}, title = {New}, year = {2024},
  url = {https://example.org/new}, keywords = {rating, chains},
}
"""


def test_example_publication_labels_urls_and_order(tmp_path):
    module = _load_research_list()
    bib = tmp_path / "research.bib"
    bib.write_text(BIB, encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        source = module._BibTeX(str(bib), encoding="utf-8")

    assert module._cite_label(source["old"]) == "Smith et al. (2020)"
    assert module._cite_label(source["new"]) == "van Rijn & Smith (2024)"
    assert module._paper_url(source["old"]) == "https://doi.org/10.1000/old"
    assert module._paper_url(source["new"]) == "https://example.org/new"
    assert module._keys_for_tag(source, "rating") == ["new", "old"]
    assert module._keys_for_tag(source, "groups") == []
