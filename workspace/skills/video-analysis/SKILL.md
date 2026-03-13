# Video Analysis Skill

Analyses a video file and returns its full transcript, scene-by-scene storyline, and answers to specific questions.

## Pipeline

1. **Frame extraction** — ffmpeg pulls 1 keyframe/sec (configurable)
2. **Audio transcription** — openai-whisper converts speech to text
3. **LLM analysis** — frames + transcript sent to `google/gemini-2.5-flash-preview` via OpenRouter

## Usage

```bash
python3 ~/.nanobot/workspace/skills/video-analysis/video-analyzer.py \
  /path/to/video.mp4 \
  --question "Who are the main characters?" \
  --question "What happens at the end?" \
  --output /tmp/analysis.json
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--fps` | `1.0` | Keyframes per second |
| `--max-frames` | `60` | Cap on frames sent to LLM |
| `--question` | — | Question to answer (repeatable) |
| `--model` | `google/gemini-2.5-flash-preview` | OpenRouter model |
| `--whisper-model` | `base` | Whisper model size (tiny/base/small/medium/large) |
| `--output` | — | Save full JSON result to path |

## Dependencies

```bash
pip install openai-whisper openai ffmpeg-python Pillow
# ffmpeg must be in PATH
```

## Output

- **Storyline** — scene-by-scene narrative of the full video
- **Transcript** — cleaned-up speech-to-text
- **Question answers** — responses to any `--question` flags
- **JSON** (if `--output` set) — all of the above in structured form

## CRITICAL: Failure handling rules

**You MUST follow these rules exactly. No exceptions.**

1. **Check exit code and stderr before doing anything else.** If the script exits non-zero or prints `❌`, the analysis has FAILED.
2. **On failure, attempt to self-heal before retrying:**
   - If the error is `❌ ANALYSIS FAILED — Missing dependency: whisper`, run `pip install openai-whisper` then retry.
   - If the error is `❌ ANALYSIS FAILED — Missing dependency: ffmpeg` or `ffmpeg: not found`, run `apt-get install -y ffmpeg` then retry.
   - For any other missing dependency shown in the error, install it with pip then retry.
   - Retry up to 2 times total after self-healing. Transient errors (model timeouts) also often resolve on plain retry.
3. **If all retries fail, tell the user honestly:**
   - State exactly what failed (copy the error message)
   - Give specific recommendations to fix it (e.g. "install ffmpeg", "check your OpenRouter key", "video file may be corrupt")
4. **NEVER fabricate or infer video content.** If the script did not produce output, you have NO information about the video. Do not guess, summarise, or describe anything about it.
5. **A hallucinated response is worse than an honest failure.** Always choose honesty.
