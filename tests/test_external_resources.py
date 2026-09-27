"""Archive validation must reject a downloaded file that only has a matching hash."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import validate_external_resources


class ExternalArchiveTests(unittest.TestCase):
    def test_zip_integrity_is_checked_after_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("guide.txt", "lesson")
            with patch.object(validate_external_resources, "ROOT", Path(directory)):
                complete = {"local_path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                self.assertEqual(validate_external_resources.check_resource(complete), "verified")
                path.write_bytes(path.read_bytes()[:-24])
                truncated = {"local_path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                with self.assertRaises((ValueError, zipfile.BadZipFile)):
                    validate_external_resources.check_resource(truncated)


if __name__ == "__main__":
    unittest.main()
