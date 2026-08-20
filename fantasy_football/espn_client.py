import json
import requests
from .models import Player, PlayerStats

# ESPN stat ID to our field name mapping
STAT_ID_MAP = {
    "0": "passing_attempts",
    "1": "passing_completions",
    "3": "passing_yards",
    "4": "passing_tds",
    "20": "interceptions",
    "19": "two_point_conversions",   # passing 2pt
    "23": "rushing_attempts",
    "24": "rushing_yards",
    "25": "rushing_tds",
    "26": "two_point_conversions",   # rushing 2pt
    "41": "receptions",
    "42": "receiving_yards",
    "43": "receiving_tds",
    "44": "two_point_conversions",   # receiving 2pt
    "58": "targets",
    "72": "fumbles_lost",
    "210": "games_played",
}

# ESPN position IDs (defaultPositionId)
POSITION_MAP = {1: "QB", 2: "RB", 3: "WR", 4: "TE"}

# ESPN slot IDs for filtering (different from position IDs)
SLOT_IDS = [0, 2, 4, 6]  # QB=0, RB=2, WR=4, TE=6

BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}/segments/0/leaguedefaults/3"
ATHLETE_URL = "https://site.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{athlete_id}"


def fetch_players(year: int = 2024, week: int = 0, limit: int = 100) -> list[Player]:
    """
    Fetch RB and WR stats from ESPN's public API.

    Args:
        year: NFL season year.
        week: Week number (0 = full season totals).
        limit: Max number of players to return.
    """
    url = BASE_URL.format(year=year)
    params = {"view": "kona_player_info"}
    if week > 0:
        params["scoringPeriodId"] = week

    filters = {
        "players": {
            "filterSlotIds": {"value": SLOT_IDS},
            "limit": limit,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
            "filterStatus": {"value": ["FREEAGENT", "WAIVERS", "ONTEAM"]},
        }
    }

    headers = {"X-Fantasy-Filter": json.dumps(filters)}
    response = requests.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()

    data = response.json()
    players = _parse_players(data, year, week)
    _fetch_ages(players)
    return players


def _parse_players(data: dict, year: int, week: int) -> list[Player]:
    """Parse ESPN API response into Player objects."""
    players = []

    for entry in data.get("players", []):
        player_data = entry.get("player", {})
        position_id = player_data.get("defaultPositionId")

        if position_id not in POSITION_MAP:
            continue

        player = Player(
            name=player_data.get("fullName", "Unknown"),
            team=_get_team_abbrev(player_data.get("proTeamId", 0)),
            position=POSITION_MAP[position_id],
            espn_id=player_data.get("id", 0),
        )

        # Find the right stat set (season or weekly)
        stat_set = _find_stat_set(player_data.get("stats", []), year, week)
        if stat_set:
            player.stats = _parse_stats(stat_set.get("stats", {}))

        players.append(player)

    return players


def _find_stat_set(stat_sets: list, year: int, week: int) -> dict | None:
    """Find the matching stat set for the requested period."""
    # Stat set IDs: "00{year}" = season actuals, "10{year}" = projected season
    # For weekly: "01{week}{year}" pattern or similar
    target_prefix = "00" if week == 0 else "01"

    for stat_set in stat_sets:
        stat_id = stat_set.get("id", "")
        source = stat_set.get("statSourceId", -1)
        split = stat_set.get("statSplitTypeId", -1)

        # We want actual stats (sourceId=0), not projections (sourceId=1)
        if source == 0:
            if week == 0 and split == 0:  # Full season actuals
                return stat_set
            elif week > 0 and split == 1:  # Weekly split
                scoring_period = stat_set.get("scoringPeriodId", 0)
                if scoring_period == week:
                    return stat_set

    # Fallback: return first actual stat set if available
    for stat_set in stat_sets:
        if stat_set.get("statSourceId", -1) == 0:
            return stat_set

    return None


def _fetch_ages(players: list[Player]) -> None:
    """Fetch age for each player from ESPN's athlete API."""
    for player in players:
        try:
            url = ATHLETE_URL.format(athlete_id=player.espn_id)
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                athlete = data.get("athlete", data)
                player.age = athlete.get("age")
        except requests.RequestException:
            pass


def _parse_stats(raw_stats: dict) -> PlayerStats:
    """Convert ESPN stat dict (keyed by stat ID) to PlayerStats."""
    stats = PlayerStats()
    for stat_id, value in raw_stats.items():
        field_name = STAT_ID_MAP.get(stat_id)
        if field_name:
            current = getattr(stats, field_name, 0)
            # For 2pt conversions, accumulate rushing + receiving
            if field_name == "two_point_conversions":
                setattr(stats, field_name, int(current + value))
            elif isinstance(getattr(stats, field_name), int):
                setattr(stats, field_name, int(value))
            else:
                setattr(stats, field_name, float(value))
    return stats


# ESPN team ID to abbreviation
_TEAM_ABBREV = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE",
    6: "DAL", 7: "DEN", 8: "DET", 9: "GB", 10: "TEN",
    11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA",
    16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ",
    21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF",
    26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX",
    33: "BAL", 34: "HOU",
}


def _get_team_abbrev(team_id: int) -> str:
    return _TEAM_ABBREV.get(team_id, "FA")


def fetch_players_with_history(year: int = 2025, week: int = 0, limit: int = 100) -> list[Player]:
    """
    Fetch current season players and attach 3-year historical averages.

    Looks at the 3 seasons prior to `year` (e.g., 2022-2024 for year=2025).
    """
    from .scoring import calculate_score

    # Fetch current season
    players = fetch_players(year=year, week=week, limit=limit)

    # Fetch prior 3 seasons (stats only, no age lookups needed)
    prior_years = [year - 1, year - 2, year - 3]
    # espn_id -> list of (season_year, points, games_played)
    history: dict[int, list[tuple[int, float, int]]] = {}

    for prior_year in prior_years:
        try:
            url = BASE_URL.format(year=prior_year)
            params = {"view": "kona_player_info"}
            filters = {
                "players": {
                    "filterSlotIds": {"value": SLOT_IDS},
                    "limit": 300,
                    "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                    "filterStatus": {"value": ["FREEAGENT", "WAIVERS", "ONTEAM"]},
                }
            }
            headers = {"X-Fantasy-Filter": json.dumps(filters)}
            response = requests.get(url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            for entry in data.get("players", []):
                player_data = entry.get("player", {})
                espn_id = player_data.get("id", 0)
                position_id = player_data.get("defaultPositionId")

                if position_id not in POSITION_MAP:
                    continue

                stat_set = _find_stat_set(player_data.get("stats", []), prior_year, 0)
                if stat_set:
                    stats = _parse_stats(stat_set.get("stats", {}))
                    points = calculate_score(stats)
                    gp = stats.games_played
                    if gp > 0:
                        history.setdefault(espn_id, []).append((prior_year, points, gp))
        except requests.RequestException:
            continue

    # Include the current season in the history (unless it's 2026+)
    if year <= 2025:
        for player in players:
            gp = player.stats.games_played
            if gp > 0:
                pts = calculate_score(player.stats)
                history.setdefault(player.espn_id, []).append((year, pts, gp))

    # Attach historical averages to current players
    for player in players:
        seasons = history.get(player.espn_id, [])
        if seasons:
            # Sort by year so most recent is last
            seasons.sort(key=lambda x: x[0])

            player.seasons_played = len(seasons)
            total_points = sum(pts for _, pts, _ in seasons)
            total_games = sum(gp for _, _, gp in seasons)
            total_possible = sum(17 if yr >= 2021 else 16 for yr, _, _ in seasons)
            player.games_played_3yr = total_games
            player.games_missed_3yr = total_possible - total_games
            player.avg_pts_g_3yr = round(total_points / total_games, 1) if total_games > 0 else None
            player.avg_pts_3yr = round(total_points / len(seasons), 1)

            # Recency-weighted Pts/G: most recent season weighted heaviest
            # Weights: most recent=50%, second=30%, third=20%, fourth=10%
            # Normalized so they sum to 1.0
            weight_table = [0.50, 0.30, 0.20, 0.10]
            # Seasons are oldest-first, reverse so most recent gets highest weight
            pts_g_per_season = [(pts / gp) for _, pts, gp in seasons]
            pts_g_per_season.reverse()
            weights = weight_table[:len(pts_g_per_season)]
            weight_sum = sum(weights)
            recency_pts_g = sum(pg * w for pg, w in zip(pts_g_per_season, weights)) / weight_sum

            # Reliability score: recency-weighted Pts/G * availability
            if total_possible > 0:
                availability = total_games / total_possible
                player.reliability_score = round(recency_pts_g * availability, 1)

            # Breakout detection: latest season Pts/G is 40%+ above prior seasons avg
            if len(seasons) >= 2:
                latest_pts_g = seasons[-1][1] / seasons[-1][2]
                prior_pts = sum(pts for _, pts, _ in seasons[:-1])
                prior_gp = sum(gp for _, _, gp in seasons[:-1])
                prior_avg_pts_g = prior_pts / prior_gp if prior_gp > 0 else 0
                if prior_avg_pts_g > 0 and latest_pts_g >= prior_avg_pts_g * 1.4:
                    player.breakout = True

    # Fetch college stats for players with < 2 NFL seasons
    _fetch_college_scores(players)

    return players


COLLEGE_STATS_URL = "https://site.api.espn.com/apis/common/v3/sports/football/college-football/athletes/{athlete_id}/stats"
ESTIMATED_COLLEGE_GAMES = 13  # typical college season


def _fetch_college_scores(players: list[Player]) -> None:
    """Fetch college stats and compute a dominance score for players with < 2 NFL seasons."""
    for player in players:
        if player.seasons_played >= 2:
            continue

        try:
            url = COLLEGE_STATS_URL.format(athlete_id=player.espn_id)
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                continue

            data = response.json()
            categories = {c["name"]: c for c in data.get("categories", [])}

            rushing = categories.get("rushing", {})
            receiving = categories.get("receiving", {})

            # Get final college season stats
            rush_seasons = rushing.get("statistics", [])
            rec_seasons = receiving.get("statistics", [])

            if not rush_seasons and not rec_seasons:
                continue

            # Use the last (most recent) season
            final_rush = _parse_college_season(rush_seasons[-1]["stats"], rushing.get("names", [])) if rush_seasons else {}
            final_rec = _parse_college_season(rec_seasons[-1]["stats"], receiving.get("names", [])) if rec_seasons else {}
            final_year = ""
            if rush_seasons:
                final_year = str(rush_seasons[-1].get("season", {}).get("year", ""))
            elif rec_seasons:
                final_year = str(rec_seasons[-1].get("season", {}).get("year", ""))

            # Calculate estimated PPR fantasy points for that college season
            rush_yds = final_rush.get("rushingYards", 0)
            rush_tds = final_rush.get("rushingTouchdowns", 0)
            rec = final_rec.get("receptions", 0)
            rec_yds = final_rec.get("receivingYards", 0)
            rec_tds = final_rec.get("receivingTouchdowns", 0)

            fantasy_pts = (rush_yds * 0.1 + rush_tds * 6 +
                           rec * 1.0 + rec_yds * 0.1 + rec_tds * 6)

            pts_per_game = fantasy_pts / ESTIMATED_COLLEGE_GAMES
            player.college_dom_score = round(pts_per_game, 1)

            # Build summary string
            parts = []
            if rush_yds > 0:
                parts.append(f"{rush_yds}yds/{rush_tds}td rush")
            if rec > 0:
                parts.append(f"{rec}rec/{rec_yds}yds/{rec_tds}td")
            player.college_final_year = f"{final_year}: {', '.join(parts)}"

        except requests.RequestException:
            pass


def _parse_college_season(stats: list[str], names: list[str]) -> dict:
    """Parse a college season stats array into a dict."""
    result = {}
    for name, value in zip(names, stats):
        try:
            result[name] = float(value.replace(",", ""))
        except (ValueError, AttributeError):
            result[name] = 0
    return result
