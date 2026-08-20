import tkinter as tk
from tkinter import ttk, messagebox
import threading
from fantasy_football.espn_client import fetch_players, fetch_players_with_history
from fantasy_football.scoring import score_players


COLUMNS = {
    "rank": ("Rank", 50),
    "name": ("Player", 180),
    "age": ("Age", 50),
    "position": ("Pos", 50),
    "team": ("Team", 55),
    "gp": ("GP", 45),
    "gm": ("GM", 45),
    "receptions": ("Rec", 50),
    "rec_yds": ("RecYds", 70),
    "rec_td": ("RecTD", 55),
    "rush_att": ("Rush", 55),
    "rush_yds": ("RushYds", 70),
    "rush_td": ("RushTD", 60),
    "fum": ("Fum", 45),
    "points": ("Points", 70),
    "pts_g": ("Pts/G", 60),
    "avg_pts_g_3yr": ("3yr Pts/G", 75),
    "avg_pts_3yr": ("3yr Avg", 70),
    "seasons": ("Szns", 45),
    "gm_3yr": ("3yr GM", 55),
    "rel_score": ("RelScr", 65),
    "breakout": ("BRK", 45),
    "col_score": ("ColScr", 60),
}

# Columns that should sort numerically
NUMERIC_COLUMNS = {
    "rank", "age", "gp", "gm", "receptions", "rec_yds", "rec_td",
    "rush_att", "rush_yds", "rush_td", "fum", "points", "pts_g",
    "avg_pts_g_3yr", "avg_pts_3yr", "seasons", "gm_3yr", "rel_score",
    "col_score",
}


class FantasyFootballApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Fantasy Football PPR Scoring Engine")
        self.root.geometry("1650x700")
        self.sort_reverse = {}
        self.cached_players = []  # store fetched players for search tab

        self._build_status_bar()
        self._build_notebook()

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab 1: Rankings
        self.rankings_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.rankings_tab, text="  Rankings  ")
        self._build_rankings_tab()

        # Tab 2: Player Search
        self.search_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.search_tab, text="  Player Search  ")
        self._build_search_tab()

    # ── Rankings Tab ──────────────────────────────────────────────

    def _build_rankings_tab(self):
        self._build_controls(self.rankings_tab)
        self._build_table(self.rankings_tab)

    def _build_controls(self, parent):
        frame = ttk.Frame(parent, padding=10)
        frame.pack(fill=tk.X)

        ttk.Label(frame, text="Year:").pack(side=tk.LEFT, padx=(0, 5))
        self.year_var = tk.StringVar(value="2025")
        ttk.Entry(frame, textvariable=self.year_var, width=6).pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(frame, text="Week:").pack(side=tk.LEFT, padx=(0, 5))
        self.week_var = tk.StringVar(value="0")
        ttk.Combobox(frame, textvariable=self.week_var, width=5,
                     values=["0"] + [str(i) for i in range(1, 19)]).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(frame, text="(0 = Full Season)").pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(frame, text="Position:").pack(side=tk.LEFT, padx=(0, 5))
        self.pos_var = tk.StringVar(value="ALL")
        ttk.Combobox(frame, textvariable=self.pos_var, width=5,
                     values=["ALL", "RB", "WR"], state="readonly").pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(frame, text="Limit:").pack(side=tk.LEFT, padx=(0, 5))
        self.limit_var = tk.StringVar(value="50")
        ttk.Entry(frame, textvariable=self.limit_var, width=5).pack(side=tk.LEFT, padx=(0, 15))

        self.history_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="3yr History", variable=self.history_var).pack(side=tk.LEFT, padx=(0, 15))

        ttk.Button(frame, text="Fetch & Score", command=self._on_fetch).pack(side=tk.LEFT, padx=(10, 0))

    def _build_table(self, parent):
        container = ttk.Frame(parent)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))

        scrollbar_y = ttk.Scrollbar(container, orient=tk.VERTICAL)
        scrollbar_x = ttk.Scrollbar(container, orient=tk.HORIZONTAL)

        col_ids = list(COLUMNS.keys())
        self.tree = ttk.Treeview(container, columns=col_ids, show="headings",
                                 yscrollcommand=scrollbar_y.set,
                                 xscrollcommand=scrollbar_x.set)

        scrollbar_y.config(command=self.tree.yview)
        scrollbar_x.config(command=self.tree.xview)

        for col_id, (heading, width) in COLUMNS.items():
            self.tree.heading(col_id, text=heading,
                              command=lambda c=col_id: self._sort_column(c))
            anchor = tk.W if col_id == "name" else tk.CENTER
            self.tree.column(col_id, width=width, anchor=anchor, minwidth=40)
            self.sort_reverse[col_id] = False

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)

        self.tree.tag_configure("even", background="#f0f0f0")
        self.tree.tag_configure("odd", background="#ffffff")

    # ── Player Search Tab ─────────────────────────────────────────

    def _build_search_tab(self):
        # Search bar
        search_frame = ttk.Frame(self.search_tab, padding=10)
        search_frame.pack(fill=tk.X)

        ttk.Label(search_frame, text="Search Player:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=(0, 10))
        search_entry.bind("<Return>", lambda e: self._on_search())
        search_entry.bind("<KeyRelease>", lambda e: self._on_search())

        ttk.Label(search_frame, text="(searches loaded data — fetch from Rankings tab first)",
                  foreground="gray").pack(side=tk.LEFT)

        # Matching players list
        list_frame = ttk.Frame(self.search_tab)
        list_frame.pack(fill=tk.X, padx=10, pady=(0, 5))

        ttk.Label(list_frame, text="Matching Players:").pack(anchor=tk.W)
        self.match_listbox = tk.Listbox(list_frame, height=5)
        self.match_listbox.pack(fill=tk.X, pady=(2, 0))
        self.match_listbox.bind("<<ListboxSelect>>", self._on_player_select)

        # Player detail area
        detail_frame = ttk.LabelFrame(self.search_tab, text="Player Details", padding=10)
        detail_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.detail_text = tk.Text(detail_frame, wrap=tk.WORD, font=("Courier", 13),
                                   state=tk.DISABLED, bg="#fafafa")
        self.detail_text.pack(fill=tk.BOTH, expand=True)

    def _on_search(self):
        query = self.search_var.get().strip().lower()
        self.match_listbox.delete(0, tk.END)

        if not query or not self.cached_players:
            return

        matches = [p for p in self.cached_players if query in p.name.lower()]
        for player in matches[:20]:
            self.match_listbox.insert(tk.END, f"{player.name} ({player.position} - {player.team})")

    def _on_player_select(self, event):
        selection = self.match_listbox.curselection()
        if not selection:
            return

        selected_text = self.match_listbox.get(selection[0])
        # Extract player name from "Name (POS - TEAM)"
        player_name = selected_text.split(" (")[0]

        player = None
        for p in self.cached_players:
            if p.name == player_name:
                player = p
                break

        if player:
            self._show_player_detail(player)

    def _show_player_detail(self, p):
        from fantasy_football.scoring import calculate_score

        s = p.stats
        pts_g = p.fantasy_points / s.games_played if s.games_played > 0 else 0.0

        lines = []
        lines.append(f"{'=' * 50}")
        lines.append(f"  {p.name}")
        lines.append(f"{'=' * 50}")
        lines.append("")

        # Basic info
        lines.append(f"  Position:    {p.position}")
        lines.append(f"  Team:        {p.team}")
        age_str = str(p.age) if p.age else "N/A"
        lines.append(f"  Age:         {age_str}")
        lines.append("")

        # Current season stats
        lines.append(f"  ── Current Season {'─' * 30}")
        lines.append(f"  Games Played:      {s.games_played}")
        lines.append(f"  Fantasy Points:    {p.fantasy_points:.2f}")
        lines.append(f"  Points/Game:       {pts_g:.1f}")
        lines.append("")
        lines.append(f"  Rushing:    {s.rushing_attempts} att, {s.rushing_yards:.1f} yds, {s.rushing_tds} TD")
        lines.append(f"  Receiving:  {s.receptions} rec, {s.receiving_yards:.1f} yds, {s.receiving_tds} TD")
        lines.append(f"  Fumbles:    {s.fumbles_lost}")
        lines.append("")

        # Historical data
        if p.seasons_played > 0:
            lines.append(f"  ── Historical ({p.seasons_played} seasons) {'─' * 22}")
            avg_pg = f"{p.avg_pts_g_3yr:.1f}" if p.avg_pts_g_3yr is not None else "N/A"
            avg_pt = f"{p.avg_pts_3yr:.1f}" if p.avg_pts_3yr is not None else "N/A"
            lines.append(f"  Avg Pts/Game:      {avg_pg}")
            lines.append(f"  Avg Pts/Season:    {avg_pt}")
            lines.append(f"  Total Games Missed:{p.games_missed_3yr}")
            rel = f"{p.reliability_score:.1f}" if p.reliability_score is not None else "N/A"
            lines.append(f"  Reliability Score: {rel}")
            if p.breakout:
                lines.append(f"  Breakout:          YES")
            lines.append("")

        # College data
        if p.college_dom_score is not None:
            lines.append(f"  ── College {'─' * 37}")
            lines.append(f"  Dominance Score:   {p.college_dom_score:.1f}")
            if p.college_final_year:
                lines.append(f"  Final Year Stats:  {p.college_final_year}")
            lines.append("")

        self.detail_text.config(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", "\n".join(lines))
        self.detail_text.config(state=tk.DISABLED)

    # ── Status Bar ────────────────────────────────────────────────

    def _build_status_bar(self):
        self.status_var = tk.StringVar(value="Ready. Click 'Fetch & Score' to load data.")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN,
                  anchor=tk.W, padding=5).pack(fill=tk.X, side=tk.BOTTOM)

    # ── Data Fetching ─────────────────────────────────────────────

    def _on_fetch(self):
        try:
            year = int(self.year_var.get())
            week = int(self.week_var.get())
            limit = int(self.limit_var.get())
        except ValueError:
            messagebox.showerror("Input Error", "Year, Week, and Limit must be numbers.")
            return

        history = self.history_var.get()
        msg = "Fetching data from ESPN..."
        if history:
            msg = "Fetching data from ESPN (+ 3 prior seasons)..."
        self.status_var.set(msg)
        self.root.update_idletasks()

        thread = threading.Thread(target=self._fetch_data, args=(year, week, limit, history), daemon=True)
        thread.start()

    def _fetch_data(self, year, week, limit, history):
        try:
            if history:
                players = fetch_players_with_history(year=year, week=week, limit=limit)
            else:
                players = fetch_players(year=year, week=week, limit=limit)

            pos = self.pos_var.get()
            if pos != "ALL":
                players = [p for p in players if p.position == pos]

            scored = score_players(players)
            total_games = 1 if week > 0 else 17

            # Cache for search tab
            self.cached_players = scored

            rows = []
            for i, player in enumerate(scored, 1):
                s = player.stats
                gm = total_games - s.games_played
                pts_g = player.fantasy_points / s.games_played if s.games_played > 0 else 0.0

                avg_pg = round(player.avg_pts_g_3yr, 1) if player.avg_pts_g_3yr is not None else "--"
                avg_pt = round(player.avg_pts_3yr, 1) if player.avg_pts_3yr is not None else "--"
                szns = player.seasons_played if player.seasons_played > 0 else "--"
                gm_3yr = player.games_missed_3yr if player.seasons_played > 0 else "--"
                rel = round(player.reliability_score, 1) if player.reliability_score is not None else "--"
                brk = "YES" if player.breakout else ""
                col_scr = round(player.college_dom_score, 1) if player.college_dom_score is not None else "--"

                rows.append((
                    i,
                    player.name,
                    player.age if player.age else "--",
                    player.position,
                    player.team,
                    s.games_played,
                    gm,
                    s.receptions,
                    round(s.receiving_yards, 1),
                    s.receiving_tds,
                    s.rushing_attempts,
                    round(s.rushing_yards, 1),
                    s.rushing_tds,
                    s.fumbles_lost,
                    round(player.fantasy_points, 2),
                    round(pts_g, 1),
                    avg_pg,
                    avg_pt,
                    szns,
                    gm_3yr,
                    rel,
                    brk,
                    col_scr,
                ))

            self.root.after(0, lambda: self._populate_table(rows, len(scored)))

        except Exception as e:
            self.root.after(0, lambda: self._show_error(str(e)))

    def _populate_table(self, rows, count):
        self.tree.delete(*self.tree.get_children())
        for idx, row in enumerate(rows):
            tag = "even" if idx % 2 == 0 else "odd"
            self.tree.insert("", tk.END, values=row, tags=(tag,))
        self.status_var.set(f"Loaded {count} players. Search available in Player Search tab.")

    def _show_error(self, msg):
        self.status_var.set("Error fetching data.")
        messagebox.showerror("Error", f"Failed to fetch data:\n{msg}")

    # ── Column Sorting ────────────────────────────────────────────

    def _sort_column(self, col):
        items = [(self.tree.set(item, col), item) for item in self.tree.get_children("")]

        if col in NUMERIC_COLUMNS:
            def sort_key(val):
                try:
                    return float(val[0])
                except (ValueError, TypeError):
                    return -1
        else:
            def sort_key(val):
                return val[0].lower()

        reverse = self.sort_reverse.get(col, False)
        items.sort(key=sort_key, reverse=reverse)
        self.sort_reverse[col] = not reverse

        for idx, (_, item) in enumerate(items):
            self.tree.move(item, "", idx)
            tag = "even" if idx % 2 == 0 else "odd"
            self.tree.item(item, tags=(tag,))

        direction = " v" if reverse else " ^"
        for c in COLUMNS:
            heading = COLUMNS[c][0]
            if c == col:
                heading += direction
            self.tree.heading(c, text=heading)


def main():
    root = tk.Tk()
    FantasyFootballApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
