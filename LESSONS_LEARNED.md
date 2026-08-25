# Fantasy Football DB Engine - Lessons Learned

A running log of problems encountered, solutions discovered, and design decisions made while building this app.

---

## Data Sources

### nflverse is the Best Free NFL Data Source
- Provides per-week stats from 1999-2024 via CSV files hosted on GitHub
- Also includes roster data (1999-2026) with birth_date, espn_id, draft_number, rookie_year
- Free, no API key needed, and the CSVs are fast to parse
- Limitation: doesn't have data for the current in-progress season (e.g., 2025)

### ESPN as a Fallback for Current Season
- ESPN's public fantasy API (`lm-api-reads.fantasy.espn.com`) doesn't require authentication
- Use the `X-Fantasy-Filter` header with JSON to filter by position, ownership status, etc.
- The `limit` parameter in the filter matters a lot — originally set to 300 across all positions, which only returned ~91 RBs. Bumping to 1000 fixed it
- ESPN uses its own stat IDs (e.g., "3" = passing yards, "24" = rushing yards) that need mapping
- ESPN position IDs (defaultPositionId) differ from slot IDs (filterSlotIds) — don't confuse them

### ESPN College Stats API
- `site.api.espn.com/apis/common/v3/sports/football/college-football/athletes/{id}/stats`
- Returns categories (rushing, receiving, passing) with per-season stat arrays
- Many players return 404 or empty data — you must handle this gracefully and cache the "no data" result, otherwise you'll re-fetch hundreds of players on every app load
- The stat field names vary slightly between categories (e.g., "gamesPlayed" vs "games")
- Originally used a fixed 13-game estimate for college seasons; switched to actual games played from the API for accuracy

---

## Player Identity & Matching

### Name Normalization is Critical
- ESPN and nflverse use different name formats: ESPN had "James Cook III" while nflverse had "James Cook"
- Solution: strip punctuation AND suffixes (Jr, Sr, II, III, IV, V) when matching
- This prevents duplicate entries for the same player across data sources
- The `_normalize_name()` function lowercases, removes punctuation, then strips suffix tokens

### Player IDs
- nflverse uses GSIS IDs (e.g., "00-0033873") — not human-readable
- ESPN uses numeric athlete IDs
- When merging ESPN fallback data into nflverse records, match by normalized name + position
- For the college CSV, added a `name` column alongside `player_id` so the file is human-editable

---

## Scoring & Metrics

### PPR Scoring Formula
- 1 pt per reception, 0.1 per rushing/receiving yard, 6 per rushing/receiving TD
- 4 per passing TD, 0.04 per passing yard, -2 per INT and fumble lost, 2 per 2pt conversion

### Games Per Season Changed in 2021
- Pre-2021: 16-game seasons. 2021+: 17-game seasons
- This affects availability calculations (games played / games possible)
- Must use `games_in_season(year)` helper instead of hardcoding 17

### Reliability Score (RelScr) - Recency-Weighted
- Weights: most recent season = 50%, second = 30%, third = 20%, fourth = 10%, etc.
- Multiply recency-weighted Pts/G by availability (total games / total possible games)
- This balances per-game production with durability

### Age-Adjusted Reliability Score (AdjRel)
- RelScr multiplied by an age factor: `max(0, 1.0 - max(0, age - threshold) * 0.03)`
- Position-specific age thresholds: QB=32, WR=29, RB=27, TE=29
- 3% penalty per year beyond the threshold
- Kept the raw RelScr as a separate column so users can see both

### Breakout Detection
- Originally compared latest season Pts/G against average of ALL prior seasons
- This caused false positives: James Cook's breakout year looked huge compared to his average because it included a low-production rookie year
- Fixed: compare latest season vs. previous season only (1.4x threshold)

### Backup QB Detection Was a Bad Idea
- Tried filtering out seasons with <200 pass attempts as "backup" seasons
- This backfired: Jayden Daniels played only 7 games in 2025 (injury, not backup) and fell below the threshold, making his availability look like 17/17 and inflating his RelScr to 20.9
- Lesson: don't try to be too clever with filtering — let all seasons count equally

---

## Caching Strategy

### CSV Caching Saves Massive Load Time
- First load fetches from nflverse (28 years of data) + ESPN + birth dates — takes minutes
- Subsequent loads read from local CSVs in seconds
- Cache version tracking (`_CACHE_VERSION`) forces re-fetch when the data format changes

### Cache the "No Data" Result Too
- 220+ players had no college data on ESPN (404 or empty stats)
- Originally only cached players WITH data, so those 220 were re-fetched every single run
- Fix: save all attempted players to the CSV (with empty score), and check `_college_attempted` flag before fetching
- General principle: if you tried and got nothing, that's still information worth caching

### Birth Dates from Rosters
- Originally fetched age per-player from ESPN's athlete API — extremely slow (one HTTP call per player)
- Switched to nflverse roster CSVs which include birth_date — bulk download, much faster
- Must download ALL roster years (2026 down to 1999) to cover every player; skipping years creates gaps

---

## Rookie Projections

### College-to-NFL Scaling Factors
- Historical median ratio of NFL Pts/G to college dominance score, grouped by position and draft tier
- Draft tiers: top-10 pick, rest of round 1, round 2, round 3+
- Using median (not mean) avoids skew from outlier busts/booms
- Find a historical comparable player ("comp") for each rookie based on similar college production and draft position

---

## UI / Frontend

### ttkbootstrap Gotchas
- `ttkbootstrap.PanedWindow` doesn't exist — use `ttk.Panedwindow` (lowercase 'w', from standard ttk)
- The "darkly" theme works well for a draft-day dark mode aesthetic
- `bootstyle` parameter controls widget styling in ttkbootstrap

### Dual Frontend Architecture
- tkinter (gui.py) for desktop, Streamlit (streamlit_app.py) for mobile/web access
- Both share the same backend (fantasy_football/player_db.py)
- Streamlit Community Cloud provides free hosting — useful for accessing the app on a phone at a draft party
- `@st.cache_resource` prevents re-loading the database on every Streamlit interaction

---

## General Engineering Lessons

1. **Start simple, add complexity only when needed.** The backup QB filter seemed smart but created worse problems than it solved.

2. **When a metric looks wrong, trace it all the way back.** Jayden Daniels' inflated score wasn't a math bug — it was a data filtering decision that removed a season from the calculation.

3. **Cache aggressively, but cache failures too.** If you only cache successes, you'll keep retrying the same failures forever.

4. **Normalize before matching.** Any time you join data from two sources, name formatting differences will bite you.

5. **Don't hardcode constants that change over time.** The 16-to-17 game season change broke availability calculations everywhere a `17` was hardcoded.

6. **Add human-readable columns to machine-readable files.** A `name` column in the college CSV costs nothing but makes manual editing possible.

7. **Test with real data edge cases.** Players with short careers, injured seasons, position changes, and name suffixes all exposed bugs that toy data wouldn't catch.
