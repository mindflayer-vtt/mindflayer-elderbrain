"""Fetch only official published serial-install releases; verify before use."""
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request

from serial_bundle import LIMIT, unique_object, verify

REPOSITORY = "mindflayer-vtt/mindflayer-keypad"
API = "https://api.github.com/repos/" + REPOSITORY + "/releases/"


def version_string(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value):
        raise ValueError("Select a stable firmware release version")
    return value


def safe_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or
            parsed.hostname not in {"api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}):
        raise ValueError("Unsafe firmware download URL")
    return url


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        safe_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def fetch(url, maximum):
    request = urllib.request.Request(safe_url(url), headers={"User-Agent": "mindflayer-elderbrain", "Accept": "application/vnd.github+json" if url.startswith(API) else "application/octet-stream"})
    with urllib.request.build_opener(ReleaseRedirect()).open(request, timeout=30) as response:
        safe_url(response.url)
        if response.status != 200:
            raise ValueError("Firmware download failed")
        size = response.headers.get("Content-Length")
        if size is not None and (not size.isdigit() or int(size) > maximum):
            raise ValueError("Firmware response exceeds size limit")
        chunks, received = [], 0
        deadline = time.monotonic() + 120
        while received <= maximum:
            if time.monotonic() > deadline:
                raise TimeoutError("Firmware download exceeded its deadline")
            chunk = response.read1(min(65536, maximum + 1 - received))
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
        data = b"".join(chunks)
        if len(data) > maximum or (size is not None and len(data) != int(size)):
            raise ValueError("Invalid firmware response size")
        return data


def release(version=None):
    endpoint = "latest" if version is None else "tags/v" + version_string(version)
    metadata = json.loads(fetch(API + endpoint, 1024 * 1024), object_pairs_hook=unique_object)
    if (not isinstance(metadata, dict) or metadata.get("draft") is not False or metadata.get("prerelease") is not False or
            not isinstance(metadata.get("tag_name"), str) or not metadata["tag_name"].startswith("v")):
        raise ValueError("Firmware release is not a published stable release")
    selected = version_string(metadata["tag_name"][1:])
    if version is not None and selected != version:
        raise ValueError("Firmware release version mismatch")
    name = "mindflayer-keypad-" + selected + "-serial-install.tar.gz"
    assets = metadata.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Invalid firmware release assets")
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == name]
    if len(matches) != 1:
        raise ValueError("This release has no unique serial-install bundle; OTA artifacts cannot initialize a keypad")
    asset = matches[0]
    expected_url = "https://github.com/" + REPOSITORY + "/releases/download/v" + selected + "/" + name
    if asset.get("browser_download_url") != expected_url or type(asset.get("size")) is not int or not 0 < asset["size"] <= LIMIT:
        raise ValueError("Invalid serial-install release asset")
    return {"version": selected, "url": expected_url, "size": asset["size"]}


def download(version, destination, public_key):
    selected = release(version)
    data = fetch(selected["url"], LIMIT)
    if len(data) != selected["size"]:
        raise ValueError("Serial-install download size differs from release metadata")
    destination = Path(destination)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    # A failed signature leaves a private, untrusted artifact for diagnostics;
    # callers must not execute it or treat its existence as successful download.
    manifest, _ = verify(destination, public_key, expected_version=version)
    return manifest
