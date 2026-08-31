"""
Player database that loads up to 20 years of NFL data from nflverse and provides
career search and year-by-year breakdowns.  Results are cached to CSV for fast
subsequent launches.  ESPN endpoints are used on-demand for age and college stats.
"""
import csv
import io
import json
import os
from datetime import date
import requests
from dataclasses import dataclass, field, fields
from .models import PlayerStats
from .scoring import calculate_score

_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(os.path.dirname(_DIR), "data")


def games_in_season(year: int) -> int:
    """Return the number of regular-season games for a given NFL season."""
    return 17 if year >= 2021 else 16
SEASONS_CSV = os.path.join(_DATA_DIR, "seasons.csv")
COLLEGE_CSV = os.path.join(_DATA_DIR, "college.csv")
BIRTHS_CSV = os.path.join(_DATA_DIR, "births.csv")
ROOKIES_CSV = os.path.join(_DATA_DIR, "rookies.csv")
META_FILE = os.path.join(_DATA_DIR, "meta.json")

_CACHE_VERSION = 3  # bump when cache format changes

# nflverse data URLs
NFLVERSE_URL = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats_{year}.csv"
NFLVERSE_ROSTER_URL = "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{year}.csv"
NFLVERSE_POSITIONS = {"QB", "RB", "WR", "TE"}

# Age decline thresholds by position — age at which penalty starts
_AGE_THRESHOLD = {"QB": 32, "WR": 29, "RB": 27, "TE": 29}
_AGE_PENALTY_RATE = 0.03  # 3% per year beyond threshold


def _draft_round(pick: int) -> int:
    """Convert overall draft pick number to round."""
    if pick <= 32: return 1
    if pick <= 64: return 2
    if pick <= 100: return 3
    if pick <= 135: return 4
    if pick <= 176: return 5
    if pick <= 220: return 6
    return 7


def _draft_tier(pick: int) -> int:
    """Convert overall draft pick to tier for projection scaling."""
    if pick <= 10: return 0   # top-10
    if pick <= 32: return 1   # rest of round 1
    if pick <= 64: return 2   # round 2
    return 3                  # round 3+

# nflverse column name → PlayerStats field name
_NFLVERSE_STAT_MAP = {
    "passing_yards": "passing_yards",
    "passing_tds": "passing_tds",
    "interceptions": "interceptions",
    "attempts": "passing_attempts",
    "completions": "passing_completions",
    "rushing_yards": "rushing_yards",
    "rushing_tds": "rushing_tds",
    "carries": "rushing_attempts",
    "receptions": "receptions",
    "receiving_yards": "receiving_yards",
    "receiving_tds": "receiving_tds",
    "targets": "targets",
}
_NFLVERSE_FUMBLE_COLS = ["rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost"]
_NFLVERSE_2PT_COLS = ["passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions"]

# ESPN endpoints (fallback for missing nflverse years + on-demand lookups)
ESPN_BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}/segments/0/leaguedefaults/3"
ESPN_ATHLETE_URL = "https://site.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{athlete_id}"
ESPN_SEARCH_URL = "https://site.web.api.espn.com/apis/common/v3/search"
ESPN_COLLEGE_URL = "https://site.api.espn.com/apis/common/v3/sports/football/college-football/athletes/{athlete_id}/stats"
ESPN_POSITION_MAP = {1: "QB", 2: "RB", 3: "WR", 4: "TE"}
ESPN_SLOT_IDS = [0, 2, 4, 6]
ESTIMATED_COLLEGE_GAMES = 13

# PlayerStats field names for CSV columns
_STAT_FIELDS = [f.name for f in fields(PlayerStats)]


def _safe_float(val) -> float:
    """Convert a CSV value to float, handling empty/NA values."""
    if not val or val in ("NA", "None", "nan", ""):
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _parse_college_season(stats: list[str], names: list[str]) -> dict:
    """Parse a college season stats array into a dict."""
    result = {}
    for name, value in zip(names, stats):
        try:
            result[name] = float(value.replace(",", ""))
        except (ValueError, AttributeError):
            result[name] = 0
    return result


@dataclass
class SeasonRecord:
    year: int
    team: str
    position: str
    stats: PlayerStats
    fantasy_points: float = 0.0
    pts_per_game: float = 0.0


@dataclass
class RookieProjection:
    """Projected rookie stats based on college production and draft capital."""
    player_id: str
    name: str
    position: str
    team: str
    espn_id: int | None = None
    draft_number: int | None = None
    draft_round: int = 0
    college_dom_score: float | None = None
    projected_pts_g: float | None = None
    scale_factor: float = 0.0
    college_final_year: str = ""
    comp_name: str = ""  # historical comparable player


@dataclass
class PlayerRecord:
    """Full career record for a player."""
    player_id: str  # nflverse GSIS ID (e.g. "00-0033873")
    name: str
    position: str
    current_team: str
    espn_id: int | None = None  # for ESPN lookups (college)
    birth_date: date | None = None  # from nflverse rosters
    draft_number: int | None = None
    rookie_year: int | None = None
    seasons: list[SeasonRecord] = field(default_factory=list)
    # College stats (raw + computed)
    college_games: int = 0
    college_pass_yds: float = 0.0
    college_pass_tds: float = 0.0
    college_ints: float = 0.0
    college_rush_yds: float = 0.0
    college_rush_tds: float = 0.0
    college_rec: float = 0.0
    college_rec_yds: float = 0.0
    college_rec_tds: float = 0.0
    college_dom_score: float | None = None
    college_final_year: str = ""
    _college_attempted: bool = False  # True if we already tried fetching from ESPN
    top_offense: bool = False  # True if current team was top-10 offense last season AND player was on that team
    _top_offenses_ref: dict | None = None  # Reference to PlayerDatabase.top_offenses

    def compute_college_score(self):
        """Calculate college_dom_score from raw college stats."""
        games = self.college_games if self.college_games > 0 else ESTIMATED_COLLEGE_GAMES
        fantasy_pts = (self.college_pass_yds * 0.04 + self.college_pass_tds * 4 + self.college_ints * -2 +
                       self.college_rush_yds * 0.1 + self.college_rush_tds * 6 +
                       self.college_rec * 1.0 + self.college_rec_yds * 0.1 + self.college_rec_tds * 6)
        if fantasy_pts > 0:
            self.college_dom_score = round(fantasy_pts / games, 1)

    @property
    def age(self) -> int | None:
        if self.birth_date is None:
            return None
        today = date.today()
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )

    @property
    def total_games(self) -> int:
        return sum(s.stats.games_played for s in self.seasons)

    @property
    def total_games_missed(self) -> int:
        total_possible = sum(games_in_season(s.year) for s in self.seasons)
        return total_possible - self.total_games

    @property
    def career_pts_g(self) -> float | None:
        tg = self.total_games
        if tg == 0:
            return None
        return round(sum(s.fantasy_points for s in self.seasons) / tg, 1)

    @property
    def career_total_pts(self) -> float:
        return round(sum(s.fantasy_points for s in self.seasons), 1)

    def is_top_offense_for_year(self, year: int) -> bool:
        """Check if this player was on a top-10 offense for a given season.

        Requires: team was top-10 the previous year (year-1),
        AND the player was on that same team in year-1.
        """
        if not self._top_offenses_ref:
            return self.top_offense  # fallback to static flag
        prev_year = year - 1
        top_teams = self._top_offenses_ref.get(prev_year, set())
        # Find the player's team for this year
        season = next((s for s in self.seasons if s.year == year), None)
        if not season or season.team not in top_teams:
            return False
        # Was the player on this same team the previous year?
        prev_season = next((s for s in self.seasons if s.year == prev_year), None)
        return prev_season is not None and prev_season.team == season.team

    @property
    def raw_reliability_score(self) -> float | None:
        """Recency-weighted Pts/G × availability (no age penalty), with top-offense boost."""
        return self.raw_reliability_score_for_year(None)

    def raw_reliability_score_for_year(self, year: int | None = None) -> float | None:
        """Recency-weighted Pts/G × availability, with optional year-aware top-offense boost."""
        if not self.seasons:
            return None
        weight_table = [0.50, 0.30, 0.20, 0.10, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05]
        sorted_seasons = sorted(self.seasons, key=lambda s: s.year, reverse=True)
        pts_g_list = [s.pts_per_game for s in sorted_seasons if s.stats.games_played > 0]
        if not pts_g_list:
            return None
        weights = weight_table[:len(pts_g_list)]
        w_sum = sum(weights)
        recency_pts_g = sum(pg * w for pg, w in zip(pts_g_list, weights)) / w_sum
        total_possible = sum(games_in_season(s.year) for s in self.seasons)
        availability = self.total_games / total_possible if total_possible > 0 else 0
        score = recency_pts_g * availability
        if year is not None:
            if self.is_top_offense_for_year(year):
                score *= _OFFENSE_BOOST
        elif self.top_offense:
            score *= _OFFENSE_BOOST
        return round(score, 1)

    @property
    def season_reliability_score(self) -> float | None:
        """Most recent season: Pts/G × season availability (no age penalty)."""
        if not self.seasons:
            return None
        latest = max(self.seasons, key=lambda s: s.year)
        if latest.stats.games_played == 0:
            return None
        pts_g = latest.pts_per_game
        possible = games_in_season(latest.year)
        availability = latest.stats.games_played / possible if possible > 0 else 0
        return round(pts_g * availability, 1)

    @property
    def reliability_score(self) -> float | None:
        """Recency-weighted Pts/G × availability × age penalty."""
        return self.reliability_score_for_year(None)

    def reliability_score_for_year(self, year: int | None = None) -> float | None:
        """Recency-weighted Pts/G × availability × age penalty, year-aware."""
        raw = self.raw_reliability_score_for_year(year)
        if raw is None:
            return None
        age_factor = 1.0
        player_age = self.age
        if player_age is not None:
            threshold = _AGE_THRESHOLD.get(self.position, 29)
            years_over = max(0, player_age - threshold)
            age_factor = max(0.0, 1.0 - years_over * _AGE_PENALTY_RATE)
        return round(raw * age_factor, 1)

    @property
    def breakout(self) -> bool:
        """Latest season Pts/G is 40%+ above the previous season's Pts/G."""
        playable = sorted(
            [s for s in self.seasons if s.stats.games_played > 0],
            key=lambda s: s.year,
        )
        if len(playable) < 2:
            return False
        latest = playable[-1]
        previous = playable[-2]
        return previous.pts_per_game > 0 and latest.pts_per_game >= previous.pts_per_game * 1.4


_OFFENSE_BOOST = 1.05  # 5% boost for players on top-10 offenses


class PlayerDatabase:
    """Loads and indexes all players across multiple seasons."""

    def __init__(self):
        self.players: dict[str, PlayerRecord] = {}  # player_id -> PlayerRecord
        self.rookie_projections: list[RookieProjection] = []
        self.top_offenses: dict[int, set[str]] = {}  # year -> set of top-10 team abbrevs
        self.loaded = False
        self._on_progress = None
        self._on_complete = None

    def set_callbacks(self, on_progress=None, on_complete=None):
        self._on_progress = on_progress
        self._on_complete = on_complete

    def load(self, end_year: int = 2025, num_years: int = 27):
        """Load player data — from CSV cache if available, otherwise from nflverse."""
        start_year = end_year - num_years + 1
        years = list(range(start_year, end_year + 1))

        # Check cache version — clear stale caches
        meta = self._load_meta()
        if meta.get("version") != _CACHE_VERSION:
            for f in (SEASONS_CSV, COLLEGE_CSV, META_FILE):
                if os.path.exists(f):
                    os.remove(f)
            meta = {}

        attempted_years = set(meta.get("attempted_years", []))

        # Try loading from cache first
        cached_years = self._load_from_csv()
        if cached_years:
            missing_years = [y for y in years
                             if y not in cached_years and y not in attempted_years]
            if not missing_years:
                if self._on_progress:
                    self._on_progress("Loaded from cache.")
                self._score_all()
                self._compute_top_offenses()
                self._load_college_from_csv()
                self._load_births_from_csv()
                if not any(r.birth_date for r in self.players.values()):
                    self._fetch_and_cache_births()
                self._fetch_all_college_scores()
                if not self._load_rookies_from_csv():
                    self._build_rookie_scale_factors()
                    self._load_2026_rookies()
                self.loaded = True
                if self._on_complete:
                    year_range = f"{min(cached_years)}-{max(cached_years)}"
                    self._on_complete(f"Loaded {len(self.players)} players, {len(cached_years)} seasons ({year_range}) from cache.")
                return
            years = missing_years

        for i, year in enumerate(years):
            if self._on_progress:
                self._on_progress(f"Fetching {year} season... ({i + 1}/{len(years)})")
            attempted_years.add(year)
            try:
                self._load_year_nflverse(year)
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    # nflverse doesn't have this year — try ESPN as fallback
                    if self._on_progress:
                        self._on_progress(f"Fetching {year} season from ESPN (fallback)... ({i + 1}/{len(years)})")
                    try:
                        self._load_year_espn(year)
                    except Exception:
                        continue
                else:
                    continue
            except Exception:
                continue

        # Merge any ESPN-fallback players into nflverse records by name
        self._merge_espn_players()

        self._score_all()
        self._compute_top_offenses()

        # Fetch birth dates from nflverse rosters
        self._fetch_and_cache_births()

        # Batch-fetch college scores for young players
        self._fetch_all_college_scores()

        # Build rookie projections
        self._build_rookie_scale_factors()
        self._load_2026_rookies()

        # Save everything to CSV for next time
        if self._on_progress:
            self._on_progress("Saving to cache...")
        self._save_to_csv()
        self._save_meta(attempted_years)

        self.loaded = True
        all_years = set()
        for r in self.players.values():
            for s in r.seasons:
                all_years.add(s.year)
        if self._on_complete:
            if all_years:
                year_range = f"{min(all_years)}-{max(all_years)}"
                self._on_complete(f"Loaded {len(self.players)} players, {len(all_years)} seasons ({year_range}).")
            else:
                self._on_complete("No player data found.")

    def _score_all(self):
        """Score all seasons and update current team to most recent."""
        for record in self.players.values():
            for season in record.seasons:
                season.fantasy_points = calculate_score(season.stats)
                gp = season.stats.games_played
                season.pts_per_game = round(season.fantasy_points / gp, 1) if gp > 0 else 0.0
            # Set current_team from most recent season
            if record.seasons:
                latest = max(record.seasons, key=lambda s: s.year)
                record.current_team = latest.team

    def _compute_top_offenses(self):
        """Rank teams by total fantasy points per season, store top 10 per year."""
        # team -> year -> total fantasy points
        team_pts: dict[str, dict[int, float]] = {}
        for record in self.players.values():
            for season in record.seasons:
                if season.stats.games_played == 0:
                    continue
                team_pts.setdefault(season.team, {})
                team_pts[season.team][season.year] = (
                    team_pts[season.team].get(season.year, 0) + season.fantasy_points
                )

        # For each year, find top 10 teams
        all_years = set()
        for team_years in team_pts.values():
            all_years.update(team_years.keys())

        for year in all_years:
            year_totals = []
            for team, years in team_pts.items():
                if year in years:
                    year_totals.append((team, years[year]))
            year_totals.sort(key=lambda x: x[1], reverse=True)
            self.top_offenses[year] = {team for team, _ in year_totals[:10]}

        # Tag players with top_offenses reference and set default top_offense flag
        for record in self.players.values():
            record._top_offenses_ref = self.top_offenses
            record.top_offense = False
            if not record.seasons:
                continue
            latest = max(record.seasons, key=lambda s: s.year)
            prev_year = latest.year - 1
            top_teams = self.top_offenses.get(prev_year, set())
            if record.current_team not in top_teams:
                continue
            prev_season = next((s for s in record.seasons if s.year == prev_year), None)
            if prev_season and prev_season.team == record.current_team:
                record.top_offense = True

    # ── nflverse data loading ─────────────────────────────────

    def _load_year_nflverse(self, year: int):
        """Download one season from nflverse and aggregate weekly stats into season totals."""
        url = NFLVERSE_URL.format(year=year)
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        reader = csv.DictReader(io.StringIO(response.text))

        # Accumulate weekly stats per player: player_id -> {name, pos, team, accum dict}
        accumulators: dict[str, dict] = {}

        for row in reader:
            if row.get("season_type") != "REG":
                continue
            pos = row.get("position", "")
            if pos not in NFLVERSE_POSITIONS:
                continue

            pid = row.get("player_id", "")
            if not pid:
                continue

            if pid not in accumulators:
                accumulators[pid] = {
                    "name": row.get("player_display_name", "Unknown"),
                    "position": pos,
                    "team": row.get("recent_team", "FA"),
                    "games": 0,
                    "stats": {f: 0.0 for f in _STAT_FIELDS},
                }

            acc = accumulators[pid]
            acc["games"] += 1
            acc["team"] = row.get("recent_team", acc["team"])

            # Accumulate mapped stat columns
            for nfl_col, our_field in _NFLVERSE_STAT_MAP.items():
                acc["stats"][our_field] += _safe_float(row.get(nfl_col, "0"))

            # Fumbles lost (sum of rushing + receiving + sack)
            for col in _NFLVERSE_FUMBLE_COLS:
                acc["stats"]["fumbles_lost"] += _safe_float(row.get(col, "0"))

            # 2-point conversions (sum of passing + rushing + receiving)
            for col in _NFLVERSE_2PT_COLS:
                acc["stats"]["two_point_conversions"] += _safe_float(row.get(col, "0"))

        # Convert accumulators into PlayerRecords
        for pid, acc in accumulators.items():
            if acc["games"] == 0:
                continue

            # Build PlayerStats with correct types
            stats = PlayerStats()
            for field_name in _STAT_FIELDS:
                val = acc["stats"][field_name]
                attr_type = type(getattr(PlayerStats(), field_name))
                if attr_type == int:
                    setattr(stats, field_name, int(round(val)))
                else:
                    setattr(stats, field_name, val)
            stats.games_played = acc["games"]

            if pid not in self.players:
                self.players[pid] = PlayerRecord(
                    player_id=pid,
                    name=acc["name"],
                    position=acc["position"],
                    current_team=acc["team"],
                )

            record = self.players[pid]
            record.current_team = acc["team"]
            record.name = acc["name"]

            existing_years = {s.year for s in record.seasons}
            if year not in existing_years:
                record.seasons.append(SeasonRecord(
                    year=year,
                    team=acc["team"],
                    position=acc["position"],
                    stats=stats,
                ))

    # ── Merging ESPN fallback players into nflverse records ─────

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a player name for matching: lowercase, strip punctuation and suffixes."""
        import re
        name = re.sub(r"[^a-z\s]", "", name.lower()).strip()
        # Strip common suffixes (jr, sr, ii, iii, iv, v)
        name = re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", name)
        return name

    def _merge_espn_players(self):
        """Merge ESPN-sourced players into nflverse records by matching name + position."""
        espn_pids = [pid for pid in self.players if pid.startswith("espn-")]
        if not espn_pids:
            return

        # Build normalized name+position -> nflverse player_id lookup
        nflverse_by_name: dict[str, str] = {}
        for pid, record in self.players.items():
            if not pid.startswith("espn-"):
                key = f"{self._normalize_name(record.name)}|{record.position}"
                nflverse_by_name[key] = pid

        to_delete = []
        for espn_pid in espn_pids:
            espn_record = self.players[espn_pid]
            key = f"{self._normalize_name(espn_record.name)}|{espn_record.position}"
            nfl_pid = nflverse_by_name.get(key)

            if nfl_pid:
                # Merge seasons into existing nflverse record
                nfl_record = self.players[nfl_pid]
                existing_years = {s.year for s in nfl_record.seasons}
                for season in espn_record.seasons:
                    if season.year not in existing_years:
                        nfl_record.seasons.append(season)
                # Carry over ESPN ID
                if espn_record.espn_id:
                    nfl_record.espn_id = espn_record.espn_id
                # Update team to latest
                nfl_record.current_team = espn_record.current_team
                to_delete.append(espn_pid)
            # else: no nflverse match, keep the ESPN record as-is

        for pid in to_delete:
            del self.players[pid]

    # ── ESPN fallback for missing nflverse years ───────────────

    def _load_year_espn(self, year: int):
        """Fallback: load a season from ESPN's fantasy API."""
        from .espn_client import _find_stat_set, _parse_stats, _get_team_abbrev

        url = ESPN_BASE_URL.format(year=year)
        params = {"view": "kona_player_info"}
        filters = {
            "players": {
                "filterSlotIds": {"value": ESPN_SLOT_IDS},
                "limit": 1000,
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

            if position_id not in ESPN_POSITION_MAP:
                continue

            position = ESPN_POSITION_MAP[position_id]
            name = player_data.get("fullName", "Unknown")
            team = _get_team_abbrev(player_data.get("proTeamId", 0))

            stat_set = _find_stat_set(player_data.get("stats", []), year, 0)
            if not stat_set:
                continue

            stats = _parse_stats(stat_set.get("stats", {}))
            if stats.games_played == 0:
                continue

            # Use ESPN ID as player_id (as string) for ESPN-sourced players
            pid = f"espn-{espn_id}"

            if pid not in self.players:
                self.players[pid] = PlayerRecord(
                    player_id=pid,
                    name=name,
                    position=position,
                    current_team=team,
                    espn_id=espn_id,
                )

            record = self.players[pid]
            record.current_team = team
            record.name = name

            existing_years = {s.year for s in record.seasons}
            if year not in existing_years:
                record.seasons.append(SeasonRecord(
                    year=year,
                    team=team,
                    position=position,
                    stats=stats,
                ))

    # ── On-demand ESPN lookups (age, college) ─────────────────

    def fetch_player_details(self, player_id: str):
        """On-demand: look up ESPN ID, then fetch college stats."""
        record = self.players.get(player_id)
        if not record:
            return

        # Fetch college stats for young players
        if record.college_dom_score is None and len(record.seasons) < 3:
            # Find ESPN ID if we don't have one yet
            if record.espn_id is None:
                record.espn_id = self._find_espn_id(record.name)
            if record.espn_id is not None:
                self._fetch_college_for_player(record)
                if record.college_dom_score is not None:
                    self._save_college_csv()

    def _find_espn_id(self, name: str) -> int | None:
        """Search ESPN for a player by name to find their athlete ID."""
        try:
            params = {
                "query": name,
                "limit": 5,
                "type": "player",
                "sport": "football",
                "league": "nfl",
            }
            resp = requests.get(ESPN_SEARCH_URL, params=params, timeout=10)
            if resp.status_code != 200:
                return None
            data = resp.json()

            # Response may have items at top level or nested under results
            items = data.get("items", [])
            if not items:
                for section in data.get("results", []):
                    items.extend(section.get("items", []))

            # Look for exact name match first
            for item in items:
                if item.get("displayName", "").lower() == name.lower():
                    return int(item["id"])

            # Fallback: first result
            if items:
                return int(items[0]["id"])
        except Exception:
            pass
        return None

    def _fetch_college_for_player(self, record: PlayerRecord):
        """Fetch college stats for a single player using their ESPN ID."""
        if record.espn_id is None:
            return
        try:
            url = ESPN_COLLEGE_URL.format(athlete_id=record.espn_id)
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return

            data = response.json()
            categories = {c["name"]: c for c in data.get("categories", [])}

            rushing = categories.get("rushing", {})
            receiving = categories.get("receiving", {})
            passing = categories.get("passing", {})

            rush_seasons = rushing.get("statistics", [])
            rec_seasons = receiving.get("statistics", [])
            pass_seasons = passing.get("statistics", [])

            if not rush_seasons and not rec_seasons and not pass_seasons:
                return

            final_rush = _parse_college_season(rush_seasons[-1]["stats"], rushing.get("names", [])) if rush_seasons else {}
            final_rec = _parse_college_season(rec_seasons[-1]["stats"], receiving.get("names", [])) if rec_seasons else {}
            final_pass = _parse_college_season(pass_seasons[-1]["stats"], passing.get("names", [])) if pass_seasons else {}

            final_year = ""
            for seasons_list in [pass_seasons, rush_seasons, rec_seasons]:
                if seasons_list:
                    final_year = str(seasons_list[-1].get("season", {}).get("year", ""))
                    break

            # Get actual games played from whichever category has it
            games = 0
            for stats_dict in [final_pass, final_rush, final_rec]:
                gp = stats_dict.get("gamesPlayed", stats_dict.get("games", 0))
                if gp > 0:
                    games = max(games, int(gp))

            # Store raw stats on the record
            record.college_games = games
            record.college_pass_yds = final_pass.get("passingYards", final_pass.get("netPassingYards", 0))
            record.college_pass_tds = final_pass.get("passingTouchdowns", 0)
            record.college_ints = final_pass.get("interceptions", 0)
            record.college_rush_yds = final_rush.get("rushingYards", 0)
            record.college_rush_tds = final_rush.get("rushingTouchdowns", 0)
            record.college_rec = final_rec.get("receptions", 0)
            record.college_rec_yds = final_rec.get("receivingYards", 0)
            record.college_rec_tds = final_rec.get("receivingTouchdowns", 0)

            # Compute score from raw stats
            record.compute_college_score()

            # Build summary string
            parts = []
            if record.college_pass_yds > 0:
                parts.append(f"{record.college_pass_yds:.0f}yds/{record.college_pass_tds:.0f}td/{record.college_ints:.0f}int pass")
            if record.college_rush_yds > 0:
                parts.append(f"{record.college_rush_yds:.0f}yds/{record.college_rush_tds:.0f}td rush")
            if record.college_rec > 0:
                parts.append(f"{record.college_rec:.0f}rec/{record.college_rec_yds:.0f}yds/{record.college_rec_tds:.0f}td")
            record.college_final_year = f"{final_year}: {', '.join(parts)}"

        except requests.RequestException:
            pass

    def _fetch_all_college_scores(self):
        """Batch-fetch college scores for all players with < 3 NFL seasons."""
        young = [r for r in self.players.values()
                 if len(r.seasons) < 3 and r.college_dom_score is None
                 and r.espn_id is not None and not r._college_attempted]
        if not young:
            return
        for i, record in enumerate(young, 1):
            if self._on_progress:
                self._on_progress(f"Fetching college stats... ({i}/{len(young)})")
            self._fetch_college_for_player(record)
            record._college_attempted = True
        self._save_college_csv()

    # ── Rookie projections ─────────────────────────────────────

    def _build_rookie_scale_factors(self) -> dict[tuple[str, int], float]:
        """Build historical college-to-NFL scaling factors by position and draft tier."""
        from statistics import median

        # Collect ratios: (position, draft_tier) -> list of (nfl_pts_g / college_dom_score, player_name)
        ratios: dict[tuple[str, int], list[tuple[float, str]]] = {}
        pos_ratios: dict[str, list[float]] = {}

        for record in self.players.values():
            if record.college_dom_score is None or record.college_dom_score <= 0:
                continue
            if record.rookie_year is None or record.draft_number is None:
                continue

            # Find the rookie season
            rookie_season = next((s for s in record.seasons if s.year == record.rookie_year), None)
            if not rookie_season or rookie_season.stats.games_played < 4:
                continue

            ratio = rookie_season.pts_per_game / record.college_dom_score
            tier = _draft_tier(record.draft_number)
            key = (record.position, tier)
            ratios.setdefault(key, []).append((ratio, record.name))
            pos_ratios.setdefault(record.position, []).append(ratio)

        # Compute median for each bucket, fallback to position median
        scale_factors: dict[tuple[str, int], float] = {}
        for pos in NFLVERSE_POSITIONS:
            pos_median = median(pos_ratios[pos]) if pos in pos_ratios and len(pos_ratios[pos]) >= 3 else 0.5
            for tier in range(4):
                key = (pos, tier)
                bucket = ratios.get(key, [])
                if len(bucket) >= 5:
                    scale_factors[key] = median([r for r, _ in bucket])
                else:
                    scale_factors[key] = pos_median

        self._scale_factors = scale_factors
        self._rookie_comp_data = ratios  # keep for finding comps
        return scale_factors

    def _load_2026_rookies(self):
        """Load 2026 rookies from roster data and project their fantasy output."""
        self.rookie_projections: list[RookieProjection] = []

        # _roster_2026 is populated during _fetch_and_cache_births
        roster_data = getattr(self, '_roster_2026', None)
        if not roster_data:
            return

        # Filter to skill positions
        rookies_raw = []
        for info in roster_data:
            # Need to get position from the roster row - re-download 2026 roster
            pass

        # Re-download 2026 roster to get full info including position
        if self._on_progress:
            self._on_progress("Loading 2026 rookies...")
        try:
            url = NFLVERSE_ROSTER_URL.format(year=2026)
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                rookie_yr = row.get("rookie_year", "")
                if rookie_yr != "2026":
                    continue
                pos = row.get("position", "")
                if pos not in NFLVERSE_POSITIONS:
                    continue
                gsis_id = row.get("gsis_id", "")
                espn_id_str = row.get("espn_id", "")
                draft_num_str = row.get("draft_number", "")
                espn_id = int(espn_id_str) if espn_id_str else None
                draft_num = int(draft_num_str) if draft_num_str else None

                rookies_raw.append({
                    "gsis_id": gsis_id,
                    "name": row.get("full_name", "Unknown"),
                    "position": pos,
                    "team": row.get("team", "FA"),
                    "espn_id": espn_id,
                    "draft_number": draft_num,
                })
        except Exception:
            return

        if not rookies_raw:
            return

        # Fetch college stats for each rookie
        for i, rk in enumerate(rookies_raw, 1):
            if self._on_progress:
                self._on_progress(f"Fetching rookie college stats... ({i}/{len(rookies_raw)})")

            proj = RookieProjection(
                player_id=rk["gsis_id"],
                name=rk["name"],
                position=rk["position"],
                team=rk["team"],
                espn_id=rk["espn_id"],
                draft_number=rk["draft_number"],
                draft_round=_draft_round(rk["draft_number"]) if rk["draft_number"] else 0,
            )

            # Fetch college stats using a temporary PlayerRecord
            if rk["espn_id"]:
                temp = PlayerRecord(
                    player_id=rk["gsis_id"], name=rk["name"],
                    position=rk["position"], current_team=rk["team"],
                    espn_id=rk["espn_id"],
                )
                self._fetch_college_for_player(temp)
                proj.college_dom_score = temp.college_dom_score
                proj.college_final_year = temp.college_final_year

            # Project using scale factor
            if proj.college_dom_score and proj.draft_number:
                tier = _draft_tier(proj.draft_number)
                key = (proj.position, tier)
                scale = self._scale_factors.get(key, 0.5)
                proj.scale_factor = round(scale, 2)
                proj.projected_pts_g = round(proj.college_dom_score * scale, 1)

                # Find best historical comp
                comp_data = self._rookie_comp_data.get(key, [])
                if comp_data:
                    target_ratio = proj.scale_factor
                    best_comp = min(comp_data, key=lambda x: abs(x[0] - target_ratio))
                    proj.comp_name = best_comp[1]

            self.rookie_projections.append(proj)

        # Sort by projected pts/g
        self.rookie_projections.sort(
            key=lambda r: r.projected_pts_g if r.projected_pts_g else 0, reverse=True
        )

        self._save_rookies_csv()

    def _save_rookies_csv(self):
        """Save rookie projections to CSV cache."""
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(ROOKIES_CSV, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["player_id", "name", "position", "team", "espn_id",
                             "draft_number", "draft_round", "college_dom_score",
                             "projected_pts_g", "scale_factor", "college_final_year", "comp_name"])
            for r in self.rookie_projections:
                writer.writerow([
                    r.player_id, r.name, r.position, r.team,
                    r.espn_id or "", r.draft_number or "", r.draft_round,
                    r.college_dom_score or "", r.projected_pts_g or "",
                    r.scale_factor, r.college_final_year, r.comp_name,
                ])

    def _load_rookies_from_csv(self) -> bool:
        """Load rookie projections from CSV cache. Returns True if loaded."""
        if not os.path.exists(ROOKIES_CSV):
            return False
        try:
            self.rookie_projections = []
            with open(ROOKIES_CSV, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    proj = RookieProjection(
                        player_id=row["player_id"],
                        name=row["name"],
                        position=row["position"],
                        team=row["team"],
                        espn_id=int(row["espn_id"]) if row.get("espn_id") else None,
                        draft_number=int(row["draft_number"]) if row.get("draft_number") else None,
                        draft_round=int(row.get("draft_round", 0)),
                        college_dom_score=float(row["college_dom_score"]) if row.get("college_dom_score") else None,
                        projected_pts_g=float(row["projected_pts_g"]) if row.get("projected_pts_g") else None,
                        scale_factor=float(row.get("scale_factor", 0)),
                        college_final_year=row.get("college_final_year", ""),
                        comp_name=row.get("comp_name", ""),
                    )
                    self.rookie_projections.append(proj)
            return len(self.rookie_projections) > 0
        except Exception:
            self.rookie_projections = []
            return False

    # ── CSV persistence ────────────────────────────────────────

    def _load_meta(self) -> dict:
        """Load metadata (cache version, attempted years)."""
        if not os.path.exists(META_FILE):
            return {}
        try:
            with open(META_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_meta(self, attempted_years: set[int]):
        """Save metadata."""
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(META_FILE, "w") as f:
            json.dump({
                "version": _CACHE_VERSION,
                "attempted_years": sorted(attempted_years),
            }, f)

    def _save_to_csv(self):
        """Save all season data to CSV."""
        os.makedirs(_DATA_DIR, exist_ok=True)

        header = ["player_id", "name", "position", "team", "year"] + _STAT_FIELDS
        with open(SEASONS_CSV, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for record in self.players.values():
                for s in record.seasons:
                    row = [record.player_id, record.name, s.position, s.team, s.year]
                    row += [getattr(s.stats, field) for field in _STAT_FIELDS]
                    writer.writerow(row)

    def _load_from_csv(self) -> set[int]:
        """Load season data from CSV. Returns set of years loaded, or empty set if no cache."""
        if not os.path.exists(SEASONS_CSV):
            return set()

        if self._on_progress:
            self._on_progress("Loading from cache...")

        years_loaded = set()
        try:
            with open(SEASONS_CSV, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pid = row["player_id"]
                    year = int(row["year"])
                    years_loaded.add(year)

                    name = row["name"]
                    position = row["position"]
                    team = row["team"]

                    stats = PlayerStats()
                    for field_name in _STAT_FIELDS:
                        val = row.get(field_name, "0")
                        attr_type = type(getattr(stats, field_name))
                        if attr_type == float:
                            setattr(stats, field_name, float(val))
                        else:
                            setattr(stats, field_name, int(float(val)))

                    if stats.games_played == 0:
                        continue

                    if pid not in self.players:
                        self.players[pid] = PlayerRecord(
                            player_id=pid,
                            name=name,
                            position=position,
                            current_team=team,
                        )

                    record = self.players[pid]
                    record.current_team = team
                    record.name = name

                    existing_years = {s.year for s in record.seasons}
                    if year not in existing_years:
                        record.seasons.append(SeasonRecord(
                            year=year, team=team, position=position, stats=stats,
                        ))
        except Exception:
            self.players.clear()
            return set()

        return years_loaded

    def _load_college_from_csv(self):
        """Load college data from CSV cache."""
        if not os.path.exists(COLLEGE_CSV):
            return
        try:
            with open(COLLEGE_CSV, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pid = row["player_id"]
                    record = self.players.get(pid)
                    if record:
                        record._college_attempted = True
                        record.college_final_year = row.get("college_final_year", "")
                        # New format with raw stats
                        if "college_games" in row:
                            record.college_games = int(float(row.get("college_games", 0) or 0))
                            record.college_pass_yds = float(row.get("college_pass_yds", 0) or 0)
                            record.college_pass_tds = float(row.get("college_pass_tds", 0) or 0)
                            record.college_ints = float(row.get("college_ints", 0) or 0)
                            record.college_rush_yds = float(row.get("college_rush_yds", 0) or 0)
                            record.college_rush_tds = float(row.get("college_rush_tds", 0) or 0)
                            record.college_rec = float(row.get("college_rec", 0) or 0)
                            record.college_rec_yds = float(row.get("college_rec_yds", 0) or 0)
                            record.college_rec_tds = float(row.get("college_rec_tds", 0) or 0)
                            record.compute_college_score()
                        else:
                            # Old format fallback: just the pre-computed score
                            score = row.get("college_dom_score", "")
                            if score:
                                record.college_dom_score = float(score)
        except Exception:
            pass

    def _fetch_and_cache_births(self):
        """Fetch birth dates from nflverse roster data and cache to CSV."""
        if self._on_progress:
            self._on_progress("Fetching birth dates from nflverse rosters...")

        # gsis_id -> roster info, espn_id -> birth_date (for ESPN-fallback players)
        roster_by_gsis: dict[str, dict] = {}  # gsis_id -> {birth_date, espn_id, draft_number, rookie_year}
        births_by_espn: dict[str, str] = {}   # espn_id -> birth_date

        # Download rosters for every year from 1999-2026 to cover all players
        for year in range(2026, 1998, -1):
            if self._on_progress:
                self._on_progress(f"Fetching roster {year}...")
            try:
                url = NFLVERSE_ROSTER_URL.format(year=year)
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                reader = csv.DictReader(io.StringIO(resp.text))
                for row in reader:
                    gsis_id = row.get("gsis_id", "")
                    espn_id = row.get("espn_id", "")
                    bd = row.get("birth_date", "")
                    draft_num = row.get("draft_number", "")
                    rookie_yr = row.get("rookie_year", "")
                    if gsis_id and gsis_id not in roster_by_gsis and bd:
                        roster_by_gsis[gsis_id] = {
                            "birth_date": bd,
                            "espn_id": espn_id,
                            "draft_number": draft_num,
                            "rookie_year": rookie_yr,
                        }
                    if espn_id and espn_id not in births_by_espn and bd:
                        births_by_espn[espn_id] = bd
            except Exception:
                continue

        # Also store raw roster data for 2026 rookies (needed for projections)
        self._roster_2026 = [
            info for gsis_id, info in roster_by_gsis.items()
            if info.get("rookie_year") == "2026"
        ]
        # Attach gsis_id to each entry
        for gsis_id, info in roster_by_gsis.items():
            if info.get("rookie_year") == "2026":
                info["gsis_id"] = gsis_id

        # Apply to our players
        for pid, record in self.players.items():
            roster_info = roster_by_gsis.get(pid)
            if roster_info:
                bd_str = roster_info["birth_date"]
                try:
                    record.birth_date = date.fromisoformat(bd_str)
                except ValueError:
                    pass
                espn_id_str = roster_info["espn_id"]
                if espn_id_str and record.espn_id is None:
                    try:
                        record.espn_id = int(espn_id_str)
                    except ValueError:
                        pass
                dn = roster_info["draft_number"]
                if dn and record.draft_number is None:
                    try:
                        record.draft_number = int(dn)
                    except ValueError:
                        pass
                ry = roster_info["rookie_year"]
                if ry and record.rookie_year is None:
                    try:
                        record.rookie_year = int(ry)
                    except ValueError:
                        pass
            elif pid.startswith("espn-"):
                espn_num = pid.removeprefix("espn-")
                bd_str = births_by_espn.get(espn_num)
                if bd_str:
                    try:
                        record.birth_date = date.fromisoformat(bd_str)
                    except ValueError:
                        pass

        # Cache to CSV
        self._save_births_csv()

    def _save_births_csv(self):
        """Save birth dates, ESPN IDs, draft info to CSV cache."""
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(BIRTHS_CSV, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["player_id", "birth_date", "espn_id", "draft_number", "rookie_year"])
            for record in self.players.values():
                if record.birth_date or record.espn_id:
                    bd = record.birth_date.isoformat() if record.birth_date else ""
                    espn = record.espn_id if record.espn_id else ""
                    dn = record.draft_number if record.draft_number else ""
                    ry = record.rookie_year if record.rookie_year else ""
                    writer.writerow([record.player_id, bd, espn, dn, ry])

    def _load_births_from_csv(self):
        """Load birth dates, ESPN IDs, draft info from CSV cache."""
        if not os.path.exists(BIRTHS_CSV):
            return
        try:
            with open(BIRTHS_CSV, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pid = row["player_id"]
                    record = self.players.get(pid)
                    if not record:
                        continue
                    bd = row.get("birth_date", "")
                    if bd:
                        try:
                            record.birth_date = date.fromisoformat(bd)
                        except ValueError:
                            pass
                    espn = row.get("espn_id", "")
                    if espn and record.espn_id is None:
                        try:
                            record.espn_id = int(espn)
                        except ValueError:
                            pass
                    dn = row.get("draft_number", "")
                    if dn and record.draft_number is None:
                        try:
                            record.draft_number = int(dn)
                        except ValueError:
                            pass
                    ry = row.get("rookie_year", "")
                    if ry and record.rookie_year is None:
                        try:
                            record.rookie_year = int(ry)
                        except ValueError:
                            pass
        except Exception:
            pass

    def _save_college_csv(self):
        """Save college data (raw stats) for all players who have it or were attempted."""
        os.makedirs(_DATA_DIR, exist_ok=True)
        cols = ["player_id", "name", "college_dom_score", "college_final_year",
                "college_games", "college_pass_yds", "college_pass_tds",
                "college_ints", "college_rush_yds", "college_rush_tds",
                "college_rec", "college_rec_yds", "college_rec_tds"]
        with open(COLLEGE_CSV, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(cols)
            for record in self.players.values():
                if record.college_dom_score is not None or record._college_attempted:
                    writer.writerow([
                        record.player_id, record.name,
                        record.college_dom_score or "",
                        record.college_final_year, record.college_games,
                        record.college_pass_yds, record.college_pass_tds,
                        record.college_ints, record.college_rush_yds,
                        record.college_rush_tds, record.college_rec,
                        record.college_rec_yds, record.college_rec_tds,
                    ])

    # ── Public API ─────────────────────────────────────────────

    def search(self, query: str, limit: int = 20) -> list[PlayerRecord]:
        """Search players by name (case-insensitive partial match)."""
        query = query.strip().lower()
        if not query:
            return []
        results = [p for p in self.players.values() if query in p.name.lower()]
        results.sort(key=lambda p: p.career_total_pts, reverse=True)
        return results[:limit]

    def get_player(self, player_id: str) -> PlayerRecord | None:
        return self.players.get(player_id)
