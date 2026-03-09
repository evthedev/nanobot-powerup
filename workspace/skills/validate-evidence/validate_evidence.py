#!/usr/bin/env python3
"""
validate_evidence.py — validate a claim against evidence using OCR + LLM.

Pipeline:
  screenshot → Tesseract OCR → raw text ─┐
  fetched text                            ├─→ LLM judgment → verdict
  any other text                         ─┘

No keyword pre-specification needed. The LLM understands context, synonyms,
numbers, dates — keyword matching cannot.

USAGE:
  echo '<JSON>' | python3 validate_evidence.py
  python3 validate_evidence.py --json '<JSON>'

INPUT:
  {
    "claim": "Qantas QF9 PER to LHR on 15 Apr 2026 costs AUD 1457",
    "evidence": [
      {"type": "screenshot", "path": "/root/.nanobot/workspace/screenshots/foo.jpg", "label": "skyscanner"},
      {"type": "text",       "content": "page text here",                             "label": "web_fetch"}
    ]
  }

EVIDENCE TYPES:
  screenshot  — OCR'd with Tesseract, text passed to LLM
  text        — raw text passed directly to LLM
  ocr         — pre-extracted OCR text (skips Tesseract)

OUTPUT:
  {
    "verdict":  "SUPPORTED" | "UNSUPPORTED" | "INCONCLUSIVE",
    "confidence": 0.0–1.0,
    "reasoning": "...",
    "issues":   ["specific problems found"],
    "evidence_results": [{"label": ..., "type": ..., "text_excerpt": ...}]
  }
"""

import json
import os
import re
import shutil
import subprocess
import sys
import argparse
from pathlib import Path

_SSL_VERIFY = os.environ.get("NANOBOT_SSL_VERIFY", "true").lower() not in ("false", "0", "no")
if not _SSL_VERIFY:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context  # noqa
    os.environ["PYTHONHTTPSVERIFY"] = "0"
    os.environ["CURL_CA_BUNDLE"] = ""
    os.environ["REQUESTS_CA_BUNDLE"] = ""
    try: import urllib3; urllib3.disable_warnings()
    except ImportError: pass

_EVAL_SYSTEM_PROMPT = """\
You are an evidence verifier for an AI assistant. You will be given:
1. A CLAIM the assistant wants to present to a user
2. EVIDENCE extracted from web pages and screenshots (via OCR)

Determine whether the evidence actually supports the specific claim.

Respond ONLY with a JSON object — no prose, no markdown fences:
{
  "verdict": "SUPPORTED" | "UNSUPPORTED" | "INCONCLUSIVE",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<one or two sentences>",
  "issues": ["<specific thing missing or wrong>", ...]
}

Verdict rules:
- SUPPORTED: evidence clearly contains the specific information in the claim
- UNSUPPORTED: evidence contradicts the claim, is about something different, or is a bot/login wall
- INCONCLUSIVE: evidence is related but doesn't clearly confirm or deny the claim

Be strict on numbers, prices, dates, codes — "AUD 1,457" and "AUD 1500" are different.
If evidence contains bot-detection language, set verdict to UNSUPPORTED and note it in issues.
If evidence is very short or clearly a loading/error page, set verdict to INCONCLUSIVE.\
"""


def ocr_image(path: str) -> str:
    """Run Tesseract OCR on a screenshot. Returns '' if tesseract unavailable."""
    if not shutil.which("tesseract"):
        return ""
    try:
        result = subprocess.run(
            ["tesseract", path, "stdout", "--psm", "3", "-l", "eng"],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout.strip()
    except Exception as e:
        return f"[OCR error: {e}]"


def collect_evidence_text(items: list[dict]) -> list[dict]:
    """
    Resolve each evidence item to its text representation.
    Returns list of {label, type, text}.
    """
    resolved = []
    for item in items:
        ev_type = item.get("type", "text")
        label = item.get("label", ev_type)

        if ev_type == "screenshot":
            path = item.get("path", "")
            if not Path(path).exists():
                resolved.append({
                    "label": label, "type": ev_type,
                    "text": f"[file not found: {path}]",
                    "error": True,
                })
                continue
            text = ocr_image(path)
            if not text:
                text = "[OCR returned no text — tesseract may not be installed or image is blank]"
        elif ev_type == "ocr":
            text = item.get("content", "")
        else:
            text = item.get("content", "")

        resolved.append({
            "label": label,
            "type": ev_type,
            "text": text,
            "error": False,
        })

    return resolved


def load_llm_config() -> dict:
    """
    Read ~/.nanobot/config.json and return {model, api_key, api_base, provider}.
    Priority: openrouter → grok → nvidia → groq.
    """
    config_path = Path.home() / ".nanobot" / "config.json"
    if not config_path.exists():
        return {}

    try:
        config = json.loads(config_path.read_text())
    except Exception:
        return {}

    # Use smart_model for evaluation — fast and cheap, not the main model
    model = (
        config.get("agents", {}).get("defaults", {}).get("smartModel")
        or config.get("agents", {}).get("defaults", {}).get("smart_model")
    )

    providers = config.get("providers", {})
    priority = ["openrouter", "grok", "nvidia", "groq"]

    for name in priority:
        p = providers.get(name, {})
        key = p.get("apiKey") or p.get("api_key", "")
        base = p.get("apiBase") or p.get("api_base", "")
        if key:
            # When routing through openrouter, prefix the model name so litellm
            # sends to openrouter regardless of the model's native provider prefix.
            if name == "openrouter" and model and not model.startswith("openrouter/"):
                model = f"openrouter/{model}"
            return {"model": model, "api_key": key, "api_base": base, "provider": name}

    return {}


def call_llm(claim: str, evidence_blocks: list[dict], image_paths: list[dict] = None) -> dict:
    """Call the configured LLM to evaluate the claim against evidence.
    image_paths: list of {label, path} for direct vision input (when OCR yields no useful text).
    """
    try:
        import litellm
    except ImportError:
        return {
            "verdict": "INCONCLUSIVE",
            "confidence": 0.0,
            "reasoning": "litellm not installed — cannot evaluate semantically",
            "issues": ["install litellm: pip install litellm"],
        }

    cfg = load_llm_config()
    if not cfg.get("api_key"):
        return {
            "verdict": "INCONCLUSIVE",
            "confidence": 0.0,
            "reasoning": "no LLM API key found in config.json",
            "issues": ["configure openrouter, grok, nvidia, or groq in ~/.nanobot/config.json"],
        }

    provider = cfg.get("provider", "")
    api_key = cfg["api_key"]
    api_base = cfg.get("api_base", "")

    env_key_map = {
        "openrouter": "OPENROUTER_API_KEY",
        "grok":       "XAI_API_KEY",
        "nvidia":     "NVIDIA_API_KEY",
        "groq":       "GROQ_API_KEY",
    }
    if provider in env_key_map:
        os.environ.setdefault(env_key_map[provider], api_key)
    if api_base:
        litellm.api_base = api_base

    litellm.suppress_debug_info = True
    litellm.drop_params = True

    # Build user message — text evidence first, then inline images if any
    evidence_text = ""
    for i, ev in enumerate(evidence_blocks, 1):
        excerpt = ev["text"][:3000]
        evidence_text += f"\n--- Evidence {i}: {ev['label']} ({ev['type']}) ---\n{excerpt}\n"

    if image_paths:
        # Vision message: multipart content with text + base64 images
        import base64
        content = [{"type": "text", "text": f"CLAIM:\n{claim}\n\nEVIDENCE (text):{evidence_text}\nAlso examine the attached image(s) directly."}]
        for img in image_paths:
            p = Path(img["path"])
            if p.exists():
                b64 = base64.b64encode(p.read_bytes()).decode()
                suffix = p.suffix.lower().lstrip(".")
                mime = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
                content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        user_content = content
    else:
        user_content = f"CLAIM:\n{claim}\n\nEVIDENCE:{evidence_text}"

    try:
        response = litellm.completion(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": _EVAL_SYSTEM_PROMPT},
                {"role": "user",   "content": user_content},
            ],
            max_tokens=400,
            temperature=0.0,
            ssl_verify=_SSL_VERIFY,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)

    except json.JSONDecodeError:
        return {
            "verdict": "INCONCLUSIVE",
            "confidence": 0.5,
            "reasoning": f"LLM returned non-JSON response: {raw[:200]}",
            "issues": [],
        }
    except Exception as e:
        return {
            "verdict": "INCONCLUSIVE",
            "confidence": 0.0,
            "reasoning": f"LLM call failed: {e}",
            "issues": [str(e)],
        }


def validate(payload: dict) -> dict:
    claim = payload.get("claim", "").strip()
    evidence_items = payload.get("evidence", [])

    if not claim:
        return {"error": "missing 'claim' field"}
    if not evidence_items:
        return {"error": "missing 'evidence' array"}

    resolved = collect_evidence_text(evidence_items)

    # For screenshot evidence where OCR yields little text, pass images directly to vision LLM
    image_paths = [
        {"label": ev["label"], "path": item["path"]}
        for ev, item in zip(resolved, evidence_items)
        if item.get("type") == "screenshot" and len(ev.get("text", "").strip()) < 100
    ]
    result = call_llm(claim, resolved, image_paths=image_paths or None)

    return {
        "verdict":          result.get("verdict", "INCONCLUSIVE"),
        "confidence":       result.get("confidence", 0.0),
        "reasoning":        result.get("reasoning", ""),
        "issues":           result.get("issues", []),
        "claim":            claim,
        "evidence_results": [
            {
                "label":        ev["label"],
                "type":         ev["type"],
                "text_excerpt": ev["text"][:300],
            }
            for ev in resolved
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Validate a claim against evidence using OCR + LLM")
    parser.add_argument("--json", dest="json_str", help="JSON payload as string")
    args, _ = parser.parse_known_args()

    if args.json_str:
        raw = args.json_str
    elif not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
    else:
        parser.print_help()
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"invalid JSON: {e}"}))
        sys.exit(1)

    result = validate(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
