"""Small-sample statistics for comparing runs."""

import math


def wilson_interval(correct: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    p = correct / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    denominator = 1 + z * z / total
    return max(0.0, (centre - spread) / denominator), min(1.0, (centre + spread) / denominator)


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar test on the clues where two runs disagree."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(only_a, only_b) + 1)) / 2**n
    return min(1.0, 2 * tail)
