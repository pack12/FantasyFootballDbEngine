import streamlit as st
import pandas as pd
from fantasy_football.player_db import PlayerDatabase, games_in_season

# ── Toggle this to enable/disable Draft Board ────────────────
ENABLE_DRAFT_BOARD = True


st.set_page_config(
    page_title="Fantasy Football DB Engine",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="collapsed",
)


@st.cache_resource(show_spinner="Loading player database...")
def load_db():
    db = PlayerDatabase()
    db.load()
    return db


db = load_db()


def _load_draft_sheet():
    """Load draft board data from Google Sheets."""
    try:
        from streamlit_gsheets import GSheetsConnection
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Draftboard", ttl=5)
        if df is not None and not df.empty:
            df = df.dropna(how="all")
            return df
    except Exception as e:
        st.error(f"Failed to load from Google Sheets: {e}")
    return pd.DataFrame(columns=["user", "player_id", "name", "position", "team", "tier", "drafted"])


def _save_draft_sheet(df: pd.DataFrame):
    """Save draft board data to Google Sheets."""
    try:
        from streamlit_gsheets import GSheetsConnection
        conn = st.connection("gsheets", type=GSheetsConnection)
        conn.update(worksheet="Draftboard", data=df)
        conn.reset()  # Clear read cache so next load gets fresh data
    except Exception as e:
        st.error(f"Failed to save to Google Sheets: {e}")


st.title("Fantasy Football DB Engine")

if ENABLE_DRAFT_BOARD:
    tab_rankings, tab_search, tab_compare, tab_rookies, tab_draft = st.tabs(["Rankings", "Player Search", "Compare", "2026 Rookies", "Draft Board"])
else:
    tab_rankings, tab_search, tab_compare, tab_rookies = st.tabs(["Rankings", "Player Search", "Compare", "2026 Rookies"])

# ── Rankings Tab ──────────────────────────────────────────────

with tab_rankings:
    if ENABLE_DRAFT_BOARD:
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    else:
        col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        year = st.selectbox("Year", list(range(2025, 1998, -1)), index=0)
    with col2:
        pos = st.selectbox("Position", ["ALL", "QB", "RB", "WR", "TE"], index=0, key="rank_pos")
    with col3:
        limit = st.number_input("Limit", min_value=1, max_value=500, value=50)

    # Draft board integration
    _rankings_drafted_ids = set()
    hide_drafted = False
    if ENABLE_DRAFT_BOARD:
        with col4:
            hide_drafted = st.checkbox("Hide drafted", value=False, key="hide_drafted")
        try:
            _rankings_draft_df = _load_draft_sheet()
            if not _rankings_draft_df.empty and "drafted" in _rankings_draft_df.columns:
                _drafted_rows = _rankings_draft_df[_rankings_draft_df["drafted"] == True]  # noqa: E712
                _rankings_drafted_ids = set(_drafted_rows["player_id"].tolist())
        except Exception:
            pass

    # Build rankings data
    ranked = []
    for record in db.players.values():
        if pos != "ALL" and record.position != pos:
            continue
        season = next((s for s in record.seasons if s.year == year), None)
        if not season:
            continue
        if hide_drafted and record.player_id in _rankings_drafted_ids:
            continue
        ranked.append((record, season))

    ranked.sort(key=lambda x: x[1].pts_per_game, reverse=True)
    ranked = ranked[:limit]

    if ranked:
        rows = []
        for i, (record, season) in enumerate(ranked, 1):
            szn_rel = record.season_reliability_score
            raw_rel = record.raw_reliability_score_for_year(year)
            rel = record.reliability_score_for_year(year)
            col_scr = record.college_dom_score
            sorted_yrs = sorted(s.year for s in record.seasons)
            season_num = sorted_yrs.index(year) + 1 if year in sorted_yrs else None
            is_drafted = record.player_id in _rankings_drafted_ids if ENABLE_DRAFT_BOARD else False
            row_data = {
                "Rank": i,
            }
            if ENABLE_DRAFT_BOARD:
                row_data["Status"] = "TAKEN" if is_drafted else ""
            row_data.update({
                "Player": record.name,
                "Age": record.age if record.age is not None else None,
                "Pos": record.position,
                "Team": record.current_team,
                "GP": season.stats.games_played,
                "GM": games_in_season(year) - season.stats.games_played,
                "Points": round(season.fantasy_points, 2),
                "Pts/G": season.pts_per_game,
                "Car Pts/G": record.career_pts_g,
                "Car Pts": record.career_total_pts,
                "Yr#": season_num,
                "Szns": len(record.seasons),
                "Car GM": record.total_games_missed,
                "SznRel": round(szn_rel, 1) if szn_rel is not None else None,
                "RelScr": round(raw_rel, 1) if raw_rel is not None else None,
                "AdjRel": round(rel, 1) if rel is not None else None,
                "BRK": "YES" if record.breakout else "",
                "ColScr": round(col_scr, 1) if col_scr is not None else None,
            })
            rows.append(row_data)

        df = pd.DataFrame(rows)
        col_config = {
                "Rank": st.column_config.NumberColumn(width="small"),
        }
        if ENABLE_DRAFT_BOARD:
            col_config["Status"] = st.column_config.TextColumn(width="small")
        col_config.update({
                "Player": st.column_config.TextColumn(width="medium"),
                "Age": st.column_config.NumberColumn(width="small"),
                "Pos": st.column_config.TextColumn(width="small"),
                "Team": st.column_config.TextColumn(width="small"),
                "GP": st.column_config.NumberColumn(width="small"),
                "GM": st.column_config.NumberColumn(width="small"),
                "Points": st.column_config.NumberColumn(format="%.2f"),
                "Pts/G": st.column_config.NumberColumn(format="%.1f"),
                "Car Pts/G": st.column_config.NumberColumn(format="%.1f"),
                "Car Pts": st.column_config.NumberColumn(format="%.1f"),
                "Yr#": st.column_config.NumberColumn(width="small"),
                "Szns": st.column_config.NumberColumn(width="small"),
                "Car GM": st.column_config.NumberColumn(width="small"),
                "SznRel": st.column_config.NumberColumn(format="%.1f"),
                "RelScr": st.column_config.NumberColumn(format="%.1f"),
                "AdjRel": st.column_config.NumberColumn(format="%.1f"),
                "BRK": st.column_config.TextColumn(width="small"),
                "ColScr": st.column_config.NumberColumn(format="%.1f"),
        })
        st.dataframe(
            df,
            width="stretch",
            hide_index=True,
            height=600,
            column_config=col_config,
        )
        caption = f"{len(rows)} players shown for {year} season"
        if ENABLE_DRAFT_BOARD:
            drafted_count = sum(1 for r in rows if r.get("Status") == "TAKEN")
            if drafted_count:
                caption += f" ({drafted_count} drafted)"
        st.caption(caption)
    else:
        st.info(f"No player data found for {year}.")

# ── Player Search Tab ─────────────────────────────────────────

with tab_search:
    query = st.text_input("Search Player", placeholder="Type a player name...")

    if query:
        results = db.search(query.strip(), limit=30)
        if results:
            # Build a list of names for selection
            options = []
            for p in results:
                num_seasons = len(p.seasons)
                career_pts = p.career_pts_g
                pts_str = f"{career_pts:.1f} pts/g" if career_pts else ""
                options.append(f"{p.name}  |  {p.position}  |  {p.current_team}  |  {num_seasons} szn  |  {pts_str}")

            selected_idx = st.selectbox(
                "Select a player",
                range(len(options)),
                format_func=lambda i: options[i],
                key="player_select",
            )

            p = results[selected_idx]

            # Fetch college details on-demand
            db.fetch_player_details(p.player_id)

            # Player info columns
            info_col, stats_col = st.columns([1, 2])

            with info_col:
                st.subheader(p.name)
                age_str = str(p.age) if p.age else "N/A"
                st.markdown(f"""
                **Position:** {p.position}
                **Team:** {p.current_team}
                **Age:** {age_str}
                **NFL Seasons:** {len(p.seasons)}
                """)

                st.markdown("---")
                st.markdown("**Career Summary**")
                career_pg = p.career_pts_g
                raw_rel = p.raw_reliability_score
                rel = p.reliability_score
                st.markdown(f"""
                **Total Fantasy Pts:** {p.career_total_pts:.1f}
                **Career Pts/Game:** {f'{career_pg:.1f}' if career_pg else 'N/A'}
                **Total Games:** {p.total_games}
                **Games Missed:** {p.total_games_missed}
                **Reliability Score:** {f'{raw_rel:.1f}' if raw_rel else 'N/A'}
                **Age-Adj RelScore:** {f'{rel:.1f}' if rel else 'N/A'}
                {'**Breakout: YES**' if p.breakout else ''}
                """)

                if p.college_dom_score is not None:
                    st.markdown("---")
                    st.markdown("**College**")
                    st.markdown(f"**Dominance Score:** {p.college_dom_score:.1f}")
                    if p.college_final_year:
                        st.markdown(f"**Final Year:** {p.college_final_year}")

            with stats_col:
                st.markdown("**Season-by-Season**")
                sorted_seasons = sorted(p.seasons, key=lambda s: s.year, reverse=True)

                if p.position == "QB":
                    season_rows = []
                    for s in sorted_seasons:
                        st_ = s.stats
                        season_rows.append({
                            "Year": s.year,
                            "Team": s.team,
                            "GP": st_.games_played,
                            "PaYds": int(st_.passing_yards),
                            "PaTD": st_.passing_tds,
                            "INT": st_.interceptions,
                            "RuYds": int(st_.rushing_yards),
                            "RuTD": st_.rushing_tds,
                            "Fum": st_.fumbles_lost,
                            "Pts": round(s.fantasy_points, 1),
                            "Pts/G": s.pts_per_game,
                        })
                else:
                    season_rows = []
                    for s in sorted_seasons:
                        st_ = s.stats
                        season_rows.append({
                            "Year": s.year,
                            "Team": s.team,
                            "GP": st_.games_played,
                            "Rec": st_.receptions,
                            "RecYds": int(st_.receiving_yards),
                            "RecTD": st_.receiving_tds,
                            "RuAtt": st_.rushing_attempts,
                            "RuYds": int(st_.rushing_yards),
                            "RuTD": st_.rushing_tds,
                            "Fum": st_.fumbles_lost,
                            "Pts": round(s.fantasy_points, 1),
                            "Pts/G": s.pts_per_game,
                        })

                st.dataframe(
                    pd.DataFrame(season_rows),
                    width="stretch",
                    hide_index=True,
                    height=min(len(sorted_seasons) * 40 + 40, 500),
                )
        else:
            st.warning("No players found.")

# ── Compare Tab ───────────────────────────────────────────────

with tab_compare:
    cmp_pos = st.selectbox("Position", ["QB", "RB", "WR", "TE"], index=1, key="cmp_pos")

    # Get players for selected position, sorted by career points
    cmp_players = [p for p in db.players.values() if p.position == cmp_pos]
    cmp_players.sort(key=lambda p: p.career_total_pts, reverse=True)
    cmp_names = [f"{p.name} ({p.current_team})" for p in cmp_players]

    c1, c2 = st.columns(2)
    with c1:
        p1_idx = st.selectbox("Player 1", range(len(cmp_names)),
                               format_func=lambda i: cmp_names[i], key="cmp_p1")
    with c2:
        p2_default = min(1, len(cmp_names) - 1)
        p2_idx = st.selectbox("Player 2", range(len(cmp_names)),
                               format_func=lambda i: cmp_names[i], index=p2_default, key="cmp_p2")

    if cmp_players and p1_idx != p2_idx:
        p1 = cmp_players[p1_idx]
        p2 = cmp_players[p2_idx]

        def better(v1, v2, lower_is_better=False):
            """Return styling markers for the better value."""
            if v1 is None or v2 is None:
                return "", ""
            try:
                f1, f2 = float(v1), float(v2)
                if lower_is_better:
                    return ("**", "") if f1 < f2 else ("", "**") if f2 < f1 else ("", "")
                return ("**", "") if f1 > f2 else ("", "**") if f2 > f1 else ("", "")
            except (ValueError, TypeError):
                return "", ""

        # Profile comparison
        col1, col2 = st.columns(2)
        with col1:
            st.subheader(p1.name)
            st.markdown(f"**Team:** {p1.current_team}")
            st.markdown(f"**Age:** {p1.age if p1.age else 'N/A'}")
            st.markdown(f"**Seasons:** {len(p1.seasons)}")
        with col2:
            st.subheader(p2.name)
            st.markdown(f"**Team:** {p2.current_team}")
            st.markdown(f"**Age:** {p2.age if p2.age else 'N/A'}")
            st.markdown(f"**Seasons:** {len(p2.seasons)}")

        # Career comparison table
        st.markdown("### Career Comparison")

        def fmt(v, decimals=1):
            if v is None:
                return "N/A"
            return f"{v:.{decimals}f}" if isinstance(v, float) else str(v)

        career_data = {
            "Stat": ["Total Pts", "Career Pts/G", "Total Games", "Games Missed",
                     "RelScr", "AdjRel", "Breakout"],
            p1.name: [
                fmt(p1.career_total_pts), fmt(p1.career_pts_g),
                str(p1.total_games), str(p1.total_games_missed),
                fmt(p1.raw_reliability_score), fmt(p1.reliability_score),
                "YES" if p1.breakout else "",
            ],
            p2.name: [
                fmt(p2.career_total_pts), fmt(p2.career_pts_g),
                str(p2.total_games), str(p2.total_games_missed),
                fmt(p2.raw_reliability_score), fmt(p2.reliability_score),
                "YES" if p2.breakout else "",
            ],
        }
        st.dataframe(pd.DataFrame(career_data), width="stretch", hide_index=True)

        # Season-by-season comparison
        st.markdown("### Season-by-Season")

        p1_years = {s.year: s for s in p1.seasons}
        p2_years = {s.year: s for s in p2.seasons}
        all_years = sorted(set(p1_years.keys()) | set(p2_years.keys()), reverse=True)

        if cmp_pos == "QB":
            season_rows = []
            for yr in all_years:
                s1 = p1_years.get(yr)
                s2 = p2_years.get(yr)
                season_rows.append({
                    "Year": yr,
                    f"{p1.name} GP": s1.stats.games_played if s1 else "",
                    f"{p2.name} GP": s2.stats.games_played if s2 else "",
                    f"{p1.name} PaYds": int(s1.stats.passing_yards) if s1 else "",
                    f"{p2.name} PaYds": int(s2.stats.passing_yards) if s2 else "",
                    f"{p1.name} PaTD": s1.stats.passing_tds if s1 else "",
                    f"{p2.name} PaTD": s2.stats.passing_tds if s2 else "",
                    f"{p1.name} INT": s1.stats.interceptions if s1 else "",
                    f"{p2.name} INT": s2.stats.interceptions if s2 else "",
                    f"{p1.name} Pts/G": s1.pts_per_game if s1 else "",
                    f"{p2.name} Pts/G": s2.pts_per_game if s2 else "",
                })
        else:
            season_rows = []
            for yr in all_years:
                s1 = p1_years.get(yr)
                s2 = p2_years.get(yr)
                season_rows.append({
                    "Year": yr,
                    f"{p1.name} GP": s1.stats.games_played if s1 else "",
                    f"{p2.name} GP": s2.stats.games_played if s2 else "",
                    f"{p1.name} Rec": s1.stats.receptions if s1 else "",
                    f"{p2.name} Rec": s2.stats.receptions if s2 else "",
                    f"{p1.name} RecYds": int(s1.stats.receiving_yards) if s1 else "",
                    f"{p2.name} RecYds": int(s2.stats.receiving_yards) if s2 else "",
                    f"{p1.name} RuYds": int(s1.stats.rushing_yards) if s1 else "",
                    f"{p2.name} RuYds": int(s2.stats.rushing_yards) if s2 else "",
                    f"{p1.name} Pts/G": s1.pts_per_game if s1 else "",
                    f"{p2.name} Pts/G": s2.pts_per_game if s2 else "",
                })

        cmp_df = pd.DataFrame(season_rows).astype(str).replace("", None)
        st.dataframe(cmp_df, width="stretch", hide_index=True,
                     height=min(len(all_years) * 40 + 40, 500))

    elif cmp_players and p1_idx == p2_idx:
        st.warning("Select two different players to compare.")

# ── Rookies Tab ───────────────────────────────────────────────

with tab_rookies:
    r_col1, r_col2 = st.columns([1, 2])
    with r_col1:
        rookie_pos = st.selectbox("Position", ["ALL", "QB", "RB", "WR", "TE"], index=0, key="rookie_pos")
    with r_col2:
        compare_vets = st.checkbox("Compare with Veterans (uses RelScr)")

    projections = db.rookie_projections

    if not projections:
        st.info("No 2026 rookie projection data available. Try refreshing the database.")
    else:
        if rookie_pos != "ALL":
            projections = [r for r in projections if r.position == rookie_pos]

        rows = []
        for r in projections:
            rows.append({
                "Player": r.name,
                "Pos": r.position,
                "Team": r.team,
                "Rd": r.draft_round if r.draft_round else None,
                "Pick": r.draft_number if r.draft_number else None,
                "ColScr": round(r.college_dom_score, 1) if r.college_dom_score else None,
                "Proj Pts/G": r.projected_pts_g,
                "Comp Player": r.comp_name,
                "College Stats": r.college_final_year,
                "_sort": r.projected_pts_g or 0,
                "_type": "🟢 Rookie",
            })

        if compare_vets:
            for record in db.players.values():
                if rookie_pos != "ALL" and record.position != rookie_pos:
                    continue
                rel = record.raw_reliability_score
                if rel is None:
                    continue
                rows.append({
                    "Player": record.name,
                    "Pos": record.position,
                    "Team": record.current_team,
                    "Rd": None,
                    "Pick": None,
                    "ColScr": None,
                    "Proj Pts/G": rel,
                    "Comp Player": f"{len(record.seasons)} seasons",
                    "College Stats": "",
                    "_sort": rel,
                    "_type": "Veteran",
                })

        rows.sort(key=lambda r: r["_sort"], reverse=True)

        # Add rank
        for i, row in enumerate(rows, 1):
            row["Rank"] = i

        df = pd.DataFrame(rows)
        display_cols = ["Rank", "_type", "Player", "Pos", "Team", "Rd", "Pick",
                        "ColScr", "Proj Pts/G", "Comp Player", "College Stats"]

        st.dataframe(
            df[display_cols],
            width="stretch",
            hide_index=True,
            height=600,
            column_config={
                "Rank": st.column_config.NumberColumn(width="small"),
                "_type": st.column_config.TextColumn("Type", width="small"),
                "Player": st.column_config.TextColumn(width="medium"),
                "Pos": st.column_config.TextColumn(width="small"),
                "Team": st.column_config.TextColumn(width="small"),
                "Rd": st.column_config.NumberColumn(width="small"),
                "Pick": st.column_config.NumberColumn(width="small"),
                "ColScr": st.column_config.NumberColumn(format="%.1f"),
                "Proj Pts/G": st.column_config.NumberColumn(format="%.1f"),
                "Comp Player": st.column_config.TextColumn(width="medium"),
                "College Stats": st.column_config.TextColumn(width="large"),
            },
        )

        rookie_count = sum(1 for r in rows if r["_type"] == "🟢 Rookie")
        vet_count = sum(1 for r in rows if r["_type"] == "Veteran")
        caption = f"{rookie_count} rookies"
        if vet_count:
            caption += f" + {vet_count} veterans"
        st.caption(caption)

# ── Draft Board Tab ──────────────────────────────────────────

if ENABLE_DRAFT_BOARD:
    with tab_draft:
        # User identification
        if "draft_user" not in st.session_state:
            st.session_state.draft_user = ""

        user_col, info_col = st.columns([1, 2])
        with user_col:
            draft_user = st.text_input("Your draft code (e.g. 'john')", value=st.session_state.draft_user,
                                        key="draft_user_input", placeholder="Enter your name or code...")
        with info_col:
            if draft_user:
                st.success(f"Logged in as: **{draft_user}**")
            else:
                st.warning("Enter a draft code to get started.")

        if draft_user:
            st.session_state.draft_user = draft_user

            # Load data from Google Sheets
            all_draft_data = _load_draft_sheet()
            user_draft = all_draft_data[all_draft_data["user"] == draft_user].copy()

            # Collect all drafted player_ids across ALL users
            all_drafted_ids = set()
            if "drafted" in all_draft_data.columns:
                drafted_rows = all_draft_data[all_draft_data["drafted"] == True]  # noqa: E712
                all_drafted_ids = set(drafted_rows["player_id"].tolist())

            # --- Add player section ---
            st.markdown("### Add Player to Board")
            add_col1, add_col2, add_col3 = st.columns([2, 1, 1])

            with add_col1:
                add_query = st.text_input("Search player to add", placeholder="Type a player name...",
                                           key="draft_add_search")
            with add_col2:
                tier = st.selectbox("Tier", [1, 2, 3, 4, 5], index=0, key="draft_tier",
                                    help="1 = must draft, 5 = deep sleeper")

            if add_query:
                search_results = db.search(add_query.strip(), limit=10)
                if search_results:
                    add_options = [f"{p.name}  |  {p.position}  |  {p.current_team}" for p in search_results]
                    with add_col1:
                        add_idx = st.selectbox("Select player", range(len(add_options)),
                                                format_func=lambda i: add_options[i], key="draft_add_select")

                    selected_player = search_results[add_idx]

                    # Check if already on this user's board
                    already_on_board = selected_player.player_id in user_draft["player_id"].values if not user_draft.empty else False

                    with add_col3:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if already_on_board:
                            st.info("Already on your board")
                        elif st.button("Add to Board", type="primary", key="draft_add_btn"):
                            new_row = pd.DataFrame([{
                                "user": draft_user,
                                "player_id": selected_player.player_id,
                                "name": selected_player.name,
                                "position": selected_player.position,
                                "team": selected_player.current_team,
                                "tier": tier,
                                "drafted": False,
                            }])
                            all_draft_data = pd.concat([all_draft_data, new_row], ignore_index=True)
                            _save_draft_sheet(all_draft_data)
                            st.rerun()

            st.markdown("---")

            # --- Draft board display by position ---
            st.markdown("### Your Draft Board")
            pos_tabs = st.tabs(["QB", "RB", "WR", "TE"])

            for pos_tab, pos in zip(pos_tabs, ["QB", "RB", "WR", "TE"]):
                with pos_tab:
                    pos_players = user_draft[user_draft["position"] == pos].copy() if not user_draft.empty else pd.DataFrame()

                    if pos_players.empty:
                        st.info(f"No {pos}s on your board yet. Use the search above to add players.")
                        continue

                    # Sort by tier, then by name
                    pos_players["tier"] = pos_players["tier"].astype(int)
                    pos_players = pos_players.sort_values(["tier", "name"])

                    for _, row in pos_players.iterrows():
                        is_drafted = row.get("drafted", False)
                        if pd.isna(is_drafted):
                            is_drafted = False
                        is_drafted = bool(is_drafted)

                        player_id = row["player_id"]
                        name = row["name"]
                        team = row.get("team", "")
                        player_tier = int(row["tier"])

                        # Look up live stats
                        record = db.get_player(player_id)
                        stat_parts = []
                        if record:
                            # 2025 season Pts/G
                            season_2025 = next((s for s in record.seasons if s.year == 2025), None)
                            if season_2025 and season_2025.pts_per_game > 0:
                                stat_parts.append(f"Pts/G '25: {season_2025.pts_per_game:.1f}")
                            # Career Pts/G
                            cpg = record.career_pts_g
                            if cpg:
                                stat_parts.append(f"Car: {cpg:.1f}")
                            # Reliability score
                            rel = record.raw_reliability_score
                            if rel:
                                stat_parts.append(f"Rel: {rel:.1f}")
                        stat_str = " | ".join(stat_parts)

                        # Tier colors
                        tier_colors = {
                            1: "#FFD700",  # Gold
                            2: "#C0C0C0",  # Silver
                            3: "#CD7F32",  # Bronze
                            4: "#6CA6CD",  # Steel blue
                            5: "#8A8A8A",  # Grey
                        }
                        tier_color = tier_colors.get(player_tier, "#e0e0e0")

                        col_status, col_info, col_actions = st.columns([0.5, 3, 1.5])

                        with col_status:
                            if is_drafted:
                                st.markdown("~~:red[TAKEN]~~")
                            else:
                                st.markdown(":green[AVAIL]")

                        with col_info:
                            display_text = f"T{player_tier} — {name} ({team})"
                            if stat_str:
                                display_text += f" — {stat_str}"
                            if is_drafted:
                                st.markdown(f"~~<span style='color:{tier_color}'>{display_text}</span>~~",
                                            unsafe_allow_html=True)
                            else:
                                st.markdown(f"<span style='color:{tier_color}; font-weight:bold'>{display_text}</span>",
                                            unsafe_allow_html=True)

                        with col_actions:
                            btn_cols = st.columns(2)
                            with btn_cols[0]:
                                if not is_drafted:
                                    if st.button("Draft", key=f"draft_{draft_user}_{player_id}",
                                                  type="secondary"):
                                        mask = ((all_draft_data["player_id"] == player_id) &
                                                (all_draft_data["user"] == draft_user))
                                        all_draft_data.loc[mask, "drafted"] = True
                                        _save_draft_sheet(all_draft_data)
                                        st.rerun()
                                else:
                                    if st.button("Undo", key=f"undraft_{draft_user}_{player_id}",
                                                  type="secondary"):
                                        mask = ((all_draft_data["player_id"] == player_id) &
                                                (all_draft_data["user"] == draft_user))
                                        all_draft_data.loc[mask, "drafted"] = False
                                        _save_draft_sheet(all_draft_data)
                                        st.rerun()
                            with btn_cols[1]:
                                if st.button("Remove", key=f"remove_{draft_user}_{player_id}",
                                              type="secondary"):
                                    mask = ~((all_draft_data["player_id"] == player_id) &
                                             (all_draft_data["user"] == draft_user))
                                    all_draft_data = all_draft_data[mask]
                                    _save_draft_sheet(all_draft_data)
                                    st.rerun()

            # --- Show drafted players affecting Rankings ---
            if all_drafted_ids:
                st.markdown("---")
                st.caption(f"{len(all_drafted_ids)} players drafted across all users — these are greyed out in Rankings.")
