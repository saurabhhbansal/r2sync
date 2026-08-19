"""Interactive Terminal User Interface (TUI) for r2sync."""

import curses
import os
import sys
import time
from datetime import datetime
from typing import List, Optional

from r2sync.client.ipc_client import IPCClient
from r2sync.config import APP_VERSION, SETTING_SPEED_PROFILE
from r2sync.core.database import Database
from r2sync.core.speed_profiles import SPEED_PROFILES, get_speed_profile, list_speed_profiles
from r2sync.core.updater import AutoUpdater


class R2SyncTUI:
    """Interactive terminal user interface for Linux / terminal environments."""

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.db = Database()
        self.ipc = IPCClient()
        self.running = True
        self.current_tab = 0  # 0: Backups, 1: Multi-PC Sync, 2: Activity, 3: Speed Profiles
        self.selected_idx = 0
        self.status_msg = "Ready. Use [j/k] or arrows to navigate, [Enter] to run, [Tab] to switch views."
        self.update_msg = ""
        self.profiles = list_speed_profiles()

        # Initialize curses settings
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.timeout(1000)  # refresh every 1 second

        # Setup colors
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)     # Header / selected tab
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)     # Selected row
            curses.init_pair(3, curses.COLOR_GREEN, -1)                    # Active / success
            curses.init_pair(4, curses.COLOR_YELLOW, -1)                   # Warning / sync
            curses.init_pair(5, curses.COLOR_RED, -1)                      # Error / conflict
            curses.init_pair(6, curses.COLOR_CYAN, -1)                     # Stat / Info

    def run(self):
        while self.running:
            self._render()
            self._handle_input()

    def _render(self):
        self.stdscr.erase()
        max_y, max_x = self.stdscr.getmaxyx()
        if max_y < 16 or max_x < 60:
            self.stdscr.addstr(0, 0, "Terminal window too small for r2sync TUI. Please enlarge window.")
            self.stdscr.refresh()
            return

        # 1. Header Bar
        header = f"  r2sync v{APP_VERSION} — Cloudflare R2 Terminal Dashboard  "
        speed_id = self.db.get_setting("speed_profile") or "turbo"
        speed_prof = get_speed_profile(speed_id)
        right_info = f"Speed: {speed_prof.label} ({speed_prof.transfers} streams)  "

        hdr_str = header.ljust(max_x - len(right_info)) + right_info
        try:
            self.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
            self.stdscr.addstr(0, 0, hdr_str[:max_x])
            self.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
        except curses.error:
            pass

        # 2. Summary Bento Row
        stats = self.db.get_summary_stats()
        gb_stored = stats.get("total_bytes_stored", 0) / (1024 ** 3)
        jobs = self.db.list_jobs()
        datasets = self.db.list_sync_datasets()
        conflicts = self.db.count_unresolved_conflicts()

        stat_line = (
            f" [ Storage: {gb_stored:.2f} GB ]  "
            f"[ Jobs: {len(jobs)} ({stats.get('active_jobs', 0)} active) ]  "
            f"[ Sync Folders: {len(datasets)} ]  "
            f"[ Conflicts: {conflicts} ]"
        )
        try:
            self.stdscr.attron(curses.color_pair(6))
            self.stdscr.addstr(2, 2, stat_line[:max_x - 4])
            self.stdscr.attroff(curses.color_pair(6))
        except curses.error:
            pass

        # 3. Tab Bar
        tabs = ["[1] Backup Jobs", "[2] Multi-PC Sync", "[3] Activity Log", "[4] Speed Profiles"]
        tab_x = 2
        for idx, tab_name in enumerate(tabs):
            try:
                if idx == self.current_tab:
                    self.stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
                    self.stdscr.addstr(4, tab_x, f" {tab_name} ")
                    self.stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)
                else:
                    self.stdscr.addstr(4, tab_x, f" {tab_name} ")
                tab_x += len(tab_name) + 4
            except curses.error:
                pass

        # Horizontal Divider
        try:
            self.stdscr.addstr(5, 0, "─" * max_x)
        except curses.error:
            pass

        # 4. Main Tab Content
        content_top = 7
        content_bottom = max_y - 4

        if self.current_tab == 0:
            self._render_jobs_tab(content_top, content_bottom, max_x, jobs)
        elif self.current_tab == 1:
            self._render_sync_tab(content_top, content_bottom, max_x, datasets)
        elif self.current_tab == 2:
            self._render_activity_tab(content_top, content_bottom, max_x)
        elif self.current_tab == 3:
            self._render_speed_tab(content_top, content_bottom, max_x, speed_id)

        # 5. Bottom Status / Update Bar
        try:
            self.stdscr.addstr(max_y - 3, 0, "─" * max_x)
            status_display = self.update_msg or self.status_msg
            self.stdscr.addstr(max_y - 2, 2, f"Status: {status_display}"[:max_x - 4])

            # Keybindings Help
            key_help = " [Tab/1-4] Views | [↑/↓] Select | [Enter/r] Run | [b] Backup All | [p] Speed | [u] Update | [q] Quit"
            self.stdscr.attron(curses.color_pair(1))
            self.stdscr.addstr(max_y - 1, 0, key_help.ljust(max_x)[:max_x])
            self.stdscr.attroff(curses.color_pair(1))
        except curses.error:
            pass

        self.stdscr.refresh()

    def _render_jobs_tab(self, top: int, bottom: int, max_x: int, jobs: list):
        hdr = " ID  | Name                 | Status   | Mode | Last Run            | Source Path"
        try:
            self.stdscr.attron(curses.A_BOLD)
            self.stdscr.addstr(top - 1, 2, hdr[:max_x - 4])
            self.stdscr.attroff(curses.A_BOLD)
        except curses.error:
            pass

        if not jobs:
            try:
                self.stdscr.addstr(top + 1, 4, "No backup jobs configured. Use GUI or CLI to add a job.")
            except curses.error:
                pass
            return

        for idx, job in enumerate(jobs):
            row_y = top + idx
            if row_y >= bottom:
                break

            status_str = "ENABLED " if job.enabled else "DISABLED"
            last_run = job.last_run_at[:19].replace("T", " ") if job.last_run_at else "Never"
            row_str = f" #{job.id:<3}| {job.name:<20.20} | {status_str} | {job.backup_mode:<4} | {last_run:<19} | {job.source_path}"

            try:
                if idx == self.selected_idx:
                    self.stdscr.attron(curses.color_pair(2))
                    self.stdscr.addstr(row_y, 2, row_str.ljust(max_x - 4)[:max_x - 4])
                    self.stdscr.attroff(curses.color_pair(2))
                else:
                    color = curses.color_pair(3) if job.enabled else curses.color_pair(4)
                    self.stdscr.attron(color)
                    self.stdscr.addstr(row_y, 2, row_str[:max_x - 4])
                    self.stdscr.attroff(color)
            except curses.error:
                pass

    def _render_sync_tab(self, top: int, bottom: int, max_x: int, datasets: list):
        hdr = " Dataset ID | Name                 | Status   | Mode     | Local Path"
        try:
            self.stdscr.attron(curses.A_BOLD)
            self.stdscr.addstr(top - 1, 2, hdr[:max_x - 4])
            self.stdscr.attroff(curses.A_BOLD)
        except curses.error:
            pass

        if not datasets:
            try:
                self.stdscr.addstr(top + 1, 4, "No shared Multi-PC datasets. Use GUI to add a sync folder.")
            except curses.error:
                pass
            return

        for idx, ds in enumerate(datasets):
            row_y = top + idx
            if row_y >= bottom:
                break

            status_str = "PAUSED" if ds.paused else ds.status.upper()
            row_str = f" {ds.dataset_id[:10]} | {ds.name:<20.20} | {status_str:<8} | {ds.schedule_mode:<8} | {ds.local_path}"

            try:
                if idx == self.selected_idx:
                    self.stdscr.attron(curses.color_pair(2))
                    self.stdscr.addstr(row_y, 2, row_str.ljust(max_x - 4)[:max_x - 4])
                    self.stdscr.attroff(curses.color_pair(2))
                else:
                    self.stdscr.addstr(row_y, 2, row_str[:max_x - 4])
            except curses.error:
                pass

    def _render_activity_tab(self, top: int, bottom: int, max_x: int):
        runs = self.db.list_runs(limit=15)
        hdr = " Run ID | Job Name             | Status    | Transferred  | Files | Completed At"
        try:
            self.stdscr.attron(curses.A_BOLD)
            self.stdscr.addstr(top - 1, 2, hdr[:max_x - 4])
            self.stdscr.attroff(curses.A_BOLD)
        except curses.error:
            pass

        for idx, r in enumerate(runs):
            row_y = top + idx
            if row_y >= bottom:
                break
            mb = round(r.bytes_transferred / (1024 * 1024), 2)
            time_str = r.completed_at[:19].replace("T", " ") if r.completed_at else "Running..."
            row_str = f" #{r.id:<5} | {r.job_name:<20.20} | {r.status.upper():<9} | {mb:>7.2f} MB   | {r.files_transferred:>5} | {time_str}"
            try:
                color = curses.color_pair(3) if r.status == "completed" else curses.color_pair(5)
                self.stdscr.attron(color)
                self.stdscr.addstr(row_y, 2, row_str[:max_x - 4])
                self.stdscr.attroff(color)
            except curses.error:
                pass

    def _render_speed_tab(self, top: int, bottom: int, max_x: int, active_speed_id: str):
        try:
            self.stdscr.attron(curses.A_BOLD)
            self.stdscr.addstr(top - 1, 2, " Select a Speed & Concurrency Profile (Press [Enter] or [1-5] to activate):")
            self.stdscr.attroff(curses.A_BOLD)
        except curses.error:
            pass

        for idx, p in enumerate(self.profiles):
            row_y = top + 1 + (idx * 2)
            if row_y >= bottom:
                break

            active_mark = "● ACTIVE" if p.id == active_speed_id else "○"
            line = f" [{idx + 1}] {p.label:<20} {active_mark:<10} | Streams: {p.transfers:<2} | Checkers: {p.checkers:<2} | Buffer: {p.buffer_size:<4} | Chunk: {p.chunk_size}"
            desc = f"     ↳ {p.description}"

            try:
                if p.id == active_speed_id:
                    self.stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
                    self.stdscr.addstr(row_y, 2, line[:max_x - 4])
                    self.stdscr.addstr(row_y + 1, 2, desc[:max_x - 4])
                    self.stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)
                else:
                    self.stdscr.addstr(row_y, 2, line[:max_x - 4])
                    self.stdscr.attron(curses.color_pair(6))
                    self.stdscr.addstr(row_y + 1, 2, desc[:max_x - 4])
                    self.stdscr.attroff(curses.color_pair(6))
            except curses.error:
                pass

    def _handle_input(self):
        try:
            key = self.stdscr.getch()
        except Exception:
            return

        if key == -1:
            return

        if key in (ord('q'), ord('Q')):
            self.running = False
        elif key in (ord('\t'), ):
            self.current_tab = (self.current_tab + 1) % 4
            self.selected_idx = 0
        elif key in (ord('1'), ord('2'), ord('3'), ord('4')):
            if self.current_tab == 3 and key in (ord('1'), ord('2'), ord('3'), ord('4'), ord('5')):
                prof_idx = key - ord('1')
                if 0 <= prof_idx < len(self.profiles):
                    p = self.profiles[prof_idx]
                    self.db.set_setting("speed_profile", p.id)
                    self.status_msg = f"Speed profile updated to: {p.label}"
            else:
                self.current_tab = key - ord('1')
                self.selected_idx = 0
        elif key in (curses.KEY_UP, ord('k'), ord('K')):
            if self.selected_idx > 0:
                self.selected_idx -= 1
        elif key in (curses.KEY_DOWN, ord('j'), ord('J')):
            self.selected_idx += 1
        elif key in (ord('p'), ord('P')):
            # Cycle speed profile
            curr = self.db.get_setting("speed_profile") or "turbo"
            idx = 0
            for i, p in enumerate(self.profiles):
                if p.id == curr:
                    idx = (i + 1) % len(self.profiles)
                    break
            new_p = self.profiles[idx]
            self.db.set_setting("speed_profile", new_p.id)
            self.status_msg = f"Speed profile switched to: {new_p.label} ({new_p.transfers} streams)"
        elif key in (ord('b'), ord('B')):
            # Backup all jobs
            jobs = self.db.list_jobs()
            count = 0
            for j in jobs:
                if j.enabled and j.id:
                    self._run_job_action(j.id)
                    count += 1
            self.status_msg = f"Triggered backup for {count} active jobs."
        elif key in (ord('u'), ord('U')):
            self.update_msg = "Checking GitHub for updates..."
            self._check_update()
        elif key in (10, 13, ord('r'), ord('R')):
            # Run selected job or dataset
            if self.current_tab == 0:
                jobs = self.db.list_jobs()
                if 0 <= self.selected_idx < len(jobs):
                    j = jobs[self.selected_idx]
                    self._run_job_action(j.id)
                    self.status_msg = f"Backup job #{j.id} ('{j.name}') started."
            elif self.current_tab == 1:
                datasets = self.db.list_sync_datasets()
                if 0 <= self.selected_idx < len(datasets):
                    ds = datasets[self.selected_idx]
                    self._run_sync_action(ds.dataset_id)
                    self.status_msg = f"Sync dataset '{ds.name}' triggered."
            elif self.current_tab == 3:
                if 0 <= self.selected_idx < len(self.profiles):
                    p = self.profiles[self.selected_idx]
                    self.db.set_setting("speed_profile", p.id)
                    self.status_msg = f"Speed profile set to: {p.label}"

    def _run_job_action(self, job_id: int):
        if self.ipc.is_service_running():
            self.ipc.run_job_now(job_id)
        else:
            from r2sync.core.backup_engine import BackupEngine
            from r2sync.core.credentials import get_r2_credentials
            be = BackupEngine(self.db)
            job = self.db.get_job(job_id)
            if job:
                import threading
                threading.Thread(target=lambda: be.run_job_sync(job, get_r2_credentials()), daemon=True).start()

    def _run_sync_action(self, dataset_id: str):
        if self.ipc.is_service_running():
            self.ipc.sync_dataset_now(dataset_id)
        else:
            from r2sync.core.sync_engine import SyncEngine
            from r2sync.core.credentials import get_r2_credentials
            se = SyncEngine(self.db)
            import threading
            threading.Thread(target=lambda: se.run_dataset_sync(dataset_id, get_r2_credentials()), daemon=True).start()

    def _check_update(self):
        try:
            info = AutoUpdater.check_for_updates()
            if info.available:
                self.update_msg = f"New version v{info.latest_version} available! Run 'pip install -U r2sync' or download from {info.html_url}"
            else:
                self.update_msg = f"You are on the latest version (v{APP_VERSION})."
        except Exception as e:
            self.update_msg = f"Update check failed: {e}"


def run_tui():
    """Launch the r2sync interactive curses TUI."""
    try:
        curses.wrapper(lambda stdscr: R2SyncTUI(stdscr).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run_tui()
