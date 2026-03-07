"""
Theme system for the todo app.

Defines themes for both ANSI/REPL mode (render.py + shell.py) and
curses/TUI mode (tui.py). Each theme specifies semantic color codes,
curses color pair definitions, and visual element strings.

Standalone — no dependencies on other todo modules.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

try:
    import curses

    _HAS_CURSES = True
except ImportError:
    _HAS_CURSES = False

# Provide curses color constants even when curses is unavailable
if _HAS_CURSES:
    COLOR_BLACK = curses.COLOR_BLACK
    COLOR_RED = curses.COLOR_RED
    COLOR_GREEN = curses.COLOR_GREEN
    COLOR_YELLOW = curses.COLOR_YELLOW
    COLOR_BLUE = curses.COLOR_BLUE
    COLOR_MAGENTA = curses.COLOR_MAGENTA
    COLOR_CYAN = curses.COLOR_CYAN
    COLOR_WHITE = curses.COLOR_WHITE
else:
    COLOR_BLACK = 0
    COLOR_RED = 1
    COLOR_GREEN = 2
    COLOR_YELLOW = 3
    COLOR_BLUE = 4
    COLOR_MAGENTA = 5
    COLOR_CYAN = 6
    COLOR_WHITE = 7


@dataclass
class Theme:
    """Complete theme definition for the todo app."""

    name: str

    # ── Semantic ANSI color codes (for REPL / render.py) ──────────────
    accent: str = ""
    accent_bold: str = ""
    success: str = ""
    warning: str = ""
    error: str = ""
    info: str = ""
    text: str = ""
    text_bold: str = ""
    dim: str = ""
    header: str = ""
    reset: str = ""

    # ── Curses color pair definitions ─────────────────────────────────
    # List of 8 (fg, bg) tuples. Index 0 → pair 1, index 1 → pair 2, etc.
    #   Pair 1: accent (borders, prompt)
    #   Pair 2: success
    #   Pair 3: warning / pending
    #   Pair 4: error
    #   Pair 5: header / project name
    #   Pair 6: status bar (fg on bg)
    #   Pair 7: highlighted / selected item (fg on bg)
    #   Pair 8: normal text
    curses_pairs: List[Tuple[int, int]] = field(default_factory=list)

    # ── Visual elements (strings) ─────────────────────────────────────
    border_top_left: str = "+"
    border_top_right: str = "+"
    border_bottom_left: str = "+"
    border_bottom_right: str = "+"
    border_h: str = "-"
    border_v: str = "|"

    icon_success: str = "[OK]"
    icon_error: str = "[!!]"
    icon_warning: str = "[??]"
    icon_info: str = "[--]"

    checkbox_checked: str = "[x]"
    checkbox_unchecked: str = "[ ]"

    tree_branch: str = "├──"
    tree_last: str = "└──"

    collapse_open: str = "-"
    collapse_closed: str = "+"

    prompt_prefix: str = "todo"
    prompt_arrow: str = ">"

    divider_char: str = "-"

    banner_lines: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
# Theme definitions
# ═══════════════════════════════════════════════════════════════════════

# ── Modern (default) ──────────────────────────────────────────────────
# Clean cyan accent, unicode box drawing, matches the current app look.

modern_theme = Theme(
    name="modern",
    # ANSI colors
    accent="\033[96m",
    accent_bold="\033[1m\033[96m",
    success="\033[92m",
    warning="\033[93m",
    error="\033[31m",
    info="\033[94m",
    text="\033[37m",
    text_bold="\033[1m\033[97m",
    dim="\033[2m",
    header="\033[1m\033[96m",
    reset="\033[0m",
    # Curses pairs (pair 1–8)
    curses_pairs=[
        (COLOR_CYAN, -1),      # 1: accent
        (COLOR_GREEN, -1),     # 2: success
        (COLOR_YELLOW, -1),    # 3: warning / pending
        (COLOR_RED, -1),       # 4: error
        (COLOR_BLUE, -1),      # 5: header / project name
        (COLOR_WHITE, COLOR_BLUE),   # 6: status bar
        (COLOR_BLACK, COLOR_CYAN),   # 7: highlighted / selected
        (COLOR_WHITE, -1),     # 8: normal text
    ],
    # Box drawing
    border_top_left="╭",
    border_top_right="╮",
    border_bottom_left="╰",
    border_bottom_right="╯",
    border_h="─",
    border_v="│",
    # Icons
    icon_success="✓",
    icon_error="✗",
    icon_warning="⚠",
    icon_info="ℹ",
    # Checkboxes
    checkbox_checked="[x]",
    checkbox_unchecked="[ ]",
    # Tree
    tree_branch="├──",
    tree_last="└──",
    # Collapse
    collapse_open="▾",
    collapse_closed="▸",
    # Prompt
    prompt_prefix="todo",
    prompt_arrow=">",
    # Divider
    divider_char="─",
    # Banner
    banner_lines=[
        "",
        "  \033[1m\033[96mtodo\033[0m  \033[2minteractive mode\033[0m",
        "  \033[2mType \033[0m\033[97mhelp\033[0m\033[2m for commands, \033[0m\033[97mq\033[0m\033[2m to quit\033[0m",
        "",
    ],
)


# ── Cyber ─────────────────────────────────────────────────────────────
# Neon green + magenta, hacker aesthetic.

cyber_theme = Theme(
    name="cyber",
    # ANSI colors
    accent="\033[92m",
    accent_bold="\033[1m\033[92m",
    success="\033[92m",
    warning="\033[93m",
    error="\033[91m",
    info="\033[92m",
    text="\033[37m",
    text_bold="\033[1m\033[97m",
    dim="\033[2m",
    header="\033[95m",
    reset="\033[0m",
    # Curses pairs
    curses_pairs=[
        (COLOR_GREEN, -1),           # 1: accent
        (COLOR_GREEN, -1),           # 2: success
        (COLOR_YELLOW, -1),          # 3: warning / pending
        (COLOR_RED, -1),             # 4: error
        (COLOR_MAGENTA, -1),         # 5: header / project name
        (COLOR_GREEN, COLOR_BLACK),  # 6: status bar
        (COLOR_BLACK, COLOR_GREEN),  # 7: highlighted / selected
        (COLOR_GREEN, -1),           # 8: normal text
    ],
    # Box drawing — thin single lines
    border_top_left="┌",
    border_top_right="┐",
    border_bottom_left="└",
    border_bottom_right="┘",
    border_h="─",
    border_v="│",
    # Icons
    icon_success="»",
    icon_error="×",
    icon_warning="!",
    icon_info=">",
    # Checkboxes
    checkbox_checked="[■]",
    checkbox_unchecked="[□]",
    # Tree
    tree_branch="├──",
    tree_last="└──",
    # Collapse
    collapse_open="▿",
    collapse_closed="▹",
    # Prompt
    prompt_prefix="λ",
    prompt_arrow=">",
    # Divider
    divider_char="·",
    # Banner
    banner_lines=[
        "",
        "  \033[92m┌─────────────────────────┐\033[0m",
        "  \033[92m│\033[0m  \033[1m\033[92m>> \033[95mtodo\033[92m_system\033[0m \033[2mv1.0\033[0m  \033[92m│\033[0m",
        "  \033[92m│\033[0m  \033[2m   connected · secure\033[0m   \033[92m│\033[0m",
        "  \033[92m└─────────────────────────┘\033[0m",
        "  \033[2mλ enter \033[0m\033[97mhelp\033[0m\033[2m // \033[0m\033[97mq\033[0m\033[2m to disconnect\033[0m",
        "",
    ],
)


# ── Minimal ───────────────────────────────────────────────────────────
# No colors, ASCII-only, maximum compatibility.

minimal_theme = Theme(
    name="minimal",
    # ANSI colors — all empty (no color output)
    accent="",
    accent_bold="",
    success="",
    warning="",
    error="",
    info="",
    text="",
    text_bold="",
    dim="",
    header="",
    reset="",
    # Curses pairs — white on default for everything
    curses_pairs=[
        (COLOR_WHITE, -1),  # 1: accent
        (COLOR_WHITE, -1),  # 2: success
        (COLOR_WHITE, -1),  # 3: warning / pending
        (COLOR_WHITE, -1),  # 4: error
        (COLOR_WHITE, -1),  # 5: header / project name
        (COLOR_WHITE, -1),  # 6: status bar
        (COLOR_WHITE, -1),  # 7: highlighted / selected
        (COLOR_WHITE, -1),  # 8: normal text
    ],
    # Box drawing — plain ASCII
    border_top_left="+",
    border_top_right="+",
    border_bottom_left="+",
    border_bottom_right="+",
    border_h="-",
    border_v="|",
    # Icons
    icon_success="[OK]",
    icon_error="[!!]",
    icon_warning="[??]",
    icon_info="[--]",
    # Checkboxes
    checkbox_checked="[x]",
    checkbox_unchecked="[ ]",
    # Tree
    tree_branch="├──",
    tree_last="└──",
    # Collapse
    collapse_open="+",
    collapse_closed="-",
    # Prompt
    prompt_prefix="todo",
    prompt_arrow=":",
    # Divider
    divider_char="-",
    # Banner
    banner_lines=[
        "",
        "  todo - interactive mode",
        "  Type 'help' for commands, 'q' to quit",
        "",
    ],
)


# ═══════════════════════════════════════════════════════════════════════
# Theme registry and accessors
# ═══════════════════════════════════════════════════════════════════════

THEMES = {
    "modern": modern_theme,
    "cyber": cyber_theme,
    "minimal": minimal_theme,
}

DEFAULT_THEME = "modern"

_current_theme: Optional[Theme] = None


def get_theme() -> Theme:
    """Get the current active theme. Returns modern if none set."""
    global _current_theme
    if _current_theme is None:
        _current_theme = THEMES[DEFAULT_THEME]
    return _current_theme


def set_theme(name: str) -> bool:
    """Set the active theme by name. Returns False if name is invalid."""
    global _current_theme
    if name not in THEMES:
        return False
    _current_theme = THEMES[name]
    return True


def list_themes() -> list:
    """Return list of available theme names."""
    return list(THEMES.keys())
