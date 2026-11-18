import argparse
from pathlib import Path
import sys

from .projects import PROJECT_SUFFIXES, ProjectError, discover_projects, read_project
from .reports import make_report, render_report
from .sources import redact


class InventoryParser(argparse.ArgumentParser):
    def format_usage(self) -> str:
        return super().format_usage().replace("usage: ", "Aufruf: ", 1)

    def format_help(self) -> str:
        return super().format_help().replace("usage: ", "Aufruf: ", 1)

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: Aufruffehler: {redact(message)}\n")


def _parser() -> argparse.ArgumentParser:
    parser = InventoryParser(
        prog="qgis-inventar",
        usage="qgis-inventar PFAD [PFAD ...] [--format md|html|json] [-o DATEI] "
              "[--no-recursive] [--fail-on-missing]",
        description="Erstellt ein Inventar aus QGIS-Projektdateien.",
        add_help=False,
    )
    positional = parser.add_argument_group("Eingabe")
    positional.add_argument("paths", nargs="+", metavar="PFAD", type=Path,
                            help="QGIS-Projektdatei oder Ordner")
    options = parser.add_argument_group("Optionen")
    options.add_argument("-h", "--help", action="help", help="Diese Hilfe anzeigen")
    options.add_argument("--format", choices=("md", "html", "json"), default="md",
                         help="Berichtsformat (Standard: md)")
    options.add_argument("-o", metavar="DATEI", type=Path, help="Bericht als UTF-8-Datei speichern")
    options.add_argument("--no-recursive", action="store_true",
                         help="Unterordner bei der Suche überspringen")
    options.add_argument("--fail-on-missing", action="store_true",
                         help="Exit-Code 1 bei fehlenden Datenquellen zurückgeben")
    return parser


def _write_report(destination: Path, report: str, projects: list[Path]) -> None:
    if any(path.suffix.lower() in PROJECT_SUFFIXES for path in (destination, destination.resolve())):
        raise ProjectError("Ausgabedatei darf keine QGIS-Projektdatei sein")
    if destination.exists() and any(destination.samefile(project) for project in projects if project.exists()):
        raise ProjectError("Ausgabedatei darf keine QGIS-Projektdatei sein")
    destination.write_text(report, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        paths = discover_projects(args.paths, recursive=not args.no_recursive)
        if not paths:
            raise ProjectError("Keine QGIS-Projekte gefunden")
        projects = [read_project(path) for path in paths]
        for project in projects:
            if project["error"]:
                print(f'Warnung: {project["file"]}: {project["error"]}', file=sys.stderr)
        report = make_report(projects)
        output = render_report(report, args.format)
        if args.o is None:
            if hasattr(sys.stdout, "buffer") and not sys.stdout.isatty():
                sys.stdout.buffer.write(output.encode("utf-8"))
            else:
                sys.stdout.write(output)
        else:
            _write_report(args.o, output, paths)
    except (OSError, ProjectError, RuntimeError) as error:
        print(f"Aufruffehler: {redact(str(error))}", file=sys.stderr)
        return 2
    return int(args.fail_on_missing and report["summary"]["missing_sources"] > 0)
