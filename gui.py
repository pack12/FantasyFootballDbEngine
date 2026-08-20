import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import threading
from fantasy_football.player_db import PlayerDatabase


RANKING_COLUMNS = [
    ("rank", "Rank", 50),
    ("name", "Player", 180),
    ("position", "Pos", 50),
    ("team", "Team", 55),
    ("gp", "GP", 45),
    ("gm", "GM", 45),
    ("points", "Points", 75),
    ("pts_g", "Pts/G", 65),
    ("avg_pts_g_3yr", "Car Pts/G", 80),
    ("avg_pts_3yr", "Car Pts", 75),
    ("seasons", "Szns", 50),
    ("gm_3yr", "Car GM", 60),
    ("rel_score", "RelScr", 70),
    ("breakout", "BRK", 50),
    ("col_score", "ColScr", 65),
]

TEXT_COLUMNS = {"name", "position", "team", "breakout"}


class FantasyFootballApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Fantasy Football db Engine")
        self.root.geometry("1200x750")
        self.sort_reverse = {}
        self.cached_players = []
        self.db = PlayerDatabase()

        self._build_status_bar()
        self._build_notebook()

        # Auto-load player database on startup
        self._start_db_load()

    def _start_db_load(self, force_refresh=False):
        if force_refresh:
            import os
            from fantasy_football.player_db import SEASONS_CSV, COLLEGE_CSV, META_FILE, _DATA_DIR
            for f in (SEASONS_CSV, COLLEGE_CSV, META_FILE):
                if os.path.exists(f):
                    os.remove(f)
            # Remove any leftover data dir contents
            if os.path.isdir(_DATA_DIR):
                for fname in os.listdir(_DATA_DIR):
                    os.remove(os.path.join(_DATA_DIR, fname))
            self.db = PlayerDatabase()

        self.status_var.set("Loading player data...")
        self.root.update_idletasks()

        def on_progress(msg):
            self.root.after(0, lambda: self.status_var.set(msg))

        def on_complete(msg):
            self.root.after(0, lambda: self.status_var.set(msg))
            self.root.after(0, lambda: self.search_status_label.config(
                text=f"({len(self.db.players)} players loaded)", bootstyle="success"))
            self.root.after(0, lambda: self.rankings_status_label.config(
                text="Ready", bootstyle="success"))

        self.db.set_callbacks(on_progress=on_progress, on_complete=on_complete)
        thread = threading.Thread(target=self.db.load, daemon=True)
        thread.start()

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

        ttk.Label(frame, text="Year:", bootstyle="light").pack(side=tk.LEFT, padx=(0, 5))
        self.year_var = tk.StringVar(value="2025")
        years = [str(y) for y in range(2025, 1998, -1)]
        ttk.Combobox(frame, textvariable=self.year_var, width=6,
                     values=years, state="readonly", bootstyle="info").pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(frame, text="Position:", bootstyle="light").pack(side=tk.LEFT, padx=(0, 5))
        self.pos_var = tk.StringVar(value="ALL")
        ttk.Combobox(frame, textvariable=self.pos_var, width=5,
                     values=["ALL", "QB", "RB", "WR", "TE"], state="readonly", bootstyle="info").pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(frame, text="Limit:", bootstyle="light").pack(side=tk.LEFT, padx=(0, 5))
        self.limit_var = tk.StringVar(value="50")
        ttk.Entry(frame, textvariable=self.limit_var, width=5, bootstyle="info").pack(side=tk.LEFT, padx=(0, 15))

        ttk.Button(frame, text="Show Rankings", command=self._on_fetch,
                   bootstyle="success").pack(side=tk.LEFT, padx=(10, 0))

        ttk.Button(frame, text="Refresh from nflverse",
                   command=self._on_refresh, bootstyle="warning-outline").pack(side=tk.LEFT, padx=(10, 0))

        self.rankings_status_label = ttk.Label(frame, text="(waiting for database...)",
                                                bootstyle="secondary")
        self.rankings_status_label.pack(side=tk.LEFT, padx=(10, 0))

    def _build_table(self, parent):
        container = ttk.Frame(parent)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))

        self.current_columns = {col_id: (heading, width) for col_id, heading, width in RANKING_COLUMNS}
        col_ids = [c[0] for c in RANKING_COLUMNS]

        scrollbar_y = ttk.Scrollbar(container, orient=tk.VERTICAL)
        scrollbar_x = ttk.Scrollbar(container, orient=tk.HORIZONTAL)

        self.tree = ttk.Treeview(container, columns=col_ids, show="headings",
                                 yscrollcommand=scrollbar_y.set,
                                 xscrollcommand=scrollbar_x.set)

        scrollbar_y.config(command=self.tree.yview)
        scrollbar_x.config(command=self.tree.xview)

        for col_id, heading, width in RANKING_COLUMNS:
            self.tree.heading(col_id, text=heading,
                              command=lambda c=col_id: self._sort_column(c))
            anchor = tk.W if col_id == "name" else tk.CENTER
            self.tree.column(col_id, width=width, anchor=anchor, minwidth=40)
            self.sort_reverse[col_id] = False

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)

        self.tree.tag_configure("even", background="#2a2d2e")
        self.tree.tag_configure("odd", background="#222529")

    # ── Player Search Tab ─────────────────────────────────────────

    def _build_search_tab(self):
        # Search bar
        search_frame = ttk.Frame(self.search_tab, padding=10)
        search_frame.pack(fill=tk.X)

        ttk.Label(search_frame, text="Search Player:", bootstyle="light").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=30, bootstyle="info")
        search_entry.pack(side=tk.LEFT, padx=(0, 10))
        search_entry.bind("<KeyRelease>", lambda e: self._on_search())

        self.search_status_label = ttk.Label(search_frame, text="(loading player database...)",
                                              bootstyle="secondary")
        self.search_status_label.pack(side=tk.LEFT)

        # Split: player list on left, detail on right
        paned = ttk.Panedwindow(self.search_tab, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Left: matching players list
        list_frame = ttk.LabelFrame(paned, text="Matching Players", padding=5)
        paned.add(list_frame, weight=1)

        list_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.match_listbox = tk.Listbox(list_frame, yscrollcommand=list_scroll.set, font=("Courier", 12),
                                         bg="#2a2d2e", fg="#e0e0e0", selectbackground="#375a7f",
                                         selectforeground="#ffffff", highlightthickness=0, bd=0)
        list_scroll.config(command=self.match_listbox.yview)
        self.match_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.match_listbox.bind("<<ListboxSelect>>", self._on_player_select)

        # Right: player detail
        detail_frame = ttk.LabelFrame(paned, text="Player Details", padding=5)
        paned.add(detail_frame, weight=2)

        self.detail_text = tk.Text(detail_frame, wrap=tk.WORD, font=("Courier", 13),
                                   state=tk.DISABLED, bg="#222529", fg="#e0e0e0",
                                   insertbackground="#e0e0e0", highlightthickness=0, bd=0)
        self.detail_text.pack(fill=tk.BOTH, expand=True)

    def _on_search(self):
        if not self.db.loaded:
            return

        self.search_status_label.config(text="")
        query = self.search_var.get().strip()
        self.match_listbox.delete(0, tk.END)
        self._search_results = []

        if not query:
            return

        results = self.db.search(query, limit=30)
        self._search_results = results

        for player in results:
            num_seasons = len(player.seasons)
            years = f"{player.seasons[0].year}-{player.seasons[-1].year}" if num_seasons > 1 else str(player.seasons[0].year)
            career_pts = player.career_pts_g
            pts_str = f"{career_pts:.1f} pts/g" if career_pts else ""
            self.match_listbox.insert(
                tk.END,
                f"{player.name:<22} {player.position:<3} {player.current_team:<4} {num_seasons}szn  {pts_str}"
            )

    def _on_player_select(self, event):
        selection = self.match_listbox.curselection()
        if not selection or not self._search_results:
            return

        player = self._search_results[selection[0]]

        # Fetch age + college on-demand in background
        def fetch_and_show():
            self.db.fetch_player_details(player.player_id)
            self.root.after(0, lambda: self._show_player_detail(player))

        threading.Thread(target=fetch_and_show, daemon=True).start()

    def _show_player_detail(self, p):
        lines = []
        lines.append(f"{'=' * 55}")
        lines.append(f"  {p.name}")
        lines.append(f"{'=' * 55}")
        lines.append("")

        # Basic info
        lines.append(f"  Position:    {p.position}")
        lines.append(f"  Team:        {p.current_team}")
        age_str = str(p.age) if p.age else "N/A"
        lines.append(f"  Age:         {age_str}")
        lines.append(f"  NFL Seasons: {len(p.seasons)}")
        lines.append("")

        # Career summary
        lines.append(f"  ── Career Summary {'─' * 35}")
        lines.append(f"  Total Fantasy Pts: {p.career_total_pts:.1f}")
        career_pg = p.career_pts_g
        lines.append(f"  Career Pts/Game:   {career_pg:.1f}" if career_pg else "  Career Pts/Game:   N/A")
        lines.append(f"  Total Games:       {p.total_games}")
        lines.append(f"  Total Games Missed:{p.total_games_missed}")
        rel = p.reliability_score
        lines.append(f"  Reliability Score: {rel:.1f}" if rel else "  Reliability Score: N/A")
        if p.breakout:
            lines.append(f"  Breakout:          YES")
        lines.append("")

        # Season-by-season table
        sorted_seasons = sorted(p.seasons, key=lambda s: s.year, reverse=True)

        if p.position == "QB":
            lines.append(f"  ── Season-by-Season {'─' * 33}")
            lines.append(f"  {'Year':<6} {'Team':<5} {'GP':<4} {'PaYds':<7} {'PaTD':<5} {'INT':<4} "
                         f"{'RuYds':<7} {'RuTD':<5} {'Fum':<4} {'Pts':<8} {'Pts/G'}")
            lines.append(f"  {'─' * 70}")
            for s in sorted_seasons:
                st = s.stats
                lines.append(f"  {s.year:<6} {s.team:<5} {st.games_played:<4} "
                             f"{st.passing_yards:<7.0f} {st.passing_tds:<5} {st.interceptions:<4} "
                             f"{st.rushing_yards:<7.0f} {st.rushing_tds:<5} {st.fumbles_lost:<4} "
                             f"{s.fantasy_points:<8.1f} {s.pts_per_game:.1f}")
        else:
            lines.append(f"  ── Season-by-Season {'─' * 33}")
            lines.append(f"  {'Year':<6} {'Team':<5} {'GP':<4} {'Rec':<5} {'RecYds':<8} {'RecTD':<6} "
                         f"{'RuAtt':<6} {'RuYds':<8} {'RuTD':<5} {'Fum':<4} {'Pts':<8} {'Pts/G'}")
            lines.append(f"  {'─' * 78}")
            for s in sorted_seasons:
                st = s.stats
                lines.append(f"  {s.year:<6} {s.team:<5} {st.games_played:<4} "
                             f"{st.receptions:<5} {st.receiving_yards:<8.0f} {st.receiving_tds:<6} "
                             f"{st.rushing_attempts:<6} {st.rushing_yards:<8.0f} {st.rushing_tds:<5} "
                             f"{st.fumbles_lost:<4} {s.fantasy_points:<8.1f} {s.pts_per_game:.1f}")

        lines.append("")

        # College data
        if p.college_dom_score is not None:
            lines.append(f"  ── College {'─' * 42}")
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
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN,
                  anchor=tk.W, padding=5).pack(fill=tk.X, side=tk.BOTTOM)

    def _on_refresh(self):
        if not self.db.loaded:
            messagebox.showinfo("Please Wait", "Database is still loading.")
            return
        result = messagebox.askyesno("Refresh Data",
                                      "This will re-fetch all data from nflverse.\nThis may take a moment.\n\nContinue?")
        if result:
            self.tree.delete(*self.tree.get_children())
            self.rankings_status_label.config(text="(refreshing...)", bootstyle="warning")
            thread = threading.Thread(target=lambda: self._start_db_load(force_refresh=True), daemon=True)
            thread.start()

    # ── Rankings Data ───────────────────────────────────────────

    def _on_fetch(self):
        if not self.db.loaded:
            messagebox.showinfo("Please Wait", "Player database is still loading.")
            return

        try:
            year = int(self.year_var.get())
            limit = int(self.limit_var.get())
        except ValueError:
            messagebox.showerror("Input Error", "Year and Limit must be numbers.")
            return

        pos = self.pos_var.get()

        # Find all players who have a season for the selected year
        ranked = []
        for record in self.db.players.values():
            if pos != "ALL" and record.position != pos:
                continue
            season = next((s for s in record.seasons if s.year == year), None)
            if not season:
                continue
            ranked.append((record, season))

        # Sort by fantasy points for that season (descending)
        ranked.sort(key=lambda x: x[1].fantasy_points, reverse=True)
        ranked = ranked[:limit]

        rows = []
        for i, (record, season) in enumerate(ranked, 1):
            rel = record.reliability_score
            col_scr = record.college_dom_score

            rows.append((
                i,
                record.name,
                record.position,
                record.current_team,
                season.stats.games_played,
                17 - season.stats.games_played,
                round(season.fantasy_points, 2),
                season.pts_per_game,
                record.career_pts_g if record.career_pts_g else "--",
                record.career_total_pts,
                len(record.seasons),
                record.total_games_missed,
                round(rel, 1) if rel is not None else "--",
                "YES" if record.breakout else "",
                round(col_scr, 1) if col_scr is not None else "--",
            ))

        self._populate_table(rows, len(rows))

    def _populate_table(self, rows, count):
        self.tree.delete(*self.tree.get_children())
        for idx, row in enumerate(rows):
            tag = "even" if idx % 2 == 0 else "odd"
            self.tree.insert("", tk.END, values=row, tags=(tag,))
        self.status_var.set(f"Loaded {count} players.")

    # ── Column Sorting ────────────────────────────────────────────

    def _sort_column(self, col):
        items = [(self.tree.set(item, col), item) for item in self.tree.get_children("")]

        is_numeric = col not in TEXT_COLUMNS
        if is_numeric:
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
        for c in self.current_columns:
            heading = self.current_columns[c][0]
            if c == col:
                heading += direction
            self.tree.heading(c, text=heading)


def main():
    root = ttk.Window(themename="darkly")
    FantasyFootballApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
