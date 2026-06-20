"""
Single source of truth for MLB/MiLB league-level logic.

Every piece of level knowledge — sportId mapping, historical-spelling aliases,
hierarchy rank, and era-aware display string — lives here. No other module may
define its own level constant table; they import from this one instead.

Background: the 2020–21 MiLB reorganization renamed levels and eliminated the
short-season tier, but the *hierarchy* never changed. So we model each level as
a "tier" with a stable rank, plus an era-aware display name:

    tier   rank  2021+ (modern)   2020- (legacy / "period name")
    ─────  ────  ──────────────   ──────────────────────────────
    MLB     0    MLB              MLB
    AAA     1    AAA              AAA
    AA      2    AA               AA
    A+      3    A+  (High-A)     A(Adv)  (Class A-Advanced)
    A       4    A   (Low-A)      A(Full) (Class A full-season)
    A-      5    — (eliminated)   A(Short) (Class A Short Season)
    ROK     6    ROK              ROK
    WIN     7    WIN              WIN
    Minors  99   Minors           Minors

`level_rank` collapses every era/spelling onto its tier for sorting/comparison;
`level_display` keeps the period-accurate name (driven by the season `year`).
"""

from dataclasses import dataclass
from typing import Optional

# Season cutoff: 2021 onward uses the reorganized ("modern") names. 2020 had no
# MiLB season (COVID), so the boundary is clean.
_MODERN_FROM_YEAR = 2021

# Sentinel values used by client-side filters; never treated as real levels.
_SENTINELS = frozenset({"_combined", "_all", ""})


@dataclass(frozen=True)
class Tier:
    key: str                       # canonical tier key, e.g. "A+"
    rank: int                      # hierarchy rank (lower = higher level)
    sport_ids: tuple               # MLB Stats API sportId(s)
    modern: Optional[str]          # 2021+ display string (None = tier eliminated)
    legacy: str                    # 2020- display string ("period name")
    aliases: tuple                 # every raw spelling seen in the API / DB
    names: tuple = ()              # official MLB Stats API sport `name` strings


# ── The one and only level table ──
TIERS = (
    Tier("MLB",    0,  (1,),  "MLB",    "MLB",      ("MLB",),
         ("Major League Baseball",)),
    Tier("AAA",    1,  (11,), "AAA",    "AAA",      ("AAA",),
         ("Triple-A",)),
    Tier("AA",     2,  (12,), "AA",     "AA",       ("AA",),
         ("Double-A",)),
    Tier("A+",     3,  (13,), "A+",     "A(Adv)",   ("A+", "A(Adv)", "A (Adv)"),
         ("High-A", "Class A-Advanced", "Class A Advanced")),
    Tier("A",      4,  (14,), "A",      "A(Full)",  ("A", "A(Full)", "A (Full)"),
         ("Single-A", "Low-A", "Class A")),
    Tier("A-",     5,  (15,), None,     "A(Short)", ("A-", "A(Short)", "A (Short)"),
         ("Class A Short Season",)),
    Tier("ROK",    6,  (16,), "ROK",    "ROK",      ("ROK", "ROA", "Rk", "Rookie"),
         ("Rookie", "Rookie Advanced")),
    Tier("WIN",    7,  (17,), "WIN",    "WIN",      ("WIN",),
         ("Winter Leagues",)),
    Tier("Minors", 99, (21,), "Minors", "Minors",   ("Minors",),
         ("Minor League Baseball",)),
)

_UNKNOWN_RANK = 50  # below every real level, above the "Minors" aggregate (99)

_BY_ALIAS = {alias: t for t in TIERS for alias in t.aliases}
_BY_SPORT_ID = {sid: t for t in TIERS for sid in t.sport_ids}
_BY_NAME = {name: t for t in TIERS for name in t.names}


def resolve_tier(raw: Optional[str]) -> Optional[Tier]:
    """Resolve any raw level spelling (modern code or historical) to its Tier."""
    if not raw:
        return None
    return _BY_ALIAS.get(raw)


def level_rank(raw: Optional[str]) -> int:
    """Hierarchy rank for sorting/comparison (lower = higher level).

    Collapses every era/spelling onto its tier, so `A(Adv)` and `A+` rank equal.
    Unknown levels fall back to 50 (below real levels, above the Minors aggregate).
    """
    tier = resolve_tier(raw)
    return tier.rank if tier else _UNKNOWN_RANK


def level_display(raw: Optional[str], year: Optional[int]) -> Optional[str]:
    """Period-accurate display string for *raw* as it was known in *year*.

    - Sentinels (`_combined`, `_all`, ``) and unknown values pass through.
    - 2021+ seasons use the modern code (A+, A, ROK …); 2020- seasons keep the
      period name (A(Adv), A(Full), A(Short) …). Driven by *year*.
    - This makes game_logs (which store modern codes) and season_stats (which
      store period names) render identically for the same season.
    """
    if raw in _SENTINELS or raw is None:
        return raw
    tier = resolve_tier(raw)
    if tier is None:
        return raw
    if year is not None and year >= _MODERN_FROM_YEAR and tier.modern is not None:
        return tier.modern
    return tier.legacy


def is_mlb(raw: Optional[str]) -> bool:
    """Whether *raw* is the MLB tier (used for the hero badge's special style)."""
    tier = resolve_tier(raw)
    return tier is not None and tier.key == "MLB"


def sport_id_to_code(sport_id: int) -> str:
    """Map an MLB Stats API sportId to a stored level code.

    Used at sync time for currentTeam / game-log levels. Falls back to the
    period name for the defunct sportId 15 (short season) so the stored value is
    never empty; the display layer normalizes it anyway.
    """
    tier = _BY_SPORT_ID.get(sport_id)
    if tier is None:
        return ""
    return tier.modern or tier.legacy


def sport_name_to_code(name: str) -> str:
    """Map an official MLB Stats API sport ``name`` to a stored level code.

    Fallback for :func:`sport_id_to_code` when only the sport name is available.
    Returns ``tier.modern or tier.legacy`` (so the defunct short season yields
    its period name, never empty); unknown names yield ``""``.
    """
    tier = _BY_NAME.get(name)
    if tier is None:
        return ""
    return tier.modern or tier.legacy


def tier_keys_ordered() -> list:
    """Tier keys ordered by rank (highest level first) — for SQL CASE ordering."""
    return [t.key for t in sorted(TIERS, key=lambda t: t.rank)]
