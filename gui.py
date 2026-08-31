import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import threading
from fantasy_football.player_db import PlayerDatabase, games_in_season, BIRTHS_CSV, ROOKIES_CSV


RANKING_COLUMNS = [
    ("rank", "Rank", 50),
    ("name", "Player", 180),
    ("age", "Age", 45),
    ("position", "Pos", 50),
    ("team", "Team", 55),
    ("gp", "GP", 45),
    ("gm", "GM", 45),
    ("points", "Points", 75),
    ("pts_g", "Pts/G", 65),
    ("avg_pts_g_3yr", "Car Pts/G", 80),
    ("avg_pts_3yr", "Car Pts", 75),
    ("season_num", "Yr#", 45),
    ("seasons", "Szns", 50),
    ("gm_3yr", "Car GM", 60),
    ("szn_rel", "SznRel", 70),
    ("raw_rel", "RelScr", 70),
    ("rel_score", "AdjRel", 70),
    ("breakout", "BRK", 50),
    ("col_score", "ColScr", 65),
]

TEXT_COLUMNS = {"name", "position", "team", "breakout"}

ROOKIE_COLUMNS = [
    ("rank", "Rank", 50),
    ("name", "Player", 180),
    ("position", "Pos", 50),
    ("team", "Team", 55),
    ("draft_rd", "Rd", 40),
    ("draft_pick", "Pick", 50),
    ("col_score", "ColScr", 70),
    ("proj_pts_g", "Proj Pts/G", 90),
    ("comp", "Comp Player", 180),
    ("college_year", "College Stats", 300),
]

ROOKIE_TEXT_COLS = {"name", "position", "team", "comp", "college_year"}


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
            for f in (SEASONS_CSV, COLLEGE_CSV, BIRTHS_CSV, ROOKIES_CSV, META_FILE):
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
            self.root.after(0, self._update_compare_players)

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

        # Tab 3: Compare
        self.compare_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.compare_tab, text="  Compare  ")
        self._build_compare_tab()

        # Tab 4: Rookies
        self.rookies_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.rookies_tab, text="  2026 Rookies  ")
        self._build_rookies_tab()

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
        raw_rel = p.raw_reliability_score
        rel = p.reliability_score
        lines.append(f"  Reliability Score: {raw_rel:.1f}" if raw_rel else "  Reliability Score: N/A")
        lines.append(f"  Age-Adj RelScore:  {rel:.1f}" if rel else "  Age-Adj RelScore:  N/A")
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

    # ── Compare Tab ────────────────────────────────────────────────

    def _build_compare_tab(self):
        # Controls row 1: position
        row1 = ttk.Frame(self.compare_tab, padding=(10, 10, 10, 0))
        row1.pack(fill=tk.X)

        ttk.Label(row1, text="Position:", bootstyle="light").pack(side=tk.LEFT, padx=(0, 5))
        self.cmp_pos_var = tk.StringVar(value="RB")
        cmp_pos_combo = ttk.Combobox(row1, textvariable=self.cmp_pos_var, width=5,
                     values=["QB", "RB", "WR", "TE"], state="readonly", bootstyle="info")
        cmp_pos_combo.pack(side=tk.LEFT, padx=(0, 15))
        cmp_pos_combo.bind("<<ComboboxSelected>>", lambda e: self._update_compare_players())

        ttk.Button(row1, text="Compare", command=self._on_compare,
                   bootstyle="success").pack(side=tk.LEFT, padx=(10, 0))

        # Controls row 2: player search boxes side by side
        row2 = ttk.Frame(self.compare_tab, padding=(10, 5, 10, 5))
        row2.pack(fill=tk.X)

        # Player 1 search
        p1_frame = ttk.LabelFrame(row2, text="Player 1", padding=5, bootstyle="info")
        p1_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self.cmp_p1_search_var = tk.StringVar()
        p1_entry = ttk.Entry(p1_frame, textvariable=self.cmp_p1_search_var, bootstyle="info")
        p1_entry.pack(fill=tk.X)
        p1_entry.bind("<KeyRelease>", lambda e: self._filter_compare_list(1))

        self.cmp_p1_listbox = tk.Listbox(p1_frame, height=6, bg="#222529", fg="#e0e0e0",
                                          selectbackground="#375a7f", highlightthickness=0, bd=1,
                                          exportselection=False)
        self.cmp_p1_listbox.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        self.cmp_p1_listbox.bind("<<ListboxSelect>>", lambda e: self._on_cmp_player_select(1))

        self.cmp_p1_selected_var = tk.StringVar(value="No player selected")
        ttk.Label(p1_frame, textvariable=self.cmp_p1_selected_var,
                  bootstyle="success", font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W, pady=(3, 0))

        # Player 2 search
        p2_frame = ttk.LabelFrame(row2, text="Player 2", padding=5, bootstyle="info")
        p2_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        self.cmp_p2_search_var = tk.StringVar()
        p2_entry = ttk.Entry(p2_frame, textvariable=self.cmp_p2_search_var, bootstyle="info")
        p2_entry.pack(fill=tk.X)
        p2_entry.bind("<KeyRelease>", lambda e: self._filter_compare_list(2))

        self.cmp_p2_listbox = tk.Listbox(p2_frame, height=6, bg="#222529", fg="#e0e0e0",
                                          selectbackground="#375a7f", highlightthickness=0, bd=1,
                                          exportselection=False)
        self.cmp_p2_listbox.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        self.cmp_p2_listbox.bind("<<ListboxSelect>>", lambda e: self._on_cmp_player_select(2))

        self.cmp_p2_selected_var = tk.StringVar(value="No player selected")
        ttk.Label(p2_frame, textvariable=self.cmp_p2_selected_var,
                  bootstyle="success", font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W, pady=(3, 0))

        # Detail area
        self.compare_text = tk.Text(self.compare_tab, wrap=tk.NONE, font=("Courier", 12),
                                     state=tk.DISABLED, bg="#222529", fg="#e0e0e0",
                                     insertbackground="#e0e0e0", highlightthickness=0, bd=0)
        cmp_scroll_y = ttk.Scrollbar(self.compare_tab, orient=tk.VERTICAL, command=self.compare_text.yview)
        cmp_scroll_x = ttk.Scrollbar(self.compare_tab, orient=tk.HORIZONTAL, command=self.compare_text.xview)
        self.compare_text.config(yscrollcommand=cmp_scroll_y.set, xscrollcommand=cmp_scroll_x.set)
        cmp_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        cmp_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.compare_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Store player lists and locked-in selections
        self._cmp_players = []
        self._cmp_filtered_1 = []
        self._cmp_filtered_2 = []
        self._cmp_selected_1 = None  # PlayerRecord
        self._cmp_selected_2 = None

    def _update_compare_players(self):
        """Update player lists based on selected position."""
        if not self.db.loaded:
            return
        pos = self.cmp_pos_var.get()
        players = [p for p in self.db.players.values() if p.position == pos]
        players.sort(key=lambda p: p.career_total_pts, reverse=True)
        self._cmp_players = players
        self.cmp_p1_search_var.set("")
        self.cmp_p2_search_var.set("")
        self._filter_compare_list(1)
        self._filter_compare_list(2)

    def _filter_compare_list(self, player_num: int):
        """Filter the player listbox as user types."""
        if player_num == 1:
            query = self.cmp_p1_search_var.get().strip().lower()
            listbox = self.cmp_p1_listbox
        else:
            query = self.cmp_p2_search_var.get().strip().lower()
            listbox = self.cmp_p2_listbox

        listbox.delete(0, tk.END)

        if not query:
            filtered = self._cmp_players[:]
        else:
            filtered = [p for p in self._cmp_players if query in p.name.lower()]

        if player_num == 1:
            self._cmp_filtered_1 = filtered
        else:
            self._cmp_filtered_2 = filtered

        for p in filtered:
            listbox.insert(tk.END, f"{p.name} ({p.current_team})")

    def _on_cmp_player_select(self, player_num: int):
        """Lock in the selected player and show their name."""
        if player_num == 1:
            sel = self.cmp_p1_listbox.curselection()
            if sel and sel[0] < len(self._cmp_filtered_1):
                player = self._cmp_filtered_1[sel[0]]
                self._cmp_selected_1 = player
                self.cmp_p1_selected_var.set(f">> {player.name} ({player.current_team})")
        else:
            sel = self.cmp_p2_listbox.curselection()
            if sel and sel[0] < len(self._cmp_filtered_2):
                player = self._cmp_filtered_2[sel[0]]
                self._cmp_selected_2 = player
                self.cmp_p2_selected_var.set(f">> {player.name} ({player.current_team})")

    def _on_compare(self):
        if not self.db.loaded:
            return
        if not self._cmp_players:
            self._update_compare_players()

        p1 = self._cmp_selected_1
        p2 = self._cmp_selected_2
        if not p1 or not p2:
            return
        if p1.player_id == p2.player_id:
            return

        lines = self._build_comparison(p1, p2)

        self.compare_text.config(state=tk.NORMAL)
        self.compare_text.delete("1.0", tk.END)
        self.compare_text.insert("1.0", "\n".join(lines))
        self.compare_text.config(state=tk.DISABLED)

    def _build_comparison(self, p1, p2):
        """Build side-by-side comparison text for two players."""
        W = 30  # column width
        lines = []

        def row(label, v1, v2, highlight=True):
            """Add a comparison row. Highlight the better value if numeric."""
            s1 = str(v1) if v1 is not None else "N/A"
            s2 = str(v2) if v2 is not None else "N/A"
            marker1 = marker2 = " "
            if highlight and v1 is not None and v2 is not None:
                try:
                    f1, f2 = float(v1), float(v2)
                    if f1 > f2:
                        marker1 = "+"
                    elif f2 > f1:
                        marker2 = "+"
                except (ValueError, TypeError):
                    pass
            lines.append(f"  {label:<18} {marker1}{s1:>{W-1}}    {marker2}{s2:>{W-1}}")

        def row_lower(label, v1, v2):
            """Like row() but lower is better (e.g., games missed, fumbles)."""
            s1 = str(v1) if v1 is not None else "N/A"
            s2 = str(v2) if v2 is not None else "N/A"
            marker1 = marker2 = " "
            if v1 is not None and v2 is not None:
                try:
                    f1, f2 = float(v1), float(v2)
                    if f1 < f2:
                        marker1 = "+"
                    elif f2 < f1:
                        marker2 = "+"
                except (ValueError, TypeError):
                    pass
            lines.append(f"  {label:<18} {marker1}{s1:>{W-1}}    {marker2}{s2:>{W-1}}")

        # Header
        lines.append(f"  {'':18} {p1.name:>{W}}    {p2.name:>{W}}")
        lines.append(f"  {'=' * (18 + W * 2 + 6)}")
        lines.append("")

        # Basic info
        lines.append(f"  {'── Profile ──':18} {'':>{W}}    {'':>{W}}")
        row("Team", p1.current_team, p2.current_team, highlight=False)
        row("Age", p1.age, p2.age, highlight=False)
        row("Seasons", len(p1.seasons), len(p2.seasons))
        lines.append("")

        # Career stats
        lines.append(f"  {'── Career ──':18} {'':>{W}}    {'':>{W}}")
        row("Total Pts", f"{p1.career_total_pts:.1f}", f"{p2.career_total_pts:.1f}")
        row("Career Pts/G", f"{p1.career_pts_g:.1f}" if p1.career_pts_g else None,
            f"{p2.career_pts_g:.1f}" if p2.career_pts_g else None)
        row("Total Games", p1.total_games, p2.total_games)
        row_lower("Games Missed", p1.total_games_missed, p2.total_games_missed)
        row("RelScr", f"{p1.raw_reliability_score:.1f}" if p1.raw_reliability_score else None,
            f"{p2.raw_reliability_score:.1f}" if p2.raw_reliability_score else None)
        row("AdjRel", f"{p1.reliability_score:.1f}" if p1.reliability_score else None,
            f"{p2.reliability_score:.1f}" if p2.reliability_score else None)
        lines.append("")

        # Find overlapping years
        p1_years = {s.year: s for s in p1.seasons}
        p2_years = {s.year: s for s in p2.seasons}
        all_years = sorted(set(p1_years.keys()) | set(p2_years.keys()), reverse=True)

        # Season-by-season comparison
        if p1.position == "QB":
            lines.append(f"  {'── Season-by-Season ──'}")
            lines.append(f"  {'Year':<6} {'':>{W}}    {'':>{W}}")
            lines.append(f"  {'─' * (18 + W * 2 + 6)}")
            for yr in all_years:
                s1 = p1_years.get(yr)
                s2 = p2_years.get(yr)
                lines.append(f"  {yr}")
                row("  GP",
                    s1.stats.games_played if s1 else None,
                    s2.stats.games_played if s2 else None)
                row("  Pass Yds",
                    f"{s1.stats.passing_yards:.0f}" if s1 else None,
                    f"{s2.stats.passing_yards:.0f}" if s2 else None)
                row("  Pass TD",
                    s1.stats.passing_tds if s1 else None,
                    s2.stats.passing_tds if s2 else None)
                row_lower("  INT",
                    s1.stats.interceptions if s1 else None,
                    s2.stats.interceptions if s2 else None)
                row("  Rush Yds",
                    f"{s1.stats.rushing_yards:.0f}" if s1 else None,
                    f"{s2.stats.rushing_yards:.0f}" if s2 else None)
                row("  Pts",
                    f"{s1.fantasy_points:.1f}" if s1 else None,
                    f"{s2.fantasy_points:.1f}" if s2 else None)
                row("  Pts/G",
                    f"{s1.pts_per_game:.1f}" if s1 else None,
                    f"{s2.pts_per_game:.1f}" if s2 else None)
                lines.append("")
        else:
            lines.append(f"  {'── Season-by-Season ──'}")
            lines.append(f"  {'─' * (18 + W * 2 + 6)}")
            for yr in all_years:
                s1 = p1_years.get(yr)
                s2 = p2_years.get(yr)
                lines.append(f"  {yr}")
                row("  GP",
                    s1.stats.games_played if s1 else None,
                    s2.stats.games_played if s2 else None)
                row("  Rec",
                    s1.stats.receptions if s1 else None,
                    s2.stats.receptions if s2 else None)
                row("  Rec Yds",
                    f"{s1.stats.receiving_yards:.0f}" if s1 else None,
                    f"{s2.stats.receiving_yards:.0f}" if s2 else None)
                row("  Rec TD",
                    s1.stats.receiving_tds if s1 else None,
                    s2.stats.receiving_tds if s2 else None)
                row("  Rush Att",
                    s1.stats.rushing_attempts if s1 else None,
                    s2.stats.rushing_attempts if s2 else None)
                row("  Rush Yds",
                    f"{s1.stats.rushing_yards:.0f}" if s1 else None,
                    f"{s2.stats.rushing_yards:.0f}" if s2 else None)
                row("  Rush TD",
                    s1.stats.rushing_tds if s1 else None,
                    s2.stats.rushing_tds if s2 else None)
                row("  Pts",
                    f"{s1.fantasy_points:.1f}" if s1 else None,
                    f"{s2.fantasy_points:.1f}" if s2 else None)
                row("  Pts/G",
                    f"{s1.pts_per_game:.1f}" if s1 else None,
                    f"{s2.pts_per_game:.1f}" if s2 else None)
                lines.append("")

        return lines

    # ── Rookies Tab ───────────────────────────────────────────────

    def _build_rookies_tab(self):
        # Controls
        frame = ttk.Frame(self.rookies_tab, padding=10)
        frame.pack(fill=tk.X)

        ttk.Label(frame, text="Position:", bootstyle="light").pack(side=tk.LEFT, padx=(0, 5))
        self.rookie_pos_var = tk.StringVar(value="ALL")
        ttk.Combobox(frame, textvariable=self.rookie_pos_var, width=5,
                     values=["ALL", "QB", "RB", "WR", "TE"], state="readonly",
                     bootstyle="info").pack(side=tk.LEFT, padx=(0, 15))

        ttk.Button(frame, text="Show Rookies", command=self._on_show_rookies,
                   bootstyle="success").pack(side=tk.LEFT, padx=(10, 0))

        self.compare_vets_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Compare with Veterans", variable=self.compare_vets_var,
                        bootstyle="info-round-toggle").pack(side=tk.LEFT, padx=(15, 0))

        self.rookie_status_label = ttk.Label(frame, text="", bootstyle="secondary")
        self.rookie_status_label.pack(side=tk.LEFT, padx=(10, 0))

        # Table
        container = ttk.Frame(self.rookies_tab)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))

        col_ids = [c[0] for c in ROOKIE_COLUMNS]
        scrollbar_y = ttk.Scrollbar(container, orient=tk.VERTICAL)
        self.rookie_tree = ttk.Treeview(container, columns=col_ids, show="headings",
                                         yscrollcommand=scrollbar_y.set)
        scrollbar_y.config(command=self.rookie_tree.yview)

        for col_id, heading, width in ROOKIE_COLUMNS:
            self.rookie_tree.heading(col_id, text=heading,
                                     command=lambda c=col_id: self._sort_rookie_column(c))
            anchor = tk.W if col_id in ("name", "comp", "college_year") else tk.CENTER
            self.rookie_tree.column(col_id, width=width, anchor=anchor, minwidth=40)

        self.rookie_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)

        self.rookie_tree.tag_configure("rookie", background="#1a3a2a")
        self.rookie_tree.tag_configure("vet_even", background="#2a2d2e")
        self.rookie_tree.tag_configure("vet_odd", background="#222529")
        self.rookie_sort_reverse = {}

    def _on_show_rookies(self):
        if not self.db.loaded:
            self.rookie_status_label.config(text="Database still loading...")
            return

        pos = self.rookie_pos_var.get()
        projections = self.db.rookie_projections

        if not projections:
            self.rookie_status_label.config(text="No 2026 rookie data available")
            return

        if pos != "ALL":
            projections = [r for r in projections if r.position == pos]

        # Build rows: rookies
        rows = []
        for r in projections:
            rows.append({
                "name": r.name,
                "position": r.position,
                "team": r.team,
                "draft_rd": r.draft_round if r.draft_round else "--",
                "draft_pick": r.draft_number if r.draft_number else "--",
                "col_score": round(r.college_dom_score, 1) if r.college_dom_score else "--",
                "proj_pts_g": r.projected_pts_g if r.projected_pts_g else "--",
                "comp": r.comp_name,
                "college_year": r.college_final_year,
                "sort_key": r.projected_pts_g or 0,
                "is_rookie": True,
            })

        # Optionally add veterans for comparison
        if self.compare_vets_var.get():
            for record in self.db.players.values():
                if pos != "ALL" and record.position != pos:
                    continue
                rel = record.raw_reliability_score
                if rel is None:
                    continue
                rows.append({
                    "name": record.name,
                    "position": record.position,
                    "team": record.current_team,
                    "draft_rd": "",
                    "draft_pick": "",
                    "col_score": "",
                    "proj_pts_g": rel,
                    "comp": f"{len(record.seasons)} seasons",
                    "college_year": "",
                    "sort_key": rel,
                    "is_rookie": False,
                })

        # Sort by projected pts/g
        rows.sort(key=lambda r: r["sort_key"], reverse=True)

        # Populate tree
        self.rookie_tree.delete(*self.rookie_tree.get_children())
        vet_idx = 0
        for i, row in enumerate(rows, 1):
            if row["is_rookie"]:
                tag = "rookie"
            else:
                tag = "vet_even" if vet_idx % 2 == 0 else "vet_odd"
                vet_idx += 1

            self.rookie_tree.insert("", tk.END, values=(
                i, row["name"], row["position"], row["team"],
                row["draft_rd"], row["draft_pick"], row["col_score"],
                row["proj_pts_g"], row["comp"], row["college_year"],
            ), tags=(tag,))

        rookie_count = sum(1 for r in rows if r["is_rookie"])
        vet_count = sum(1 for r in rows if not r["is_rookie"])
        status = f"{rookie_count} rookies"
        if vet_count:
            status += f" + {vet_count} veterans (using RelScr for comparison)"
        self.rookie_status_label.config(text=status)

    def _sort_rookie_column(self, col):
        items = [(self.rookie_tree.set(item, col), item) for item in self.rookie_tree.get_children("")]
        is_numeric = col not in ROOKIE_TEXT_COLS
        if is_numeric:
            def sort_key(val):
                try:
                    return float(val[0])
                except (ValueError, TypeError):
                    return -1
        else:
            def sort_key(val):
                return val[0].lower()
        reverse = self.rookie_sort_reverse.get(col, False)
        items.sort(key=sort_key, reverse=reverse)
        self.rookie_sort_reverse[col] = not reverse
        for idx, (_, item) in enumerate(items):
            self.rookie_tree.move(item, "", idx)

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

        # Sort by Pts/G for that season (descending)
        ranked.sort(key=lambda x: x[1].pts_per_game, reverse=True)
        ranked = ranked[:limit]

        rows = []
        for i, (record, season) in enumerate(ranked, 1):
            szn_rel = record.season_reliability_score
            raw_rel = record.raw_reliability_score_for_year(year)
            rel = record.reliability_score_for_year(year)
            col_scr = record.college_dom_score
            age = record.age if record.age is not None else "--"

            sorted_yrs = sorted(s.year for s in record.seasons)
            season_num = sorted_yrs.index(year) + 1 if year in sorted_yrs else "--"

            rows.append((
                i,
                record.name,
                age,
                record.position,
                record.current_team,
                season.stats.games_played,
                games_in_season(int(self.year_var.get())) - season.stats.games_played,
                round(season.fantasy_points, 2),
                season.pts_per_game,
                record.career_pts_g if record.career_pts_g else "--",
                record.career_total_pts,
                season_num,
                len(record.seasons),
                record.total_games_missed,
                round(szn_rel, 1) if szn_rel is not None else "--",
                round(raw_rel, 1) if raw_rel is not None else "--",
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
