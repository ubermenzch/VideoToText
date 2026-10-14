"""Register project-specific native libraries without modifying system Python."""
import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_dll_handles = []


def configure():
    for variable, relative in {
        "HF_HOME": ".cache/huggingface", "TORCH_HOME": ".cache/torch",
        "NLTK_DATA": ".cache/nltk", "MPLCONFIGDIR": ".cache/matplotlib",
    }.items():
        os.environ.setdefault(variable, str(ROOT / relative))
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        directories = [ROOT / ".tools/ffmpeg/ffmpeg-7.1.1-full_build-shared/bin"]
        spec = importlib.util.find_spec("torch")
        if spec and spec.submodule_search_locations:
            directories.extend(Path(p) / "lib" for p in spec.submodule_search_locations)
        for directory in directories:
            if directory.is_dir():
                _dll_handles.append(os.add_dll_directory(str(directory)))


configure()
