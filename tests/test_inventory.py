from contextlib import redirect_stderr, redirect_stdout
from html import escape
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import quote
from zipfile import ZipFile

from qgis_projekt_inventar import classify_source, redact
from qgis_projekt_inventar.cli import main
from qgis_projekt_inventar.projects import read_project


def layer(layer_id="roads", name="Straßen", provider="ogr", source="./roads.gpkg"):
    return (
        f'<maplayer type="vector" geometry="Line"><id>{escape(layer_id)}</id>'
        f'<layername>{escape(name)}</layername><provider>{escape(provider)}</provider>'
        f'<datasource>{escape(source)}</datasource>'
        '<srs><spatialrefsys><authid>EPSG:25832</authid></spatialrefsys></srs></maplayer>'
    )


def project_xml(layers="", tree=""):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<qgis version="3.40.0" projectname="Ersatztitel"><title>Verkehr</title>'
        '<projectCrs><spatialrefsys><authid>EPSG:25832</authid></spatialrefsys></projectCrs>'
        '<properties><Paths><Absolute>false</Absolute></Paths></properties>'
        f'{tree}<projectlayers>{layers}</projectlayers></qgis>'
    )


class InventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return path

    def run_cli(self, *args):
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            try:
                code = main([str(arg) for arg in args])
            except SystemExit as exit:
                code = exit.code
        return code, output.getvalue(), errors.getvalue()

    def test_qgs_and_qgz_have_identical_layers(self):
        original = self.write("projekt.qgs", project_xml(layer()))
        self.write("roads.gpkg", b"")
        archive = self.root / "projekt.qgz"
        with ZipFile(archive, "w") as zipped:
            zipped.writestr("styles.db", b"")
            zipped.write(original, "inner/first.QGS")
            zipped.writestr("second.qgs", "<broken/>")
        qgs = read_project(original)
        qgz = read_project(archive)
        self.assertIsNone(qgs["error"])
        self.assertIsNone(qgz["error"])
        self.assertEqual(qgs["layers"], qgz["layers"])
        self.assertEqual(qgz["title"], "Verkehr")
        self.assertEqual(qgz["qgis_version"], "3.40.0")
        self.assertEqual(qgz["crs"], "EPSG:25832")
        self.assertEqual(qgz["path_mode"], "relativ")
        self.assertEqual(qgz["format"], "qgz")
        self.assertEqual(qgz["size"], archive.stat().st_size)
        self.assertEqual(qgz["layers"][0]["geometry"], "Line")

    def test_existing_relative_and_missing_absolute_source(self):
        present = self.write("data/roads.gpkg", b"")
        missing = self.root / "missing.gpkg"
        for value in ("data/roads.gpkg", ".\\data\\roads.gpkg"):
            with self.subTest(value=value):
                source = classify_source("ogr", value, self.root)
                self.assertEqual((source.kind, source.path, source.status), ("file", present, "ok"))
        for value in (str(missing), missing.as_posix()):
            with self.subTest(value=value):
                source = classify_source("ogr", value, self.root)
                self.assertEqual((source.path, source.status), (missing, "missing"))

    def test_file_source_wrappers(self):
        gpkg = self.write("daten.gpkg", b"")
        archive = self.write("karten.zip", b"")
        csv = self.write("daten mit Leerzeichen.csv", b"")
        cases = [
            ("ogr", "./daten.gpkg|layername=x", gpkg),
            ("gdal", f"GPKG:{gpkg}:raster", gpkg),
            ("gdal", "/vsizip/./karten.zip/subdir/roads.shp", archive),
            ("delimitedtext", f"{csv.as_uri()}?delimiter=%2C", csv),
            ("spatialite", "dbname='./daten.gpkg' table='roads' (geom)", gpkg),
        ]
        for provider, value, expected in cases:
            with self.subTest(provider=provider, value=value):
                source = classify_source(provider, value, self.root)
                self.assertEqual((source.kind, source.path, source.status), ("file", expected, "ok"))

    def test_credentials_are_absent_from_all_reports(self):
        raw_url = "https://angela:heimlich@host/wms?service=WMS&token=privat%26nachtrag"
        project = self.write("credentials.qgs", project_xml(
            layer("db", "Datenbank", "postgres", "user='ludwig' password='geheim' authcfg=abc123")
            + layer("web", "Kartenserver", "wms", "url=" + raw_url)
            + layer("encoded", "Kodierter Kartenserver", "wms", "url=" + quote(raw_url, safe=""))
        ))
        for output_format in ("md", "html", "json"):
            with self.subTest(output_format=output_format):
                code, output, errors = self.run_cli(project, "--format", output_format)
                self.assertEqual((code, errors), (0, ""))
                for secret in ("ludwig", "geheim", "angela", "heimlich", "privat", "nachtrag"):
                    self.assertNotIn(secret, output)
                self.assertIn("authcfg=abc123", output)
                self.assertIn("@host/wms", output)

    def test_redact(self):
        self.assertEqual(
            redact("USER=person password='mit Leerzeichen' authcfg=public"),
            "USER=*** password=*** authcfg=public",
        )
        self.assertEqual(redact("password='it''s secret'"), "password=***")
        for key in ("password", "pass", "token", "apikey", "api_key", "key", "access_token", "%74oken"):
            with self.subTest(key=key):
                self.assertEqual(
                    redact(f"HTTPS://person:secret@host/?{key}=confidential&ok=yes"),
                    f"HTTPS://***@host/?{key}=***&ok=yes",
                )

    def test_redact_username_and_percent_encoded_queries(self):
        self.assertEqual(redact("username='person' url='https://h/wfs'"),
                         "username=*** url='https://h/wfs'")
        self.assertEqual(
            redact("url=https://h/wms?map%3D/a.map%26token%3Dgeheim%26x%3D1"),
            "url=https://h/wms?map%3D/a.map%26token%3D***%26x%3D1",
        )
        source = classify_source(
            "wms", "crs=EPSG:25832&password=g1&url=https://h/wms?TOKEN%3Dg2&username=person",
            Path("."),
        )
        self.assertEqual(source.display, "https://h/wms?TOKEN%3D***&username=***")
        source = classify_source("wfs", "password='g3' url='https://h/wfs' username='person'", Path("."))
        self.assertEqual(source.display, "https://h/wfs")

    def test_doctype_and_entity_are_reported_without_aborting(self):
        self.write("a.qgs", '<?xml version="1.0"?><!-- Kommentar -->'
                   '<!DOCTYPE qgis [<!ENTITY item "geheim">]><qgis/>')
        self.write("b.qgs", '<!ENTITY item "geheim"><qgis/>')
        self.write("c.qgs", '<!DOCTYPE qgis SYSTEM "file:///not-read"><qgis/>'.encode("utf-16"))
        self.write("d.qgs", '<!-- <!DOCTYPE qgis> --><qgis version="3.40"/>')
        code, output, errors = self.run_cli(self.root, "--format", "json")
        report = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(report["summary"]["projects_with_errors"], 3)
        self.assertEqual([p["error"] for p in report["projects"]], ["DOCTYPE nicht erlaubt"] * 3 + [None])
        self.assertEqual(errors.count("Warnung:"), 3)
        self.assertNotIn("geheim", output + errors)

    def test_bad_zip_and_zip_without_qgs_do_not_abort(self):
        self.write("a.qgz", b"not a ZIP")
        with ZipFile(self.root / "b.qgz", "w") as archive:
            archive.writestr("not-a-project.txt", "<qgis/>")
        self.write("c.qgs", project_xml(layer()))
        code, output, errors = self.run_cli(self.root, "--format", "json")
        report = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(report["summary"]["projects_with_errors"], 2)
        self.assertIn("ZIP", report["projects"][0]["error"])
        self.assertIn("keine .qgs", report["projects"][1]["error"])
        self.assertEqual(report["projects"][2]["layers"][0]["name"], "Straßen")
        self.assertEqual(errors.count("Warnung:"), 2)

    def test_directory_search(self):
        top = self.write("Z.QGS", project_xml())
        child = self.write("unterordner/a.QgS", project_xml())
        self.write("backup.qgs~", b"")
        self.write("backup.qgz~", b"")
        self.write(".git/hidden.qgs", b"")
        self.write("unterordner/.git/hidden.qgz", b"")
        self.assertEqual(self.run_cli(self.root, ".git", "--format", "json")[0], 0)
        for options, expected in (([], [child, top]), (["--no-recursive"], [top])):
            with self.subTest(options=options):
                code, output, errors = self.run_cli(self.root, top, "--format", "json", *options)
                self.assertEqual((code, errors), (0, ""))
                files = [Path(p["file"]) for p in json.loads(output)["projects"]]
                self.assertEqual(files, expected)

    def test_html_escapes_script_and_markdown_escapes_pipes(self):
        path = self.write("projekt.qgs", project_xml(layer(name="<script> | Straßen")))
        _, html, _ = self.run_cli(path, "--format", "html")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt; | Straßen", html)
        self.assertIn('class="missing"', html)
        _, md, _ = self.run_cli(path)
        self.assertIn(r"| &lt;script&gt; \| Straßen | vector |", md)
        self.assertIn("### Fehlende Quellen", md)

    def test_nested_group_paths(self):
        tree = (
            '<layer-tree-group name=""><layer-tree-group name="Grundlagen">'
            '<layer-tree-group name="Verkehr"><layer-tree-layer id="roads"/>'
            '</layer-tree-group></layer-tree-group></layer-tree-group>'
        )
        path = self.write("gruppen.qgs", project_xml(layer() + layer("unlisted"), tree))
        self.assertEqual(
            [entry["group"] for entry in read_project(path)["layers"]],
            ["Grundlagen / Verkehr", ""],
        )

    def test_exit_codes(self):
        missing = self.write("missing.qgs", project_xml(layer()))
        present = self.write("present.qgs", project_xml(layer(source="./present.gpkg")))
        self.write("present.gpkg", b"")
        broken = self.write("broken.qgs", "<not-qgis/>")
        empty = self.root / "empty"
        empty.mkdir()
        for args, expected in (
            ((missing,), 0), ((missing, "--fail-on-missing"), 1),
            ((present, "--fail-on-missing"), 0), ((broken, "--fail-on-missing"), 0),
            ((broken, missing, "--fail-on-missing"), 1), ((empty,), 2),
            ((present, self.root / "absent"), 2), ((), 2),
            ((present, "--format", "csv"), 2),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.run_cli(*args)[0], expected)

    def test_module_entry_point_writes_utf8_output_file(self):
        path = self.write("projekt.qgs", project_xml(layer(name="Straßen 日本語")))
        report = self.root / "bericht.json"
        result = subprocess.run(
            [sys.executable, "-m", "qgis_projekt_inventar", str(path),
             "--format", "json", "-o", str(report)],
            capture_output=True,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertIn("Straßen 日本語", report.read_text(encoding="utf-8"))
        self.assertEqual(self.run_cli(path, "-o", path)[0], 2)
        self.assertIn("<qgis", path.read_text(encoding="utf-8"))

    def test_source_kinds_that_are_not_checked(self):
        for provider, value, kind in (
            ("ogr", "https://host/data.gpkg", "url"),
            ("gdal", "/vsicurl/ftp://host/file.tif", "url"),
            ("pdal", "http://host/points.laz", "url"),
            ("oracle", "server=host", "database"),
            ("virtual", "query=select 1", "memory"),
            ("xyz", "url=https://host/{z}/{x}/{y}", "url"),
            ("plugin", "example", "other"),
        ):
            with self.subTest(provider=provider, value=value):
                source = classify_source(provider, value, self.root)
                self.assertEqual((source.kind, source.path, source.status), (kind, None, "not-checked"))

    def test_oversized_zip_member_is_rejected_before_reading(self):
        path = self.root / "oversized.qgz"
        with ZipFile(path, "w") as archive:
            archive.writestr("large.qgs", "<qgis/>")
        with patch("qgis_projekt_inventar.projects.MAX_MEMBER_SIZE", 6):
            with patch.object(ZipFile, "read", side_effect=AssertionError("Member read")):
                self.assertIn("zu gro\u00df", read_project(path)["error"])

    def test_xml_encoding_and_project_defaults(self):
        xml = '<?xml version="1.0" encoding="ISO-8859-1"?><qgis projectname="\u00d6PNV"/>'
        project = read_project(self.write("kodierung.qgs", xml.encode("iso-8859-1")))
        self.assertIsNone(project["error"])
        self.assertEqual(project["title"], "\u00d6PNV")
        self.assertEqual(project["crs"], "")
        self.assertEqual(project["path_mode"], "unbekannt")
