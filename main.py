import argparse
from fantasy_football.espn_client import fetch_players, fetch_players_with_history
from fantasy_football.scoring import score_players


def main():
    parser = argparse.ArgumentParser(description="Fantasy Football PPR Scoring Engine")
    parser.add_argument("--year", type=int, default=2024, help="NFL season year (default: 2024)")
    parser.add_argument("--week", type=int, default=0, help="Week number (0 = full season, default: 0)")
    parser.add_argument("--limit", type=int, default=50, help="Number of players to fetch (default: 50)")
    parser.add_argument("--position", choices=["QB", "RB", "WR", "TE", "ALL"], default="ALL",
                        help="Filter by position (default: ALL)")
    parser.add_argument("--history", action="store_true",
                        help="Include 3-year historical averages")
    args = parser.parse_args()

    period = f"Week {args.week}" if args.week > 0 else "Full Season"
    print(f"\nFetching {args.year} {period} stats from ESPN...\n")

    if args.history:
        print("Also fetching 3 prior seasons for historical averages...\n")
        players = fetch_players_with_history(year=args.year, week=args.week, limit=args.limit)
    else:
        players = fetch_players(year=args.year, week=args.week, limit=args.limit)

    if args.position != "ALL":
        players = [p for p in players if p.position == args.position]

    scored = score_players(players)

    total_games = 1 if args.week > 0 else (17 if args.year >= 2021 else 16)

    hist_header = ""
    if args.history:
        hist_header = (f"{'3yr Pts/G':<10} {'3yr Avg':<8} {'Szns':<5} {'3yr GM':<6} "
                       f"{'RelScr':<7} {'BRK':<4} {'ColScr':<7}")

    print(f"{'Rank':<5} {'Player':<25} {'Age':<5} {'Pos':<5} {'Team':<5} {'GP':<4} {'GM':<4} "
          f"{'PaYds':<7} {'PaTD':<5} {'INT':<4} "
          f"{'Rec':<5} {'RecYds':<8} {'RecTD':<6} {'Rush':<6} {'RushYds':<8} {'RushTD':<7} {'Fum':<5} "
          f"{'Points':<8} {'Pts/G':<7} {hist_header}")
    print("-" * (140 + (47 if args.history else 0)))

    for i, player in enumerate(scored, 1):
        s = player.stats
        age_str = str(player.age) if player.age else "--"
        games_missed = total_games - s.games_played
        pts_per_game = player.fantasy_points / s.games_played if s.games_played > 0 else 0.0

        hist_cols = ""
        if args.history:
            avg_pg = f"{player.avg_pts_g_3yr:.1f}" if player.avg_pts_g_3yr is not None else "--"
            avg_pt = f"{player.avg_pts_3yr:.1f}" if player.avg_pts_3yr is not None else "--"
            szns = str(player.seasons_played) if player.seasons_played > 0 else "--"
            gm_3yr = str(player.games_missed_3yr) if player.seasons_played > 0 else "--"
            rel = f"{player.reliability_score:.1f}" if player.reliability_score is not None else "--"
            brk = "YES" if player.breakout else ""
            col = f"{player.college_dom_score:.1f}" if player.college_dom_score is not None else "--"
            hist_cols = (f"{avg_pg:<10} {avg_pt:<8} {szns:<5} {gm_3yr:<6} "
                         f"{rel:<7} {brk:<4} {col:<7}")

        pa_yds = f"{s.passing_yards:.0f}" if s.passing_yards else ""
        pa_td = str(s.passing_tds) if s.passing_tds else ""
        ints = str(s.interceptions) if s.interceptions else ""

        print(f"{i:<5} {player.name:<25} {age_str:<5} {player.position:<5} {player.team:<5} "
              f"{s.games_played:<4} {games_missed:<4} "
              f"{pa_yds:<7} {pa_td:<5} {ints:<4} "
              f"{s.receptions:<5} {s.receiving_yards:<8.1f} {s.receiving_tds:<6} "
              f"{s.rushing_attempts:<6} {s.rushing_yards:<8.1f} {s.rushing_tds:<7} "
              f"{s.fumbles_lost:<5} {player.fantasy_points:<8.2f} {pts_per_game:<7.1f} {hist_cols}")


if __name__ == "__main__":
    main()
