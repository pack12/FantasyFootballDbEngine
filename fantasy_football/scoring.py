from .models import Player, PlayerStats

# PPR scoring rules
SCORING_RULES = {
    "rushing_yards": 0.1,        # 1 point per 10 yards
    "rushing_tds": 6.0,
    "receptions": 1.0,           # PPR: 1 point per reception
    "receiving_yards": 0.1,      # 1 point per 10 yards
    "receiving_tds": 6.0,
    "fumbles_lost": -2.0,
    "two_point_conversions": 2.0,
}


def calculate_score(stats: PlayerStats) -> float:
    """Calculate PPR fantasy points from a stat line."""
    points = 0.0
    for stat_name, multiplier in SCORING_RULES.items():
        points += getattr(stats, stat_name, 0) * multiplier
    return round(points, 2)


def score_player(player: Player) -> Player:
    """Score a player and update their fantasy_points field."""
    player.fantasy_points = calculate_score(player.stats)
    return player


def score_players(players: list[Player]) -> list[Player]:
    """Score a list of players and return them sorted by points (descending)."""
    for player in players:
        score_player(player)
    return sorted(players, key=lambda p: p.fantasy_points, reverse=True)
