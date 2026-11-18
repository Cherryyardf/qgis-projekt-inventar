from datetime import datetime
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib

from .sources import classify_source, redact


PROJECT_SUFFIXES = {".qgs", ".qgz"}
MAX_MEMBER_SIZE = 200 * 1024 * 1024
_PROLOG_TOKEN = re.compile(rb"\s*(<\?|<!--|<!\s*(?:DOCTYPE|ENTITY)\b)", re.IGNORECASE)
_PROLOG_END = {b"<?": b"?>", b"<!--": b"-->"}


class ProjectError(ValueError):
    pass


def discover_projects(inputs: list[Path], recursive: bool) -> list[Path]:
    def raise_walk_error(error: OSError) -> None:
        raise error

    projects = set()
    for path in inputs:
        if not path.exists():
            raise ProjectError(f"Pfad existiert nicht: {path}")
        if any(part.lower() == ".git" for part in path.absolute().parts):
            continue
        if path.is_dir():
            for directory, subdirs, files in os.walk(path, onerror=raise_walk_error):
                subdirs[:] = [name for name in subdirs if name.lower() != ".git" and recursive]
                projects.update(
                    (Path(directory) / name).absolute()
                    for name in files
                    if Path(name).suffix.lower() in PROJECT_SUFFIXES
                )
        elif path.is_file() and path.suffix.lower() in PROJECT_SUFFIXES:
            projects.add(path.absolute())
    return sorted(projects, key=lambda path: (str(path).casefold(), str(path)))


def _read_xml(path: Path) -> bytes:
    if path.suffix.lower() == ".qgs":
        return path.read_bytes()
    try:
        with zipfile.ZipFile(path) as archive:
            member = next(
                (entry for entry in archive.infolist()
                 if not entry.is_dir() and entry.filename.lower().endswith(".qgs")),
                None,
            )
            if member is None:
                raise ProjectError("ZIP enthält keine .qgs-Datei")
            if member.file_size > MAX_MEMBER_SIZE:
                raise ProjectError("QGS-Mitglied ist zu groß")
            return archive.read(member)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error):
        raise ProjectError("ZIP kann nicht gelesen werden") from None


def _parse_xml(data: bytes) -> ET.Element:
    # Normalize the ASCII markup of UTF-16/32 for the prolog check only.
    header = data.replace(b"\0", b"") if b"\0" in data[:8] else data
    offset = 3 if header.startswith(b"\xef\xbb\xbf") else 0
    if header.startswith((b"\xff\xfe", b"\xfe\xff")):
        offset = 2
    while token := _PROLOG_TOKEN.match(header, offset):
        closing = _PROLOG_END.get(token[1])
        if closing is None:
            raise ProjectError("DOCTYPE nicht erlaubt")
        end = header.find(closing, token.end())
        if end == -1:
            break
        offset = end + len(closing)
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, LookupError, ValueError):
        raise ProjectError("Ungültiges oder nicht unterstütztes XML") from None
    if root.tag != "qgis":
        raise ProjectError("Wurzelelement ist nicht qgis")
    return root


def _groups(root: ET.Element) -> dict[str, str]:
    groups = {}
    stack = [(node, ()) for node in reversed(root.findall("layer-tree-group"))]
    while stack:
        node, parent = stack.pop()
        if node.tag == "layer-tree-group":
            name = node.get("name", "")
            parent = (*parent, name) if name else parent
            stack.extend((child, parent) for child in reversed(list(node)))
        elif node.tag == "layer-tree-layer" and "id" in node.attrib:
            groups.setdefault(node.attrib["id"], " / ".join(parent))
    return groups


def _text(node: ET.Element, path: str) -> str:
    return node.findtext(path, "").strip()


def _layers(root: ET.Element, project_dir: Path) -> list[dict]:
    groups = _groups(root)
    layers = []
    for node in root.findall("projectlayers/maplayer"):
        layer_id = _text(node, "id")
        provider = _text(node, "provider")
        source = classify_source(provider, _text(node, "datasource"), project_dir)
        layer = {
            "id": layer_id,
            "group": groups.get(layer_id, ""),
            "name": _text(node, "layername"),
            "type": node.get("type", ""),
            "geometry": node.get("geometry", ""),
            "provider": provider,
            "crs": _text(node, "srs/spatialrefsys/authid"),
        }
        layers.append({
            **{key: redact(value) for key, value in layer.items()},
            "source": {
                "kind": source.kind,
                "path": redact(str(source.path)) if source.path is not None else None,
                "display": source.display,
                "status": source.status,
            },
        })
    return layers


def read_project(path: Path) -> dict:
    project = {
        "file": redact(str(path)),
        "size": None,
        "modified": None,
        "format": path.suffix.lower()[1:],
        "qgis_version": "",
        "title": "",
        "crs": "",
        "path_mode": "unbekannt",
        "layers": [],
        "error": None,
    }
    try:
        stat = path.stat()
        project["size"] = stat.st_size
        project["modified"] = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat()
        root = _parse_xml(_read_xml(path))
        project.update(
            qgis_version=redact(root.get("version", "")),
            title=redact(_text(root, "title") or root.get("projectname", "")),
            crs=redact(_text(root, "projectCrs/spatialrefsys/authid")),
            path_mode={"true": "absolut", "false": "relativ"}.get(
                _text(root, "properties/Paths/Absolute").lower(), "unbekannt"
            ),
            layers=_layers(root, path.parent),
        )
    except (OSError, ProjectError) as error:
        project["error"] = redact(str(error))
    return project
