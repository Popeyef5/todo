"""
Task parsing and manipulation for interactive mode
"""

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


TASK_RE = re.compile(r'^(\s*[-*]\s+\[)([ xX])(\]\s+)(.*)$')
TASK_ID_RE = re.compile(r'\s*<!-- todo:id=([a-f0-9]+) -->$')


@dataclass
class TaskRef:
    """Reference to a single checkbox task in a .todo file"""
    project_name: str
    todo_path: Path
    line_no: int
    checked: bool
    text: str
    indent: str = ""
    task_id: str = ""

    @property
    def display_file(self) -> str:
        return self.todo_path.name


def parse_tasks_from_file(file_path: Path, project_name: str = "") -> List[TaskRef]:
    """Parse all checkbox tasks from a .todo file"""
    tasks = []
    if not file_path.exists():
        return tasks

    lines = file_path.read_text().splitlines()
    for i, line in enumerate(lines):
        m = TASK_RE.match(line)
        if m:
            prefix = m.group(1)
            check_char = m.group(2)
            text = m.group(4)
            task_id = ""
            id_match = TASK_ID_RE.search(text)
            if id_match:
                task_id = id_match.group(1)
                text = text[:id_match.start()]
            indent = ""
            for ch in prefix:
                if ch in (' ', '\t'):
                    indent += ch
                else:
                    break
            tasks.append(TaskRef(
                project_name=project_name,
                todo_path=file_path,
                line_no=i,
                checked=check_char.lower() == 'x',
                text=text,
                indent=indent,
                task_id=task_id,
            ))
    return tasks


def ensure_task_ids(file_path: Path):
    """Add stable IDs to any checkbox tasks that don't have one yet."""
    if not file_path.exists():
        return
    lines = file_path.read_text().splitlines()
    changed = False
    for i, line in enumerate(lines):
        m = TASK_RE.match(line)
        if m and not TASK_ID_RE.search(m.group(4)):
            tid = uuid.uuid4().hex[:8]
            lines[i] = f"{line} <!-- todo:id={tid} -->"
            changed = True
    if changed:
        file_path.write_text("\n".join(lines) + "\n" if lines else "")


def _get_indent_level(line: str) -> int:
    """Return the number of leading spaces on a line."""
    return len(line) - len(line.lstrip())


def _find_subtree_end(lines: List[str], parent_line: int) -> int:
    """Return the line index *after* the last child (recursively) of parent_line.

    Children are lines that are indented more than the parent and are
    contiguous (no blank-line gap required — we just look at indentation).
    """
    parent_indent = _get_indent_level(lines[parent_line])
    end = parent_line + 1
    while end < len(lines):
        l = lines[end]
        if l.strip() == '':
            end += 1
            continue
        if _get_indent_level(l) > parent_indent:
            end += 1
        else:
            break
    return end


def _find_parent_line(lines: List[str], child_line: int) -> Optional[int]:
    """Walk upward from child_line to find the nearest task with strictly less indent."""
    child_indent = _get_indent_level(lines[child_line])
    if child_indent == 0:
        return None
    for i in range(child_line - 1, -1, -1):
        l = lines[i]
        if l.strip() == '':
            continue
        if _get_indent_level(l) < child_indent and TASK_RE.match(l):
            return i
    return None


def toggle_task_in_file(file_path: Path, line_no: int) -> bool:
    """Toggle a checkbox on a specific line. Returns new checked state.

    Completing a parent auto-completes all children.
    Un-completing a child auto-un-completes its ancestor chain.
    """
    lines = file_path.read_text().splitlines()
    if line_no >= len(lines):
        return False

    line = lines[line_no]
    m = TASK_RE.match(line)
    if not m:
        return False

    check_char = m.group(2)
    new_char = ' ' if check_char.lower() == 'x' else 'x'
    lines[line_no] = f"{m.group(1)}{new_char}{m.group(3)}{m.group(4)}"

    if new_char == 'x':
        # Completing: also complete all children
        parent_indent = _get_indent_level(lines[line_no])
        for i in range(line_no + 1, len(lines)):
            cl = lines[i]
            if cl.strip() == '':
                continue
            if _get_indent_level(cl) <= parent_indent:
                break
            cm = TASK_RE.match(cl)
            if cm and cm.group(2).lower() != 'x':
                lines[i] = f"{cm.group(1)}x{cm.group(3)}{cm.group(4)}"
    else:
        # Un-completing: un-complete ancestor chain
        cur = line_no
        while True:
            parent = _find_parent_line(lines, cur)
            if parent is None:
                break
            pm = TASK_RE.match(lines[parent])
            if pm and pm.group(2).lower() == 'x':
                lines[parent] = f"{pm.group(1)} {pm.group(3)}{pm.group(4)}"
            cur = parent

    file_path.write_text("\n".join(lines) + "\n" if lines else "")
    return new_char == 'x'


def add_task_to_file(file_path: Path, text: str, indent: str = "",
                     after_line: Optional[int] = None):
    """Add a new unchecked task to a file.

    If *after_line* is given the task is inserted right after that line's
    subtree (so sibling tasks stay grouped).  Otherwise it is appended.
    *indent* is the leading whitespace to prepend (e.g. "    " for a child).
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tid = uuid.uuid4().hex[:8]
    new_line = f"{indent}- [ ] {text} <!-- todo:id={tid} -->"

    if after_line is not None and file_path.exists():
        lines = file_path.read_text().splitlines()
        insert_at = _find_subtree_end(lines, after_line)
        lines.insert(insert_at, new_line)
        file_path.write_text("\n".join(lines) + "\n" if lines else "")
    else:
        content = file_path.read_text() if file_path.exists() else ""
        if content and not content.endswith("\n"):
            content += "\n"
        content += new_line + "\n"
        file_path.write_text(content)


def edit_task_in_file(file_path: Path, line_no: int, new_text: str) -> bool:
    """Edit the text of a task on a specific line"""
    lines = file_path.read_text().splitlines()
    if line_no >= len(lines):
        return False

    line = lines[line_no]
    m = TASK_RE.match(line)
    if not m:
        return False

    old_text = m.group(4)
    id_match = TASK_ID_RE.search(old_text)
    id_suffix = id_match.group(0) if id_match else ""
    lines[line_no] = f"{m.group(1)}{m.group(2)}{m.group(3)}{new_text}{id_suffix}"
    file_path.write_text("\n".join(lines) + "\n" if lines else "")
    return True


def remove_task_from_file(file_path: Path, line_no: int) -> bool:
    """Remove a task line and all its children from a file"""
    lines = file_path.read_text().splitlines()
    if line_no >= len(lines):
        return False

    line = lines[line_no]
    m = TASK_RE.match(line)
    if not m:
        return False

    subtree_end = _find_subtree_end(lines, line_no)
    del lines[line_no:subtree_end]
    file_path.write_text("\n".join(lines) + "\n" if lines else "")
    return True
