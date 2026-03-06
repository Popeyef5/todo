"""
Terminal rendering utilities - ANSI colors, box drawing, tree views
"""

import os
import sys
import shutil


def supports_color() -> bool:
    """Check if terminal supports ANSI colors"""
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    return True


_COLOR = supports_color()


# ANSI color codes
class Style:
    RESET = "\033[0m" if _COLOR else ""
    BOLD = "\033[1m" if _COLOR else ""
    DIM = "\033[2m" if _COLOR else ""
    ITALIC = "\033[3m" if _COLOR else ""
    UNDERLINE = "\033[4m" if _COLOR else ""

    # Colors
    RED = "\033[31m" if _COLOR else ""
    GREEN = "\033[32m" if _COLOR else ""
    YELLOW = "\033[33m" if _COLOR else ""
    BLUE = "\033[34m" if _COLOR else ""
    MAGENTA = "\033[35m" if _COLOR else ""
    CYAN = "\033[36m" if _COLOR else ""
    WHITE = "\033[37m" if _COLOR else ""
    GRAY = "\033[90m" if _COLOR else ""

    # Bright
    BRIGHT_GREEN = "\033[92m" if _COLOR else ""
    BRIGHT_YELLOW = "\033[93m" if _COLOR else ""
    BRIGHT_BLUE = "\033[94m" if _COLOR else ""
    BRIGHT_MAGENTA = "\033[95m" if _COLOR else ""
    BRIGHT_CYAN = "\033[96m" if _COLOR else ""
    BRIGHT_WHITE = "\033[97m" if _COLOR else ""

    # Background
    BG_BLUE = "\033[44m" if _COLOR else ""
    BG_GRAY = "\033[100m" if _COLOR else ""


S = Style


def term_width() -> int:
    """Get terminal width"""
    return shutil.get_terminal_size((80, 24)).columns


def color(text: str, *styles) -> str:
    """Apply color/style to text"""
    if not _COLOR:
        return text
    prefix = "".join(styles)
    return f"{prefix}{text}{S.RESET}"


def box(title: str, lines: list, accent=S.CYAN) -> str:
    """Render a box with title and content lines"""
    w = term_width() - 2
    title_display = f" {title} "
    top = f"{accent}╭{'─' * (len(title_display))}{S.RESET}{'─' * (w - len(title_display) - 1)}{accent}╮{S.RESET}"
    top = f"{accent}╭{S.RESET}{accent}{S.BOLD}{title_display}{S.RESET}{'─' * (w - len(title_display))}{accent}╮{S.RESET}"

    bottom = f"{accent}╰{'─' * w}╯{S.RESET}"

    result = [top]
    for line in lines:
        # Strip ANSI for length calculation
        stripped = _strip_ansi(line)
        pad = w - len(stripped)
        if pad < 0:
            pad = 0
        result.append(f"{accent}│{S.RESET}{line}{' ' * pad}{accent}│{S.RESET}")
    result.append(bottom)
    return "\n".join(result)


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text for length calculation"""
    import re
    return re.sub(r'\033\[[0-9;]*m', '', text)


def header(text: str) -> str:
    """Render a section header"""
    return f"\n{S.BOLD}{S.BRIGHT_CYAN}{text}{S.RESET}"


def success(text: str) -> str:
    return f"{S.BRIGHT_GREEN}✓{S.RESET} {text}"


def error(text: str) -> str:
    return f"{S.RED}✗{S.RESET} {text}"


def warn(text: str) -> str:
    return f"{S.BRIGHT_YELLOW}⚠{S.RESET} {text}"


def info(text: str) -> str:
    return f"{S.BRIGHT_BLUE}ℹ{S.RESET} {text}"


def dim(text: str) -> str:
    return color(text, S.DIM)


def task_line(index: int, checked: bool, text: str, project: str = "", file: str = "") -> str:
    """Render a single task line"""
    idx = color(f"{index:>3}", S.DIM)
    if checked:
        checkbox = color("[x]", S.GREEN)
        label = color(text, S.DIM)
    else:
        checkbox = color("[ ]", S.YELLOW)
        label = text

    parts = [f"  {idx} {checkbox} {label}"]

    if project or file:
        loc = []
        if project:
            loc.append(color(project, S.BLUE))
        if file:
            loc.append(color(file, S.DIM))
        parts.append(f"  {color('│', S.DIM)} {' › '.join(loc)}")

    return parts[0]


def project_tree(projects: list, current: str = None) -> str:
    """Render a tree of projects"""
    lines = []
    for i, p in enumerate(projects):
        is_last = i == len(projects) - 1
        branch = "└──" if is_last else "├──"
        marker = color(" ●", S.BRIGHT_CYAN) if p["name"] == current else "  "
        name = color(p["name"], S.BOLD, S.BRIGHT_WHITE) if p["name"] == current else color(p["name"], S.WHITE)
        todo_count = p.get("todo_count", 0)
        count_str = color(f"({todo_count} todos)", S.DIM)
        ptype = color(f"[{p.get('type', 'dir')}]", S.DIM)
        lines.append(f"  {color(branch, S.DIM)} {name} {count_str} {ptype}{marker}")
    return "\n".join(lines)


def divider() -> str:
    """Render a horizontal divider"""
    w = term_width()
    return color("─" * w, S.DIM)


def banner() -> str:
    """Render the welcome banner"""
    lines = [
        "",
        f"  {S.BOLD}{S.BRIGHT_CYAN}todo{S.RESET}  {S.DIM}interactive mode{S.RESET}",
        f"  {S.DIM}Type {S.RESET}{S.BRIGHT_WHITE}help{S.RESET}{S.DIM} for commands, {S.RESET}{S.BRIGHT_WHITE}q{S.RESET}{S.DIM} to quit{S.RESET}",
        "",
    ]
    return "\n".join(lines)


def prompt_str(project: str = None) -> str:
    """Build the prompt string"""
    if project:
        return f"{S.BRIGHT_CYAN}todo{S.RESET} {S.DIM}({S.RESET}{S.BRIGHT_WHITE}{project}{S.RESET}{S.DIM}){S.RESET}{S.BRIGHT_CYAN}>{S.RESET} "
    return f"{S.BRIGHT_CYAN}todo>{S.RESET} "
