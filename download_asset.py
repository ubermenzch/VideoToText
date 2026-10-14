"""Download a public archive without depending on Windows Schannel credentials."""
from pathlib import Path
import sys
import time
import urllib.request


def main():
    url, filename = sys.argv[1:]
    target = Path(filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    offset = target.stat().st_size if target.exists() else 0
    headers = {"User-Agent": "VideoToText-Preparation/1.0"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
        resumed = offset > 0 and response.status == 206
        written = offset if resumed else 0
        total = written + int(response.headers.get("Content-Length", 0))
        last_progress = 0.0
        with target.open("ab" if resumed else "wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                written += len(chunk)
                if time.monotonic() - last_progress > 15:
                    print(f"Downloaded {written / 1048576:.1f} / {total / 1048576:.1f} MiB", flush=True)
                    last_progress = time.monotonic()
        if total and written != total:
            raise RuntimeError("Incomplete archive download; rerun to resume.")
        print(f"Download complete: {written / 1048576:.1f} MiB", flush=True)


if __name__ == "__main__":
    main()
