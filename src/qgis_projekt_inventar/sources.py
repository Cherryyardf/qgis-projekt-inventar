from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
import re
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname


_FILE_PROVIDERS = {"ogr", "gdal", "mdal", "pdal", "spatialite"}
_DATABASE_PROVIDERS = {"postgres", "mssql", "oracle", "hana", "db2"}
_URL_PROVIDERS = {
    "wms", "wfs", "wcs", "arcgismapserver", "arcgisfeatureserver", "vectortile", "xyz",
}
_WEB_URL = re.compile(r"^(?:https?|ftp)://", re.IGNORECASE)
_SECRET_KEYS = {
    "password", "pass", "token", "apikey", "api_key", "key", "access_token",
    "user", "username",
}
_ASSIGNMENT = re.compile(
    r"""(?<![\w%])((?:password|username|user)\s*=\s*)(?:'(?:\\.|''|[^'\\])*'|"(?:\\.|""|[^"\\])*"|[^\s&#|;]*)""",
    re.IGNORECASE,
)
_USERINFO = re.compile(r"([a-z][a-z\d+.-]*://)[^/\s?#]*@", re.IGNORECASE)
_QUERY = re.compile(r"([?&;])([^?&;=#\s]+)=([^&#\s;|]*)")
# Percent-encoded nested queries, e.g. url=https://host/wms?token%3Dabc%26x%3D1
_ENCODED_QUERY = re.compile(r"(%3F|%26|[?&;])([^?&;=#\s%]+)%3D((?:(?!%26)[^&#\s;|])*)", re.IGNORECASE)
_DBNAME = re.compile(r"(?<!\w)dbname\s*=\s*'((?:''|[^'])*)'", re.IGNORECASE)
_URL_PARAMETER = re.compile(r"(?:^|[&\s])url=([^\s]+)", re.IGNORECASE)


@dataclass(frozen=True)
class SourceInfo:
    kind: str
    path: Path | None
    display: str
    status: str


def redact(text: str) -> str:
    def redact_query(match: re.Match) -> str:
        separator, name, value = match.groups()
        if unquote(name).lower() in _SECRET_KEYS:
            value = "***"
        return f"{separator}{name}={value}"

    text = _USERINFO.sub(r"\1***@", text)
    text = _ASSIGNMENT.sub(r"\1***", text)
    text = _QUERY.sub(redact_query, text)
    return _ENCODED_QUERY.sub(
        lambda m: f"{m[1]}{m[2]}%3D***" if unquote(m[2]).lower() in _SECRET_KEYS else m[0],
        text,
    )


def _file_source(value: str, display: str, project_dir: Path) -> SourceInfo:
    if not value:
        return SourceInfo("file", None, display, "missing")
    path = Path(value.replace("\\", "/"))
    windows_path = PureWindowsPath(value)
    if not path.is_absolute() and not windows_path.is_absolute():
        path = project_dir / path
    try:
        path = path.resolve() if path.is_absolute() or not windows_path.is_absolute() else path
        exists = path.exists()
    except (OSError, ValueError, RuntimeError):
        exists = False
    return SourceInfo("file", path, display, "ok" if exists else "missing")


def classify_source(provider: str, datasource: str, project_dir: Path) -> SourceInfo:
    provider = provider.strip().lower()
    display = redact(datasource)
    value = datasource.strip()
    if provider in _FILE_PROVIDERS:
        value = value.split("|", 1)[0].strip()
        if value.upper().startswith("GPKG:"):
            value = value[5:]
            separator = value.lower().rfind(".gpkg:")
            if separator != -1:
                value = value[:separator + len(".gpkg")]
        database = _DBNAME.search(value)
        if database:
            value = database[1].replace("''", "'")
        if value.lower().startswith("/vsizip/"):
            value = re.split(r"(?i)(?<=\.zip)[/\\]", value[8:], maxsplit=1)[0]
        if value.lower().startswith("/vsicurl/") or _WEB_URL.match(value):
            return SourceInfo("url", None, display, "not-checked")
        return _file_source(value, display, project_dir)

    if provider == "delimitedtext" and value.lower().startswith("file://"):
        try:
            url = urlsplit(value)
            host = f"//{url.netloc}" if url.netloc and url.netloc.lower() != "localhost" else ""
            return _file_source(url2pathname(host + url.path), display, project_dir)
        except ValueError:
            return SourceInfo("file", None, display, "missing")
    if provider in _DATABASE_PROVIDERS:
        return SourceInfo("database", None, display, "not-checked")
    if provider in _URL_PROVIDERS:
        parameter = _URL_PARAMETER.search(value)
        if parameter:
            # The value can be URL-encoded or contain its own unescaped query.
            url = parameter[1].strip("'\"")
            if "?" not in url:
                url = url.split("&", 1)[0]
            if not _WEB_URL.match(url):
                url = unquote(url)
            display = redact(url)
        return SourceInfo("url", None, display, "not-checked")
    if provider in {"memory", "virtual"}:
        return SourceInfo("memory", None, display, "not-checked")
    return SourceInfo("other", None, display, "not-checked")
