#!/usr/bin/env python3
"""Collect model-card metadata for a curated set of exact upstream model IDs."""
import argparse
import datetime
import json
import pathlib
import urllib.parse
import urllib.request

MODELS = (
    "meta-llama/Llama-3.1-8B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "Qwen/Qwen2.5-7B-Instruct",
    "deepseek-ai/DeepSeek-R1",
    "google/gemma-3-4b-it",
    "microsoft/phi-4",
    "openai/gpt-oss-20b",
    "zai-org/GLM-4.5",
    "moonshotai/Kimi-K2-Instruct",
    "nvidia/NVIDIA-Nemotron-Nano-9B-v2",
)
OUTPUT = pathlib.Path("docs/open-weight-models-monthly.json")


def fetch_model(model_id, opener=urllib.request.urlopen):
    url = "https://huggingface.co/api/models/" + urllib.parse.quote(model_id, safe="/")
    request = urllib.request.Request(url, headers={"User-Agent": "ai-hive-open-weights-tracker/1.0"})
    with opener(request, timeout=25) as response:
        item = json.load(response)
    if item.get("id") != model_id:
        raise ValueError(f"Unexpected model identity for {model_id}")
    card = item.get("cardData") or {}
    tags = item.get("tags") or []
    license_tag = card.get("license") or next(
        (tag.removeprefix("license:") for tag in tags if tag.startswith("license:")), None
    )
    return {
        "model_id": model_id,
        "model_card": "https://huggingface.co/" + model_id,
        "license_tag_unverified": license_tag,
        "gated": item.get("gated", "unknown"),
        "last_modified": item.get("lastModified"),
        "source_api": url,
    }


def build_snapshot(month, fetch=fetch_model):
    # One review per calendar month; deterministic output on repeat runs.
    datetime.date.fromisoformat(month + "-01")
    return {
        "schema_version": 1,
        "review_month_utc": month,
        "disclaimer": "Model API tags are not legal verification; check the exact LICENSE and model card.",
        "models": [fetch(model_id) for model_id in MODELS],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m"))
    parser.add_argument("--output", type=pathlib.Path, default=OUTPUT)
    args = parser.parse_args()
    payload = build_snapshot(args.month)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
