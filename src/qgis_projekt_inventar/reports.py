from collections import Counter
from datetime import datetime
from html import escape
import json
import re


_COLUMNS = ("Gruppe", "Name", "Typ", "Provider", "KBS", "Quelle", "Status")
_STATUS = {"ok": "ok", "missing": "fehlt", "not-checked": "nicht geprüft"}
_STYLE = """
:root { color-scheme: light dark; background: #fff; color: #20252b; }
body { font: 1rem/1.5 system-ui, sans-serif; margin: 2rem auto; padding: 0 1rem; max-width: 80rem; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: .45rem; border: 1px solid #888; text-align: left; overflow-wrap: anywhere; }
.table { overflow-x: auto; }
.missing { color: #ae1515; font-weight: bold; }
@media (prefers-color-scheme: dark) {
  :root { background: #191d22; color: #eee; }
  .missing { color: #ff8d8d; }
}
"""


def make_report(projects: list[dict]) -> dict:
    layers = [layer for project in projects for layer in project["layers"]]
    crs_counts = Counter(item["crs"] for item in [*projects, *layers] if item["crs"])
    return {
        "generated": datetime.now().astimezone().isoformat(),
        "summary": {
            "projects": len(projects),
            "layers": len(layers),
            "missing_sources": sum(layer["source"]["status"] == "missing" for layer in layers),
            "crs": dict(sorted(crs_counts.items())),
            "projects_with_errors": sum(project["error"] is not None for project in projects),
        },
        "projects": projects,
    }


def _summary_items(summary: dict) -> list[tuple[str, object]]:
    crs = ", ".join(f"{name} ({count})" for name, count in summary["crs"].items())
    return [
        ("Projekte", summary["projects"]),
        ("Layer gesamt", summary["layers"]),
        ("Fehlende Quellen gesamt", summary["missing_sources"]),
        ("Verwendete KBS", crs or "keine"),
        ("Projekte mit Fehlern", summary["projects_with_errors"]),
    ]


def _project_items(project: dict) -> list[tuple[str, object]]:
    return [
        ("Datei", project["file"]),
        ("Größe", f'{project["size"]} Byte' if project["size"] is not None else "unbekannt"),
        ("Änderungszeit", project["modified"] or "unbekannt"),
        ("Format", project["format"]),
        ("QGIS-Version", project["qgis_version"]),
        ("Projekttitel", project["title"]),
        ("Projekt-KBS", project["crs"]),
        ("Pfadmodus", project["path_mode"]),
    ]


def _layer_values(layer: dict) -> tuple[str, ...]:
    source = layer["source"]
    return (
        layer["group"], layer["name"], layer["type"], layer["provider"],
        layer["crs"], source["display"], _STATUS[source["status"]],
    )


def _missing_sources(project: dict) -> list[str]:
    return [
        f'{layer["name"]}: {layer["source"]["display"]}'
        for layer in project["layers"] if layer["source"]["status"] == "missing"
    ]


def _md(value: object) -> str:
    text = escape(str(value), quote=False)
    text = re.sub(r"([\\|*_~\x60\[\]#!])", r"\\\1", text)
    return " ".join(text.splitlines())


def _markdown(report: dict) -> str:
    lines = ["# QGIS-Projektinventar", "", "## Zusammenfassung", ""]
    lines.extend(f"- {label}: {_md(value)}" for label, value in _summary_items(report["summary"]))
    for project in report["projects"]:
        lines.extend(["", f'## {_md(project["title"] or project["file"])}', ""])
        lines.extend(f"- {label}: {_md(value)}" for label, value in _project_items(project))
        if project["error"]:
            lines.extend(["", f'**Fehler:** {_md(project["error"])}'])
        if project["layers"]:
            lines.extend([
                "", "| " + " | ".join(_COLUMNS) + " |",
                "| " + " | ".join("---" for _ in _COLUMNS) + " |",
            ])
            lines.extend(
                "| " + " | ".join(map(_md, _layer_values(layer))) + " |"
                for layer in project["layers"]
            )
        missing = _missing_sources(project)
        if missing:
            lines.extend(["", "### Fehlende Quellen", ""])
            lines.extend(f"- {_md(source)}" for source in missing)
    return "\n".join(lines) + "\n"


def _html(report: dict) -> str:
    def escaped_list(items: list[tuple[str, object]]) -> str:
        return "<ul>" + "".join(
            f"<li>{escape(label)}: {escape(str(value))}</li>" for label, value in items
        ) + "</ul>"

    lines = [
        '<!doctype html>', '<html lang="de">', '<head>', '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>QGIS-Projektinventar</title>', f"<style>{_STYLE}</style>", "</head>", "<body>",
        "<h1>QGIS-Projektinventar</h1>", "<h2>Zusammenfassung</h2>",
        escaped_list(_summary_items(report["summary"])),
    ]
    for project in report["projects"]:
        lines.extend([
            "<section>", f'<h2>{escape(project["title"] or project["file"])}</h2>',
            escaped_list(_project_items(project)),
        ])
        if project["error"]:
            lines.append(f'<p><strong>Fehler:</strong> {escape(project["error"])}</p>')
        if project["layers"]:
            headers = "".join(f'<th scope="col">{escape(label)}</th>' for label in _COLUMNS)
            lines.append(f'<div class="table"><table><thead><tr>{headers}</tr></thead><tbody>')
            for layer in project["layers"]:
                row = '<tr class="missing">' if layer["source"]["status"] == "missing" else "<tr>"
                lines.append(row + "".join(
                    f"<td>{escape(value)}</td>" for value in _layer_values(layer)
                ) + "</tr>")
            lines.append("</tbody></table></div>")
        missing = _missing_sources(project)
        if missing:
            lines.append('<h3>Fehlende Quellen</h3><ul class="missing">')
            lines.extend(f"<li>{escape(source)}</li>" for source in missing)
            lines.append("</ul>")
        lines.append("</section>")
    return "\n".join([*lines, "</body>", "</html>", ""])


def render_report(report: dict, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output_format == "html":
        return _html(report)
    return _markdown(report)
