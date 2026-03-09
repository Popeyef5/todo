"""
Split-pane TUI with VIM-like modal mode.

Upper half: persistent task list panel (always visible, auto-refreshes).
Lower half: CLI output area + input prompt.

Ctrl+T switches between REPL mode (CLI input) and Modal mode (navigate/act on tasks).
"""

import curses
import io
import shlex
import sys
import termios
from pathlib import Path
from typing import List, Optional

from todo.core.manager import TodoManager
from todo.sync.auth import resolve_token, _token_from_cli, clear_token_cache
from todo.sync.main_sync import MainSync
from todo.sync.background import BackgroundSync
from todo.sync.providers import GitHubProvider, GitLabProvider, parse_remote_url
from todo.ui.tasks import (
    TaskRef, parse_tasks_from_file, toggle_task_in_file,
    add_task_to_file, edit_task_in_file, remove_task_from_file,
    get_children_ids,
)
from todo.ui.themes import (
    get_theme, set_theme, list_themes, load_custom_themes,
    resolve_dynamic_vars, build_dynamic_context, MAX_BANNER_LINES,
)

CTRL_T = 20
CTRL_F = 6
CTRL_S = 19


class TodoTUI:
    """Split-pane TUI with REPL and Modal modes"""

    def __init__(self, manager: TodoManager, initial_target: str = None):
        self.manager = manager
        self.current_project = None
        self.tasks: List[TaskRef] = []
        self.dirty = False

        # Mode
        self.mode = 'repl'  # 'repl' or 'modal'
        self.modal_cursor = 0
        self.fullscreen = False

        # REPL state
        self.input_buffer = ''
        self.input_cursor = 0
        self.output_lines: List[str] = []
        self.cmd_history: List[str] = []
        self.history_pos = -1
        self.history_stash = ''
        self.output_scroll = 0  # 0 = pinned to bottom, >0 = scrolled up

        # Task panel scroll
        self.task_scroll = 0
        self.collapsed_projects: set = set()  # project names that are collapsed
        self.nav_items: list = []  # list of ('task', idx) or ('header', project_name)

        # Input mode for modal operations (add/edit/pick_project/confirm_delete)
        self.input_mode = None
        self.edit_task_index = None
        self._pending_add_text = None  # stash text during project pick
        self._add_target_project = None  # project inferred for modal add
        self._add_indent = ""            # indent for the new task
        self._add_after_line = None      # line_no to insert after (subtree end)
        self._delete_target_index = None  # task index pending delete confirmation
        self._delete_target_project = None  # project name pending delete confirmation
        self._input_mode_output_start = 0  # output_lines count when input_mode was set

        # Setup wizard state
        self._setup_provider = None   # "github" / "gitlab" / "other"
        self._setup_token = None
        self._setup_username = None

        self._bg_sync = None  # BackgroundSync instance
        self._main_sync = None  # MainSync instance (set in _start_background_sync)
        self._setup_group_name = None  # when set, setup wizard targets this group
        self._initial_target = initial_target

        # Staging ground
        self.stage_view = False

        # Find filter (modal mode)
        self.find_filter = ''

        # Hide completed tasks
        self.hide_done = False

    def run(self):
        """Entry point"""
        curses.wrapper(self._main)

    def _main(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(1)
        stdscr.keypad(True)
        stdscr.timeout(1000)

        # Disable XON/XOFF flow control so Ctrl+S reaches us as a keypress
        fd = sys.stdin.fileno()
        attrs = termios.tcgetattr(fd)
        attrs[0] &= ~termios.IXON
        termios.tcsetattr(fd, termios.TCSANOW, attrs)

        curses.start_color()
        curses.use_default_colors()
        # Load custom themes from ~/.todo/themes/, then apply saved preference
        load_custom_themes(self.manager.themes_dir)
        saved_theme = self.manager.config.get("theme")
        if saved_theme:
            set_theme(saved_theme)
        self._apply_theme_colors()

        # Initial scope
        if self._initial_target:
            self._set_project(self._initial_target)

        # Initial sync (async — UI renders immediately)
        self._add_output("syncing...")
        self._start_background_sync()

        self._refresh_tasks()
        self._add_output("todo interactive mode — Type 'help' for commands, Ctrl+T for modal mode")

        self.stdscr.clear()
        self.stdscr.refresh()
        self._create_windows()
        self._full_render()

        while True:
            try:
                key = self.stdscr.getch()
            except KeyboardInterrupt:
                self._quit()
                return

            if key == -1:
                # Timeout — check for background sync and refresh dynamic content
                self._check_pending_sync()
                self._render_mid_banner()
                self._render_top_banner()
                curses.doupdate()
                continue

            if key == curses.KEY_RESIZE:
                self._create_windows()
                self._full_render()
                continue

            if key == CTRL_T:
                self._toggle_mode()
                continue

            if key == CTRL_F:
                self._toggle_fullscreen()
                continue

            if key == CTRL_S:
                self._toggle_stage_view()
                continue

            if self.mode == 'modal':
                self._handle_modal_key(key)
            else:
                self._handle_repl_key(key)

    # ── Theme ─────────────────────────────────────────────────────────

    def _apply_theme_colors(self):
        """Initialize curses color pairs from the current theme."""
        theme = get_theme()
        for i, (fg, bg) in enumerate(theme.curses_pairs):
            curses.init_pair(i + 1, fg, bg)

    # ── Window management ─────────────────────────────────────────────

    def _create_windows(self):
        h, w = self.stdscr.getmaxyx()
        theme = get_theme()

        # Calculate banner heights (capped at MAX_BANNER_LINES)
        self.top_banner_h = min(len(theme.tui_banner_top), MAX_BANNER_LINES) if theme.tui_banner_top else 0
        self.mid_banner_h = min(len(theme.tui_banner_mid), MAX_BANNER_LINES) if theme.tui_banner_mid else 0

        # Terminal panel chrome: top border + bottom border + optional separator
        # Show separator when not fullscreen, or when fullscreen with an active prompt
        fs_prompt = self.fullscreen and self.input_mode
        has_sep = bool(theme.input_separator) and (not self.fullscreen or fs_prompt)
        term_chrome = 2 + (1 if has_sep else 0)  # top/bottom border + separator

        # Fixed vertical space: banners + status bar(1) + terminal chrome + input line(1)
        fixed = self.top_banner_h + self.mid_banner_h + 1 + term_chrome + 1
        remaining = max(h - fixed, 4)  # at least 4 rows for panels

        if fs_prompt:
            # Temporarily shrink task panel to show only the prompt-related lines
            prompt_lines = len(self.output_lines) - self._input_mode_output_start
            self.output_h = max(min(prompt_lines, remaining // 3, 10), 1)
            self.task_h = max(remaining - self.output_h, 3)
        elif self.fullscreen:
            self.task_h = max(remaining, 3)
            self.output_h = 0
        else:
            self.task_h = max(remaining // 2, 3)
            self.output_h = max(remaining - self.task_h, 1)

        # Row positions (top to bottom), adjusted by status_bar_position
        pos = theme.status_bar_position
        if pos == "top":
            self.status_y = 0
            self.top_banner_y = 1
            self.task_y = 1 + self.top_banner_h
            self.mid_banner_y = self.task_y + self.task_h
            self.term_top_y = self.mid_banner_y + self.mid_banner_h
        elif pos == "bottom":
            self.top_banner_y = 0
            self.task_y = self.top_banner_h
            self.mid_banner_y = self.task_y + self.task_h
            self.term_top_y = self.mid_banner_y + self.mid_banner_h
        else:  # "middle" (default)
            self.top_banner_y = 0
            self.task_y = self.top_banner_h
            self.mid_banner_y = self.task_y + self.task_h
            self.status_y = self.mid_banner_y + self.mid_banner_h
            self.term_top_y = self.status_y + 1

        self.output_y = self.term_top_y + 1            # output content start
        self.sep_y = self.output_y + self.output_h if has_sep else None
        self.input_y = (self.sep_y + 1) if has_sep else (self.output_y + self.output_h)
        self.term_bottom_y = self.input_y + 1          # terminal bottom border

        if pos == "bottom":
            self.status_y = self.term_bottom_y + 1

        self.width = w
        self.height = h

        self.task_win = curses.newwin(self.task_h, w, self.task_y, 0)
        self.task_win.keypad(True)
        if self.output_h > 0:
            self.output_win = curses.newwin(self.output_h, w, self.output_y, 0)
            self.output_win.keypad(True)
        else:
            self.output_win = None

    # ── Rendering ─────────────────────────────────────────────────────

    def _build_context(self) -> dict:
        """Build the dynamic variable context for banner rendering."""
        pending = sum(1 for t in self.tasks if not t.checked)
        done = sum(1 for t in self.tasks if t.checked)
        return build_dynamic_context(
            project=self.current_project or "all",
            tasks_pending=pending,
            tasks_done=done,
            tasks_total=len(self.tasks),
        )

    def _full_render(self):
        if self.fullscreen:
            # Recalculate layout when input_mode changes visibility of output panel
            self._create_windows()
            self.stdscr.clear()
            self.stdscr.refresh()
        self._render_top_banner()
        self._render_task_panel()
        self._render_mid_banner()
        self._render_status_bar()
        self._render_term_border_top()
        self._render_output_panel()
        self._render_input_separator()
        self._render_input_line()
        self._render_term_border_bottom()
        self._position_cursor()
        curses.doupdate()

    def _render_banner(self, lines: List[str], start_y: int, count: int,
                       align: str = "center"):
        """Render banner lines on stdscr with the given alignment."""
        if count <= 0:
            return
        import re
        w = self.width
        ctx = self._build_context()
        for i, line in enumerate(lines[:count]):
            y = start_y + i
            if y >= self.height:
                break
            resolved = resolve_dynamic_vars(line, ctx)
            # Strip ANSI codes — curses uses color pairs, not escape sequences
            clean = re.sub(r'\033\[[0-9;]*m', '', resolved)
            pad = max(w - len(clean), 0)
            if align == "left":
                aligned = clean + " " * pad
            elif align == "right":
                aligned = " " * pad + clean
            else:
                left_pad = pad // 2
                aligned = " " * left_pad + clean + " " * (pad - left_pad)
            try:
                self.stdscr.addnstr(y, 0, aligned, w - 1, curses.color_pair(1))
            except curses.error:
                pass
        self.stdscr.noutrefresh()

    def _render_top_banner(self):
        theme = get_theme()
        self._render_banner(theme.tui_banner_top, self.top_banner_y, self.top_banner_h,
                            theme.tui_banner_top_align)

    def _render_mid_banner(self):
        theme = get_theme()
        self._render_banner(theme.tui_banner_mid, self.mid_banner_y, self.mid_banner_h,
                            theme.tui_banner_mid_align)

    def _render_term_border_top(self):
        """Draw the terminal panel top border on stdscr."""
        theme = get_theme()
        w = self.width
        y = self.term_top_y
        if y >= self.height:
            return
        border = theme.border_top_left + theme.border_h * max(w - 2, 0)
        try:
            self.stdscr.addnstr(y, 0, border, w - 1, curses.color_pair(1))
            self.stdscr.insstr(y, w - 1, theme.border_top_right, curses.color_pair(1))
        except curses.error:
            pass
        self.stdscr.noutrefresh()

    def _render_term_border_bottom(self):
        """Draw the terminal panel bottom border on stdscr."""
        theme = get_theme()
        w = self.width
        y = self.term_bottom_y
        if y >= self.height:
            return
        border = theme.border_bottom_left + theme.border_h * max(w - 2, 0)
        try:
            self.stdscr.addnstr(y, 0, border, w - 1, curses.color_pair(1))
            self.stdscr.insstr(y, w - 1, theme.border_bottom_right, curses.color_pair(1))
        except curses.error:
            pass
        self.stdscr.noutrefresh()

    def _render_input_separator(self):
        """Draw the separator line between output and input inside the terminal box."""
        theme = get_theme()
        if not theme.input_separator or self.sep_y is None or (self.fullscreen and not self.input_mode):
            return
        w = self.width
        if self.sep_y >= self.height:
            return
        if theme.tui_bordered:
            sep = theme.border_tee_left + theme.input_separator * max(w - 2, 0)
        else:
            sep = theme.input_separator * w
        try:
            self.stdscr.addnstr(self.sep_y, 0, sep, w - 1, curses.color_pair(1))
            if theme.tui_bordered:
                self.stdscr.insstr(self.sep_y, w - 1, theme.border_tee_right, curses.color_pair(1))
        except curses.error:
            pass
        self.stdscr.noutrefresh()

    def _render_task_panel(self):
        win = self.task_win
        win.erase()
        h, w = win.getmaxyx()

        # Title
        if self.stage_view:
            scope = "⚡ staging"
        else:
            scope = self.current_project or "all projects"
        unchecked = sum(1 for t in self.tasks if not t.checked)
        checked = sum(1 for t in self.tasks if t.checked)
        title = f" {scope} — {unchecked} pending, {checked} done "
        if self.find_filter:
            title += f"[find: {self.find_filter}] "

        theme = get_theme()
        bordered = theme.tui_bordered
        # Content area: if bordered, cols 1..w-2; otherwise 0..w-1
        cx = 1 if bordered else 0
        cw = w - 2 if bordered else w

        try:
            win.addstr(0, 0, theme.border_top_left, curses.color_pair(1))
            title_avail = w - 2
            win.addnstr(0, 1, title, title_avail, curses.color_pair(1) | curses.A_BOLD)
            fill_start = 1 + min(len(title), title_avail)
            fill_len = w - 2 - fill_start + 1
            if fill_len > 0:
                win.addnstr(0, fill_start, theme.border_h * fill_len, fill_len, curses.color_pair(1))
            if bordered and w >= 2:
                win.insstr(0, w - 1, theme.border_top_right, curses.color_pair(1))
        except curses.error:
            pass

        # Clamp cursor
        if self.nav_items:
            self.modal_cursor = max(0, min(self.modal_cursor, len(self.nav_items) - 1))

        # Build a flat list of display rows for scrolling
        # Each entry: ('header', project_name, nav_idx_or_None) or ('task', task_idx, nav_idx_or_None)
        display_rows = []
        if self.current_project:
            for nav_idx, item in enumerate(self.nav_items):
                display_rows.append(('task', item[1], nav_idx))
        else:
            nav_lookup = {tuple(item): idx for idx, item in enumerate(self.nav_items)}

            # Group tasks by project for ordered iteration
            tasks_by_project = {}
            for i, task in enumerate(self.tasks):
                if self.find_filter and self.find_filter not in task.text.lower():
                    continue
                tasks_by_project.setdefault(task.project_name, []).append(i)

            # Merge project names from tasks and registry, sorted
            all_names = set(tasks_by_project.keys())
            if not self.find_filter and not self.stage_view:
                all_names |= set(p["name"] for p in self.manager.list_projects())
            sorted_projects = sorted(all_names)

            seen_projects = set()
            for pname in sorted_projects:
                if pname in seen_projects:
                    continue
                seen_projects.add(pname)
                # Emit ancestor headers
                parts = pname.split("/")
                for j in range(1, len(parts)):
                    ancestor = "/".join(parts[:j])
                    if ancestor not in seen_projects:
                        seen_projects.add(ancestor)
                        header_nav = nav_lookup.get(('header', ancestor))
                        display_rows.append(('header', ancestor, header_nav))
                is_collapsed = self._is_project_collapsed(pname)
                header_nav = nav_lookup.get(('header', pname))
                display_rows.append(('header', pname, header_nav))
                if is_collapsed:
                    continue
                for task_idx in tasks_by_project.get(pname, []):
                    if not self._is_project_collapsed(pname):
                        task_nav = nav_lookup.get(('task', task_idx))
                        display_rows.append(('task', task_idx, task_nav))

        # Find which display row the cursor is on for scrolling
        cursor_display_row = 0
        cur_item = self._current_nav_item()
        for dr_idx, dr in enumerate(display_rows):
            if dr[2] is not None and dr[2] == self.modal_cursor:
                cursor_display_row = dr_idx
                break

        # Scrolling
        visible_rows = h - 2
        if visible_rows > 0 and display_rows:
            if cursor_display_row < self.task_scroll:
                self.task_scroll = cursor_display_row
            elif cursor_display_row >= self.task_scroll + visible_rows:
                self.task_scroll = cursor_display_row - visible_rows + 1

        # Draw
        row = 1
        for dr_idx, dr in enumerate(display_rows):
            if row >= h - 1:
                break
            if dr_idx < self.task_scroll:
                continue

            kind, value, nav_idx = dr
            is_highlighted = (self.mode == 'modal' and nav_idx is not None
                              and nav_idx == self.modal_cursor)

            if kind == 'header':
                project_name = value
                is_collapsed = project_name in self.collapsed_projects
                collapse_icon = theme.collapse_closed if is_collapsed else theme.collapse_open
                depth = project_name.count("/")
                display_name = project_name.rsplit("/", 1)[-1] if "/" in project_name else project_name
                header_indent = "    " * depth
                label = f"     {header_indent}{collapse_icon} {display_name}"
                try:
                    if bordered:
                        win.addstr(row, 0, theme.border_v, curses.color_pair(1))
                    if is_highlighted:
                        win.addnstr(row, cx, label.ljust(cw), cw,
                                    curses.color_pair(7) | curses.A_BOLD)
                    else:
                        win.addnstr(row, cx, label, cw,
                                    curses.color_pair(5) | curses.A_BOLD)
                    if bordered and w >= 2:
                        win.insstr(row, w - 1, theme.border_v, curses.color_pair(1))
                except curses.error:
                    pass
                row += 1
            else:
                task_idx = value
                task = self.tasks[task_idx]
                idx_str = f"{task_idx + 1:>3}"
                checkbox = theme.checkbox_checked if task.checked else theme.checkbox_unchecked
                task_depth = len(task.indent) // 4
                project_depth = task.project_name.count("/") + 1 if not self.current_project else 0
                indent_visual = "    " * (task_depth + project_depth)
                line_text = f" {idx_str} {indent_visual}{checkbox} {task.text}"

                if len(line_text) >= cw:
                    line_text = line_text[:cw - 1] + "…"

                try:
                    if bordered:
                        win.addstr(row, 0, theme.border_v, curses.color_pair(1))
                    if is_highlighted:
                        win.addnstr(row, cx, line_text.ljust(cw), cw,
                                    curses.color_pair(7) | curses.A_BOLD)
                    elif task.checked:
                        win.addnstr(row, cx, line_text.ljust(cw), cw, curses.A_DIM)
                    else:
                        prefix = f" {idx_str} {indent_visual}"
                        win.addstr(row, cx, prefix, curses.A_DIM)
                        cb_attr = curses.color_pair(3)
                        win.addstr(row, cx + len(prefix), checkbox, cb_attr)
                        text_col = cx + len(prefix) + len(checkbox) + 1
                        avail = w - text_col - (1 if bordered else 0) - 1
                        if avail > 0:
                            win.addnstr(row, text_col, task.text, avail)
                    if bordered and w >= 2:
                        win.insstr(row, w - 1, theme.border_v, curses.color_pair(1))
                except curses.error:
                    pass
                row += 1

        # Draw side borders on empty rows
        if bordered:
            for r in range(row, h - 1):
                try:
                    win.addstr(r, 0, theme.border_v, curses.color_pair(1))
                    win.insstr(r, w - 1, theme.border_v, curses.color_pair(1))
                except curses.error:
                    pass

        if not self.nav_items and 1 < h - 1:
            try:
                win.addnstr(1, cx + 1, "No tasks found", cw - 2, curses.A_DIM)
            except curses.error:
                pass

        # Bottom border
        try:
            bottom = theme.border_bottom_left + theme.border_h * max(w - 2, 0)
            win.addnstr(h - 1, 0, bottom, w - 1, curses.color_pair(1))
            win.insstr(h - 1, w - 1, theme.border_bottom_right, curses.color_pair(1))
        except curses.error:
            pass

        win.noutrefresh()

    def _render_status_bar(self):
        h, w = self.stdscr.getmaxyx()
        theme = get_theme()
        sep = theme.border_v
        mode_label = " MODAL " if self.mode == 'modal' else " REPL "
        if self.fullscreen:
            mode_label += "⛶ "
        project_label = f" {self.current_project}" if self.current_project else " all"

        if self.stage_view:
            project_label = " ⚡staging"
        if self.mode == 'modal':
            hint = " ↑↓:nav  t:toggle  a:add  A:child  e:edit  d:del  f:find  s:stage  u:use  c:collapse  ^S:view  q:quit"
        else:
            hint = " ^T:mode  ^F:full  ^S:staging  PgUp/PgDn:scroll  Tab:complete"

        bar = f"{mode_label}{sep}{project_label} {sep}{hint}"
        bar = bar.ljust(w)

        attr = curses.color_pair(6) | curses.A_BOLD
        try:
            self.stdscr.addnstr(self.status_y, 0, bar, w - 1, attr)
            self.stdscr.insstr(self.status_y, w - 1, bar[w - 1] if len(bar) > w - 1 else " ", attr)
        except curses.error:
            pass
        self.stdscr.noutrefresh()

    def _render_output_panel(self):
        win = self.output_win
        if win is None:
            return
        win.erase()
        h, w = win.getmaxyx()
        if h <= 0:
            win.noutrefresh()
            return

        theme = get_theme()
        bordered = theme.tui_bordered
        cx = 1 if bordered else 0
        cw = w - 2 if bordered else w

        total = len(self.output_lines)
        end = total - self.output_scroll
        start = max(end - h, 0)
        visible = self.output_lines[start:end]
        for i, line in enumerate(visible):
            display = line[:cw - 1] if len(line) >= cw else line
            try:
                if bordered:
                    win.addstr(i, 0, theme.border_v, curses.color_pair(1))
                if line.startswith("✓") or line.startswith("»"):
                    win.addnstr(i, cx, display, cw, curses.color_pair(2))
                elif line.startswith("✗") or line.startswith("×"):
                    win.addnstr(i, cx, display, cw, curses.color_pair(4))
                else:
                    win.addnstr(i, cx, display, cw)
                if bordered and w >= 2:
                    win.insstr(i, w - 1, theme.border_v, curses.color_pair(1))
            except curses.error:
                pass

        # Side borders on empty rows
        if bordered:
            for r in range(len(visible), h):
                try:
                    win.addstr(r, 0, theme.border_v, curses.color_pair(1))
                    win.insstr(r, w - 1, theme.border_v, curses.color_pair(1))
                except curses.error:
                    pass

        win.noutrefresh()

    def _render_input_line(self):
        h, w = self.stdscr.getmaxyx()
        y = self.input_y
        if y >= h:
            return

        theme = get_theme()
        bordered = theme.tui_bordered

        try:
            self.stdscr.move(y, 0)
            self.stdscr.clrtoeol()
        except curses.error:
            pass

        cx = 1 if bordered else 0
        prompt = self._get_prompt()

        try:
            if bordered:
                self.stdscr.addstr(y, 0, theme.border_v, curses.color_pair(1))
            self.stdscr.addnstr(y, cx, prompt, w - cx - 1, curses.color_pair(1))
            avail = w - cx - len(prompt) - (1 if bordered else 0) - 1
            if avail > 0:
                self.stdscr.addnstr(y, cx + len(prompt), self.input_buffer[:avail], avail)
            if bordered and w >= 2:
                self.stdscr.insstr(y, w - 1, theme.border_v, curses.color_pair(1))
        except curses.error:
            pass

        self.stdscr.noutrefresh()

    def _get_prompt(self) -> str:
        if self.input_mode == 'find':
            return "find> "
        if self.input_mode == 'add':
            proj = self._add_target_project or self.current_project or ''
            return f"add({proj})> " if proj else "add> "
        if self.input_mode == 'project_new':
            return "project new> "
        if self.input_mode == 'edit':
            return "edit> "
        if self.input_mode in ('pick_project', 'use_project'):
            return "project #? "
        if self.input_mode == 'confirm_delete':
            return "delete? (y/n) "
        if self.input_mode == 'confirm_delete_project':
            return "delete project? (y/n) "
        if self.input_mode == 'confirm_quit':
            return "quit? (y/n) "
        if self.input_mode == 'confirm_nuke':
            return "nuke? type 'yes': "
        if self.input_mode == 'setup_provider':
            return "provider [1/2/3]: "
        if self.input_mode == 'setup_token':
            return "token: "
        if self.input_mode == 'setup_repo_choice':
            return "choose [1/2]: "
        if self.input_mode == 'setup_repo_name':
            return "repo name: "
        if self.input_mode == 'setup_repo_url':
            return "repo URL: "
        if self.input_mode == 'setup_confirm':
            return "[Y/n]: "
        theme = get_theme()
        if self.current_project:
            return f"{theme.prompt_prefix}({self.current_project}){theme.prompt_arrow} "
        return f"{theme.prompt_prefix}{theme.prompt_arrow} "

    def _position_cursor(self):
        if self.mode == 'repl' or self.input_mode:
            cx = 1 if get_theme().tui_bordered else 0
            prompt_len = len(self._get_prompt())
            cursor_x = min(cx + prompt_len + self.input_cursor, self.width - 1)
            try:
                curses.curs_set(1)
                self.stdscr.move(self.input_y, cursor_x)
            except curses.error:
                pass
        else:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    def _toggle_mode(self):
        if self.input_mode:
            return
        self.mode = 'modal' if self.mode == 'repl' else 'repl'
        if self.mode == 'repl' and self.fullscreen:
            self.fullscreen = False
            self._create_windows()
        self._full_render()

    def _toggle_fullscreen(self):
        if self.input_mode:
            return
        self.fullscreen = not self.fullscreen
        if self.fullscreen and self.mode == 'repl':
            self.mode = 'modal'
        self._create_windows()
        self.stdscr.clear()
        self.stdscr.refresh()
        self._full_render()

    # ── Modal mode key handling ───────────────────────────────────────

    def _handle_modal_key(self, key):
        if self.input_mode:
            self._handle_input_mode_key(key)
            return

        if key == 27:  # ESC
            self._full_render()
            return

        if key in (curses.KEY_UP, ord('k')):
            if self.modal_cursor > 0:
                self.modal_cursor -= 1
                self._full_render()
            return

        if key in (curses.KEY_DOWN, ord('j')):
            if self.modal_cursor < len(self.nav_items) - 1:
                self.modal_cursor += 1
                self._full_render()
            return

        if key == ord('t'):
            self._modal_toggle()
            return

        if key == ord('A'):  # Shift+A: add child of current task
            self._modal_start_add_child()
            return

        if key == ord('a'):
            self._modal_start_add()
            return

        if key == ord('e'):
            self._modal_start_edit()
            return

        if key == ord('d'):
            self._modal_delete()
            return

        if key == ord('u'):
            self._modal_start_use()
            return

        if key == ord('c'):
            self._modal_toggle_collapse()
            return

        if key == ord('f'):
            self._modal_start_find()
            return

        if key == ord('s'):
            self._modal_stage_unstage()
            return

        if key == ord('h'):
            self._toggle_hide_done()
            return

        if key == ord('p'):
            self._modal_start_new_project()
            return

        if key == ord('P'):  # Shift+P: new subproject under current project
            self._modal_start_new_subproject()
            return

        if key == ord('q'):
            self._modal_quit()
            return

    def _modal_toggle(self):
        task = self._current_nav_task()
        if not task:
            return
        item = self._current_nav_item()
        task_idx = item[1]
        new_state = toggle_task_in_file(task.todo_path, task.line_no)
        state_str = "done" if new_state else "pending"
        self._add_output(f"✓ #{task_idx + 1} → {state_str}: {task.text}")
        self._propagate()
        self._refresh_tasks()
        self._full_render()

    def _modal_start_add(self):
        self._input_mode_output_start = len(self.output_lines)
        # Infer project: current scope, or from the highlighted item
        project = self.current_project or self._current_nav_project()
        if not project:
            self._add_output("✗ No project available. Create one first with 'new <name>'")
            self._full_render()
            return
        self._add_target_project = project
        # If the highlighted task is a subtask, add as a sibling (same indent)
        task = self._current_nav_task()
        if task and task.indent:
            self._add_indent = task.indent
            self._add_after_line = task.line_no
        else:
            self._add_indent = ""
            self._add_after_line = None
        self.input_mode = 'add'
        self.input_buffer = ''
        self.input_cursor = 0
        self._full_render()

    def _modal_start_add_child(self):
        self._input_mode_output_start = len(self.output_lines)
        task = self._current_nav_task()
        if not task:
            self._add_output("✗ Select a task to add a child to")
            self._full_render()
            return
        project = self.current_project or task.project_name
        self._add_target_project = project
        self._add_indent = task.indent + "    "
        self._add_after_line = task.line_no
        self.input_mode = 'add'
        self.input_buffer = ''
        self.input_cursor = 0
        self._full_render()

    def _modal_start_edit(self):
        self._input_mode_output_start = len(self.output_lines)
        task = self._current_nav_task()
        if not task:
            return
        item = self._current_nav_item()
        self.input_mode = 'edit'
        self.edit_task_index = item[1]
        self.input_buffer = task.text
        self.input_cursor = len(task.text)
        self._full_render()

    def _modal_delete(self):
        self._input_mode_output_start = len(self.output_lines)
        item = self._current_nav_item()
        if not item:
            return
        if item[0] == 'header':
            project_name = item[1]
            self._delete_target_project = project_name
            self._add_output(f"  Delete project '{project_name}' and all its tasks?")
            self.input_mode = 'confirm_delete_project'
            self.input_buffer = ''
            self.input_cursor = 0
            self._full_render()
            return
        task = self._current_nav_task()
        if not task:
            return
        self._delete_target_index = item[1]
        self._add_output(f"  Delete '{task.text}'?")
        self.input_mode = 'confirm_delete'
        self.input_buffer = ''
        self.input_cursor = 0
        self._full_render()

    def _modal_start_use(self):
        self._input_mode_output_start = len(self.output_lines)
        projects = self.manager.list_projects()
        if not projects:
            self._add_output("✗ No projects.")
            self._full_render()
            return
        self._add_output("  Switch to project (name or #, empty for global):")
        for i, p in enumerate(projects, 1):
            marker = " ●" if p['name'] == self.current_project else ""
            self._add_output(f"    {i}) {p['name']}{marker}")
        self.input_mode = 'use_project'
        self.input_buffer = ''
        self.input_cursor = 0
        self._full_render()

    def _modal_start_find(self):
        self._input_mode_output_start = len(self.output_lines)
        self.input_mode = 'find'
        self.input_buffer = ''
        self.input_cursor = 0
        self.find_filter = ''
        self._full_render()

    def _modal_start_new_project(self):
        self._input_mode_output_start = len(self.output_lines)
        self.input_mode = 'project_new'
        self.input_buffer = ''
        self.input_cursor = 0
        self._full_render()

    def _modal_start_new_subproject(self):
        self._input_mode_output_start = len(self.output_lines)
        project = self.current_project or self._current_nav_project()
        prefix = f"{project}/" if project else ''
        self.input_mode = 'project_new'
        self.input_buffer = prefix
        self.input_cursor = len(prefix)
        self._full_render()

    def _modal_quit(self):
        self._input_mode_output_start = len(self.output_lines)
        self._add_output("  Quit?")
        self.input_mode = 'confirm_quit'
        self.input_buffer = ''
        self.input_cursor = 0
        self._full_render()

    def _modal_toggle_collapse(self):
        """Toggle collapse for the project of the highlighted item."""
        if self.current_project:
            return
        project = self._current_nav_project()
        if not project:
            return
        if project in self.collapsed_projects:
            self.collapsed_projects.discard(project)
        else:
            self.collapsed_projects.add(project)
        self._rebuild_nav_items()
        self._full_render()

    def _toggle_hide_done(self):
        self.hide_done = not self.hide_done
        self.modal_cursor = 0
        self.task_scroll = 0
        self._refresh_tasks()
        if self.hide_done:
            self._add_output("✓ Hiding completed tasks")
        else:
            self._add_output("✓ Showing all tasks")
        self._full_render()

    def _toggle_stage_view(self):
        if self.input_mode:
            return
        self.stage_view = not self.stage_view
        self.modal_cursor = 0
        self.task_scroll = 0
        self._refresh_tasks()
        if self.stage_view:
            self._add_output("⚡ Staging view")
        else:
            self._add_output("✓ Normal view")
        self._full_render()

    def _modal_stage_unstage(self):
        item = self._current_nav_item()
        if not item:
            return

        if item[0] == 'header':
            self._stage_unstage_project(item[1])
            return

        task = self._current_nav_task()
        if not task:
            return
        if not task.task_id:
            self._add_output("✗ Task has no ID")
            self._full_render()
            return
        staged_ids = self.manager.load_staged_ids()
        child_ids = get_children_ids(self.tasks, task)
        if task.task_id in staged_ids:
            staged_ids.discard(task.task_id)
            for cid in child_ids:
                staged_ids.discard(cid)
            self.manager.save_staged_ids(staged_ids)
            self._add_output(f"✓ Unstaged: {task.text}")
            if self.stage_view:
                self._refresh_tasks()
                if self.modal_cursor >= len(self.nav_items) and self.nav_items:
                    self.modal_cursor = len(self.nav_items) - 1
        else:
            staged_ids.add(task.task_id)
            for cid in child_ids:
                staged_ids.add(cid)
            self.manager.save_staged_ids(staged_ids)
            self._add_output(f"⚡ Staged: {task.text}")
        self._full_render()

    def _stage_unstage_project(self, project_name: str):
        """Stage or unstage all tasks belonging to a project and its subprojects."""
        project_tasks = [
            t for t in self.tasks
            if t.project_name == project_name or t.project_name.startswith(project_name + "/")
        ]
        if not project_tasks:
            self._add_output(f"✗ No tasks in {project_name}")
            self._full_render()
            return
        task_ids = {t.task_id for t in project_tasks if t.task_id}
        if not task_ids:
            self._add_output(f"✗ Tasks in {project_name} have no IDs")
            self._full_render()
            return
        staged_ids = self.manager.load_staged_ids()
        # If all are already staged, unstage them; otherwise stage all
        if task_ids <= staged_ids:
            staged_ids -= task_ids
            self.manager.save_staged_ids(staged_ids)
            self._add_output(f"✓ Unstaged {len(task_ids)} tasks from {project_name}")
            if self.stage_view:
                self._refresh_tasks()
                if self.modal_cursor >= len(self.nav_items) and self.nav_items:
                    self.modal_cursor = len(self.nav_items) - 1
        else:
            staged_ids |= task_ids
            self.manager.save_staged_ids(staged_ids)
            self._add_output(f"⚡ Staged {len(task_ids)} tasks from {project_name}")
        self._full_render()

    def _handle_input_mode_key(self, key):
        if key == 27:  # ESC - cancel
            if self.input_mode == 'find':
                self.find_filter = ''
                self._reset_input_mode()
                self._rebuild_nav_items()
                self._full_render()
                return
            self._cancel_input_mode()
            return

        if self.input_mode == 'find':
            if key in (curses.KEY_ENTER, 10, 13):
                self.find_filter = self.input_buffer.strip().lower()
                self._reset_input_mode()
                self._rebuild_nav_items()
                self._full_render()
                return
            self._edit_input_buffer(key)
            self.find_filter = self.input_buffer.strip().lower()
            self.modal_cursor = 0
            self.task_scroll = 0
            self._rebuild_nav_items()
            self._render_task_panel()
            self._render_input_line()
            self._position_cursor()
            curses.doupdate()
            return

        # Confirm delete: respond to single y/n keypress
        if self.input_mode == 'confirm_delete':
            if key in (ord('y'), ord('Y')):
                self._do_confirmed_delete()
            else:
                self._add_output("(cancelled)")
                self._reset_input_mode()
                self._full_render()
            return

        # Confirm delete project: respond to single y/n keypress
        if self.input_mode == 'confirm_delete_project':
            if key in (ord('y'), ord('Y')):
                name = self._delete_target_project
                if name and self.manager.remove_project(name):
                    self._add_output(f"✓ Deleted project: {name}")
                    if self.current_project == name:
                        self.current_project = None
                    self._propagate()
                    self._refresh_tasks()
                    if self.modal_cursor >= len(self.nav_items) and self.nav_items:
                        self.modal_cursor = len(self.nav_items) - 1
                else:
                    self._add_output(f"✗ Project '{name}' not found")
            else:
                self._add_output("(cancelled)")
            self._reset_input_mode()
            self._full_render()
            return

        # Confirm quit: respond to single y/n keypress
        if self.input_mode == 'confirm_quit':
            if key in (ord('y'), ord('Y')):
                self._reset_input_mode()
                self._quit()
            else:
                self._add_output("(cancelled)")
                self._reset_input_mode()
                self._full_render()
            return

        # Confirm nuke: user types 'yes' and presses Enter
        if self.input_mode == 'confirm_nuke':
            if key in (curses.KEY_ENTER, 10, 13):
                if self.input_buffer.strip().lower() == 'yes':
                    try:
                        self.manager.nuke_all(force=True)
                        self._add_output("✓ All todo data removed. Restart to start fresh.")
                    except Exception as exc:
                        self._add_output(f"✗ {exc}")
                else:
                    self._add_output("(cancelled)")
                self._reset_input_mode()
                self._full_render()
                return
            self._edit_input_buffer(key)
            self._render_input_line()
            self._position_cursor()
            curses.doupdate()
            return

        # Pick project (for add) or use project: respond to Enter
        if self.input_mode in ('pick_project', 'use_project'):
            if key in (curses.KEY_ENTER, 10, 13):
                if self.input_mode == 'use_project':
                    self._commit_use_project()
                else:
                    self._commit_pick_project()
                return
            self._edit_input_buffer(key)
            self._render_input_line()
            self._position_cursor()
            curses.doupdate()
            return

        # Setup wizard steps: respond to Enter
        if self.input_mode and self.input_mode.startswith('setup_'):
            if key in (curses.KEY_ENTER, 10, 13):
                self._commit_setup_step()
                return
            self._edit_input_buffer(key)
            self._render_input_line()
            self._position_cursor()
            curses.doupdate()
            return

        if key in (curses.KEY_ENTER, 10, 13):
            self._commit_input_mode()
            return

        self._edit_input_buffer(key)
        self._render_input_line()
        self._position_cursor()
        curses.doupdate()

    def _cancel_input_mode(self):
        self._add_output("(cancelled)")
        self._reset_input_mode()
        self._full_render()

    def _reset_input_mode(self):
        self.input_mode = None
        self.input_buffer = ''
        self.input_cursor = 0
        self.edit_task_index = None
        self._pending_add_text = None
        self._add_target_project = None
        self._add_indent = ""
        self._add_after_line = None
        self._delete_target_index = None
        self._delete_target_project = None
        self._setup_provider = None
        self._setup_token = None
        self._setup_username = None
        self._setup_group_name = None

    def _do_confirmed_delete(self):
        idx = self._delete_target_index
        if idx is not None and idx < len(self.tasks):
            task = self.tasks[idx]
            if remove_task_from_file(task.todo_path, task.line_no):
                self._add_output(f"✓ Removed: {task.text}")
                self._propagate()
                self._refresh_tasks()
                if self.modal_cursor >= len(self.tasks) and self.tasks:
                    self.modal_cursor = len(self.tasks) - 1
            else:
                self._add_output("✗ Failed to remove task")
        self._reset_input_mode()
        self._full_render()

    def _commit_pick_project(self):
        choice = self.input_buffer.strip()
        projects = self.manager.list_projects()
        target = None

        # Try as a number first
        try:
            n = int(choice)
            if 1 <= n <= len(projects):
                target = projects[n - 1]['name']
        except ValueError:
            # Try as a name / prefix
            for p in projects:
                if p['name'] == choice:
                    target = p['name']
                    break
                if p['name'].startswith(choice):
                    target = p['name']

        if not target:
            self._add_output(f"✗ Invalid choice: {choice}")
            self._reset_input_mode()
            self._full_render()
            return

        text = self._pending_add_text
        if text:
            target_file = self.manager.get_project_path(target)
            if target_file:
                add_task_to_file(target_file, text)
                self._add_output(f"✓ Added to {target}: {text}")
                self._propagate()
                self._refresh_tasks()
            else:
                self._add_output(f"✗ Project not found: {target}")

        self._reset_input_mode()
        self._full_render()

    def _commit_use_project(self):
        choice = self.input_buffer.strip()
        projects = self.manager.list_projects()

        if not choice:
            # Empty input → global scope
            self.current_project = None
            self._refresh_tasks()
            self.modal_cursor = 0
            self.task_scroll = 0
            self._add_output("✓ Switched to global scope")
            self._reset_input_mode()
            self._full_render()
            return

        target = None
        try:
            n = int(choice)
            if 1 <= n <= len(projects):
                target = projects[n - 1]['name']
        except ValueError:
            for p in projects:
                if p['name'] == choice:
                    target = p['name']
                    break
                if p['name'].startswith(choice):
                    target = p['name']

        if not target:
            self._add_output(f"✗ Invalid choice: {choice}")
        else:
            self.current_project = target
            self._refresh_tasks()
            self.modal_cursor = 0
            self.task_scroll = 0
            self._add_output(f"✓ Switched to: {target}")

        self._reset_input_mode()
        self._full_render()

    def _commit_input_mode(self):
        text = self.input_buffer.strip()

        if self.input_mode == 'project_new' and text:
            try:
                self.manager.create_project(text)
                self._refresh_tasks()
                self._move_cursor_to_project(text)
                self._add_output(f"✓ Created project: {text}")
            except ValueError as e:
                self._add_output(f"✗ {e}")
            self._reset_input_mode()
            self._full_render()
            return

        if self.input_mode == 'add' and text:
            project = self._add_target_project or self.current_project
            target_file = self.manager.get_project_path(project)
            if target_file:
                add_task_to_file(target_file, text,
                                 indent=self._add_indent,
                                 after_line=self._add_after_line)
                self._add_output(f"✓ Added: {text}")
                self._propagate()
                self._refresh_tasks()
            else:
                self._add_output(f"✗ Project not found: {project}")
        elif self.input_mode == 'edit' and text and self.edit_task_index is not None:
            task = self.tasks[self.edit_task_index]
            if edit_task_in_file(task.todo_path, task.line_no, text):
                self._add_output(f"✓ Updated: {text}")
                self._propagate()
                self._refresh_tasks()
            else:
                self._add_output("✗ Failed to edit task")

        self._reset_input_mode()
        self._full_render()

    # ── REPL mode key handling ────────────────────────────────────────

    def _handle_repl_key(self, key):
        if self.input_mode:
            self._handle_input_mode_key(key)
            return

        if key in (curses.KEY_ENTER, 10, 13):
            self._execute_command()
            return

        if key == curses.KEY_UP:
            self._history_prev()
            return

        if key == curses.KEY_DOWN:
            self._history_next()
            return

        if key in (curses.KEY_PPAGE, curses.KEY_SR):  # Page Up or Shift+Up
            self._output_scroll_up()
            return

        if key in (curses.KEY_NPAGE, curses.KEY_SF):  # Page Down or Shift+Down
            self._output_scroll_down()
            return

        self._edit_input_buffer(key)
        self._render_input_line()
        self._position_cursor()
        curses.doupdate()

    def _edit_input_buffer(self, key):
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.input_cursor > 0:
                self.input_buffer = (
                    self.input_buffer[:self.input_cursor - 1] +
                    self.input_buffer[self.input_cursor:]
                )
                self.input_cursor -= 1
        elif key == curses.KEY_DC:
            if self.input_cursor < len(self.input_buffer):
                self.input_buffer = (
                    self.input_buffer[:self.input_cursor] +
                    self.input_buffer[self.input_cursor + 1:]
                )
        elif key == curses.KEY_LEFT:
            if self.input_cursor > 0:
                self.input_cursor -= 1
        elif key == curses.KEY_RIGHT:
            if self.input_cursor < len(self.input_buffer):
                self.input_cursor += 1
        elif key in (curses.KEY_HOME, 1):  # Ctrl+A
            self.input_cursor = 0
        elif key in (curses.KEY_END, 5):  # Ctrl+E
            self.input_cursor = len(self.input_buffer)
        elif key == 21:  # Ctrl+U
            self.input_buffer = ''
            self.input_cursor = 0
        elif key == 23:  # Ctrl+W
            pos = self.input_cursor
            while pos > 0 and self.input_buffer[pos - 1] == ' ':
                pos -= 1
            while pos > 0 and self.input_buffer[pos - 1] != ' ':
                pos -= 1
            self.input_buffer = self.input_buffer[:pos] + self.input_buffer[self.input_cursor:]
            self.input_cursor = pos
        elif key == 9:  # Tab
            self._tab_complete()
        elif 32 <= key <= 126:
            ch = chr(key)
            self.input_buffer = (
                self.input_buffer[:self.input_cursor] +
                ch +
                self.input_buffer[self.input_cursor:]
            )
            self.input_cursor += 1

    def _history_prev(self):
        if not self.cmd_history:
            return
        if self.history_pos == -1:
            self.history_stash = self.input_buffer
            self.history_pos = len(self.cmd_history) - 1
        elif self.history_pos > 0:
            self.history_pos -= 1
        else:
            return
        self.input_buffer = self.cmd_history[self.history_pos]
        self.input_cursor = len(self.input_buffer)
        self._render_input_line()
        self._position_cursor()
        curses.doupdate()

    def _history_next(self):
        if self.history_pos == -1:
            return
        if self.history_pos < len(self.cmd_history) - 1:
            self.history_pos += 1
            self.input_buffer = self.cmd_history[self.history_pos]
        else:
            self.history_pos = -1
            self.input_buffer = self.history_stash
        self.input_cursor = len(self.input_buffer)
        self._render_input_line()
        self._position_cursor()
        curses.doupdate()

    _TAB_COMMANDS = [
        'help', 'projects', 'use', 'ls', 'show', 'add', 'addc',
        'toggle', 'check', 'uncheck', 'edit', 'rm', 'project',
        'hide', 'stage', 'unstage', 'staged',
        'group', 'setup', 'sync', 'push', 'pull',
        'status', 'theme', 'config', 'nuke', 'link', 'unlink',
        'clear', 'quit', 'exit',
    ]

    def _tab_complete(self):
        text = self.input_buffer[:self.input_cursor]
        if ' ' in text:
            return  # only complete the first word
        if not text:
            return
        matches = [c for c in self._TAB_COMMANDS if c.startswith(text.lower())]
        if len(matches) == 1:
            self.input_buffer = matches[0] + ' ' + self.input_buffer[self.input_cursor:]
            self.input_cursor = len(matches[0]) + 1
            self._render_input_line()
            self._position_cursor()
            curses.doupdate()
        elif matches:
            self._add_output("  " + "  ".join(matches))
            self._render_output_panel()
            self._render_input_line()
            self._position_cursor()
            curses.doupdate()

    def _output_scroll_up(self):
        max_scroll = max(len(self.output_lines) - self.output_h, 0)
        self.output_scroll = min(self.output_scroll + self.output_h, max_scroll)
        self._render_output_panel()
        curses.doupdate()

    def _output_scroll_down(self):
        self.output_scroll = max(self.output_scroll - self.output_h, 0)
        self._render_output_panel()
        curses.doupdate()

    def _execute_command(self):
        line = self.input_buffer.strip()
        self.input_buffer = ''
        self.input_cursor = 0
        self.history_pos = -1

        if not line:
            self._full_render()
            return

        self.cmd_history.append(line)

        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()

        cmd = parts[0].lower()
        args = parts[1:]

        handler = {
            'help': self._cmd_help,
            '?': self._cmd_help,
            'projects': self._cmd_projects,
            'use': self._cmd_use,
            'ls': self._cmd_ls,
            'show': self._cmd_show,
            'add': self._cmd_add,
            'addc': self._cmd_addc,
            'toggle': self._cmd_toggle,
            't': self._cmd_toggle,
            'find': self._cmd_find,
            'hide': self._cmd_hide,
            'check': self._cmd_check,
            'uncheck': self._cmd_uncheck,
            'edit': self._cmd_edit,
            'e': self._cmd_edit,
            'rm': self._cmd_rm,
            'project': self._cmd_project,
            'stage': self._cmd_stage,
            'unstage': self._cmd_unstage,
            'staged': self._cmd_staged,
            'group': self._cmd_group,
            'setup': self._cmd_setup,
            'sync': self._cmd_sync,
            'push': self._cmd_push,
            'pull': self._cmd_pull,
            'status': self._cmd_status,
            'theme': self._cmd_theme,
            'config': self._cmd_config,
            'nuke': self._cmd_nuke,
            'link': self._cmd_link,
            'unlink': self._cmd_unlink,
            'clear': self._cmd_clear,
            'quit': self._cmd_quit,
            'q': self._cmd_quit,
            'exit': self._cmd_quit,
        }.get(cmd)

        if handler:
            try:
                handler(args)
            except Exception as exc:
                self._add_output(f"✗ {exc}")
        else:
            try:
                n = int(cmd)
                self._cmd_toggle([str(n)])
            except ValueError:
                self._add_output(f"✗ Unknown command: {cmd}")
                self._add_output("  Type 'help' for available commands")

        self._full_render()

    # ── Task management ───────────────────────────────────────────────

    def _refresh_tasks(self):
        self.tasks = []
        if self.current_project:
            path = self.manager.get_project_path(self.current_project)
            if path and path.exists():
                self.tasks = parse_tasks_from_file(path, self.current_project)
        else:
            project_paths = sorted(self.manager.get_all_project_paths(), key=lambda x: x[0])
            for name, path in project_paths:
                tasks = parse_tasks_from_file(path, name)
                self.tasks.extend(tasks)
        if self.stage_view:
            staged_ids = self.manager.load_staged_ids()
            self.tasks = [t for t in self.tasks if t.task_id in staged_ids]
        if self.hide_done:
            self.tasks = [t for t in self.tasks if not t.checked]
        self._rebuild_nav_items()

    def _is_project_collapsed(self, project_name: str) -> bool:
        """Check if a project or any of its ancestors is collapsed."""
        if project_name in self.collapsed_projects:
            return True
        parts = project_name.split("/")
        for i in range(1, len(parts)):
            ancestor = "/".join(parts[:i])
            if ancestor in self.collapsed_projects:
                return True
        return False

    def _rebuild_nav_items(self):
        """Build the list of navigable items for modal mode.

        In project scope: all items are tasks.
        In global scope: for expanded projects, items are tasks;
                         for collapsed projects, one header item per project.
        Ancestor headers are emitted before subproject headers.

        When find_filter is set, only tasks matching the filter are included.
        """
        self.nav_items = []
        if self.current_project:
            for i in range(len(self.tasks)):
                if self.find_filter and self.find_filter not in self.tasks[i].text.lower():
                    continue
                self.nav_items.append(('task', i))
        else:
            # Group tasks by project for ordered iteration
            tasks_by_project = {}
            for i, task in enumerate(self.tasks):
                if self.find_filter and self.find_filter not in task.text.lower():
                    continue
                tasks_by_project.setdefault(task.project_name, []).append(i)

            # Merge project names from tasks and registry, sorted
            all_names = set(tasks_by_project.keys())
            if not self.find_filter and not self.stage_view:
                all_names |= set(p["name"] for p in self.manager.list_projects())
            sorted_projects = sorted(all_names)

            seen_projects = set()
            for pname in sorted_projects:
                if pname in seen_projects:
                    continue
                seen_projects.add(pname)
                # Emit ancestor headers
                parts = pname.split("/")
                for j in range(1, len(parts)):
                    ancestor = "/".join(parts[:j])
                    if ancestor not in seen_projects:
                        seen_projects.add(ancestor)
                        self.nav_items.append(('header', ancestor))
                collapsed = self._is_project_collapsed(pname)
                self.nav_items.append(('header', pname))
                if collapsed:
                    continue
                for task_idx in tasks_by_project.get(pname, []):
                    if not self._is_project_collapsed(pname):
                        self.nav_items.append(('task', task_idx))
        # Clamp cursor
        if self.nav_items:
            self.modal_cursor = max(0, min(self.modal_cursor, len(self.nav_items) - 1))

    def _current_nav_item(self):
        """Return the current nav item tuple, or None."""
        if not self.nav_items or self.modal_cursor >= len(self.nav_items):
            return None
        return self.nav_items[self.modal_cursor]

    def _current_nav_task(self) -> Optional[TaskRef]:
        """Return the TaskRef for the current nav item, or None if it's a header."""
        item = self._current_nav_item()
        if item and item[0] == 'task':
            return self.tasks[item[1]]
        return None

    def _current_nav_project(self) -> Optional[str]:
        """Return the project name for the current nav item."""
        item = self._current_nav_item()
        if not item:
            return None
        if item[0] == 'header':
            return item[1]
        return self.tasks[item[1]].project_name

    def _move_cursor_to_project(self, name: str):
        """Move the modal cursor to the header for the given project name."""
        for idx, item in enumerate(self.nav_items):
            if item == ('header', name):
                self.modal_cursor = idx
                return

    def _propagate(self):
        self.dirty = True

    def _sync_quiet(self) -> dict:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            result = self.manager.sync()
        except Exception:
            result = {"sync": {"status": "error"}, "conflicts": []}
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        return result

    def _start_background_sync(self):
        """Start background sync in fetch-only mode.

        The background thread only runs git fetch + SHA comparison.
        The main thread applies pull/merge at safe points via _check_pending_sync().
        """
        self._main_sync = MainSync(self.manager.home_dir, self.manager.config)
        if self._main_sync.is_sync_enabled():
            interval = self.manager.config.get("sync_interval", 1800)
            self._bg_sync = BackgroundSync(
                self._main_sync, interval=interval,
            )
            self._bg_sync.start()

    def _stop_background_sync(self):
        """Stop background sync checker."""
        if self._bg_sync:
            self._bg_sync.stop()
            self._bg_sync = None

    def _check_pending_sync(self):
        """Check if background fetch detected remote changes.

        If the remote is ahead, do the actual pull/merge here on the main
        thread — this is a safe point between user actions so there are no
        concurrent disk writes.
        """
        if not self._bg_sync or not self._bg_sync.state.needs_apply:
            return
        self._bg_sync.state.mark_applied()
        result = self._sync_quiet()
        self._refresh_tasks()
        conflicts = result.get("conflicts", [])
        if conflicts:
            self._add_output(f"⚠ synced with {len(conflicts)} conflict(s)")
            for c in conflicts:
                self._add_output(f"  ⚠ {c}")
        else:
            self._add_output("↓ synced from remote")
        self._full_render()

    def _add_output(self, text: str):
        for line in text.split('\n'):
            self.output_lines.append(line)
        self.output_scroll = 0

    def _get_task(self, n: int) -> Optional[TaskRef]:
        if n < 1 or n > len(self.tasks):
            self._add_output(f"✗ Invalid task number: {n} (valid: 1-{len(self.tasks)})")
            return None
        return self.tasks[n - 1]

    def _set_project(self, name: str):
        projects = self.manager.list_projects()
        match = None
        for p in projects:
            if p['name'] == name:
                match = name
                break
            if p['name'].startswith(name):
                match = p['name']
        if match:
            self.current_project = match
            self._refresh_tasks()
        else:
            self._add_output(f"✗ Project not found: {name}")

    def _quit(self):
        self._stop_background_sync()
        if self.dirty:
            auto_sync = self.manager.config.get("auto_sync_on_edit", True)
            if auto_sync:
                self._quit_with_sync()
                return
        raise SystemExit(0)

    def _quit_with_sync(self):
        """Sync before exit with an animated progress indicator."""
        import threading

        result_holder = [None]
        error_holder = [None]

        def do_sync():
            try:
                result_holder[0] = self._sync_quiet()
            except Exception as e:
                error_holder[0] = e

        sync_thread = threading.Thread(target=do_sync, daemon=True)
        sync_thread.start()

        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        frame_idx = 0
        h, w = self.stdscr.getmaxyx()
        y = self.input_y

        self.stdscr.timeout(100)
        try:
            while sync_thread.is_alive():
                spinner = frames[frame_idx % len(frames)]
                msg = f"  {spinner} syncing before exit..."
                try:
                    self.stdscr.move(y, 0)
                    self.stdscr.clrtoeol()
                    self.stdscr.addnstr(y, 0, msg, w - 1, curses.color_pair(1))
                    self.stdscr.refresh()
                except curses.error:
                    pass
                frame_idx += 1
                self.stdscr.getch()  # consume timeout, drives the animation
        finally:
            self.stdscr.timeout(1000)

        sync_thread.join(timeout=5)
        raise SystemExit(0)

    # ── Command handlers ──────────────────────────────────────────────

    def _cmd_help(self, args):
        self._add_output("Navigation:")
        self._add_output("  projects        List all projects")
        self._add_output("  use <project>   Switch to a project scope")
        self._add_output("  use             Switch to global scope")
        self._add_output("Viewing:")
        self._add_output("  ls              List tasks")
        self._add_output("  find <text>     Search tasks (find with no args clears filter)")
        self._add_output("  hide            Toggle hiding completed tasks")
        self._add_output("  show <n>        Show task details")
        self._add_output("  status          Show status")
        self._add_output("Tasks:")
        self._add_output("  add <text>      Add a new task")
        self._add_output("  addc <n> <text> Add a child task to task #n")
        self._add_output("  toggle <n>      Toggle task")
        self._add_output("  check <n>       Mark done")
        self._add_output("  uncheck <n>     Mark pending")
        self._add_output("  edit <n> <text> Edit task")
        self._add_output("  rm <n>          Remove task")
        self._add_output("  <n>             Toggle shorthand")
        self._add_output("Staging:")
        self._add_output("  stage <n>       Stage task(s) for focused work")
        self._add_output("  unstage <n>     Unstage task(s)")
        self._add_output("  staged          Show staged tasks")
        self._add_output("  Ctrl+S          Toggle staging view")
        self._add_output("Projects:")
        self._add_output("  project new <name>      Create project")
        self._add_output("  project delete <name>   Delete project")
        self._add_output("Groups:")
        self._add_output("  group new <name>          Create a group")
        self._add_output("  group add <proj> <group>  Add project to group")
        self._add_output("  group sync <group>        Setup git remote for group")
        self._add_output("  group invite <grp> <user> Invite user to group")
        self._add_output("  group join <grp> <url>    Join a shared group")
        self._add_output("  group list                List groups")
        self._add_output("Sync:")
        self._add_output("  setup           Setup multi-device sync")
        self._add_output("  sync            Sync now")
        self._add_output("Config:")
        self._add_output("  config          Show configuration")
        self._add_output("  config k v      Set config key=value")
        self._add_output("  link <proj> [p] Symlink TODO.md to project")
        self._add_output("  unlink <proj>   Remove TODO.md symlink")
        self._add_output("  nuke            Delete all todo data")
        self._add_output("Other:")
        self._add_output("  theme [name]    View/switch UI theme")
        self._add_output("  clear           Clear output")
        self._add_output("  quit/q          Exit")
        self._add_output("  Ctrl+T          Toggle modal mode")

    def _cmd_projects(self, args):
        projects = self.manager.list_projects()
        if not projects:
            self._add_output("No projects. Use 'project new <name>' to create one.")
            return
        sorted_projects = sorted(projects, key=lambda p: p["name"])
        for p in sorted_projects:
            full_name = p['name']
            depth = full_name.count("/")
            display_name = full_name.rsplit("/", 1)[-1] if "/" in full_name else full_name
            indent = "  " + "    " * depth
            marker = " ●" if full_name == self.current_project else ""
            shared = f" (shared: {', '.join(p['shared_in'])})" if p['shared_in'] else ""
            self._add_output(f"{indent}{display_name}: {p['todo_count']} pending{shared}{marker}")

    def _cmd_use(self, args):
        if not args:
            self.current_project = None
            self._refresh_tasks()
            self.modal_cursor = 0
            self.task_scroll = 0
            self._add_output("✓ Switched to global scope")
            return
        self._set_project(args[0])
        self.modal_cursor = 0
        self.task_scroll = 0
        if self.current_project:
            self._add_output(f"✓ Switched to: {self.current_project}")

    def _cmd_ls(self, args):
        self._refresh_tasks()
        if not self.tasks:
            self._add_output("  No tasks found")
            return
        for i, task in enumerate(self.tasks, 1):
            checkbox = "[x]" if task.checked else "[ ]"
            self._add_output(f"  {i:>3} {checkbox} {task.text}")

    def _cmd_find(self, args):
        if not args:
            if self.find_filter:
                self.find_filter = ''
                self._rebuild_nav_items()
                self._add_output("✓ Find filter cleared")
            else:
                self._add_output("✗ Usage: find <text>")
            return
        query = ' '.join(args).lower()
        self.find_filter = query
        self._rebuild_nav_items()
        matching = [t for t in self.tasks if query in t.text.lower()]
        if not matching:
            self._add_output(f"  No tasks matching '{' '.join(args)}'")
        else:
            self._add_output(f"  Found {len(matching)} task(s) matching '{' '.join(args)}'")

    def _cmd_hide(self, args):
        self._toggle_hide_done()

    def _cmd_show(self, args):
        if not args:
            self._add_output("✗ Usage: show <n>")
            return
        try:
            n = int(args[0])
        except ValueError:
            self._add_output("✗ Expected a number")
            return
        task = self._get_task(n)
        if not task:
            return
        checkbox = "[x]" if task.checked else "[ ]"
        self._add_output(f"  Task #{n}")
        self._add_output(f"  {checkbox} {task.text}")
        self._add_output(f"  Project: {task.project_name}")
        self._add_output(f"  File:    {task.todo_path}")
        self._add_output(f"  Line:    {task.line_no + 1}")

    def _cmd_add(self, args):
        if not args:
            self._add_output("✗ Usage: add <task text>")
            return
        text = " ".join(args)
        if not self.current_project:
            # Prompt user to pick a project
            projects = self.manager.list_projects()
            if not projects:
                self._add_output("✗ No projects. Use 'project new <name>' to create one.")
                return
            if len(projects) == 1:
                # Only one project, use it directly
                target_file = self.manager.get_project_path(projects[0]['name'])
                add_task_to_file(target_file, text)
                self._propagate()
                self._refresh_tasks()
                self._add_output(f"✓ Added to {projects[0]['name']}: {text}")
                return
            self._input_mode_output_start = len(self.output_lines)
            self._add_output("  Pick a project:")
            for i, p in enumerate(projects, 1):
                self._add_output(f"    {i}) {p['name']}")
            self._pending_add_text = text
            self.input_mode = 'pick_project'
            self.input_buffer = ''
            self.input_cursor = 0
            return
        target_file = self.manager.get_project_path(self.current_project)
        if not target_file:
            self._add_output(f"✗ Project not found: {self.current_project}")
            return
        add_task_to_file(target_file, text)
        self._propagate()
        self._refresh_tasks()
        self._add_output(f"✓ Added: {text}")

    def _cmd_addc(self, args):
        if len(args) < 2:
            self._add_output("✗ Usage: addc <n> <task text>")
            return
        try:
            n = int(args[0])
        except ValueError:
            self._add_output(f"✗ Expected a number, got: {args[0]}")
            return
        parent = self._get_task(n)
        if not parent:
            return
        text = " ".join(args[1:])
        child_indent = parent.indent + "    "
        add_task_to_file(parent.todo_path, text, indent=child_indent,
                         after_line=parent.line_no)
        self._propagate()
        self._refresh_tasks()
        self._add_output(f"✓ Added under #{n}: {text}")

    def _cmd_toggle(self, args):
        if not args:
            self._add_output("✗ Usage: toggle <n> [n2 n3 ...]")
            return
        for arg in args:
            try:
                n = int(arg)
            except ValueError:
                self._add_output(f"✗ Expected a number, got: {arg}")
                continue
            task = self._get_task(n)
            if not task:
                continue
            new_state = toggle_task_in_file(task.todo_path, task.line_no)
            state_str = "done" if new_state else "pending"
            self._add_output(f"✓ #{n} → {state_str}: {task.text}")
        self._propagate()
        self._refresh_tasks()

    def _cmd_check(self, args):
        if not args:
            self._add_output("✗ Usage: check <n>")
            return
        changed = False
        for arg in args:
            try:
                n = int(arg)
            except ValueError:
                self._add_output(f"✗ Expected a number, got: {arg}")
                continue
            task = self._get_task(n)
            if not task:
                continue
            if not task.checked:
                toggle_task_in_file(task.todo_path, task.line_no)
                changed = True
                self._add_output(f"✓ #{n} → done: {task.text}")
            else:
                self._add_output(f"  #{n} already done")
        if changed:
            self._propagate()
        self._refresh_tasks()

    def _cmd_uncheck(self, args):
        if not args:
            self._add_output("✗ Usage: uncheck <n>")
            return
        changed = False
        for arg in args:
            try:
                n = int(arg)
            except ValueError:
                self._add_output(f"✗ Expected a number, got: {arg}")
                continue
            task = self._get_task(n)
            if not task:
                continue
            if task.checked:
                toggle_task_in_file(task.todo_path, task.line_no)
                changed = True
                self._add_output(f"✓ #{n} → pending: {task.text}")
            else:
                self._add_output(f"  #{n} already pending")
        if changed:
            self._propagate()
        self._refresh_tasks()

    def _cmd_edit(self, args):
        if len(args) < 2:
            self._add_output("✗ Usage: edit <n> <new text>")
            return
        try:
            n = int(args[0])
        except ValueError:
            self._add_output("✗ Expected a number")
            return
        task = self._get_task(n)
        if not task:
            return
        new_text = " ".join(args[1:])
        if edit_task_in_file(task.todo_path, task.line_no, new_text):
            self._add_output(f"✓ #{n} updated: {new_text}")
            self._propagate()
            self._refresh_tasks()
        else:
            self._add_output("✗ Failed to edit task")

    def _cmd_rm(self, args):
        if not args:
            self._add_output("✗ Usage: rm <n>")
            return
        try:
            n = int(args[0])
        except ValueError:
            self._add_output("✗ Expected a number")
            return
        task = self._get_task(n)
        if not task:
            return
        if remove_task_from_file(task.todo_path, task.line_no):
            self._add_output(f"✓ Removed: {task.text}")
            self._propagate()
            self._refresh_tasks()
        else:
            self._add_output("✗ Failed to remove task")

    def _cmd_project(self, args):
        if not args:
            self._add_output("✗ Usage: project <new|delete> ...")
            return
        sub = args[0].lower()
        if sub == 'new':
            if len(args) < 2:
                self._add_output("✗ Usage: project new <name>")
                return
            name = args[1]
            self.manager.create_project(name)
            self._refresh_tasks()
            self._move_cursor_to_project(name)
            self._add_output(f"✓ Created project: {name}")
        elif sub == 'delete':
            if len(args) < 2:
                self._add_output("✗ Usage: project delete <name>")
                return
            self._delete_target_project = args[1]
            self._input_mode_output_start = len(self.output_lines)
            self._add_output(f"  Delete project '{args[1]}' and all its tasks?")
            self.input_mode = 'confirm_delete_project'
            self.input_buffer = ''
            self.input_cursor = 0
        else:
            self._add_output(f"✗ Unknown project action: {sub}")

    def _cmd_stage(self, args):
        if not args:
            self._add_output("✗ Usage: stage <n|project> [...]  (Ctrl+S to toggle view)")
            return
        staged_ids = self.manager.load_staged_ids()
        for arg in args:
            try:
                n = int(arg)
            except ValueError:
                # Try as project name
                self._stage_project_by_name(arg, staged_ids, stage=True)
                continue
            task = self._get_task(n)
            if not task:
                continue
            if not task.task_id:
                self._add_output(f"✗ Task #{n} has no ID")
                continue
            if task.task_id in staged_ids:
                self._add_output(f"  #{n} already staged")
                continue
            staged_ids.add(task.task_id)
            for cid in get_children_ids(self.tasks, task):
                staged_ids.add(cid)
            self._add_output(f"⚡ Staged #{n}: {task.text}")
        self.manager.save_staged_ids(staged_ids)

    def _cmd_unstage(self, args):
        if not args:
            self._add_output("✗ Usage: unstage <n|project> [...]")
            return
        staged_ids = self.manager.load_staged_ids()
        for arg in args:
            try:
                n = int(arg)
            except ValueError:
                # Try as project name
                self._stage_project_by_name(arg, staged_ids, stage=False)
                continue
            task = self._get_task(n)
            if not task:
                continue
            if task.task_id not in staged_ids:
                self._add_output(f"  #{n} is not staged")
                continue
            staged_ids.discard(task.task_id)
            self._add_output(f"✓ Unstaged #{n}: {task.text}")
        self.manager.save_staged_ids(staged_ids)
        if self.stage_view:
            self._refresh_tasks()

    def _stage_project_by_name(self, name: str, staged_ids: set, stage: bool):
        """Stage or unstage all tasks in a project by name (used by REPL commands)."""
        project_tasks = [
            t for t in self.tasks
            if t.project_name == name or t.project_name.startswith(name + "/")
        ]
        if not project_tasks:
            self._add_output(f"✗ No project matching: {name}")
            return
        task_ids = {t.task_id for t in project_tasks if t.task_id}
        if not task_ids:
            self._add_output(f"✗ Tasks in {name} have no IDs")
            return
        if stage:
            staged_ids |= task_ids
            self._add_output(f"⚡ Staged {len(task_ids)} tasks from {name}")
        else:
            staged_ids -= task_ids
            self._add_output(f"✓ Unstaged {len(task_ids)} tasks from {name}")

    def _cmd_staged(self, args):
        old_view = self.stage_view
        self.stage_view = True
        self._refresh_tasks()
        if self.tasks:
            for i, task in enumerate(self.tasks, 1):
                checkbox = "[x]" if task.checked else "[ ]"
                self._add_output(f"  {i:>3} {checkbox} {task.text}  ({task.project_name})")
        else:
            self._add_output("  No staged tasks. Use 'stage <n>' to stage tasks.")
        self.stage_view = old_view
        self._refresh_tasks()

    def _cmd_group(self, args):
        """Handle group sub-commands: new, add, sync, list"""
        if not args:
            self._add_output("✗ Usage: group <new|add|sync|list> ...")
            return

        sub = args[0].lower()

        if sub == 'new':
            if len(args) < 2:
                self._add_output("✗ Usage: group new <name>")
                return
            name = args[1]
            try:
                self.manager.create_group(name)
                self._add_output(f"✓ Created group: {name}")
            except ValueError as e:
                self._add_output(f"✗ {e}")

        elif sub == 'add':
            if len(args) < 3:
                self._add_output("✗ Usage: group add <project> <group>")
                return
            project_name, group_name = args[1], args[2]
            try:
                self.manager.add_project_to_group(project_name, group_name)
                self._add_output(f"✓ Added '{project_name}' to group '{group_name}'")
            except ValueError as e:
                self._add_output(f"✗ {e}")

        elif sub == 'sync':
            if len(args) < 2:
                self._add_output("✗ Usage: group sync <group>")
                return
            group_name = args[1]
            registry = self.manager.load_registry()
            if group_name not in registry["groups"]:
                self._add_output(f"✗ Group '{group_name}' not found")
                return
            existing_remote = registry["groups"][group_name].get("remote")
            if existing_remote:
                self._add_output(f"ℹ Group '{group_name}' already has remote: {existing_remote}")
                self._add_output("  Reconfigure?")
                self._setup_group_name = group_name
                self.input_mode = 'setup_confirm'
                self.input_buffer = ''
                self.input_cursor = 0
                return
            self._setup_group_name = group_name
            self._start_group_or_main_wizard()

        elif sub == 'invite':
            if len(args) < 3:
                self._add_output("✗ Usage: group invite <group> <username>")
                return
            group_name, username = args[1], args[2]
            try:
                self._add_output(f"  Inviting '{username}' to '{group_name}'...")
                if self.manager.invite_to_group(group_name, username):
                    self._add_output(f"✓ Invited '{username}' as collaborator on '{group_name}'")
                else:
                    self._add_output(f"✗ Failed to invite '{username}'. Check the username and your permissions.")
            except ValueError as e:
                self._add_output(f"✗ {e}")

        elif sub == 'join':
            if len(args) < 3:
                self._add_output("✗ Usage: group join <group> <remote-url>")
                return
            group_name, remote_url = args[1], args[2]
            try:
                self._add_output(f"  Joining group '{group_name}'...")
                if self.manager.join_group(group_name, remote_url):
                    self._add_output(f"✓ Joined group '{group_name}'")
                    self._refresh_tasks()
                else:
                    self._add_output(f"✗ Failed to join '{group_name}'. Check the URL and your access.")
            except ValueError as e:
                self._add_output(f"✗ {e}")

        elif sub == 'list':
            registry = self.manager.load_registry()
            groups = registry.get("groups", {})
            if not groups:
                self._add_output("  No groups. Use 'group new <name>' to create one.")
                return
            for name, info in groups.items():
                remote = info.get("remote") or "no remote"
                projects = info.get("projects", [])
                proj_str = ", ".join(projects) if projects else "empty"
                self._add_output(f"  {name}: [{proj_str}] ({remote})")

        else:
            self._add_output(f"✗ Unknown group command: {sub}")
            self._add_output("  Usage: group <new|add|sync|invite|join|list>")

    def _cmd_setup(self, args):
        """Start interactive sync setup wizard."""
        main_sync = MainSync(self.manager.home_dir, self.manager.config)
        if main_sync.is_sync_enabled():
            status = main_sync.get_sync_status()
            self._add_output(f"ℹ Sync already configured: {status.get('remote_url')}")
            self._add_output("  Reconfigure?")
            self.input_mode = 'setup_confirm'
            self.input_buffer = ''
            self.input_cursor = 0
            return

        self._setup_group_name = None
        self._start_group_or_main_wizard()

    def _start_group_or_main_wizard(self):
        """Start the setup wizard, auto-detecting existing PAT if available."""
        # Try to reuse existing token from config
        for provider in ("github", "gitlab"):
            token = resolve_token(provider, self.manager.config, interactive=False)
            if token:
                prov = self._make_provider(provider, token)
                username = prov.validate_token(token) if prov else None
                if username:
                    label = "GitHub" if provider == "github" else "GitLab"
                    self._add_output(f"✓ Authenticated as {username} ({label})")
                    self._setup_provider = provider
                    self._setup_token = token
                    self._setup_username = username
                    self._show_repo_choice()
                    return
        # No existing token — fall through to provider selection
        self._start_setup_wizard()

    def _start_setup_wizard(self):
        """Begin the setup wizard from step 1 (provider selection)."""
        self._input_mode_output_start = len(self.output_lines)
        self._add_output("")
        if self._setup_group_name:
            self._add_output(f"  Git remote setup for group '{self._setup_group_name}'")
        else:
            self._add_output("  Multi-device sync setup")
        self._add_output("  Sync your todos across devices via a private git repo.")
        self._add_output("")
        self._add_output("  Provider:")
        self._add_output("    1) GitHub")
        self._add_output("    2) GitLab")
        self._add_output("    3) Other git host")
        self.input_mode = 'setup_provider'
        self.input_buffer = ''
        self.input_cursor = 0

    def _commit_setup_step(self):
        """Handle Enter press for the current setup wizard step."""
        text = self.input_buffer.strip()
        step = self.input_mode

        if step == 'setup_confirm':
            if text.lower() in ('y', 'yes', ''):
                group = self._setup_group_name
                self._reset_input_mode()
                self._setup_group_name = group  # preserve across reset
                self._start_group_or_main_wizard()
            else:
                self._add_output("(cancelled)")
                self._reset_input_mode()
            self._full_render()
            return

        if step == 'setup_provider':
            provider = {"1": "github", "2": "gitlab", "3": "other"}.get(text or "1", "github")
            self._setup_provider = provider

            if provider in ("github", "gitlab"):
                self._try_auto_auth(provider)
            else:
                self._add_output("")
                self._add_output("  Enter your git repo URL (HTTPS or SSH):")
                self.input_mode = 'setup_repo_url'
                self.input_buffer = ''
                self.input_cursor = 0
            self._full_render()
            return

        if step == 'setup_token':
            if not text:
                self._add_output("✗ No token provided. Setup aborted.")
                self._reset_input_mode()
                self._full_render()
                return
            self._validate_and_store_token(self._setup_provider, text)
            self._full_render()
            return

        if step == 'setup_repo_choice':
            if text == "1":
                default_name = self._setup_group_name or '.todos'
                self._add_output("  Repo name:")
                self.input_mode = 'setup_repo_name'
                self.input_buffer = default_name
                self.input_cursor = len(self.input_buffer)
            else:
                self._add_output("  Enter repo URL:")
                self.input_mode = 'setup_repo_url'
                self.input_buffer = ''
                self.input_cursor = 0
            self._full_render()
            return

        if step == 'setup_repo_name':
            name = text or '.todos'
            self._create_repo_and_finish(name)
            self._full_render()
            return

        if step == 'setup_repo_url':
            if not text:
                self._add_output("✗ No URL provided. Setup aborted.")
                self._reset_input_mode()
                self._full_render()
                return
            self._finish_setup(text)
            self._full_render()
            return

    def _try_auto_auth(self, provider):
        """Try to auto-detect auth, prompt for token if needed."""
        label = "GitHub" if provider == "github" else "GitLab"
        cli_name = "gh" if provider == "github" else "glab"
        config_key = "github_token" if provider == "github" else "gitlab_token"

        # Try existing token (interactive=False to avoid git credential prompts
        # that write directly to /dev/tty and corrupt the curses display)
        token = resolve_token(provider, self.manager.config, interactive=False)
        if token:
            prov = self._make_provider(provider, token)
            username = prov.validate_token(token) if prov else None
            if username:
                self._add_output(f"✓ Authenticated as {username} ({label})")
                self._setup_token = token
                self._setup_username = username
                self._show_repo_choice()
                return
            else:
                self._add_output(f"⚠ Existing {label} token is invalid or expired.")
                clear_token_cache()

        # Try CLI
        cli_token = _token_from_cli(provider)
        if cli_token:
            prov = self._make_provider(provider, cli_token)
            username = prov.validate_token(cli_token) if prov else None
            if username:
                self._add_output(f"✓ Authenticated as {username} (via {cli_name} CLI)")
                self.manager.config.set(config_key, cli_token)
                self._setup_token = cli_token
                self._setup_username = username
                self._show_repo_choice()
                return

        # Manual
        self._add_output(f"  No {label} auth found.")
        if provider == "github":
            self._add_output("  Create a token at: https://github.com/settings/tokens/new")
            self._add_output("  Required scope: 'repo'")
        else:
            self._add_output("  Create at: https://gitlab.com/-/user_settings/personal_access_tokens")
            self._add_output("  Required scope: api")
        self._add_output("")
        self.input_mode = 'setup_token'
        self.input_buffer = ''
        self.input_cursor = 0

    def _validate_and_store_token(self, provider, token):
        """Validate a manually entered token and proceed."""
        label = "GitHub" if provider == "github" else "GitLab"
        config_key = "github_token" if provider == "github" else "gitlab_token"
        prov = self._make_provider(provider, token)
        username = prov.validate_token(token) if prov else None
        if username:
            self._add_output(f"✓ Authenticated as {username}")
            self.manager.config.set(config_key, token)
            self._setup_token = token
            self._setup_username = username
            self._show_repo_choice()
        else:
            self._add_output("⚠ Token validation failed. Saving anyway.")
            self.manager.config.set(config_key, token)
            self._setup_token = token
            self._setup_username = None
            self._add_output("  Enter repo URL:")
            self.input_mode = 'setup_repo_url'
            self.input_buffer = ''
            self.input_cursor = 0

    def _show_repo_choice(self):
        """Show create-or-use repo choice."""
        self._add_output("")
        self._add_output("  Repository:")
        self._add_output("    1) Create a new private repo")
        self._add_output("    2) Use an existing repo URL")
        self.input_mode = 'setup_repo_choice'
        self.input_buffer = ''
        self.input_cursor = 0

    def _create_repo_and_finish(self, name):
        """Create a remote repo and finish setup."""
        provider = self._setup_provider
        token = self._setup_token
        username = self._setup_username
        prov = self._make_provider(provider, token)
        if not prov:
            self._add_output("✗ Provider not available.")
            self._reset_input_mode()
            return
        self._add_output(f"  Creating private repo '{name}'...")
        url = prov.create_repo(name, private=True)
        if url:
            self._add_output(f"✓ Created: {url}")
            self._finish_setup(url)
        else:
            self._add_output("✗ Failed to create repo (may already exist).")
            if username:
                fallback = prov.get_https_url(username, name)
                if fallback:
                    self._add_output(f"  Using: {fallback}")
                    self._finish_setup(fallback)
                    return
            self._add_output("  Enter repo URL manually:")
            self.input_mode = 'setup_repo_url'
            self.input_buffer = ''
            self.input_cursor = 0

    def _finish_setup(self, remote_url):
        """Apply the sync configuration — routes to group or main sync."""
        group = self._setup_group_name
        if group:
            self._add_output(f"  Configuring sync for group '{group}'...")
            if self.manager.setup_group_sync(group, remote_url):
                self._add_output(f"✓ Group '{group}' synced: {remote_url}")
            else:
                self._add_output("✗ Setup failed. Check your URL and auth.")
        else:
            self._add_output("  Configuring sync...")
            if self.manager.sync_setup(remote_url):
                self._add_output(f"✓ Sync configured: {remote_url}")
                self._start_background_sync()
            else:
                self._add_output("✗ Setup failed. Check your URL and auth.")
        self._reset_input_mode()

    def _make_provider(self, provider, token):
        """Create a provider instance."""
        if provider == "github":
            return GitHubProvider(token)
        elif provider == "gitlab":
            host = self.manager.config.get("gitlab_host", "gitlab.com")
            return GitLabProvider(token, host=host)
        return None

    def _cmd_sync(self, args):
        main_sync = MainSync(self.manager.home_dir, self.manager.config)
        if not main_sync.is_sync_enabled():
            self._add_output("ℹ Sync is not configured. Run 'setup' to configure.")
            return
        self._add_output("  syncing...")
        result = self._sync_quiet()
        self._refresh_tasks()
        conflicts = result.get("conflicts", [])
        if conflicts:
            self._add_output(f"⚠ synced with {len(conflicts)} conflict(s)")
            for c in conflicts:
                self._add_output(f"  ⚠ {c}")
        else:
            self._add_output("✓ Synced")

    def _cmd_push(self, args):
        self._add_output("  syncing...")
        result = self._sync_quiet()
        self.dirty = False
        conflicts = result.get("conflicts", [])
        if conflicts:
            self._add_output(f"⚠ pushed with {len(conflicts)} conflict(s)")
            for c in conflicts:
                self._add_output(f"  ⚠ {c}")
        else:
            self._add_output("✓ Pushed")

    def _cmd_pull(self, args):
        self._add_output("  syncing...")
        result = self._sync_quiet()
        self._refresh_tasks()
        conflicts = result.get("conflicts", [])
        if conflicts:
            self._add_output(f"⚠ pulled with {len(conflicts)} conflict(s)")
            for c in conflicts:
                self._add_output(f"  ⚠ {c}")
        else:
            self._add_output("✓ Pulled")

    def _cmd_status(self, args):
        project_list = self.manager.list_projects()
        registry = self.manager.load_registry()
        groups = registry.get("groups", {})
        self._add_output(f"  Projects: {len(project_list)}")
        self._add_output(f"  Groups:   {len(groups)}")
        self._add_output(f"  Scope:    {self.current_project or 'global (all)'}")
        self._add_output(f"  Tasks:    {len(self.tasks)} ({sum(1 for t in self.tasks if not t.checked)} pending)")
        git_dir = self.manager.home_dir / ".git"
        self._add_output(f"  Git sync: {'enabled' if git_dir.exists() else 'disabled'}")

    def _cmd_theme(self, args):
        if not args:
            current = get_theme().name
            available = list_themes()
            self._add_output(f"  Current theme: {current}")
            self._add_output(f"  Available: {', '.join(available)}")
            self._add_output(f"  Usage: theme <name>")
            return
        name = args[0].lower()
        if set_theme(name):
            self._apply_theme_colors()
            self.manager.config.set("theme", name)
            self._add_output(f"✓ Theme set to '{name}'")
            # Rebuild layout since banners/borders may have changed
            self.stdscr.clear()
            self.stdscr.refresh()
            self._create_windows()
        else:
            self._add_output(f"✗ Unknown theme: {name}")
            self._add_output(f"  Available: {', '.join(list_themes())}")

    def _cmd_config(self, args):
        if not args:
            self._add_output("Configuration:")
            for k, v in self.manager.config.config.items():
                if k in ('github_token', 'gitlab_token') and v:
                    self._add_output(f"  {k}: ****")
                else:
                    self._add_output(f"  {k}: {v}")
            return
        if len(args) < 2:
            self._add_output("✗ Usage: config <key> <value>")
            return
        key, value = args[0], ' '.join(args[1:])
        self.manager.config.set(key, value)
        self._add_output(f"✓ {key} = {value}")

    def _cmd_nuke(self, args):
        self._add_output("⚠ This will DELETE all todo data in ~/.todo/")
        self._add_output("  Type 'yes' to confirm:")
        self.input_mode = 'confirm_nuke'
        self.input_buffer = ''
        self.input_cursor = 0

    def _cmd_link(self, args):
        if not args:
            self._add_output("✗ Usage: link <project> [path]")
            return
        project_name = args[0]
        target_dir = Path(args[1]) if len(args) > 1 else None
        result = self.manager.link_project(project_name, target_dir)
        self._add_output(f"✓ Linked: {result}")

    def _cmd_unlink(self, args):
        if not args:
            self._add_output("✗ Usage: unlink <project> [path]")
            return
        project_name = args[0]
        target_dir = Path(args[1]) if len(args) > 1 else None
        if self.manager.unlink_project(project_name, target_dir):
            self._add_output(f"✓ Unlinked: {project_name}")
        else:
            self._add_output(f"✗ No symlink found for {project_name}")

    def _cmd_clear(self, args):
        self.output_lines.clear()

    def _cmd_quit(self, args):
        self._quit()
