"""
CSV Editor for seasons.csv — view, add, edit, delete, and merge player season records.
Useful for fixing missing seasons, correcting stats, and merging duplicate player entries
(e.g., when ESPN and nflverse have different names for the same player).
"""

import csv
import os
import tkinter as tk
from tkinter import ttk, messagebox

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SEASONS_CSV = os.path.join(DATA_DIR, "seasons.csv")

SEASON_COLS = [
    "player_id", "name", "position", "team", "year",
    "passing_yards", "passing_tds", "interceptions", "passing_attempts", "passing_completions",
    "rushing_yards", "rushing_tds", "receptions", "receiving_yards", "receiving_tds",
    "fumbles_lost", "two_point_conversions", "rushing_attempts", "targets", "games_played",
]

# Fields the user edits (field_name, display_label, type)
EDITABLE_FIELDS = [
    ("year", "Year", int),
    ("team", "Team", str),
    ("position", "Pos", str),
    ("games_played", "Games", int),
    ("passing_yards", "Pass Yds", float),
    ("passing_tds", "Pass TDs", int),
    ("interceptions", "INTs", int),
    ("passing_attempts", "Pass Att", int),
    ("passing_completions", "Pass Cmp", int),
    ("rushing_yards", "Rush Yds", float),
    ("rushing_tds", "Rush TDs", int),
    ("rushing_attempts", "Rush Att", int),
    ("receptions", "Rec", int),
    ("receiving_yards", "Rec Yds", float),
    ("receiving_tds", "Rec TDs", int),
    ("targets", "Targets", int),
    ("fumbles_lost", "Fum Lost", int),
    ("two_point_conversions", "2PT", int),
]


def load_seasons_csv() -> list[dict]:
    """Load all rows from seasons.csv."""
    if not os.path.exists(SEASONS_CSV):
        return []
    with open(SEASONS_CSV, "r", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def save_seasons_csv(rows: list[dict]):
    """Save rows back to seasons.csv."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SEASONS_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(SEASON_COLS)
        for row in rows:
            writer.writerow([row.get(col, "") for col in SEASON_COLS])


def get_unique_players(rows: list[dict]) -> list[tuple[str, str, str]]:
    """Get unique (player_id, name, position) tuples sorted by name."""
    players = {}
    for row in rows:
        pid = row.get("player_id", "")
        if pid and pid not in players:
            players[pid] = (pid, row.get("name", ""), row.get("position", ""))
    return sorted(players.values(), key=lambda x: x[1])


class SeasonsCSVEditor:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Seasons CSV Editor")
        self.root.geometry("1200x750")

        self.rows: list[dict] = []
        self.all_players: list[tuple[str, str, str]] = []
        self._selected_pid = ""
        self._matched: list[tuple[str, str, str]] = []

        self._build_ui()
        self._load_data()

    def _build_ui(self):
        # ── Top: Player search ──
        search_frame = ttk.LabelFrame(self.root, text="Player Search")
        search_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        search_row = ttk.Frame(search_frame)
        search_row.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(search_row, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_changed)
        self.search_entry = ttk.Entry(search_row, textvariable=self.search_var, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=(5, 10))

        self.match_listbox = tk.Listbox(search_row, height=5, width=50, exportselection=False)
        self.match_listbox.pack(side=tk.LEFT, padx=(0, 10))
        self.match_listbox.bind("<<ListboxSelect>>", self._on_match_select)

        self.selected_label_var = tk.StringVar(value="None")
        ttk.Label(search_row, text="Selected:").pack(side=tk.LEFT)
        ttk.Label(search_row, textvariable=self.selected_label_var,
                  foreground="green", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=5)

        # Merge button
        ttk.Button(search_row, text="Merge Into Selected...", command=self._merge_player).pack(side=tk.RIGHT, padx=5)

        # ── Middle: Seasons table ──
        table_frame = ttk.LabelFrame(self.root, text="Seasons")
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        display_cols = ("year", "team", "position", "games_played",
                        "passing_yards", "passing_tds", "interceptions",
                        "passing_attempts", "passing_completions",
                        "rushing_yards", "rushing_tds", "rushing_attempts",
                        "receptions", "receiving_yards", "receiving_tds",
                        "targets", "fumbles_lost", "two_point_conversions")
        col_headers = ("Year", "Team", "Pos", "GP",
                       "PassYds", "PassTD", "INT",
                       "PassAtt", "PassCmp",
                       "RushYds", "RushTD", "RushAtt",
                       "Rec", "RecYds", "RecTD",
                       "Tgt", "FumL", "2PT")

        self.tree = ttk.Treeview(table_frame, columns=display_cols, show="headings",
                                 selectmode="browse")

        for col, header in zip(display_cols, col_headers):
            width = 65
            if col == "year":
                width = 50
            elif col == "team" or col == "position":
                width = 45
            self.tree.heading(col, text=header)
            self.tree.column(col, width=width, minwidth=40)

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<<TreeviewSelect>>", self._on_season_select)

        # ── Edit form ──
        form_frame = ttk.LabelFrame(self.root, text="Add / Edit Season")
        form_frame.pack(fill=tk.X, padx=10, pady=5)

        # Row 1: year, team, pos, games
        row1 = ttk.Frame(form_frame)
        row1.pack(fill=tk.X, padx=10, pady=(10, 2))

        self.field_vars: dict[str, tk.StringVar] = {}
        row1_fields = [f for f in EDITABLE_FIELDS if f[0] in ("year", "team", "position", "games_played")]
        for field, label, _ in row1_fields:
            ttk.Label(row1, text=f"{label}:").pack(side=tk.LEFT, padx=(8, 2))
            var = tk.StringVar(value="0" if field != "team" and field != "position" else "")
            self.field_vars[field] = var
            width = 6 if field not in ("team", "position") else 5
            ttk.Entry(row1, textvariable=var, width=width).pack(side=tk.LEFT)

        # Row 2: passing stats
        row2 = ttk.Frame(form_frame)
        row2.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(row2, text="Passing:", font=("TkDefaultFont", 9, "bold")).pack(side=tk.LEFT, padx=(0, 5))
        pass_fields = [f for f in EDITABLE_FIELDS if f[0].startswith("passing") or f[0] == "interceptions"]
        for field, label, _ in pass_fields:
            ttk.Label(row2, text=f"{label}:").pack(side=tk.LEFT, padx=(8, 2))
            var = tk.StringVar(value="0")
            self.field_vars[field] = var
            ttk.Entry(row2, textvariable=var, width=7).pack(side=tk.LEFT)

        # Row 3: rushing stats
        row3 = ttk.Frame(form_frame)
        row3.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(row3, text="Rushing:", font=("TkDefaultFont", 9, "bold")).pack(side=tk.LEFT, padx=(0, 5))
        rush_fields = [f for f in EDITABLE_FIELDS if f[0].startswith("rushing")]
        for field, label, _ in rush_fields:
            ttk.Label(row3, text=f"{label}:").pack(side=tk.LEFT, padx=(8, 2))
            var = tk.StringVar(value="0")
            self.field_vars[field] = var
            ttk.Entry(row3, textvariable=var, width=7).pack(side=tk.LEFT)

        # Row 4: receiving stats + misc
        row4 = ttk.Frame(form_frame)
        row4.pack(fill=tk.X, padx=10, pady=(2, 10))
        ttk.Label(row4, text="Receiving:", font=("TkDefaultFont", 9, "bold")).pack(side=tk.LEFT, padx=(0, 5))
        rec_fields = [f for f in EDITABLE_FIELDS
                      if f[0] in ("receptions", "receiving_yards", "receiving_tds", "targets",
                                  "fumbles_lost", "two_point_conversions")]
        for field, label, _ in rec_fields:
            ttk.Label(row4, text=f"{label}:").pack(side=tk.LEFT, padx=(8, 2))
            var = tk.StringVar(value="0")
            self.field_vars[field] = var
            ttk.Entry(row4, textvariable=var, width=7).pack(side=tk.LEFT)

        # ── Buttons ──
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Button(btn_frame, text="Add Season", command=self._add_season).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Update Selected", command=self._update_season).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Delete Selected", command=self._delete_season).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Save to CSV", command=self._save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Reload", command=self._load_data).pack(side=tk.RIGHT, padx=5)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN,
                  anchor=tk.W).pack(fill=tk.X, side=tk.BOTTOM)

    def _load_data(self):
        """Load CSV data."""
        self.rows = load_seasons_csv()
        self.all_players = get_unique_players(self.rows)
        self.tree.delete(*self.tree.get_children())
        self._selected_pid = ""
        self.selected_label_var.set("None")
        self.status_var.set(f"Loaded {len(self.rows)} season rows, {len(self.all_players)} unique players")

    def _on_search_changed(self, *args):
        """Filter player list as user types."""
        query = self.search_var.get().strip().lower()
        self.match_listbox.delete(0, tk.END)
        if len(query) < 2:
            return
        self._matched = [(pid, name, pos) for pid, name, pos in self.all_players
                         if query in name.lower()][:25]
        for pid, name, pos in self._matched:
            self.match_listbox.insert(tk.END, f"{name}  ({pos})  [{pid}]")

    def _on_match_select(self, event):
        """Select a player and show their seasons."""
        sel = self.match_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._matched):
            pid, name, pos = self._matched[idx]
            self._selected_pid = pid
            self.selected_label_var.set(f"{name} ({pos}) [{pid}]")
            self._show_player_seasons(pid)

    def _show_player_seasons(self, pid: str):
        """Display all seasons for a player in the table."""
        self.tree.delete(*self.tree.get_children())
        self._player_season_indices = []

        for i, row in enumerate(self.rows):
            if row.get("player_id") == pid:
                self._player_season_indices.append(i)
                values = (
                    row.get("year", ""),
                    row.get("team", ""),
                    row.get("position", ""),
                    row.get("games_played", ""),
                    row.get("passing_yards", ""),
                    row.get("passing_tds", ""),
                    row.get("interceptions", ""),
                    row.get("passing_attempts", ""),
                    row.get("passing_completions", ""),
                    row.get("rushing_yards", ""),
                    row.get("rushing_tds", ""),
                    row.get("rushing_attempts", ""),
                    row.get("receptions", ""),
                    row.get("receiving_yards", ""),
                    row.get("receiving_tds", ""),
                    row.get("targets", ""),
                    row.get("fumbles_lost", ""),
                    row.get("two_point_conversions", ""),
                )
                self.tree.insert("", tk.END, iid=str(len(self._player_season_indices) - 1), values=values)

        self.status_var.set(f"Showing {len(self._player_season_indices)} seasons for {self.selected_label_var.get()}")

    def _on_season_select(self, event):
        """Populate form when a season row is selected."""
        sel = self.tree.selection()
        if not sel:
            return
        tree_idx = int(sel[0])
        row_idx = self._player_season_indices[tree_idx]
        row = self.rows[row_idx]

        for field, _, _ in EDITABLE_FIELDS:
            val = row.get(field, "0") or "0"
            self.field_vars[field].set(val)

    def _build_season_from_form(self) -> dict | None:
        """Build a season row dict from the form."""
        if not self._selected_pid:
            messagebox.showwarning("No Player", "Select a player first.")
            return None

        row = {
            "player_id": self._selected_pid,
            "name": self.selected_label_var.get().split(" (")[0],  # extract name
        }

        for field, label, typ in EDITABLE_FIELDS:
            raw = self.field_vars[field].get().strip()
            if typ == str:
                row[field] = raw.upper() if field == "team" else raw
            else:
                try:
                    row[field] = str(typ(float(raw))) if raw else "0"
                except ValueError:
                    messagebox.showwarning("Invalid Input", f"'{label}' must be a number.")
                    return None

        return row

    def _add_season(self):
        """Add a new season for the selected player."""
        row = self._build_season_from_form()
        if not row:
            return

        year = row.get("year", "")

        # Check for duplicate year
        for i in self._player_season_indices:
            if self.rows[i].get("year") == year:
                if not messagebox.askyesno("Duplicate Year",
                                           f"Season {year} already exists. Add anyway?"):
                    return

        self.rows.append(row)
        self._show_player_seasons(self._selected_pid)
        self.status_var.set(f"Added {year} season for {row['name']} (unsaved)")

    def _update_season(self):
        """Update the selected season row."""
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a season row to update.")
            return
        row = self._build_season_from_form()
        if not row:
            return

        tree_idx = int(sel[0])
        row_idx = self._player_season_indices[tree_idx]
        self.rows[row_idx] = row
        self._show_player_seasons(self._selected_pid)
        self.status_var.set(f"Updated {row.get('year', '')} season for {row['name']} (unsaved)")

    def _delete_season(self):
        """Delete the selected season row."""
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a season row to delete.")
            return

        tree_idx = int(sel[0])
        row_idx = self._player_season_indices[tree_idx]
        row = self.rows[row_idx]
        year = row.get("year", "?")
        name = row.get("name", row.get("player_id", ""))

        if messagebox.askyesno("Confirm Delete", f"Delete {name}'s {year} season?"):
            del self.rows[row_idx]
            self._show_player_seasons(self._selected_pid)
            self.status_var.set(f"Deleted {name} {year} season (unsaved)")

    def _merge_player(self):
        """Merge another player's seasons into the currently selected player.

        This is useful when the same real-world player exists as two records
        (e.g., 'Chris Brooks' from ESPN and 'Christopher Brooks' from nflverse).
        All seasons from the source player are moved to the target, and the
        source player's rows are deleted.
        """
        if not self._selected_pid:
            messagebox.showwarning("No Player", "Select the TARGET player first (the one to keep).")
            return

        # Open a merge dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Merge Player")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()

        target_name = self.selected_label_var.get()
        ttk.Label(dialog, text=f"Merge INTO: {target_name}",
                  font=("TkDefaultFont", 10, "bold"), foreground="green").pack(padx=10, pady=(10, 5))
        ttk.Label(dialog, text="Search for the DUPLICATE player to merge from:").pack(padx=10, pady=5)

        search_var = tk.StringVar()
        search_entry = ttk.Entry(dialog, textvariable=search_var, width=40)
        search_entry.pack(padx=10, pady=5)

        listbox = tk.Listbox(dialog, height=10, width=60, exportselection=False)
        listbox.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        matched = []

        def on_search(*args):
            nonlocal matched
            query = search_var.get().strip().lower()
            listbox.delete(0, tk.END)
            if len(query) < 2:
                return
            matched = [(pid, name, pos) for pid, name, pos in self.all_players
                       if query in name.lower() and pid != self._selected_pid][:25]
            for pid, name, pos in matched:
                # Count seasons for this player
                season_count = sum(1 for r in self.rows if r.get("player_id") == pid)
                listbox.insert(tk.END, f"{name}  ({pos})  [{pid}]  — {season_count} seasons")

        search_var.trace_add("write", on_search)

        def do_merge():
            sel = listbox.curselection()
            if not sel:
                messagebox.showwarning("No Selection", "Select the duplicate player to merge from.", parent=dialog)
                return

            source_pid, source_name, source_pos = matched[sel[0]]
            target_pid = self._selected_pid

            # Get target's existing years
            target_years = {r.get("year") for r in self.rows if r.get("player_id") == target_pid}

            # Count what will be merged
            source_seasons = [r for r in self.rows if r.get("player_id") == source_pid]
            new_seasons = [r for r in source_seasons if r.get("year") not in target_years]
            skip_seasons = [r for r in source_seasons if r.get("year") in target_years]

            msg = (f"Merge {source_name} [{source_pid}] into {target_name}?\n\n"
                   f"• {len(new_seasons)} season(s) will be added\n"
                   f"• {len(skip_seasons)} season(s) skipped (year already exists)\n"
                   f"• All of {source_name}'s rows will be deleted\n\n"
                   f"This cannot be undone (until you Save).")

            if not messagebox.askyesno("Confirm Merge", msg, parent=dialog):
                return

            # Move new seasons to target
            target_name_clean = target_name.split(" (")[0]
            for row in new_seasons:
                row["player_id"] = target_pid
                row["name"] = target_name_clean

            # Remove all source rows (including duplicates that were skipped)
            self.rows = [r for r in self.rows if r.get("player_id") != source_pid]

            # Refresh
            self.all_players = get_unique_players(self.rows)
            self._show_player_seasons(target_pid)
            self.status_var.set(
                f"Merged {len(new_seasons)} seasons from {source_name} into {target_name_clean} (unsaved)")

            dialog.destroy()

        ttk.Button(dialog, text="Merge", command=do_merge).pack(pady=10)

    def _save(self):
        """Save all rows to seasons.csv."""
        save_seasons_csv(self.rows)
        self.status_var.set(f"Saved {len(self.rows)} rows to seasons.csv")

    _player_season_indices: list[int] = []


def main():
    root = tk.Tk()
    SeasonsCSVEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
