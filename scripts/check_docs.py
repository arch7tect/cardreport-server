"""Check local documentation links, bundled examples and deployment YAML syntax."""

import json
import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml
from cardreport import ReportTemplate, datasets_from_json, datasets_from_yaml
from cardreport.adapters.csv import from_csv

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    checked = 0
    for source in [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", source.read_text()):
            url = urlsplit(target)
            if url.scheme or not url.path:
                continue
            path = (source.parent / unquote(url.path)).resolve()
            assert path.exists(), f"{source.relative_to(ROOT)}: missing {target}"
            if url.fragment and path.suffix == ".md":
                headings = [
                    re.sub(r"[^\w\- ]", "", line.lstrip("# ").lower()).replace(" ", "-")
                    for line in path.read_text().splitlines()
                    if line.startswith("#")
                ]
                assert unquote(url.fragment) in headings, (
                    f"{source.relative_to(ROOT)}: missing anchor {target}"
                )
            checked += 1
    for template_path in (ROOT / "examples").glob("*_template.*"):
        data_path = template_path.with_name(
            template_path.name.replace("_template.", "_data.")
        )
        if template_path.suffix == ".json":
            template = ReportTemplate.from_json(template_path.read_bytes())
            datasets = datasets_from_json(data_path.read_bytes())
        else:
            template = ReportTemplate.from_yaml(template_path.read_bytes())
            datasets = datasets_from_yaml(data_path.read_bytes())
        template.bind(datasets).to_html()
    reference = ReportTemplate.from_json(
        (ROOT / "examples/reference_template.json").read_bytes()
    )
    csv_data = {
        path.stem: from_csv(path, schema=reference.datasets[path.stem])
        for path in (ROOT / "examples/reference_csv").glob("*.csv")
    }
    json_data = datasets_from_json((ROOT / "examples/reference_data.json").read_bytes())
    assert csv_data.keys() == json_data.keys()
    for name, dataset in csv_data.items():
        assert dataset.columns == json_data[name].columns
        # CSV decimal fields are exact Decimals; this JSON fixture uses numbers.
        assert dataset.rows == tuple(
            tuple(
                Decimal(str(value)) if isinstance(value, float) else value
                for value in row
            )
            for row in json_data[name].rows
        )
    reference.bind(csv_data).to_html()
    mixed = {name: csv_data[name] for name in ("summary", "funnel")}
    mixed.update(
        datasets_from_json(
            (ROOT / "examples/reference_mixed/activity.json").read_bytes()
        )
    )
    mixed.update(
        datasets_from_yaml(
            (ROOT / "examples/reference_mixed/schedule.yaml").read_bytes()
        )
    )
    assert mixed.keys() == json_data.keys()
    reference.bind(mixed).to_html()
    for path in (ROOT / "deploy").rglob("*.yaml"):
        for item in yaml.safe_load_all(path.read_text()):
            assert isinstance(item, dict) and "apiVersion" in item and "kind" in item, (
                path
            )
    manifest = json.loads((ROOT / "docs/swagger-assets.json").read_text())
    assert manifest
    print(
        f"{checked} local links, all bundled template/data examples and deployment YAML passed"
    )


if __name__ == "__main__":
    main()
