#!/usr/bin/env python3
"""Fetch a dated, reviewable sample of open-weight model metadata. Standard library only."""
import datetime
import json
import os
import pathlib
import urllib.parse
import urllib.request

MODELS = [
    "meta-llama/Llama-3.1-8B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "Qwen/Qwen2.5-7B-Instruct",
    "deepseek-ai/DeepSeek-R1",
    "google/gemma-3-4b-it",
    "microsoft/phi-4",
    "openai/gpt-oss-20b",
]
OUTPUT = pathlib.Path("docs/open-weight-models-monthly.json")


def main():
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    rows = []
    for model in MODELS:
        url = "https://huggingface.co/api/models/" + urllib.parse.quote(model, safe="/")
        request = urllib.request.Request(url, headers={"User-Agent": "ai-hive-open-weights-tracker/1.0"})
        with urllib.request.urlopen(request, timeout=25) as response:
            item = json.load(response)
        card = item.get("cardData") or {}
        tags = item.get("tags") or []
        license_tag = card.get("license") or next((t.removeprefix("license:") for t in tags if t.startswith("license:")), None)
        rows.append({
            "model_id": model,
            "model_card": "https://huggingface.co/" + model,
            "license_tag_unverified": license_tag,
            "gated": item.get("gated", "unknown"),
            "last_modified": item.get("lastModified"),
            "source_api": url,
        })
    payload = {"schema_version": 1, "checked_utc": today, "disclaimer": "API metadata is not legal verification. Review exact license files and model cards.", "models": rows}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
