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
