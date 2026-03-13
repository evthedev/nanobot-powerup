#!/usr/bin/env python3
"""
video-analyzer.py — Video parsing pipeline for LLM analysis.

Extracts:
  - Keyframes (1 per second by default) as JPEG images
  - Audio transcript via whisper (openai-whisper or faster-whisper)
  - Metadata (duration, fps, resolution)

Then sends everything to an LLM (via OpenRouter) and returns:
  - Full transcript
  - Complete storyline / scene-by-scene summary
  - Answers to any questions passed via --question

Usage:
  python3 video-analyzer.py <video_path> [options]

Options:
  --fps FLOAT          Keyframe extraction rate (default: 1.0 frame/sec)
  --max-frames INT     Cap on frames sent to LLM (default: 60)
  --question TEXT      Question to answer about the video (repeatable)
  --model TEXT         OpenRouter model (default: google/gemini-2.5-flash-preview)
  --output TEXT        Output file path for JSON result (optional)
  --whisper-model TEXT Whisper model size: tiny/base/small/medium/large (default: base)

Dependencies:
  pip install openai-whisper ffmpeg-python Pillow openai

ffmpeg must be installed and in PATH.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Lazy imports (fail with clear message if missing) ─────────────────────────

def _require(pkg, install_hint):
    try:
        return __import__(pkg)
    except ImportError:
        print(f"\n❌ ANALYSIS FAILED — Missing dependency: {pkg}. Install with: {install_hint}", file=sys.stderr)
        print("❌ ANALYSIS FAILED — no results were produced.", file=sys.stderr)
        sys.exit(1)


# ── Frame extraction ──────────────────────────────────────────────────────────

def extract_frames(video_path: str, fps: float, max_frames: int, out_dir: str) -> list[str]:
    """Extract keyframes using ffmpeg. Returns list of JPEG paths."""
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"fps={fps}",
        "-q:v", "5",          # JPEG quality (2=best, 31=worst)
        "-frames:v", str(max_frames),
        os.path.join(out_dir, "frame_%04d.jpg"),
        "-y", "-loglevel", "error",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed:\n{result.stderr}")
    frames = sorted(Path(out_dir).glob("frame_*.jpg"))
    return [str(f) for f in frames]


def get_video_metadata(video_path: str) -> dict:
    """Return duration, fps, resolution via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration",
        "-of", "json", video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {}
    data = json.loads(result.stdout)
    stream = (data.get("streams") or [{}])[0]
    fps_raw = stream.get("r_frame_rate", "0/1")
    try:
        num, den = fps_raw.split("/")
        fps = round(int(num) / int(den), 2)
    except Exception:
        fps = 0
    return {
        "width": stream.get("width"),
        "height": stream.get("height"),
        "fps": fps,
        "duration_sec": round(float(stream.get("duration", 0)), 1),
    }


# ── Audio transcription ───────────────────────────────────────────────────────

def extract_audio(video_path: str, out_dir: str) -> str:
    """Extract audio track as WAV."""
    audio_path = os.path.join(out_dir, "audio.wav")
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        audio_path, "-y", "-loglevel", "error",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed:\n{result.stderr}")
    return audio_path


def transcribe(audio_path: str, model_size: str) -> str:
    """Transcribe audio using openai-whisper. Returns plain text."""
    whisper = _require("whisper", "pip install openai-whisper")
    print(f"  Loading whisper model '{model_size}'…", flush=True)
    model = whisper.load_model(model_size)
    result = model.transcribe(audio_path, fp16=False)
    return result.get("text", "").strip()


# ── LLM call ─────────────────────────────────────────────────────────────────

def _read_api_key() -> str:
    """Read OpenRouter key from config.json or env."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return key
    config_path = Path.home() / ".nanobot" / "config.json"
    try:
        cfg = json.loads(config_path.read_text())
        key = cfg.get("providers", {}).get("openrouter", {}).get("apiKey", "")
    except Exception:
        pass
    if not key:
        print("\n❌ ANALYSIS FAILED — OPENROUTER_API_KEY not set and not found in ~/.nanobot/config.json", file=sys.stderr)
        print("❌ ANALYSIS FAILED — no results were produced.", file=sys.stderr)
        sys.exit(1)
    return key


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def analyse_with_llm(
    frames: list[str],
    transcript: str,
    metadata: dict,
    questions: list[str],
    model: str,
) -> dict:
    """Send frames + transcript to LLM, return structured analysis."""
    openai = _require("openai", "pip install openai")
    client = openai.OpenAI(
        api_key=_read_api_key(),
        base_url="https://openrouter.ai/api/v1",
    )

    duration = metadata.get("duration_sec", "unknown")
    res = f"{metadata.get('width')}x{metadata.get('height')}"

    system_prompt = (
        "You are a video analysis assistant. You will be given keyframes from a video "
        "and its audio transcript. Provide:\n"
        "1. A complete scene-by-scene STORYLINE covering the full video.\n"
        "2. The full TRANSCRIPT (clean up the raw transcript if needed).\n"
        "3. Answers to any QUESTIONS asked.\n\n"
        "Be thorough and specific. Reference timestamps where relevant."
    )

    # Build content blocks: text context + images
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Video metadata: duration={duration}s, resolution={res}, "
                f"fps={metadata.get('fps')}\n\n"
                f"Audio transcript:\n{transcript or '(no audio detected)'}\n\n"
                f"Keyframes follow ({len(frames)} frames at ~{1/max(metadata.get('fps',1),0.001):.1f}s intervals):"
            ),
        }
    ]

    for i, frame_path in enumerate(frames):
        timestamp = round(i / max(metadata.get("fps", 1), 0.001), 1)
        content.append({"type": "text", "text": f"[Frame at ~{timestamp}s]"})
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{_encode_image(frame_path)}"},
        })

    questions_text = ""
    if questions:
        questions_text = "\n\nQUESTIONS TO ANSWER:\n" + "\n".join(f"- {q}" for q in questions)
    content.append({"type": "text", "text": questions_text or "\nProvide the storyline and transcript."})

    print(f"  Sending {len(frames)} frames to {model}…", flush=True)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        max_tokens=8192,
    )

    raw = response.choices[0].message.content or ""

    # Parse sections out of the response
    def _extract_section(text: str, heading: str) -> str:
        import re
        pattern = rf"(?:^|\n)#{1,3}\s*{re.escape(heading)}[^\n]*\n(.*?)(?=\n#{1,3}\s|\Z)"
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    return {
        "model": model,
        "duration_sec": duration,
        "resolution": res,
        "transcript": _extract_section(raw, "transcript") or transcript,
        "storyline": _extract_section(raw, "storyline") or raw,
        "question_answers": _extract_section(raw, "questions") or "",
        "raw_response": raw,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Analyse a video with an LLM.")
    parser.add_argument("video", help="Path to video file")
    parser.add_argument("--fps", type=float, default=1.0, help="Keyframe extraction rate (frames/sec)")
    parser.add_argument("--max-frames", type=int, default=60)
    parser.add_argument("--question", action="append", default=[], dest="questions")
    parser.add_argument("--model", default="google/gemini-2.5-flash-preview")
    parser.add_argument("--output", default=None, help="Save JSON result to this path")
    parser.add_argument("--whisper-model", default="base", dest="whisper_model")
    args = parser.parse_args()

    video_path = os.path.expanduser(args.video)
    if not os.path.exists(video_path):
        print(f"\n❌ ANALYSIS FAILED — File not found: {video_path}", file=sys.stderr)
        print("❌ ANALYSIS FAILED — no results were produced.", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        print("📹 Extracting metadata…", flush=True)
        metadata = get_video_metadata(video_path)
        print(f"   {metadata}", flush=True)

        print("🖼  Extracting keyframes…", flush=True)
        frames = extract_frames(video_path, args.fps, args.max_frames, tmp)
        print(f"   {len(frames)} frames extracted", flush=True)

        print("🎙  Transcribing audio…", flush=True)
        try:
            audio_path = extract_audio(video_path, tmp)
            transcript = transcribe(audio_path, args.whisper_model)
            print(f"   Transcript: {len(transcript)} chars", flush=True)
        except Exception as e:
            print(f"   ⚠️  Audio transcription failed: {e}", flush=True)
            transcript = ""

        print("🤖 Analysing with LLM…", flush=True)
        result = analyse_with_llm(frames, transcript, metadata, args.questions, args.model)

    print("\n" + "=" * 60)
    print("STORYLINE")
    print("=" * 60)
    print(result["storyline"])

    print("\n" + "=" * 60)
    print("TRANSCRIPT")
    print("=" * 60)
    print(result["transcript"] or "(none)")

    if result["question_answers"]:
        print("\n" + "=" * 60)
        print("QUESTION ANSWERS")
        print("=" * 60)
        print(result["question_answers"])

    if args.output:
        out_path = os.path.expanduser(args.output)
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\n✅ Full result saved to {out_path}")


if __name__ == "__main__":
    main()
