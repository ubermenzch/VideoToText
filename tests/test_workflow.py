"""Offline regression tests for launcher portability and text preservation."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from transcribe_video import speaker_turns, timestamp


class ExportTests(unittest.TestCase):
    def test_speaker_changes_preserve_unaligned_words(self):
        result = {"language": "en", "segments": [{
            "start": 0, "end": 3, "text": "Hello, world! Yes.", "speaker": "A",
            "words": [
                {"word": "Hello,", "start": 0, "end": 1, "speaker": "A"},
                {"word": "world!", "speaker": "A"},
                {"word": "Yes.", "start": 2, "end": 3, "speaker": "B"},
            ],
        }, {"start": 4, "end": 5, "text": "Fallback.", "speaker": "B"}]}
        turns = speaker_turns(result)
        self.assertEqual([t["speaker"] for t in turns], ["A", "B", "B"])
        self.assertEqual(" ".join(t["text"] for t in turns), "Hello, world! Yes. Fallback.")
        self.assertTrue(all(t["start"] <= t["end"] for t in turns))

    def test_chinese_and_subtitle_time(self):
        self.assertEqual(speaker_turns({"language": "zh", "segments": [{
            "start": 0, "end": 1, "text": "你好", "words": [{"word": "你"}, {"word": "好"}]
        }]})[0]["text"], "你好")
        self.assertEqual(timestamp(3599.9996, ","), "01:00:00,000")


@unittest.skipUnless(os.name == "nt", "Windows launcher integration")
class LauncherTests(unittest.TestCase):
    def run_launcher(self, mode, launcher="cmd"):
        # Use a separate clone-like directory; no real models or secrets are copied.
        with tempfile.TemporaryDirectory(prefix="VideoToText ", dir=ROOT / "tests") as temporary:
            root = Path(temporary) / "中文 clone with spaces"
            root.mkdir()
            for name in ("transcribe.cmd", "transcribe-video.ps1", "use-env.ps1", "project-runtime.ps1"):
                shutil.copy2(ROOT / name, root / name)
            python = str(Path(sys.executable).resolve())
            # Fake venv executable delegates to the installed Python; only tests launcher selection.
            if mode == "venv":
                scripts = root / ".venv/Scripts"
                scripts.mkdir(parents=True)
                (scripts / "python.cmd").write_text(f'@echo off\n"{python}" %*\n', encoding="utf-8")
                python = ".venv/Scripts/python.cmd"
            (root / ".videototext.json").write_text(json.dumps({
                "python": python, "device": "cpu", "model": "small", "installMode": mode,
            }), encoding="utf-8")
            (root / "transcribe_video.py").write_text(
                "import sys,json\nfrom pathlib import Path\n"
                "Path(__file__).with_name('received.json').write_text(json.dumps(sys.argv[1:]),encoding='utf-8')\n",
                encoding="utf-8")
            env = dict(os.environ)
            env.pop("HF_TOKEN", None)
            url = "https://www.youtube.com/watch?v=TEST_ID"
            if launcher == "ps1":
                url += "&feature=shared"
            escaped = str(root).replace("'", "''")
            entry = f"{escaped}/transcribe.cmd" if launcher == "cmd" else f"{escaped}/transcribe-video.ps1"
            command = f"& '{entry}' '{url}' -Language en -Speakers 2"
            process = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                      "-Command", command], cwd=ROOT, env=env,
                                     capture_output=True, timeout=60)
            self.assertEqual(process.returncode, 0, (process.stdout + process.stderr).decode(errors="replace"))
            self.assertEqual(json.loads((root / "received.json").read_text(encoding="utf-8")),
                [url, "--language", "en", "--speakers", "2", "--device", "cpu", "--model", "small"])
            self.assertFalse((root / ".secrets").exists())

    def test_system_install_cmd(self):
        self.run_launcher("system")

    def test_virtualenv_cmd(self):
        self.run_launcher("venv")

    def test_powershell_entry(self):
        self.run_launcher("system", "ps1")


if __name__ == "__main__":
    unittest.main()
