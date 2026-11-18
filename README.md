# QGIS-Projektinventar

Das Kommandozeilenwerkzeug liest QGIS-Projekte (`.qgs` und `.qgz`) und listet
Layer, Datenquellen und Koordinatenbezugssysteme (KBS) auf. Es prüft, ob
dateibasierte Quellen existieren, und verändert die Projekte dabei nicht.
QGIS und zusätzliche Python-Laufzeitpakete werden nicht benötigt.

## Installation

Voraussetzung ist Python 3.10 oder neuer. Im Repository unter PowerShell mit
`uv` eine lokale Umgebung anlegen, das Paket editierbar installieren und die
Umgebung aktivieren.

```powershell
uv venv
uv pip install -e .
.\.venv\Scripts\Activate.ps1
```

Alternativ lässt sich das Paket mit `pip` in einer lokalen Umgebung installieren.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Nach der Installation sind `qgis-inventar` und `python -m qgis_projekt_inventar`
gleichwertig.

## Verwendung

```powershell
qgis-inventar .\verkehr.qgz
qgis-inventar .\projekte .\archiv --format html -o inventar.html
qgis-inventar .\projekte --no-recursive --format json --fail-on-missing
```

Die Ordnersuche ist standardmäßig rekursiv. Sie überspringt `.git`-Ordner
und QGIS-Sicherungsdateien. Standardmäßig erscheint Markdown auf stdout.
`--format` wählt Markdown (`md`), HTML oder JSON. Mit `-o DATEI` wird der
Bericht als UTF-8-Datei gespeichert.

| Exit-Code | Bedeutung |
| --- | --- |
| 0 | Inventar erstellt |
| 1 | Mindestens eine Dateiquelle fehlt und `--fail-on-missing` ist aktiv |
| 2 | Aufruffehler, etwa ein ungültiger Eingabepfad oder ein Ordner ohne Projekte |

Fehlerhafte Projektdateien erscheinen mit Fehlermeldung im Bericht.
Die Warnung geht zusätzlich an stderr. Die übrigen Projekte werden weiter ausgewertet.

## Beispielausgabe

Dieser Markdown-Ausschnitt stammt aus einem Werkzeuglauf mit einem synthetischen
Projekt. Die Projektkopfdaten sind im Ausschnitt ausgelassen.

```markdown
## Zusammenfassung

- Projekte: 1
- Layer gesamt: 2
- Fehlende Quellen gesamt: 1
- Verwendete KBS: EPSG:25832 (3)
- Projekte mit Fehlern: 0

| Gruppe | Name | Typ | Provider | KBS | Quelle | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Grundlagen / Verkehr | Straßen | vector | ogr | EPSG:25832 | ./strassen.gpkg\|layername=strassen | ok |
| Grundlagen / Verkehr | Haltestellen | vector | ogr | EPSG:25832 | ./haltestellen.gpkg | fehlt |

### Fehlende Quellen

- Haltestellen: ./haltestellen.gpkg
```

## Weitergabe und Grenzen

Der Bericht enthält lokale Pfade. Prüfe den Bericht vor der Weitergabe.
Zugangsdaten werden geschwärzt. Datenbank- und Webquellen werden eingestuft,
aber nicht auf Erreichbarkeit geprüft. Das Werkzeug wertet Stile, Plugins
und Layouts nicht aus und repariert keine Pfade.

## Tests

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests
```

## Lizenz

[MIT](LICENSE) © 2026 Lukas Willmy
