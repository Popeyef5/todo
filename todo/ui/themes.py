"""
Theme system for the todo app.

Defines themes for both ANSI/REPL mode (render.py + shell.py) and
curses/TUI mode (tui.py). Each theme specifies semantic color codes,
curses color pair definitions, and visual element strings.

Custom themes can be loaded from YAML files in ~/.todo/themes/.
Standalone — no dependencies on other todo modules.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import curses

    _HAS_CURSES = True
except ImportError:
    _HAS_CURSES = False

try:
    import yaml

    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

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

# ═══════════════════════════════════════════════════════════════════════
# Color name mappings (used by YAML loader)
# ═══════════════════════════════════════════════════════════════════════

ANSI_COLORS: Dict[str, str] = {
    "black": "\033[30m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "gray": "\033[90m",
    "bright_red": "\033[91m",
    "bright_green": "\033[92m",
    "bright_yellow": "\033[93m",
    "bright_blue": "\033[94m",
    "bright_magenta": "\033[95m",
    "bright_cyan": "\033[96m",
    "bright_white": "\033[97m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "italic": "\033[3m",
    "reset": "\033[0m",
    "none": "",
}

CURSES_COLORS: Dict[str, int] = {
    "black": COLOR_BLACK,
    "red": COLOR_RED,
    "green": COLOR_GREEN,
    "yellow": COLOR_YELLOW,
    "blue": COLOR_BLUE,
    "magenta": COLOR_MAGENTA,
    "cyan": COLOR_CYAN,
    "white": COLOR_WHITE,
    "default": -1,
}


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

    # ── TUI layout ────────────────────────────────────────────────────
    tui_banner_top: List[str] = field(default_factory=list)   # max 14 lines
    tui_banner_top_align: str = "center"                       # "left", "center", "right"
    tui_banner_mid: List[str] = field(default_factory=list)   # max 14 lines
    tui_banner_mid_align: str = "center"                       # "left", "center", "right"
    tui_bordered: bool = True                                  # full borders on panels
    input_separator: str = ""                                  # char between output/input, "" = off
    border_tee_left: str = "├"       # left T-junction for separator
    border_tee_right: str = "┤"      # right T-junction for separator
    status_bar_position: str = "middle"  # "top", "middle", or "bottom"


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
    # TUI layout
    tui_bordered=True,
    input_separator="─",
    border_tee_left="├",
    border_tee_right="┤",
    status_bar_position="bottom",
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
    # TUI layout
    tui_bordered=True,
    input_separator="─",
    border_tee_left="├",
    border_tee_right="┤",
    status_bar_position="bottom",
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
    # TUI layout
    tui_bordered=True,
    input_separator="-",
    border_tee_left="+",
    border_tee_right="+",
    status_bar_position="bottom",
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


# ═══════════════════════════════════════════════════════════════════════
# YAML custom theme loader
# ═══════════════════════════════════════════════════════════════════════

MAX_BANNER_LINES = 14


def resolve_dynamic_vars(text: str, context: dict) -> str:
    """Replace {time}, {date}, {hostname}, etc. in text.

    Called on every render for banner lines.  Color placeholders
    ({bold}, {reset}, …) are resolved separately by _resolve_banner_colors.
    """
    for key, value in context.items():
        text = text.replace(f"{{{key}}}", str(value))
    return text


def build_dynamic_context(
    project: str = "all",
    tasks_pending: int = 0,
    tasks_done: int = 0,
    tasks_total: int = 0,
    sync_status: str = "",
) -> dict:
    """Build the context dict for dynamic variable resolution."""
    import socket
    import os
    from datetime import datetime

    now = datetime.now()
    return {
        "time": now.strftime("%H:%M:%S"),
        "time_short": now.strftime("%H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "hostname": socket.gethostname(),
        "user": os.environ.get("USER", os.environ.get("USERNAME", "")),
        "project": project,
        "tasks_pending": str(tasks_pending),
        "tasks_done": str(tasks_done),
        "tasks_total": str(tasks_total),
        "sync_status": sync_status,
    }


def _resolve_ansi(value: str) -> str:
    """Resolve a color name like 'bold+bright_cyan' to ANSI codes.

    Supports combining modifiers with '+':  bold+bright_cyan → \\033[1m\\033[96m
    Also accepts 'none' for no color output.
    """
    if not value or value == "none":
        return ""
    parts = [p.strip() for p in value.split("+")]
    codes = []
    for p in parts:
        if p in ANSI_COLORS:
            codes.append(ANSI_COLORS[p])
        else:
            return ""
    return "".join(codes)


def _resolve_curses_color(name: str) -> int:
    """Resolve a curses color name to its integer constant."""
    return CURSES_COLORS.get(name, -1)


def _resolve_banner_colors(lines: List[str]) -> List[str]:
    """Replace {color_name} placeholders in banner lines with ANSI codes.

    e.g. '{accent}todo{reset}' → '\\033[96mtodo\\033[0m'
    Only resolves names present in ANSI_COLORS.
    """
    result = []
    for line in lines:
        for name, code in ANSI_COLORS.items():
            line = line.replace(f"{{{name}}}", code)
        result.append(line)
    return result


# The 8 curses pair keys in order, matching Theme.curses_pairs indices
_CURSES_PAIR_KEYS = [
    "accent", "success", "warning", "error",
    "header", "status_bar", "highlight", "text",
]


def load_theme_from_yaml(path: Path) -> Optional[Theme]:
    """Load a theme from a YAML file. Returns None on failure.

    See ~/.todo/themes/example.yaml for the expected format.
    """
    if not _HAS_YAML:
        return None
    try:
        data = yaml.safe_load(path.read_text())
    except Exception:
        return None
    if not isinstance(data, dict) or "name" not in data:
        return None

    name = str(data["name"]).lower().replace(" ", "_")

    # ── ANSI colors ───────────────────────────────────────────────
    color_fields = [
        "accent", "accent_bold", "success", "warning", "error",
        "info", "text", "text_bold", "dim", "header",
    ]
    colors = {}
    colors_section = data.get("colors", {})
    for f in color_fields:
        if f in colors_section:
            colors[f] = _resolve_ansi(str(colors_section[f]))
    colors["reset"] = ANSI_COLORS["reset"]

    # ── Curses pairs ──────────────────────────────────────────────
    curses_section = data.get("curses", {})
    curses_pairs = []
    # Default to modern theme's pairs as fallback
    defaults = modern_theme.curses_pairs
    for i, key in enumerate(_CURSES_PAIR_KEYS):
        if key in curses_section:
            pair = curses_section[key]
            if isinstance(pair, list) and len(pair) == 2:
                fg = _resolve_curses_color(str(pair[0]))
                bg = _resolve_curses_color(str(pair[1]))
                curses_pairs.append((fg, bg))
            else:
                curses_pairs.append(defaults[i] if i < len(defaults) else (COLOR_WHITE, -1))
        else:
            curses_pairs.append(defaults[i] if i < len(defaults) else (COLOR_WHITE, -1))

    # ── Visual elements ───────────────────────────────────────────
    elements_section = data.get("elements", {})
    element_fields = [
        "border_top_left", "border_top_right", "border_bottom_left",
        "border_bottom_right", "border_h", "border_v",
        "icon_success", "icon_error", "icon_warning", "icon_info",
        "checkbox_checked", "checkbox_unchecked",
        "tree_branch", "tree_last",
        "collapse_open", "collapse_closed",
        "prompt_prefix", "prompt_arrow", "divider_char",
        "border_tee_left", "border_tee_right",
    ]
    elements = {}
    for f in element_fields:
        if f in elements_section:
            elements[f] = str(elements_section[f])

    # ── Banner ────────────────────────────────────────────────────
    raw_banner = data.get("banner", [])
    if isinstance(raw_banner, list):
        banner_lines = _resolve_banner_colors([str(l) for l in raw_banner])
    else:
        banner_lines = []

    # ── TUI banners ───────────────────────────────────────────────
    raw_top = data.get("tui_banner_top", [])
    tui_banner_top = _resolve_banner_colors(
        [str(l) for l in raw_top[:MAX_BANNER_LINES]]
    ) if isinstance(raw_top, list) else []

    raw_mid = data.get("tui_banner_mid", [])
    tui_banner_mid = _resolve_banner_colors(
        [str(l) for l in raw_mid[:MAX_BANNER_LINES]]
    ) if isinstance(raw_mid, list) else []

    # ── TUI layout flags ─────────────────────────────────────────
    tui_bordered = data.get("tui_bordered", True)
    input_separator = str(data.get("input_separator", "─"))
    if input_separator.lower() == "none":
        input_separator = ""

    # Banner alignment
    tui_banner_top_align = str(data.get("tui_banner_top_align", "center")).lower()
    if tui_banner_top_align not in ("left", "center", "right"):
        tui_banner_top_align = "center"
    tui_banner_mid_align = str(data.get("tui_banner_mid_align", "center")).lower()
    if tui_banner_mid_align not in ("left", "center", "right"):
        tui_banner_mid_align = "center"

    # Status bar position
    status_bar_position = str(data.get("status_bar_position", "middle")).lower()
    if status_bar_position not in ("top", "middle", "bottom"):
        status_bar_position = "middle"

    return Theme(
        name=name,
        curses_pairs=curses_pairs,
        banner_lines=banner_lines,
        tui_banner_top=tui_banner_top,
        tui_banner_top_align=tui_banner_top_align,
        tui_banner_mid=tui_banner_mid,
        tui_banner_mid_align=tui_banner_mid_align,
        tui_bordered=tui_bordered,
        input_separator=input_separator,
        status_bar_position=status_bar_position,
        **colors,
        **elements,
    )


def load_custom_themes(themes_dir: Path) -> int:
    """Scan a directory for .yaml theme files and register them.

    Returns the number of themes loaded. Custom themes override
    built-in themes with the same name.
    """
    if not themes_dir.is_dir():
        return 0
    count = 0
    for path in sorted(themes_dir.glob("*.yaml")):
        theme = load_theme_from_yaml(path)
        if theme:
            THEMES[theme.name] = theme
            count += 1
    for path in sorted(themes_dir.glob("*.yml")):
        theme = load_theme_from_yaml(path)
        if theme:
            THEMES[theme.name] = theme
            count += 1
    return count
