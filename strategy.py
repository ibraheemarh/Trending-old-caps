from dataclasses import dataclass
from typing import List, Dict, Any
from datetime import datetime, timezone


# =====================================================
# SECOND-WAVE STRATEGY CONFIGURATION
# =====================================================

MIN_INITIAL_PUMP_PCT = 50.0
MIN_DRAWDOWN_PCT = 30.0
MIN_RECOVERY_PCT = 10.0

MIN_CONSOLIDATION_MINUTES = 30
MAX_CONSOLIDATION_RANGE_PCT = 20.0

MIN_SAMPLES = 8
MIN_VOLUME_IMPROVEMENT = 1.20

MIN_OPPORTUNITY_SCORE = 60


# =====================================================
# DATA STRUCTURE
# =====================================================

@dataclass
class Observation:
    timestamp: float
    price: float
    volume: float = 0.0
    buys: int = 0
    sells: int = 0


# =====================================================
# GENERAL CALCULATIONS
# =====================================================

def percentage_change(start: float, end: float) -> float:
    if start <= 0:
        return 0.0

    return ((end - start) / start) * 100.0


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)

        if result != result:
            return default

        return result

    except (TypeError, ValueError):
        return default


# =====================================================
# HISTORY NORMALIZATION
# =====================================================

def normalize_history(
    history: List[Dict[str, Any]]
) -> List[Observation]:

    observations = []

    for item in history:
        timestamp = safe_float(item.get("timestamp"))
        price = safe_float(item.get("price"))

        if timestamp <= 0 or price <= 0:
            continue

        observations.append(
            Observation(
                timestamp=timestamp,
                price=price,
                volume=safe_float(item.get("volume")),
                buys=int(safe_float(item.get("buys"))),
                sells=int(safe_float(item.get("sells"))),
            )
        )

    observations.sort(key=lambda item: item.timestamp)

    return observations


# =====================================================
# SECOND-WAVE ANALYSIS
# =====================================================

def analyze_second_wave(
    history: List[Dict[str, Any]]
) -> Dict[str, Any]:

    observations = normalize_history(history)

    result = {
        "qualified": False,
        "score": 0,
        "initial_pump_pct": 0.0,
        "drawdown_pct": 0.0,
        "recovery_pct": 0.0,
        "consolidation_minutes": 0.0,
        "consolidation_range_pct": 0.0,
        "volume_improvement": 0.0,
        "buy_pressure_improving": False,
        "reasons": [],
        "warnings": [],
    }

    if len(observations) < MIN_SAMPLES:
        result["warnings"].append(
            f"Insufficient history: need at least "
            f"{MIN_SAMPLES} observations."
        )

        return result

    first = observations[0]
    latest = observations[-1]

    if latest.timestamp <= first.timestamp:
        result["warnings"].append(
            "Invalid observation time sequence."
        )

        return result

    # -------------------------------------------------
    # 1. Find the highest price and subsequent low
    # -------------------------------------------------

    peak_index = max(
        range(len(observations)),
        key=lambda index: observations[index].price,
    )

    peak = observations[peak_index]

    if peak_index >= len(observations) - 2:
        result["warnings"].append(
            "Not enough observations after the price peak."
        )

        return result

    post_peak = observations[peak_index + 1:]

    low_index = min(
        range(len(post_peak)),
        key=lambda index: post_peak[index].price,
    )

    low = post_peak[low_index]

    post_low = post_peak[low_index + 1:]

    if not post_low:
        result["warnings"].append(
            "Not enough observations after the post-peak low."
        )

        return result

    # -------------------------------------------------
    # 2. Calculate pump, drawdown and recovery
    # -------------------------------------------------

    initial_pump = percentage_change(
        first.price,
        peak.price,
    )

    drawdown = percentage_change(
        peak.price,
        low.price,
    ) * -1

    recovery = percentage_change(
        low.price,
        latest.price,
    )

    result["initial_pump_pct"] = round(initial_pump, 2)
    result["drawdown_pct"] = round(drawdown, 2)
    result["recovery_pct"] = round(recovery, 2)

    # -------------------------------------------------
    # 3. Measure consolidation
    # -------------------------------------------------

    consolidation = post_peak[low_index:]

    if len(consolidation) >= 2:
        consolidation_minutes = (
            consolidation[-1].timestamp
            - consolidation[0].timestamp
        ) / 60.0

        prices = [
            item.price for item in consolidation
        ]

        price_low = min(prices)
        price_high = max(prices)

        consolidation_range = (
            (price_high - price_low) / price_low
        ) * 100.0 if price_low > 0 else 0.0

    else:
        consolidation_minutes = 0.0
        consolidation_range = 0.0

    result["consolidation_minutes"] = round(
        consolidation_minutes,
        2,
    )

    result["consolidation_range_pct"] = round(
        consolidation_range,
        2,
    )

    # -------------------------------------------------
    # 4. Compare recent and earlier volume
    # -------------------------------------------------

    midpoint = len(observations) // 2

    earlier = observations[:midpoint]
    recent = observations[midpoint:]

    earlier_volume = sum(
        item.volume for item in earlier
    ) / max(len(earlier), 1)

    recent_volume = sum(
        item.volume for item in recent
    ) / max(len(recent), 1)

    if earlier_volume > 0:
        volume_improvement = (
            recent_volume / earlier_volume
        )
    else:
        volume_improvement = 0.0

    result["volume_improvement"] = round(
        volume_improvement,
        2,
    )

    # -------------------------------------------------
    # 5. Evaluate buying pressure
    # -------------------------------------------------

    earlier_buys = sum(
        item.buys for item in earlier
    )

    earlier_sells = sum(
        item.sells for item in earlier
    )

    recent_buys = sum(
        item.buys for item in recent
    )

    recent_sells = sum(
        item.sells for item in recent
    )

    earlier_ratio = (
        earlier_buys / max(earlier_sells, 1)
    )

    recent_ratio = (
        recent_buys / max(recent_sells, 1)
    )

    pressure_improving = (
        recent_ratio > earlier_ratio
        and recent_buys > recent_sells
    )

    result["buy_pressure_improving"] = pressure_improving

    # -------------------------------------------------
    # 6. Score the potential setup
    # -------------------------------------------------

    score = 0
    reasons = []

    if initial_pump >= MIN_INITIAL_PUMP_PCT:
        score += 20
        reasons.append("Initial pump threshold reached.")

    if drawdown >= MIN_DRAWDOWN_PCT:
        score += 20
        reasons.append("Significant drawdown detected.")

    if recovery >= MIN_RECOVERY_PCT:
        score += 20
        reasons.append("Recovery from the post-peak low.")

    if consolidation_minutes >= MIN_CONSOLIDATION_MINUTES:
        score += 15
        reasons.append("Consolidation duration reached.")

    if consolidation_range <= MAX_CONSOLIDATION_RANGE_PCT:
        score += 10
        reasons.append("Price range is relatively contained.")

    if volume_improvement >= MIN_VOLUME_IMPROVEMENT:
        score += 10
        reasons.append("Volume has improved.")

    if pressure_improving:
        score += 5
        reasons.append("Buying pressure is improving.")

    result["score"] = score
    result["reasons"] = reasons

    # -------------------------------------------------
    # 7. Determine qualification
    # -------------------------------------------------

    result["qualified"] = (
        initial_pump >= MIN_INITIAL_PUMP_PCT
        and drawdown >= MIN_DRAWDOWN_PCT
        and recovery >= MIN_RECOVERY_PCT
        and consolidation_minutes >= MIN_CONSOLIDATION_MINUTES
        and score >= MIN_OPPORTUNITY_SCORE
    )

    if not result["qualified"]:
        result["warnings"].append(
            "The observed history does not meet all "
            "second-wave qualification conditions."
        )

    return result
