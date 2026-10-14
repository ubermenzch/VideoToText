"""Fetch official GPU wheels in resumable ranges and verify their published hashes."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
WHEELS = ROOT / ".tools" / "wheels"
CHUNK = 8 * 1024 * 1024


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.extend(value for key, value in attrs if key == "href")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(4 * 1024 * 1024):
            digest.update(data)
    return digest.hexdigest()


def fetch(package, version):
    index = f"https://download.pytorch.org/whl/cu128/{package}/"
    with urllib.request.urlopen(index, timeout=60) as response:
        parser = Links()
        parser.feed(response.read().decode())
    expected_name = f"{package}-{version}+cu128-cp311-cp311-win_amd64.whl"
    link = next((item for item in parser.links if urllib.parse.unquote(urllib.parse.urlparse(item).path).endswith("/" + expected_name)), None)
    if not link:
        raise RuntimeError(f"Official wheel not found: {expected_name}")
    url, fragment = urllib.parse.urldefrag(urllib.parse.urljoin(index, link))
    expected_hash = urllib.parse.parse_qs(fragment)["sha256"][0]
    target = WHEELS / expected_name
    download_verified(url, target, expected_hash)


def download_verified(url, target, expected_hash, size=None):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    expected_name = target.name
    package = expected_name.split('-')[0]
    if target.exists() and sha256(target) == expected_hash:
        print(f"Verified cached file: {expected_name}", flush=True)
        return
    join_query = '&' if '?' in url else '?'
    if size is None:
        with urllib.request.urlopen(urllib.request.Request(url + join_query + "probe=1", headers={"Range": "bytes=0-0"}), timeout=60) as response:
            content_range = response.headers.get("Content-Range", "")
            match = re.fullmatch(r"bytes 0-0/(\d+)", content_range)
            if not match:
                raise RuntimeError(f"Server did not honor range request: {content_range}")
            size = int(match.group(1))
            response.read()
    parts = target.parent / (expected_name + ".parts")
    parts.mkdir(parents=True, exist_ok=True)
    total = (size + CHUNK - 1) // CHUNK

    def get_part(number):
        start = number * CHUNK
        end = min(size - 1, start + CHUNK - 1)
        length = end - start + 1
        path = parts / f"{number:05d}.part"
        if path.exists() and path.stat().st_size == length:
            return
        for attempt in range(4):
            try:
                request = urllib.request.Request(url + join_query + f"part={number}", headers={"Range": f"bytes={start}-{end}"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    if response.headers.get("Content-Range") != f"bytes {start}-{end}/{size}":
                        raise RuntimeError("Unexpected Content-Range")
                    data = response.read()
                if len(data) != length:
                    raise RuntimeError("Incomplete download range")
                path.write_bytes(data)
                return
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(3)

    print(f"Downloading {expected_name}: {size / 1048576:.1f} MiB in {total} ranges", flush=True)
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(get_part, number) for number in range(total)]
        for completed, future in enumerate(as_completed(futures), 1):
            future.result()
            if completed % 8 == 0 or completed == total:
                print(f"{package}: {completed}/{total} ranges complete", flush=True)
    temporary = target.with_suffix(".assembling")
    with temporary.open("wb") as output:
        for number in range(total):
            with (parts / f"{number:05d}.part").open("rb") as stream:
                while data := stream.read(4 * 1024 * 1024):
                    output.write(data)
    if sha256(temporary) != expected_hash:
        raise RuntimeError(f"SHA-256 mismatch for {expected_name}; do not use this file.")
    temporary.replace(target)
    # Only delete the exact generated part files after the official checksum passed.
    if not parts.resolve().is_relative_to(ROOT):
        raise RuntimeError("Unexpected parts directory")
    for number in range(total):
        (parts / f"{number:05d}.part").unlink()
    parts.rmdir()
    print(f"Official SHA-256 verified: {expected_name}", flush=True)


if __name__ == "__main__":
    WHEELS.mkdir(parents=True, exist_ok=True)
    for package, version in (("torch", "2.8.0"), ("torchvision", "0.23.0"), ("torchaudio", "2.8.0")):
        fetch(package, version)
