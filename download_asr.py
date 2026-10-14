"""Prefetch the multilingual ASR model from its official Hugging Face repository."""
import json
from pathlib import Path
import urllib.request
from download_pytorch import download_verified

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "models" / "whisper" / "large-v3"


def main(model_name="large-v3"):
    if model_name not in {"tiny", "base", "small", "medium", "large-v3"}:
        raise ValueError("Unsupported multilingual model")
    model = ROOT / "models" / "whisper" / model_name
    model.mkdir(parents=True, exist_ok=True)
    repo = f"Systran/faster-whisper-{model_name}"
    base = f"https://huggingface.co/{repo}/resolve/main/"
    with urllib.request.urlopen(f"https://huggingface.co/api/models/{repo}/tree/main?recursive=false&expand=true", timeout=60) as response:
        files = json.load(response)
    wanted = {"config.json", "model.bin", "preprocessor_config.json", "tokenizer.json", "vocabulary.json", "vocabulary.txt"}
    for item in files:
        name = item.get("path")
        if name not in wanted:
            continue
        target = model / name
        lfs = item.get("lfs")
        if lfs:
            download_verified(base + name, target, lfs["oid"], size=item["size"])
        elif not target.exists() or target.stat().st_size != item["size"]:
            with urllib.request.urlopen(base + name, timeout=120) as response:
                data = response.read()
            if len(data) != item["size"]:
                raise RuntimeError(f"Incomplete model file: {name}")
            target.write_bytes(data)
    if not all((model / name).exists() for name in ("config.json", "model.bin", "tokenizer.json")):
        raise RuntimeError("Required ASR model files are missing")
    print(f"ASR model files prepared: {model}", flush=True)


if __name__ == "__main__":
    main()
