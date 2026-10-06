"""The label documentation required by Stage S4 exists in ``docs/data_dictionary.md``."""

from __future__ import annotations

import pytest

from nasdaq100.labels.forward_returns import LABEL_STEMS
from nasdaq100.paths import docs_dir


@pytest.mark.unit
def test_data_dictionary_documents_every_label_column() -> None:
    path = docs_dir() / "data_dictionary.md"
    assert path.is_file(), "docs/data_dictionary.md is a required S4 deliverable"
    text = path.read_text(encoding="utf-8")
    for stem in LABEL_STEMS:
        assert f"{stem}{{h}}" in text, stem  # documented as e.g. `ret_fwd_h{h}`
    for fragment in (
        "labels.parquet",
        "adj_open",  # open-to-open (D4)
        "t_idx + 1 + h",  # the exit index definition
        "Evaluation uses `excess_h",  # evaluation vs training target must not be mixed
        "training uses `y_reg_h",
        "labels.winsor_pct",
        "load_labels",
    ):
        assert fragment in text, fragment
