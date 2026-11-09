"""Independent NHL goal simulation research module.

No network calls, no changes to model scores, ranks, tiers or hammer rules.
Probabilities are experimental and require out-of-sample calibration.
"""
from __future__ import annotations

import math
import random
import hashlib


def simulate_anytime_goal(*, shots_per_game, goals, shots, games_played,
                          trials=10_000, seed=None):
    """Simulate at least one goal in a game using a Poisson shot process.

    Shots ~ Poisson(shots_per_game), and each shot scores independently with
    a smoothed player conversion rate. Poisson thinning gives goals ~
    Poisson(shots_per_game * conversion_rate), allowing efficient sampling.
    The smoothing prior is 10% on 50 shots; this is a provisional assumption,
    not a calibrated NHL conversion estimate.
    """
    try:
        volume = float(shots_per_game)
        g, s, gp = float(goals), float(shots), float(games_played)
        n = int(trials)
    except (TypeError, ValueError, OverflowError):
        return None
    if (not all(map(math.isfinite, (volume, g, s, gp))) or
            volume < 0 or g < 0 or s <= 0 or gp < 5 or
            g > s or n < 1 or n > 100_000):
        return None
    # An explicit minimum sample avoids misleading precision.
    if s < 10:
        return None
    conversion = (g + 5.0) / (s + 50.0)
    goal_rate = volume * conversion
    p_goal = -math.expm1(-goal_rate)
    rng = random.Random(seed)
    successes = sum(rng.random() < p_goal for _ in range(n))
    estimate = successes / n
    se = math.sqrt(estimate * (1 - estimate) / n)
    return {
        "Sim Goal %": round(100 * estimate, 1),
        "Sim xGoals": round(goal_rate, 3),
        "Sim 95% MC Low": round(100 * max(0, estimate - 1.96 * se), 1),
        "Sim 95% MC High": round(100 * min(1, estimate + 1.96 * se), 1),
        "Sim Trials": n,
        "Sim Method": "Poisson shots + smoothed goal/shot conversion",
        "Sim Note": "Experimental; MC interval excludes model uncertainty",
    }


def simulate_skaters(frame, trials=10_000, slate_date=""):
    """Return a separate display frame; never mutate the original board."""
    result = frame.copy()
    records = []
    for _, player in result.iterrows():
        identity = f"{slate_date}|{player.get('Player_ID', '')}|{trials}"
        seed = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big")
        records.append(simulate_anytime_goal(
            shots_per_game=player.get("L10 S/GP"),
            goals=player.get("Goals"),
            shots=player.get("Shots"),
            games_played=player.get("GP"),
            trials=trials,
            seed=seed,
        ))
    for col in ("Sim Goal %", "Sim xGoals", "Sim 95% MC Low",
                "Sim 95% MC High", "Sim Trials", "Sim Method", "Sim Note"):
        result[col] = [row.get(col) if row else None for row in records]
    return result
