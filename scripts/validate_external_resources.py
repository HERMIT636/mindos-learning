"""Check downloaded external resources against their manifests and file formats."""

from __future__ import annotations

import hashlib
import json
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "external-resources"


def check_resource(resource: dict) -> str:
    relative = resource["local_path"]
    if relative == "NOT_DOWNLOADED":
        return "skipped"
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError(f"path escapes external-resources: {relative}")
    if not path.is_file():
        raise ValueError(f"missing file: {relative}")

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest().upper() != resource["sha256"].upper():
        raise ValueError(f"SHA256 mismatch: {relative}")

    if path.suffix == ".pdf":
        with path.open("rb") as stream:
            if not stream.read(5).startswith(b"%PDF-"):
                raise ValueError(f"missing PDF header: {relative}")
            stream.seek(max(0, path.stat().st_size - 2048))
            tail = stream.read()
            if b"startxref" not in tail or b"%%EOF" not in tail:
                raise ValueError(f"incomplete PDF trailer: {relative}")
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                if member.isfile():
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise ValueError(f"unreadable archive member: {member.name}")
                    for _ in iter(lambda: extracted.read(1024 * 1024), b""):
                        pass
    elif path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            if not archive.namelist():
                raise ValueError(f"empty ZIP archive: {relative}")
            damaged = archive.testzip()
            if damaged:
                raise ValueError(f"damaged ZIP member: {relative}: {damaged}")
    elif path.suffix == ".html":
        content = path.read_bytes().lower()
        if b"<html" not in content or b"</html>" not in content:
            raise ValueError(f"incomplete HTML document: {relative}")
    return "verified"


def main() -> None:
    verified = skipped = failed = 0
    for manifest_path in sorted((ROOT / "manifests").glob("*-manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for resource in manifest["resources"]:
            try:
                result = check_resource(resource)
                if result == "verified":
                    verified += 1
                else:
                    skipped += 1
            except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
                failed += 1
                print(f"FAIL {resource['id']}: {exc}")
    print(f"External resources: {verified} verified, {skipped} not downloaded, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
