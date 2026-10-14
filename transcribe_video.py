"""Download a video URL and export a timestamped, speaker-labelled transcript."""
import argparse
import gc
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import runtime  # Keep DLL setup local to this process, including system installs.

ROOT = Path(__file__).resolve().parent
STATUS_PATH = None


class ConsoleLog:
    """Keep Python output visible and preserve it in a UTF-8 log."""
    def __init__(self, stream, log, lock):
        self.stream, self.log, self.lock = stream, log, lock

    def write(self, text):
        safe = re.sub(r"hf_[A-Za-z0-9]+", "[REDACTED]", text)
        with self.lock:
            self.stream.write(safe)
            self.log.write(safe)
            self.log.flush()
        return len(text)

    def flush(self):
        self.stream.flush()
        self.log.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def save_json(path, data):
    def convert(value):
        if hasattr(value, "item"):
            return value.item()
        raise TypeError(f"Cannot serialize {type(value).__name__}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=convert), encoding="utf-8")
    temporary.replace(path)


def timestamp(seconds, decimal="."):
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{decimal}{milliseconds:03d}"


def join_tokens(words, language):
    separator = "" if language in {"zh", "ja"} else " "
    text = separator.join(words)
    if separator:
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def speaker_turns(result):
    turns = []
    for segment in result["segments"]:
        words = segment.get("words", [])
        if not words:
            turns.append({"start": segment["start"], "end": segment["end"],
                          "speaker": segment.get("speaker", "UNKNOWN"), "text": segment["text"].strip()})
            continue
        run = None
        for word in words:
            speaker = word.get("speaker", segment.get("speaker", "UNKNOWN"))
            start = float(word.get("start", run["end"] if run else segment["start"]))
            end = max(start, float(word.get("end", start)))
            if run and speaker != run["speaker"]:
                run["text"] = join_tokens(run.pop("tokens"), result["language"])
                turns.append(run)
                run = None
            if run is None:
                run = {"start": start, "end": end, "speaker": speaker, "tokens": []}
            run["end"] = max(run["end"], end)
            run["tokens"].append(word["word"])
        if run:
            run["text"] = join_tokens(run.pop("tokens"), result["language"])
            turns.append(run)
    return [turn for turn in turns if turn["text"]]


def main():
    global STATUS_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--language")
    parser.add_argument("--speakers", type=int)
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--model", choices=("tiny", "base", "small", "medium", "large-v3"), default="large-v3")
    args = parser.parse_args()
    from yt_dlp import YoutubeDL

    downloads = ROOT / "downloads"
    downloads.mkdir(exist_ok=True)
    print("\n>>> Download original audio", flush=True)
    options = {
        "format": "bestaudio/best", "noplaylist": True,
        "outtmpl": str(downloads / "%(extractor_key)s-%(id)s.%(ext)s"),
        "windowsfilenames": True, "retries": 5, "fragment_retries": 5,
        "socket_timeout": 30,
        "ffmpeg_location": str(ROOT / ".tools" / "ffmpeg" / "ffmpeg-7.1.1-full_build-shared" / "bin"),
        "js_runtimes": {"deno": {"path": str(ROOT / ".tools" / "deno" / "deno.exe")}},
    }
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(args.url, download=True)
        if not info or info.get("_type") == "playlist" or info.get("entries") is not None:
            raise RuntimeError("Provide a single YouTube or Bilibili video URL, not a channel or playlist URL.")
        source = Path(downloader.prepare_filename(info))
        metadata = {key: info.get(key) for key in (
            "id", "title", "duration", "webpage_url", "uploader", "language", "format_id", "ext")}
    if info.get("extractor_key") == "Youtube":
        # Use the video's canonical oEmbed title to avoid player API charset issues.
        canonical_url = "https://www.youtube.com/oembed?" + urllib.parse.urlencode({"url": args.url, "format": "json"})
        try:
            with urllib.request.urlopen(canonical_url, timeout=30) as response:
                canonical = json.loads(response.read().decode("utf-8"))
            metadata["title"] = canonical["title"]
        except Exception:
            pass  # Downloaded metadata remains a valid fallback.
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(info["id"]))
    output = ROOT / "results" / safe_id
    output.mkdir(parents=True, exist_ok=True)
    status_path = output / "status.json"
    STATUS_PATH = status_path
    save_json(output / "source.json", metadata)

    def stage(name):
        print(f"\n>>> {name}", flush=True)
        save_json(status_path, {"status": "running", "stage": name, "source": args.url, "updated": time.time()})

    stage("Convert audio to 16 kHz mono WAV")
    audio_path = output / "audio.wav"
    if not audio_path.exists():
        ffmpeg = ROOT / ".tools" / "ffmpeg" / "ffmpeg-7.1.1-full_build-shared" / "bin" / "ffmpeg.exe"
        temporary_audio = output / "audio.partial.wav"
        subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-y", "-i", str(source),
                        "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(temporary_audio)], check=True)
        temporary_audio.replace(audio_path)

    if args.download_only:
        save_json(status_path, {"status": "audio_ready", "source": args.url, "output": str(output)})
        print(f"Audio downloaded and converted: {audio_path}", flush=True)
        return

    import torch
    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable. Use -Device cpu or install a compatible NVIDIA driver.")
    print(f"Inference device: {device}; model: {args.model}", flush=True)
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    import whisperx
    from faster_whisper import WhisperModel
    stage("Multilingual speech recognition")
    raw_path = output / "asr.json"
    if raw_path.exists():
        result = json.loads(raw_path.read_text(encoding="utf-8"))
        if args.language and result["language"] != args.language:
            raise RuntimeError("Cached transcript has a different language. Rename asr.json to rerun recognition.")
        if result.get("asr_model", "large-v3") != args.model:
            raise RuntimeError("Cached transcript uses another model. Rename the results folder to start a new run.")
        print("Using saved ASR checkpoint.", flush=True)
    else:
        model_path = ROOT / "models" / "whisper" / args.model
        if not (model_path / "model.bin").exists():
            from download_asr import main as download_asr
            download_asr(args.model)
        model = WhisperModel(str(model_path), device=device, compute_type="int8_float16" if device == "cuda" else "int8",
                             download_root=str(ROOT / "models" / "whisper"), num_workers=1)
        segments, detected = model.transcribe(str(audio_path), language=args.language,
            beam_size=5, word_timestamps=True, vad_filter=True, condition_on_previous_text=False,
            hallucination_silence_threshold=2.0)
        if args.language:
            print(f"Language: {detected.language} (specified)", flush=True)
        else:
            print(f"Detected language: {detected.language}; probability: {detected.language_probability:.3f}", flush=True)
        recognized = []
        for segment in segments:
            item = {"start": segment.start, "end": segment.end, "text": segment.text.strip(),
                    "avg_logprob": segment.avg_logprob,
                    "words": [{"start": w.start, "end": w.end, "word": w.word.strip(), "probability": w.probability}
                              for w in segment.words or []]}
            recognized.append(item)
            print(f"[{timestamp(segment.start)}] {segment.text.strip()}", flush=True)
        result = {"asr_model": args.model, "language": detected.language, "language_probability": detected.language_probability if not args.language else None,
                  "language_source": "specified" if args.language else "detected",
                  "segments": recognized}
        save_json(raw_path, result)
        del model
        gc.collect()
        torch.cuda.empty_cache()

    stage("Align text timestamps")
    aligned_path = output / "aligned.json"
    if aligned_path.exists():
        result = json.loads(aligned_path.read_text(encoding="utf-8"))
    elif result["segments"]:
        alignment_model, alignment_metadata = whisperx.load_align_model(
            language_code=result["language"], device=device, model_dir=str(ROOT / "models" / "alignment"))
        language = result["language"]
        result = whisperx.align(result["segments"], alignment_model, alignment_metadata,
                                str(audio_path), device, return_char_alignments=False)
        result["language"] = language
        save_json(aligned_path, result)
        del alignment_model, alignment_metadata
        gc.collect()
        torch.cuda.empty_cache()

    stage("Assign speakers by voice")
    diarization_path = output / "diarization.json"
    if diarization_path.exists():
        diarization = json.loads(diarization_path.read_text(encoding="utf-8"))
        if diarization.get("requested_speakers") != args.speakers:
            raise RuntimeError("Cached diarization has different speaker settings. Rename diarization.json to rerun.")
    else:
        from pyannote.audio import Pipeline
        token = os.environ.get("HF_TOKEN")
        if not token:
            raise RuntimeError("Set HF_TOKEN or run setup.cmd to configure model access.")
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1", token=token)
        pipeline.to(torch.device(device))
        pipeline.segmentation_batch_size = 8 if device == "cuda" else 1
        pipeline.embedding_batch_size = 8 if device == "cuda" else 1
        kwargs = {"num_speakers": args.speakers} if args.speakers else {}
        waveform = torch.from_numpy(whisperx.load_audio(str(audio_path))).unsqueeze(0)
        last_progress = {}

        def progress(step_name, step_artifact, file=None, total=None, completed=None):
            now = time.monotonic()
            if now - last_progress.get(step_name, 0) < 10 and completed != total:
                return
            last_progress[step_name] = now
            detail = f" {completed}/{total}" if total is not None and completed is not None else ""
            print(f"Diarization: {step_name}{detail}", flush=True)
            save_json(status_path, {"status": "running", "stage": "Assign speakers by voice",
                "phase": step_name, "completed_batches": completed, "total_batches": total,
                "source": args.url, "updated": time.time()})

        speaker_output = pipeline({"waveform": waveform, "sample_rate": 16000}, hook=progress, **kwargs)
        diarization = {
            "requested_speakers": args.speakers,
            "turns": [{"start": turn.start, "end": turn.end, "speaker": speaker}
                      for turn, speaker in speaker_output.exclusive_speaker_diarization],
            "overlap_turns": [{"start": turn.start, "end": turn.end, "speaker": speaker}
                             for turn, speaker in speaker_output.speaker_diarization],
        }
        save_json(diarization_path, diarization)
        del pipeline, waveform
        gc.collect()
    import pandas as pd
    if diarization["turns"]:
        result = whisperx.assign_word_speakers(pd.DataFrame(diarization["turns"]), result, fill_nearest=True)
    turns = speaker_turns(result)
    stage("Export transcript and subtitles")
    transcript = {"source": metadata, "language": result["language"], "asr_model": args.model,
                  "diarization_model": "pyannote/speaker-diarization-community-1",
                  "speakers": sorted({t["speaker"] for t in turns}), "turns": turns,
                  "segments": result["segments"]}
    save_json(output / "transcript.json", transcript)
    header = f"Title: {metadata['title']}\nSource: {args.url}\nLanguage: {result['language']}\n\n"
    timeline = [f"[{timestamp(t['start'])} - {timestamp(t['end'])}] {t['speaker']}: {t['text']}" for t in turns]
    (output / "transcript.txt").write_text(header + "\n".join(timeline) + "\n", encoding="utf-8")
    (output / "plain.txt").write_text("\n".join(t["text"] for t in turns) + "\n", encoding="utf-8")
    srt = [f"{i}\n{timestamp(t['start'], ',')} --> {timestamp(max(t['end'], t['start'] + 0.1), ',')}\n[{t['speaker']}] {t['text']}\n"
           for i, t in enumerate(turns, 1)]
    (output / "transcript.srt").write_text("\n".join(srt), encoding="utf-8")
    vtt = [f"{timestamp(t['start'])} --> {timestamp(max(t['end'], t['start'] + 0.1))}\n[{t['speaker']}] {t['text']}\n" for t in turns]
    (output / "transcript.vtt").write_text("WEBVTT\n\n" + "\n".join(vtt), encoding="utf-8")
    if not turns:
        raise RuntimeError("No speech was recognized; review the downloaded audio.")
    save_json(status_path, {"status": "success", "source": args.url, "turns": len(turns),
                           "speakers": transcript["speakers"], "output": str(output), "updated": time.time()})
    print(f"\nSUCCESS: {len(turns)} transcript turns, {len(transcript['speakers'])} speakers.\nOutput: {output}", flush=True)


if __name__ == "__main__":
    if os.environ.get("VIDEO_TO_TEXT_LOG"):
        log_path = Path(os.environ["VIDEO_TO_TEXT_LOG"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        console_log = log_path.open("a", encoding="utf-8")
        console_lock = threading.Lock()
        sys.stdout = ConsoleLog(sys.stdout, console_log, console_lock)
        sys.stderr = ConsoleLog(sys.stderr, console_log, console_lock)
    try:
        main()
    except Exception as error:
        safe_error = re.sub(r"hf_[A-Za-z0-9]+", "[REDACTED]", str(error))
        if STATUS_PATH is not None:
            previous = json.loads(STATUS_PATH.read_text(encoding="utf-8")) if STATUS_PATH.exists() else {}
            previous.update(status="failed", error=safe_error, updated=time.time())
            save_json(STATUS_PATH, previous)
        print("\nTRANSCRIPTION FAILED: " + safe_error, file=sys.stderr, flush=True)
        sys.exit(1)
