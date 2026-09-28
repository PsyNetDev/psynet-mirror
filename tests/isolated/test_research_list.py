import importlib.util
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_research_list():
    path = ROOT / "docs" / "_ext" / "research_list.py"
    spec = importlib.util.spec_from_file_location("research_list", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_example_publication_labels_and_urls():
    module = _load_research_list()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        source = module._BibTeX(
            str(ROOT / "docs" / "introduction" / "research.bib"),
            encoding="utf-8",
        )

    assert module._cite_label(source["marjieh2024timbre"]) == "Marjieh et al. (2024)"
    assert (
        module._paper_url(source["marjieh2024timbre"])
        == "https://doi.org/10.1038/s41467-024-45812-z"
    )
    assert module._cite_label(source["harrison2020gibbs"]) == "Harrison et al. (2020)"
    assert module._cite_label(source["vanrijn2022gap"]) == "van Rijn et al. (2022)"
    assert module._keys_for_tag(source, "groups") == []
    assert module._keys_for_tag(source, "rating") == ["marjieh2024timbre"]
