"""Synthetic FinOps planning calculations; no network, pricing or runtime authority."""
from decimal import Decimal, InvalidOperation


def money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("amount must be finite and non-negative")
    return amount


def cost(quantity, unit_rate):
    return money(quantity) * money(unit_rate)


def cost_per_success(total, successes):
    if not isinstance(successes, int) or isinstance(successes, bool) or successes <= 0:
        raise ValueError("successful outcomes must be positive")
    return money(total) / Decimal(successes)


def variance(actual, forecast):
    actual, forecast = money(actual), money(forecast)
    return {"usd": actual - forecast, "percent": None if forecast == 0 else (actual - forecast) / forecast * 100}


def utilization(used_hours, provisioned_hours):
    used, provisioned = money(used_hours), money(provisioned_hours)
    if provisioned == 0 or used > provisioned:
        raise ValueError("capacity hours must be positive and used <= provisioned")
    return used / provisioned


def examples():
    api = cost(2, 2) + cost(Decimal("0.5"), 8)
    agent = cost(100, Decimal("0.07")) + cost(10, Decimal("0.02"))
    host = cost(120, Decimal("1.5")) + money(20) + cost(4, 30)
    return {
        "api": {"usd": api, "cost_per_success": cost_per_success(api, 1600)},
        "agent": {"usd": agent, "cost_per_success": cost_per_success(agent, 80)},
        "host": {"usd": host, "cost_per_success": cost_per_success(host, 8000), "utilization": utilization(120, 240)},
    }
