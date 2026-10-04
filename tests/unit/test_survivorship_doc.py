"""The survivorship documentation required by Stage S2 exists and keeps its mandatory content."""

from __future__ import annotations

import pytest

from nasdaq100.paths import docs_dir


@pytest.mark.unit
def test_survivorship_doc_has_required_sections() -> None:
    path = docs_dir() / "survivorship.md"
    assert path.is_file(), "docs/survivorship.md is a required S2 deliverable"
    text = path.read_text(encoding="utf-8")
    assert "SURVIVOR-BIASED" in text
    for fragment in (
        "Evidence",  # the survivorship evidence (Part I section I.3)
        "Claims policy",  # what may and may not be claimed (Part IV section IV.4)
        "May say",
        "Must not say",
        "in_index_pit",  # the point-in-time plug-in point
        "does **not**",  # states that the universe does not cure the bias
        "load_universe",
    ):
        assert fragment in text, fragment
