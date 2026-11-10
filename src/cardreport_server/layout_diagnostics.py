"""Allowlisted optional layout metadata at the renderer process boundary."""

from cardreport import LayoutDiagnostic


def validated_diagnostic(value: object) -> dict[str, object] | None:
    try:
        return LayoutDiagnostic.from_dict(value).to_dict()
    except ValueError:
        return None
