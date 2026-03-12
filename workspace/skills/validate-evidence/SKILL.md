---
name: validate-evidence
description: Validate that a claim is actually supported by evidence (screenshots, fetched text) before presenting it to the user. Use after taking screenshots or fetching pages when you need to confirm the content shows what you say it shows. Runs Tesseract OCR on screenshots to get visual ground truth, then uses an LLM to semantically evaluate whether the evidence supports the specific claim. Returns SUPPORTED / INCONCLUSIVE / UNSUPPORTED. No keyword pre-specification needed.
---

# Validate Evidence

OCR + LLM pipeline to verify a claim against evidence before surfacing it to the user.

```
screenshot → Tesseract OCR → text
fetched text                      → LLM judgment → SUPPORTED / INCONCLUSIVE / UNSUPPORTED
any other text
```

## When to Use

- Before telling the user a specific price, rating, date, or availability fact sourced from a screenshot
- When `screenshot_pages` returns a 🚫 BLOCKED result — validate confirms what went wrong
- When a fetch returned 200 but the content seems off (login wall, stale cache, wrong page)
- As the final gate in any research workflow before composing the user response

## Script

```bash
python3 ~/.nanobot/workspace/skills/validate-evidence/validate_evidence.py --json '<JSON>'
# or pipe:
echo '<JSON>' | python3 ~/.nanobot/workspace/skills/validate-evidence/validate_evidence.py
```

## Input

```json
{
  "claim": "Qantas QF9 PER to LHR on 15 Apr 2026 costs AUD 1457",
  "evidence": [
    {"type": "screenshot", "path": "/root/.nanobot/workspace/screenshots/foo.jpg", "label": "skyscanner"},
    {"type": "text",       "content": "...fetched page text...",                   "label": "web_fetch"},
    {"type": "ocr",        "content": "...pre-extracted OCR text...",              "label": "manual"}
  ]
}
```

Evidence types:
- `screenshot` — Tesseract OCRs the image, LLM evaluates the extracted text
- `text` — passed directly to LLM (web_fetch output, scrapling output, etc.)
- `ocr` — pre-extracted OCR text, skips Tesseract

## Output

```json
{
  "verdict":    "SUPPORTED",
  "confidence": 0.92,
  "reasoning":  "Evidence shows Qantas QF9 PER-LHR at AUD 1,457 departing 15 April 2026.",
  "issues":     [],
  "claim":      "...",
  "evidence_results": [
    {"label": "skyscanner", "type": "screenshot", "blocked": false, "text_excerpt": "..."}
  ]
}
```

## Verdicts

| Verdict | Meaning | Action |
|---|---|---|
| `SUPPORTED` | LLM confirms evidence shows the claim | Safe to present |
| `INCONCLUSIVE` | Evidence is related but incomplete | Fetch a better source or caveat |
| `UNSUPPORTED` | Evidence contradicts, is irrelevant, or is a bot wall | Do not present — retry with scrapling/stealth-browser |

## Notes

- Uses `smart_model` from `~/.nanobot/config.json` (fast, cheap — not the main model)
- Block detection (bot walls, login gates) runs before the LLM call as a fast path
- Tesseract must be installed — it is in the Docker image (`tesseract-ocr`)
- Max 3000 chars of evidence text per item sent to the LLM (keeps cost low)
