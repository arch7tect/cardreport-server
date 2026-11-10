import pytest

from cardreport_server.layout_diagnostics import validated_diagnostic


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"reason": "label_overlap", "path": "SECRET"},
        {"reason": "label_overlap", "path": "blocks.0", "text": "SECRET"},
        {
            "reason": "content_overflow",
            "path": "blocks.0",
            "box": "content",
            "overflow_bottom_mm": 10**400,
        },
    ],
)
def test_invalid_layout_diagnostics_are_dropped(value: object) -> None:
    assert validated_diagnostic(value) is None


def test_valid_layout_diagnostic_survives() -> None:
    value = {
        "reason": "content_overflow",
        "path": "blocks.0.1.content",
        "page": 2,
        "box": "content",
        "overflow_bottom_mm": 12.5,
    }
    assert validated_diagnostic(value) == value
