"""Offline schema for synthetic, derived FinOps planning records."""
import re
from datetime import date
from fractions import Fraction

CATEGORIES = {
    "inference", "cache", "embeddings_retrieval", "tools_orchestration",
    "compute", "storage_observability", "human_oversight", "other",
}
REQUIRED_TEXT = {
    "record_id", "source_record_id", "period", "scenario", "category",
    "unit", "basis", "source", "source_date",
}
ATTRIBUTION = {
    "product", "project", "team", "tenant", "agent", "workflow", "model",
    "provider", "environment", "business_outcome",
}
DECIMAL = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,8})?")
REQUIRED = REQUIRED_TEXT | {"amount_usd"}
OPTIONAL = ATTRIBUTION | {"quantity", "unit_rate_usd", "direct_amount_reason"}


def decimal_value(record, field):
    value = record.get(field)
    if not isinstance(value, str) or not DECIMAL.fullmatch(value):
        raise ValueError(f"{field} must be a nonnegative decimal string")
    return Fraction(value)


def validate_record(record):
    if not isinstance(record, dict):
        raise ValueError("expected a planning record object")
    missing = REQUIRED - record.keys()
    unexpected = record.keys() - REQUIRED - OPTIONAL
    if missing or unexpected:
        raise ValueError(f"missing fields {sorted(missing)} or unknown fields {sorted(unexpected)}")

    text_fields = REQUIRED_TEXT | (record.keys() & (ATTRIBUTION | {"direct_amount_reason"}))
    for field in sorted(text_fields):
        value = record[field]
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"{field} must be nonempty text with no surrounding whitespace")

    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", record["period"]):
        raise ValueError("period must use YYYY-MM")
    date.fromisoformat(record["period"] + "-01")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", record["source_date"]):
        raise ValueError("source_date must use YYYY-MM-DD")
    date.fromisoformat(record["source_date"])
    if record["category"] not in CATEGORIES:
        raise ValueError("unknown cost category")
    if record["basis"] not in {"metered", "estimated"}:
        raise ValueError("basis must be metered or estimated")

    amount = decimal_value(record, "amount_usd")
    rate_fields = record.keys() & {"quantity", "unit_rate_usd"}
    if "direct_amount_reason" in record:
        if rate_fields or record["unit"] != "charge":
            raise ValueError("direct amounts require unit 'charge' and no quantity or rate")
    elif amount != decimal_value(record, "quantity") * decimal_value(record, "unit_rate_usd"):
        raise ValueError("amount_usd must equal quantity multiplied by unit_rate_usd")


def validate_records(records):
    """Reject repeated records and repeated source charges within a scenario."""
    if not isinstance(records, list) or not records:
        raise ValueError("expected a nonempty array of planning records")
    record_ids = set()
    source_charges = set()
    for index, record in enumerate(records):
        try:
            validate_record(record)
            record_id = record["record_id"]
            source_charge = (record["scenario"], record["source_record_id"])
            if record_id in record_ids:
                raise ValueError("duplicate record_id")
            if source_charge in source_charges:
                raise ValueError("duplicate source charge within scenario")
            record_ids.add(record_id)
            source_charges.add(source_charge)
        except ValueError as exc:
            raise ValueError(f"record {index + 1}: {exc}") from exc
