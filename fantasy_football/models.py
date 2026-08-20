from dataclasses import dataclass, field


@dataclass
class PlayerStats:
    """Raw stat line for a QB, RB, WR, or TE."""
    passing_yards: float = 0.0
    passing_tds: int = 0
    interceptions: int = 0
    passing_attempts: int = 0
    passing_completions: int = 0
    rushing_yards: float = 0.0
    rushing_tds: int = 0
    receptions: int = 0
    receiving_yards: float = 0.0
    receiving_tds: int = 0
    fumbles_lost: int = 0
    two_point_conversions: int = 0
    rushing_attempts: int = 0
    targets: int = 0
    games_played: int = 0


@dataclass
class Player:
    name: str
    team: str
    position: str  # "QB", "RB", "WR", or "TE"
    espn_id: int = 0
    age: int | None = None
    stats: PlayerStats = field(default_factory=PlayerStats)
    fantasy_points: float = 0.0
    avg_pts_g_3yr: float | None = None
    avg_pts_3yr: float | None = None
    seasons_played: int = 0  # how many of the 3 prior seasons have data
    games_played_3yr: int = 0  # total GP across 3 prior seasons
    games_missed_3yr: int = 0  # total games missed across 3 prior seasons
    reliability_score: float | None = None  # composite: recency-weighted Pts/G * availability rate
    breakout: bool = False  # True if latest season Pts/G is 40%+ above prior average
    college_dom_score: float | None = None  # college dominance score (final year fantasy Pts/G estimate)
    college_final_year: str = ""  # summary of final college season stats
