"""Validate the local stack and prefetch ASR, alignment and diarization models."""
import argparse
import ctypes
import gc
import json
import os
from pathlib import Path
import re
import sys
import time
import wave
import runtime  # Register native libraries before importing torch/torchcodec.

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache" / "matplotlib"))


def retry(label, action):
    for attempt in range(1, 4):
        print(f"\n>>> {label} (attempt {attempt}/3)", flush=True)
        try:
            return action()
        except Exception as exc:
            print(re.sub(r"hf_[A-Za-z0-9]+", "[REDACTED]", str(exc)), flush=True)
            if attempt == 3:
                raise
            time.sleep(10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-models", action="store_true")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--model", choices=("tiny", "base", "small", "medium", "large-v3"), default="large-v3")
    parser.add_argument("--alignment-languages", nargs="*", default=[])
    args = parser.parse_args()
    import torch
    import torchcodec
    import whisperx
    import pyannote.audio
    from huggingface_hub import HfApi

    print(f"PyTorch: {torch.__version__}; CUDA: {torch.version.cuda}", flush=True)
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is unavailable; check the GPU PyTorch package and NVIDIA driver.")
    if args.device == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}", flush=True)
        ctypes.WinDLL("cublas64_12.dll")
        ctypes.WinDLL("cudnn64_9.dll")
    probe = torch.ones(32, device=args.device) * 2
    assert probe.sum().item() == 64
    del probe
    torch.cuda.empty_cache()

    # Decode a generated WAV to check the shared FFmpeg/TorchCodec installation.
    wav_path = ROOT / "logs" / "decoder-check.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 16000)
    from torchcodec.decoders import AudioDecoder
    decoder = AudioDecoder(str(wav_path))
    decoded = decoder.get_all_samples()
    assert decoded.data.numel() > 0
    del decoder, decoded
    print("Shared FFmpeg and TorchCodec audio decoding verified.", flush=True)
    if args.skip_models:
        return

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("Set HF_TOKEN or rerun setup.cmd to configure your read token.")
    api = HfApi(token=token)
    retry("Validate Hugging Face credential", lambda: api.whoami())
    retry("Check gated speaker model access", lambda: api.auth_check(repo_id="pyannote/speaker-diarization-community-1", repo_type="model"))
    print("Credential and gated model access verified.", flush=True)

    from download_nltk import prepare_nltk
    retry("Prepare official NLTK sentence tokenizer data", prepare_nltk)

    from faster_whisper import WhisperModel
    import numpy as np
    model_cache = ROOT / "models" / "whisper"
    model_cache.mkdir(parents=True, exist_ok=True)
    from download_asr import main as download_asr
    retry(f"Download verified Whisper {args.model} files", lambda: download_asr(args.model))
    compute_type = "int8_float16" if args.device == "cuda" else "int8"
    asr = retry(f"Load Whisper {args.model}", lambda: WhisperModel(
        str(model_cache / args.model), device=args.device, compute_type=compute_type,
        download_root=str(model_cache), num_workers=1,
    ))
    # Run a short synthetic input to exercise CTranslate2 GPU inference.
    def check_asr():
        segments, _ = asr.transcribe(
            np.zeros(16000, dtype=np.float32), language="en", beam_size=1,
            temperature=0.0, condition_on_previous_text=False, vad_filter=False,
        )
        list(segments)
    retry("Verify ASR GPU inference on synthetic audio", check_asr)
    del asr
    gc.collect()
    torch.cuda.empty_cache()

    align_dir = ROOT / "models" / "alignment"
    align_dir.mkdir(parents=True, exist_ok=True)
    for language in args.alignment_languages:
        model, metadata = retry(f"Download and load {language} alignment model", lambda lang=language:
            whisperx.load_align_model(language_code=lang, device="cpu", model_dir=str(align_dir)))
        del model, metadata
        gc.collect()

    from pyannote.audio import Pipeline
    pipeline = retry("Download and load speaker diarization model", lambda: Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1", token=token,
    ))
    if pipeline is None:
        raise RuntimeError("The speaker model could not be loaded; verify gated model access.")
    del pipeline
    gc.collect()
    manifest = {
        "asr_model": args.model, "compute_type": compute_type, "device": args.device,
        "asr_cache": str(model_cache), "alignment_cache": str(align_dir),
        "alignment_languages": args.alignment_languages,
        "diarization_model": "pyannote/speaker-diarization-community-1",
        "gpu_inference_checked": args.device == "cuda",
        "note": "Synthetic audio validates execution, not transcription accuracy on real recordings.",
    }
    (ROOT / "logs" / "prepared-models.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nAll requested models are downloaded and load successfully.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\nPREPARATION FAILED: " + re.sub(r"hf_[A-Za-z0-9]+", "[REDACTED]", str(error)), file=sys.stderr, flush=True)
        sys.exit(1)
