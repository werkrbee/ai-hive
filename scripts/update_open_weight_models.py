#!/usr/bin/env python3
"""Collect model-card metadata for a curated set of exact upstream model IDs."""
import argparse
import datetime
import json
import pathlib
import re
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


def validate_metadata(item, model_id):
    """Validate consumed API fields without inferring licensing or access rights."""
    def invalid(field, reason):
        # Identify the source and field, never dump arbitrary upstream values.
        raise ValueError(f"Invalid metadata for {model_id}: {field} {reason}") from None

    def optional_text(value, field):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            invalid(field, "must be a nonempty string or null")

    if not isinstance(item, dict):
        invalid("response", "must be a JSON object")
    if item.get("id") != model_id:
        invalid("id", "must match the requested model")
    revision = item.get("sha")
    if not isinstance(revision, str) or not re.fullmatch(
        r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", revision
    ):
        invalid("sha", "must be a full 40- or 64-character hexadecimal commit ID")
    gated = item.get("gated")
    if gated is not False and gated not in ("auto", "manual"):
        invalid("gated", "must be false, 'auto', or 'manual'")
    card = item.get("cardData")
    if card is not None and not isinstance(card, dict):
        invalid("cardData", "must be an object or null")
    for field in ("license", "license_name", "license_link"):
        optional_text((card or {}).get(field), "cardData." + field)
    tags = item.get("tags", [])
    if not isinstance(tags, list):
        invalid("tags", "must be an array of nonempty strings")
    for index, tag in enumerate(tags):
        if not isinstance(tag, str) or not tag.strip():
            invalid(f"tags[{index}]", "must be a nonempty string")
        if tag.startswith("license:") and not tag.removeprefix("license:").strip():
            invalid(f"tags[{index}]", "must contain a license value")
    siblings = item.get("siblings")
    if not isinstance(siblings, list):
        invalid("siblings", "must be an array of file objects")
    for index, entry in enumerate(siblings):
        field = f"siblings[{index}].rfilename"
        if not isinstance(entry, dict):
            invalid(f"siblings[{index}]", "must be a file object")
        name = entry.get("rfilename")
        if (not isinstance(name, str) or not name.strip()
                or any(part in ("", ".", "..") for part in name.split("/"))
                or "\\" in name or any(ord(char) < 32 or ord(char) == 127 for char in name)):
            invalid(field, "must be a nonempty relative repository file path")
    modified = item.get("lastModified")
    optional_text(modified, "lastModified")
    if modified is not None:
        try:
            parsed = datetime.datetime.fromisoformat(modified.replace("Z", "+00:00"))
        except ValueError:
            invalid("lastModified", "must be an ISO 8601 timestamp with a timezone")
        if parsed.tzinfo is None:
            invalid("lastModified", "must include a timezone")


def fetch_model(model_id, opener=urllib.request.urlopen):
    url = "https://huggingface.co/api/models/" + urllib.parse.quote(model_id, safe="/")
    request = urllib.request.Request(url, headers={"User-Agent": "ai-hive-open-weights-tracker/1.0"})
    with opener(request, timeout=25) as response:
        try:
            item = json.load(response)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError(f"Invalid metadata for {model_id}: response is not valid JSON") from None
    validate_metadata(item, model_id)
    card = item.get("cardData") or {}
    tags = item.get("tags") or []
    license_tag = card.get("license") or next(
        (tag.removeprefix("license:") for tag in tags if tag.startswith("license:")), None
    )
    revision = item.get("sha")
    files = [entry["rfilename"] for entry in item.get("siblings", [])
             if entry.get("rfilename", "").endswith((".safetensors", ".bin"))]
    license_file = next((entry["rfilename"] for entry in item.get("siblings", [])
                         if entry.get("rfilename", "").upper() in ("LICENSE", "LICENSE.TXT", "LICENSE.MD")), None)
    base = "https://huggingface.co/" + model_id
    revision_path = urllib.parse.quote(revision, safe="")
    return {
        "model_id": model_id,
        "model_card": "https://huggingface.co/" + model_id,
        "license_tag_unverified": license_tag,
        "license_name_unverified": card.get("license_name"),
        "license_link_unverified": card.get("license_link") or (
            base + "/blob/" + revision_path + "/" + license_file if license_file else None
        ),
        "upstream_revision": revision,
        "download_page": base + "/tree/" + revision_path,
        "weight_file_count": len(files),
        "example_weight_download": (base + "/resolve/" + revision_path + "/" +
                                    urllib.parse.quote(files[0], safe="/")) if files else None,
        "gated": item["gated"],
        "last_modified": item.get("lastModified"),
        "source_api": url,
    }


def build_snapshot(month, fetch=fetch_model):
    # Month-keyed metadata; deterministic output on repeat runs.
    datetime.date.fromisoformat(month + "-01")
    return {
        "schema_version": 2,
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
