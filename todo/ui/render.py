"""
Terminal rendering utilities - ANSI colors, box drawing, tree views

All colors and visual elements are sourced from the active theme.
"""

import os
import re
import sys
import shutil

from todo.ui.themes import get_theme


def supports_color() -> bool:
    """Check if terminal supports ANSI colors"""
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    return True


_COLOR = supports_color()


def _s(code: str) -> str:
    """Return the ANSI code if color is supported, else empty string."""
    return code if _COLOR else ""


def term_width() -> int:
    """Get terminal width"""
    return shutil.get_terminal_size((80, 24)).columns


def color(text: str, *styles) -> str:
    """Apply color/style to text"""
    if not _COLOR:
        return text
    prefix = "".join(styles)
    return f"{prefix}{text}{_s(get_theme().reset)}"


def box(title: str, lines: list, accent=None) -> str:
    """Render a box with title and content lines"""
    t = get_theme()
    ac = accent if accent is not None else _s(t.accent)
    reset = _s(t.reset)
    bold = _s(t.accent_bold)

    w = term_width() - 2
    title_display = f" {title} "

    top = (
        f"{ac}{t.border_top_left}{reset}"
        f"{bold}{title_display}{reset}"
        f"{t.border_h * (w - len(title_display))}"
        f"{ac}{t.border_top_right}{reset}"
    )

    bottom = f"{ac}{t.border_bottom_left}{t.border_h * w}{t.border_bottom_right}{reset}"

    result = [top]
    for line in lines:
        stripped = _strip_ansi(line)
        pad = w - len(stripped)
        if pad < 0:
            pad = 0
        result.append(f"{ac}{t.border_v}{reset}{line}{' ' * pad}{ac}{t.border_v}{reset}")
    result.append(bottom)
    return "\n".join(result)


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text for length calculation"""
    return re.sub(r'\033\[[0-9;]*m', '', text)


def header(text: str) -> str:
    """Render a section header"""
    t = get_theme()
    return f"\n{_s(t.header)}{text}{_s(t.reset)}"


def success(text: str) -> str:
    t = get_theme()
    return f"{_s(t.success)}{t.icon_success}{_s(t.reset)} {text}"


def error(text: str) -> str:
    t = get_theme()
    return f"{_s(t.error)}{t.icon_error}{_s(t.reset)} {text}"


def warn(text: str) -> str:
    t = get_theme()
    return f"{_s(t.warning)}{t.icon_warning}{_s(t.reset)} {text}"


def info(text: str) -> str:
    t = get_theme()
    return f"{_s(t.info)}{t.icon_info}{_s(t.reset)} {text}"


def dim(text: str) -> str:
    return color(text, _s(get_theme().dim))


def task_line(index: int, checked: bool, text: str, project: str = "", file: str = "") -> str:
    """Render a single task line"""
    t = get_theme()
    idx = color(f"{index:>3}", _s(t.dim))
    if checked:
        checkbox = color(t.checkbox_checked, _s(t.success))
        label = color(text, _s(t.dim))
    else:
        checkbox = color(t.checkbox_unchecked, _s(t.warning))
        label = text

    parts = [f"  {idx} {checkbox} {label}"]

    if project or file:
        loc = []
        if project:
            loc.append(color(project, _s(t.accent)))
        if file:
            loc.append(color(file, _s(t.dim)))
        parts.append(f"  {color(t.border_v, _s(t.dim))} {' › '.join(loc)}")

    return parts[0]


def project_tree(projects: list, current: str = None) -> str:
    """Render a tree of projects"""
    t = get_theme()
    lines = []
    for i, p in enumerate(projects):
        is_last = i == len(projects) - 1
        branch = t.tree_last if is_last else t.tree_branch
        marker = color(" ●", _s(t.accent)) if p["name"] == current else "  "
        name = color(p["name"], _s(t.text_bold)) if p["name"] == current else color(p["name"], _s(t.text))
        todo_count = p.get("todo_count", 0)
        count_str = color(f"({todo_count} todos)", _s(t.dim))
        ptype = color(f"[{p.get('type', 'dir')}]", _s(t.dim))
        lines.append(f"  {color(branch, _s(t.dim))} {name} {count_str} {ptype}{marker}")
    return "\n".join(lines)


def divider() -> str:
    """Render a horizontal divider"""
    t = get_theme()
    w = term_width()
    return color(t.divider_char * w, _s(t.dim))


def banner() -> str:
    """Render the welcome banner"""
    t = get_theme()
    return "\n".join(t.banner_lines)


def prompt_str(project: str = None) -> str:
    """Build the prompt string"""
    t = get_theme()
    prefix = _s(t.accent)
    rst = _s(t.reset)
    dm = _s(t.dim)
    tw = _s(t.text_bold)

    if project:
        return f"{prefix}{t.prompt_prefix}{rst} {dm}({rst}{tw}{project}{rst}{dm}){rst}{prefix}{t.prompt_arrow}{rst} "
    return f"{prefix}{t.prompt_prefix}{t.prompt_arrow}{rst} "


# ── Backward-compatible Style aliases ─────────────────────────────────
# These allow shell.py (and any other code using S.CYAN, S.BOLD, etc.)
# to keep working without rewriting every reference.

class _ThemeStyle:
    """Proxy that maps the old S.* attribute names to the current theme."""

    @property
    def RESET(self): return _s(get_theme().reset)
    @property
    def BOLD(self): return "\033[1m" if _COLOR else ""
    @property
    def DIM(self): return _s(get_theme().dim)
    @property
    def ITALIC(self): return "\033[3m" if _COLOR else ""
    @property
    def UNDERLINE(self): return "\033[4m" if _COLOR else ""

    # Semantic mappings
    @property
    def RED(self): return _s(get_theme().error)
    @property
    def GREEN(self): return _s(get_theme().success)
    @property
    def YELLOW(self): return _s(get_theme().warning)
    @property
    def BLUE(self): return _s(get_theme().info)
    @property
    def MAGENTA(self): return "\033[35m" if _COLOR else ""
    @property
    def CYAN(self): return _s(get_theme().accent)
    @property
    def WHITE(self): return _s(get_theme().text)
    @property
    def GRAY(self): return _s(get_theme().dim)

    @property
    def BRIGHT_GREEN(self): return _s(get_theme().success)
    @property
    def BRIGHT_YELLOW(self): return _s(get_theme().warning)
    @property
    def BRIGHT_BLUE(self): return _s(get_theme().info)
    @property
    def BRIGHT_MAGENTA(self): return _s(get_theme().header)
    @property
    def BRIGHT_CYAN(self): return _s(get_theme().accent)
    @property
    def BRIGHT_WHITE(self): return _s(get_theme().text_bold)

    @property
    def BG_BLUE(self): return "\033[44m" if _COLOR else ""
    @property
    def BG_GRAY(self): return "\033[100m" if _COLOR else ""


S = _ThemeStyle()
