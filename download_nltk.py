"""Install fixed official NLTK tokenizer archives with checksum verification."""
import hashlib
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent
DATA = ROOT / ".cache" / "nltk"
BASE = "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/"


def prepare_nltk():
    with urllib.request.urlopen(BASE + "index.xml", timeout=60) as response:
        index = ET.fromstring(response.read())
    packages = {item.attrib["id"]: item.attrib for item in index.findall("./packages/package")}
    for name in ("punkt", "punkt_tab"):
        if (DATA / "tokenizers" / name / "english").is_dir() or (name == "punkt" and (DATA / "tokenizers" / name / "english.pickle").is_file()):
            print(f"NLTK {name} is already prepared.", flush=True)
            continue
        url = BASE + f"packages/tokenizers/{name}.zip"
        with urllib.request.urlopen(url, timeout=120) as response:
            archive = response.read()
        expected = packages[name]["sha256_checksum"]
        if hashlib.sha256(archive).hexdigest() != expected:
            raise RuntimeError(f"Official checksum mismatch for NLTK {name}")
        destination = DATA / "tokenizers"
        destination.mkdir(parents=True, exist_ok=True)
        archive_path = destination / f"{name}.zip"
        archive_path.write_bytes(archive)
        with zipfile.ZipFile(archive_path) as bundle:
            for member in bundle.infolist():
                if not (destination / member.filename).resolve().is_relative_to(destination.resolve()):
                    raise RuntimeError("Unexpected tokenizer archive path")
            bundle.extractall(destination)
        print(f"NLTK {name}: official checksum verified and installed.", flush=True)


if __name__ == "__main__":
    prepare_nltk()
