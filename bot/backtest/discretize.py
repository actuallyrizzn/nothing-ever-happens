"""Discretization policies P1 / P2 (§5.1)."""

from __future__ import annotations

from bot.config import NothingHappensConfig


def discretize_p1(points: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """Data-native: every cached bar, sorted."""
    return sorted(points, key=lambda x: x[0])


def discretize_p2(
    points: list[tuple[int, float]],
    *,
    t_open: int,
    poll_interval_sec: int,
) -> list[tuple[int, float]]:
    """Poll-aligned evaluation times; ``p`` = nearest neighbor in ``points``.

    Each tuple is ``(t_grid, p_neighbor)`` so ``t_first`` matches poll clock (§5.1 P2).
    """
    if not points or poll_interval_sec <= 0:
        return discretize_p1(points)
    t_last = points[-1][0]
    if t_open > t_last:
        return []

    out: list[tuple[int, float]] = []
    t_grid = int(t_open)
    step = int(poll_interval_sec)
    while t_grid <= t_last:
        best_t, best_p = points[0]
        best_d = abs(best_t - t_grid)
        for t_i, p_i in points:
            d = abs(t_i - t_grid)
            if d < best_d or (d == best_d and t_i < best_t):
                best_d = d
                best_t, best_p = t_i, p_i
        out.append((t_grid, best_p))
        t_grid += step
    return out


def discretize_for_run(
    points: list[tuple[int, float]],
    policy: str,
    *,
    t_open: int | None,
    cfg: NothingHappensConfig,
) -> list[tuple[int, float]]:
    policy_u = policy.strip().upper()
    if policy_u in {"", "P1", "DATA_NATIVE"}:
        return discretize_p1(points)
    if policy_u in {"P2", "POLL_ALIGNED"}:
        if t_open is None:
            raise ValueError("P2 discretization requires t_open on the universe row")
        return discretize_p2(
            points,
            t_open=int(t_open),
            poll_interval_sec=int(cfg.price_poll_interval_sec),
        )
    if policy_u in {"P3", "HYBRID"}:
        # v1: same as P1 for the first-hit scan (§5.1 recommendation).
        return discretize_p1(points)
    raise ValueError(f"Unknown discretization policy: {policy!r}")
