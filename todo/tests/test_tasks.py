import re
import pytest
from pathlib import Path

from todo.ui.tasks import (
    TaskRef, parse_tasks_from_file, toggle_task_in_file,
    add_task_to_file, edit_task_in_file, remove_task_from_file,
    ensure_task_ids,
)

TASK_ID_RE = re.compile(r'<!-- todo:id=([a-f0-9]+) -->')


class TestParseTasksFromFile:

    def test_parse_unchecked(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] buy milk\n- [ ] write tests\n")
        tasks = parse_tasks_from_file(f, "proj")
        assert len(tasks) == 2
        assert tasks[0].text == "buy milk"
        assert tasks[0].checked is False
        assert tasks[0].project_name == "proj"

    def test_parse_checked(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [x] done task\n")
        tasks = parse_tasks_from_file(f)
        assert len(tasks) == 1
        assert tasks[0].checked is True

    def test_parse_with_ids(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] task <!-- todo:id=abc12345 -->\n")
        tasks = parse_tasks_from_file(f)
        assert tasks[0].task_id == "abc12345"
        assert tasks[0].text == "task"

    def test_parse_indented_subtasks(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] parent\n    - [ ] child\n")
        tasks = parse_tasks_from_file(f)
        assert len(tasks) == 2
        assert tasks[0].indent == ""
        assert tasks[1].indent == "    "

    def test_parse_nonexistent_file(self, temp_dir):
        tasks = parse_tasks_from_file(temp_dir / "nope.todo")
        assert tasks == []

    def test_parse_empty_file(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("")
        tasks = parse_tasks_from_file(f)
        assert tasks == []

    def test_parse_ignores_non_task_lines(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("# Header\nSome text\n- [ ] actual task\n\n")
        tasks = parse_tasks_from_file(f)
        assert len(tasks) == 1

    def test_display_file(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] task\n")
        tasks = parse_tasks_from_file(f)
        assert tasks[0].display_file == "test.todo"


class TestToggleTask:

    def test_toggle_unchecked_to_checked(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] task one\n")
        result = toggle_task_in_file(f, 0)
        assert result is True
        assert "[x]" in f.read_text()

    def test_toggle_checked_to_unchecked(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [x] task one\n")
        result = toggle_task_in_file(f, 0)
        assert result is False
        assert "[ ]" in f.read_text()

    def test_toggle_parent_completes_children(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] parent\n    - [ ] child1\n    - [ ] child2\n")
        toggle_task_in_file(f, 0)
        content = f.read_text()
        assert content.count("[x]") == 3

    def test_uncomplete_child_uncompletes_parent(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [x] parent\n    - [x] child\n")
        toggle_task_in_file(f, 1)
        content = f.read_text()
        assert content.count("[ ]") == 2

    def test_toggle_invalid_line(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] task\n")
        result = toggle_task_in_file(f, 99)
        assert result is False


class TestAddTask:

    def test_add_to_empty_file(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("")
        add_task_to_file(f, "new task")
        content = f.read_text()
        assert "- [ ] new task" in content
        assert TASK_ID_RE.search(content)

    def test_add_appends_to_existing(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] existing\n")
        add_task_to_file(f, "second")
        lines = f.read_text().splitlines()
        assert len(lines) == 2
        assert "second" in lines[1]

    def test_add_with_indent(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] parent\n")
        add_task_to_file(f, "child", indent="    ", after_line=0)
        content = f.read_text()
        assert "    - [ ] child" in content

    def test_add_creates_file_if_needed(self, temp_dir):
        f = temp_dir / "sub" / "test.todo"
        add_task_to_file(f, "task in new file")
        assert f.exists()
        assert "task in new file" in f.read_text()

    def test_add_after_line_inserts_correctly(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] first\n- [ ] third\n")
        add_task_to_file(f, "second", after_line=0)
        lines = f.read_text().splitlines()
        assert "second" in lines[1]
        assert "third" in lines[2]


class TestEditTask:

    def test_edit_text(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] old text <!-- todo:id=abc -->\n")
        result = edit_task_in_file(f, 0, "new text")
        assert result is True
        content = f.read_text()
        assert "new text" in content
        assert "abc" in content  # ID preserved

    def test_edit_preserves_checked_state(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [x] done <!-- todo:id=abc -->\n")
        edit_task_in_file(f, 0, "still done")
        assert "[x]" in f.read_text()

    def test_edit_invalid_line(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] task\n")
        assert edit_task_in_file(f, 99, "nope") is False


class TestRemoveTask:

    def test_remove_single_task(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] keep\n- [ ] remove\n- [ ] also keep\n")
        result = remove_task_from_file(f, 1)
        assert result is True
        content = f.read_text()
        assert "remove" not in content
        assert "keep" in content

    def test_remove_with_children(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] parent\n    - [ ] child1\n    - [ ] child2\n- [ ] sibling\n")
        remove_task_from_file(f, 0)
        content = f.read_text()
        assert "parent" not in content
        assert "child" not in content
        assert "sibling" in content

    def test_remove_invalid_line(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] task\n")
        assert remove_task_from_file(f, 99) is False


class TestEnsureTaskIds:

    def test_adds_ids_to_tasks_without_them(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] task one\n- [x] task two\n")
        ensure_task_ids(f)
        content = f.read_text()
        ids = TASK_ID_RE.findall(content)
        assert len(ids) == 2
        assert ids[0] != ids[1]

    def test_preserves_existing_ids(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] task <!-- todo:id=aabb1122 -->\n")
        ensure_task_ids(f)
        content = f.read_text()
        assert "aabb1122" in content
        # Should not double-add
        assert content.count("todo:id=") == 1

    def test_noop_on_nonexistent_file(self, temp_dir):
        ensure_task_ids(temp_dir / "nope.todo")  # should not raise

    def test_mixed_ids(self, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] has id <!-- todo:id=aaa -->\n- [ ] no id\n")
        ensure_task_ids(f)
        content = f.read_text()
        ids = TASK_ID_RE.findall(content)
        assert len(ids) == 2
        assert "aaa" in ids
