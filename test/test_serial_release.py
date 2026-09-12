import json
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from serial_release import API, REPOSITORY, release, download, safe_url, fetch


class SerialReleaseTests(unittest.TestCase):
    def metadata(self):
        name = "mindflayer-keypad-1.2.3-serial-install.tar.gz"
        return {"draft": False, "prerelease": False, "tag_name": "v1.2.3", "assets": [
            {"name": name, "size": 6, "browser_download_url": "https://github.com/" + REPOSITORY + "/releases/download/v1.2.3/" + name}]}

    def test_latest_and_explicit_stable_release_selection(self):
        with patch("serial_release.fetch", return_value=json.dumps(self.metadata()).encode()) as fetch:
            self.assertEqual(release()["version"], "1.2.3")
            self.assertEqual(fetch.call_args.args[0], API + "latest")
            release("1.2.3")
            self.assertEqual(fetch.call_args.args[0], API + "tags/v1.2.3")
            with self.assertRaises(ValueError):
                release("1.2.4")

    def test_missing_bundle_duplicate_asset_and_unpublished_releases_fail_closed(self):
        invalid = []
        for key in ("draft", "prerelease"):
            metadata = self.metadata(); metadata[key] = True; invalid.append(metadata)
        metadata = self.metadata(); metadata["assets"] = []; invalid.append(metadata)
        metadata = self.metadata(); metadata["assets"] *= 2; invalid.append(metadata)
        metadata = self.metadata(); metadata["assets"][0]["browser_download_url"] = "https://attacker.invalid/bundle"; invalid.append(metadata)
        for metadata in invalid:
            with patch("serial_release.fetch", return_value=json.dumps(metadata).encode()):
                with self.assertRaises(ValueError):
                    release("1.2.3")

    def test_redirects_must_stay_on_allowlisted_https_hosts(self):
        for url in ["http://github.com/bundle", "https://github.com.attacker.invalid/bundle", "https://user@github.com/bundle",
                    "https://127.0.0.1/bundle", "https://github.com:444/bundle", "file:///tmp/bundle"]:
            with self.assertRaises(ValueError):
                safe_url(url)
        self.assertEqual(safe_url("https://release-assets.githubusercontent.com/asset?token=public"), "https://release-assets.githubusercontent.com/asset?token=public")

    def test_download_requires_signature_and_does_not_overwrite_existing_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bundle"
            with patch("serial_release.fetch", side_effect=[json.dumps(self.metadata()).encode(), b"bundle"]), patch("serial_release.verify", side_effect=ValueError("bad signature")) as verify:
                with self.assertRaisesRegex(ValueError, "signature"):
                    download("1.2.3", target, "pinned-key")
                verify.assert_called_once_with(target, "pinned-key", expected_version="1.2.3")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with patch("serial_release.fetch", side_effect=[json.dumps(self.metadata()).encode(), b"bundle"]):
                with self.assertRaises(FileExistsError):
                    download("1.2.3", target, "pinned-key")
            self.assertEqual(target.read_bytes(), b"bundle")

    def test_download_size_and_slow_response_are_bounded(self):
        def response(data, headers):
            stream = io.BytesIO(data)
            stream.status = 200
            stream.url = API + "latest"
            stream.headers = headers
            return stream
        for data, headers in [(b"12345", {}), (b"12", {"Content-Length": "3"}), (b"", {"Content-Length": "9999"})]:
            with patch("serial_release.urllib.request.build_opener") as opener:
                opener.return_value.open.return_value = response(data, headers)
                with self.assertRaises(ValueError):
                    fetch(API + "latest", 4)
        with patch("serial_release.urllib.request.build_opener") as opener, patch("serial_release.time.monotonic", side_effect=[0, 121]):
            opener.return_value.open.return_value = response(b"1234", {})
            with self.assertRaises(TimeoutError):
                fetch(API + "latest", 4)


if __name__ == "__main__":
    unittest.main()
