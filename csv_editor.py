"""
CSV Editor for college.csv — add, edit, and delete college stat rows.
Auto-looks up player_id from seasons.csv by name search.
"""

import csv
import os
import tkinter as tk
from tkinter import ttk, messagebox

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
COLLEGE_CSV = os.path.join(DATA_DIR, "college.csv")
SEASONS_CSV = os.path.join(DATA_DIR, "seasons.csv")

# Columns in college.csv (must match player_db.py _save_college_csv)
COLLEGE_COLS = [
    "player_id", "name", "college_dom_score", "college_final_year",
    "college_games", "college_pass_yds", "college_pass_tds",
    "college_ints", "college_rush_yds", "college_rush_tds",
    "college_rec", "college_rec_yds", "college_rec_tds",
]

# The stat fields the user actually edits
EDITABLE_STAT_FIELDS = [
    ("college_games", "Games", int),
    ("college_pass_yds", "Pass Yds", float),
    ("college_pass_tds", "Pass TDs", float),
    ("college_ints", "INTs", float),
    ("college_rush_yds", "Rush Yds", float),
    ("college_rush_tds", "Rush TDs", float),
    ("college_rec", "Receptions", float),
    ("college_rec_yds", "Rec Yds", float),
    ("college_rec_tds", "Rec TDs", float),
]

ESTIMATED_COLLEGE_GAMES = 13


def compute_college_score(row: dict) -> float | None:
    """Calculate college dominance score from raw stats (mirrors PlayerRecord.compute_college_score)."""
    games = int(float(row.get("college_games", 0) or 0))
    if games <= 0:
        games = ESTIMATED_COLLEGE_GAMES
    pass_yds = float(row.get("college_pass_yds", 0) or 0)
    pass_tds = float(row.get("college_pass_tds", 0) or 0)
    ints = float(row.get("college_ints", 0) or 0)
    rush_yds = float(row.get("college_rush_yds", 0) or 0)
    rush_tds = float(row.get("college_rush_tds", 0) or 0)
    rec = float(row.get("college_rec", 0) or 0)
    rec_yds = float(row.get("college_rec_yds", 0) or 0)
    rec_tds = float(row.get("college_rec_tds", 0) or 0)

    fantasy_pts = (pass_yds * 0.04 + pass_tds * 4 + ints * -2 +
                   rush_yds * 0.1 + rush_tds * 6 +
                   rec * 1.0 + rec_yds * 0.1 + rec_tds * 6)
    if fantasy_pts > 0:
        return round(fantasy_pts / games, 1)
    return None


def load_player_lookup() -> list[tuple[str, str]]:
    """Load (player_id, name) pairs from seasons.csv for auto-lookup."""
    players = {}
    if not os.path.exists(SEASONS_CSV):
        return []
    with open(SEASONS_CSV, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("player_id", "")
            name = row.get("name", "")
            if pid and name and pid not in players:
                players[pid] = name
    # Sort by name
    return sorted(players.items(), key=lambda x: x[1])


def load_college_csv() -> list[dict]:
    """Load existing college.csv rows."""
    if not os.path.exists(COLLEGE_CSV):
        return []
    with open(COLLEGE_CSV, "r", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def save_college_csv(rows: list[dict]):
    """Save rows back to college.csv."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(COLLEGE_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLLEGE_COLS)
        for row in rows:
            writer.writerow([row.get(col, "") for col in COLLEGE_COLS])


class CollegeCSVEditor:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("College Stats CSV Editor")
        self.root.geometry("1100x650")

        self.rows: list[dict] = []
        self.player_lookup = load_player_lookup()

        self._build_ui()
        self._load_data()

    def _build_ui(self):
        # --- Top: Table ---
        table_frame = ttk.Frame(self.root)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))

        display_cols = ("name", "college_dom_score", "college_final_year",
                        "college_games", "college_pass_yds", "college_pass_tds",
                        "college_ints", "college_rush_yds", "college_rush_tds",
                        "college_rec", "college_rec_yds", "college_rec_tds")
        col_headers = ("Name", "DomScr", "Final Year", "Games",
                       "PassYds", "PassTDs", "INTs",
                       "RushYds", "RushTDs", "Rec", "RecYds", "RecTDs")

        self.tree = ttk.Treeview(table_frame, columns=display_cols, show="headings",
                                 selectmode="browse")

        for col, header in zip(display_cols, col_headers):
            width = 60 if col != "name" and col != "college_final_year" else 150
            self.tree.heading(col, text=header)
            self.tree.column(col, width=width, minwidth=50)

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # --- Middle: Search + Form ---
        form_frame = ttk.LabelFrame(self.root, text="Add / Edit Player")
        form_frame.pack(fill=tk.X, padx=10, pady=5)

        # Player search row
        search_row = ttk.Frame(form_frame)
        search_row.pack(fill=tk.X, padx=10, pady=(10, 5))

        ttk.Label(search_row, text="Player:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_changed)
        self.search_entry = ttk.Entry(search_row, textvariable=self.search_var, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=(5, 10))

        self.match_listbox = tk.Listbox(search_row, height=4, width=45)
        self.match_listbox.pack(side=tk.LEFT, padx=(0, 10))
        self.match_listbox.bind("<<ListboxSelect>>", self._on_match_select)

        self.selected_pid = tk.StringVar()
        self.selected_name = tk.StringVar()
        ttk.Label(search_row, text="Selected:").pack(side=tk.LEFT)
        self.selected_label = ttk.Label(search_row, textvariable=self.selected_name,
                                        foreground="green", font=("TkDefaultFont", 10, "bold"))
        self.selected_label.pack(side=tk.LEFT, padx=5)

        # Final year row
        year_row = ttk.Frame(form_frame)
        year_row.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(year_row, text="Final Year Label:").pack(side=tk.LEFT)
        self.final_year_var = tk.StringVar()
        ttk.Entry(year_row, textvariable=self.final_year_var, width=50).pack(side=tk.LEFT, padx=5)
        ttk.Label(year_row, text="(e.g. '2024: 1200yds/14td rush, 30rec/280yds/2td')",
                  foreground="gray").pack(side=tk.LEFT)

        # Stat fields row
        stats_row = ttk.Frame(form_frame)
        stats_row.pack(fill=tk.X, padx=10, pady=(2, 10))

        self.stat_vars: dict[str, tk.StringVar] = {}
        for field, label, _ in EDITABLE_STAT_FIELDS:
            ttk.Label(stats_row, text=f"{label}:").pack(side=tk.LEFT, padx=(8, 2))
            var = tk.StringVar(value="0")
            self.stat_vars[field] = var
            ttk.Entry(stats_row, textvariable=var, width=6).pack(side=tk.LEFT)

        # --- Bottom: Buttons ---
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Button(btn_frame, text="Add New", command=self._add_row).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Update Selected", command=self._update_row).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Delete Selected", command=self._delete_row).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Save to CSV", command=self._save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Reload", command=self._load_data).pack(side=tk.RIGHT, padx=5)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN,
                  anchor=tk.W).pack(fill=tk.X, side=tk.BOTTOM)

    def _load_data(self):
        """Load CSV and populate the table."""
        self.rows = load_college_csv()
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(self.rows):
            values = (
                row.get("name", row.get("player_id", "")),
                row.get("college_dom_score", ""),
                row.get("college_final_year", ""),
                row.get("college_games", ""),
                row.get("college_pass_yds", ""),
                row.get("college_pass_tds", ""),
                row.get("college_ints", ""),
                row.get("college_rush_yds", ""),
                row.get("college_rush_tds", ""),
                row.get("college_rec", ""),
                row.get("college_rec_yds", ""),
                row.get("college_rec_tds", ""),
            )
            self.tree.insert("", tk.END, iid=str(i), values=values)
        self.status_var.set(f"Loaded {len(self.rows)} rows from college.csv")

    def _on_select(self, event):
        """Populate form fields when a row is selected in the table."""
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        row = self.rows[idx]

        self.selected_pid.set(row.get("player_id", ""))
        name = row.get("name", "")
        self.selected_name.set(name)
        self.search_var.set(name)
        self.final_year_var.set(row.get("college_final_year", ""))

        for field, _, _ in EDITABLE_STAT_FIELDS:
            val = row.get(field, "0") or "0"
            self.stat_vars[field].set(val)

    def _on_search_changed(self, *args):
        """Filter player lookup as user types."""
        query = self.search_var.get().strip().lower()
        self.match_listbox.delete(0, tk.END)
        if len(query) < 2:
            return
        matches = [(pid, name) for pid, name in self.player_lookup
                   if query in name.lower()][:20]
        for pid, name in matches:
            self.match_listbox.insert(tk.END, f"{name}  [{pid}]")
        self._matched = matches

    def _on_match_select(self, event):
        """Set selected player from search results."""
        sel = self.match_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._matched):
            pid, name = self._matched[idx]
            self.selected_pid.set(pid)
            self.selected_name.set(name)

    def _build_row_from_form(self) -> dict | None:
        """Build a row dict from the current form values."""
        pid = self.selected_pid.get().strip()
        name = self.selected_name.get().strip()
        if not pid:
            messagebox.showwarning("No Player", "Select a player from the search results first.")
            return None

        row = {"player_id": pid, "name": name}
        row["college_final_year"] = self.final_year_var.get().strip()

        for field, label, typ in EDITABLE_STAT_FIELDS:
            raw = self.stat_vars[field].get().strip()
            try:
                row[field] = str(typ(float(raw))) if raw else "0"
            except ValueError:
                messagebox.showwarning("Invalid Input", f"'{label}' must be a number.")
                return None

        # Compute score
        score = compute_college_score(row)
        row["college_dom_score"] = str(score) if score else ""

        return row

    def _add_row(self):
        """Add a new row to the table."""
        row = self._build_row_from_form()
        if not row:
            return

        # Check if player already exists
        for i, existing in enumerate(self.rows):
            if existing.get("player_id") == row["player_id"]:
                if messagebox.askyesno("Duplicate",
                                       f"{row['name']} already exists. Update instead?"):
                    self.rows[i] = row
                    self._load_data()
                    self.status_var.set(f"Updated {row['name']} (unsaved)")
                return

        self.rows.append(row)
        idx = len(self.rows) - 1
        values = tuple(row.get(c, "") for c in COLLEGE_COLS[1:])  # skip player_id
        self.tree.insert("", tk.END, iid=str(idx), values=values)
        self.tree.see(str(idx))
        self.status_var.set(f"Added {row['name']} — DomScr: {row.get('college_dom_score', 'N/A')} (unsaved)")

    def _update_row(self):
        """Update the selected row with current form values."""
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a row in the table to update.")
            return
        row = self._build_row_from_form()
        if not row:
            return
        idx = int(sel[0])
        self.rows[idx] = row
        self._load_data()
        self.status_var.set(f"Updated {row['name']} — DomScr: {row.get('college_dom_score', 'N/A')} (unsaved)")

    def _delete_row(self):
        """Delete the selected row."""
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a row to delete.")
            return
        idx = int(sel[0])
        name = self.rows[idx].get("name", self.rows[idx].get("player_id", ""))
        if messagebox.askyesno("Confirm Delete", f"Delete {name}?"):
            del self.rows[idx]
            self._load_data()
            self.status_var.set(f"Deleted {name} (unsaved)")

    def _save(self):
        """Save all rows to college.csv."""
        save_college_csv(self.rows)
        self.status_var.set(f"Saved {len(self.rows)} rows to college.csv")

    _matched: list[tuple[str, str]] = []


def main():
    root = tk.Tk()
    CollegeCSVEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
