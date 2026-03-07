import pytest
from todo.core.conflict import ConflictManager


class TestConflictManager:

    def test_update_and_load_checksum(self, conflict_manager, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] task one\n")
        conflict_manager.update_checksum(f)
        checksums = conflict_manager.load_checksums()
        assert "test.todo" in checksums
        assert len(checksums["test.todo"]) == 64

    def test_no_conflict_when_no_stored_checksum(self, conflict_manager, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] task one\n")
        result = conflict_manager.check_conflicts(f, "- [ ] different\n")
        assert result is None

    def test_no_conflict_when_same_content(self, conflict_manager, temp_dir):
        content = "- [ ] task one\n"
        f = temp_dir / "test.todo"
        f.write_text(content)
        conflict_manager.update_checksum(f)
        result = conflict_manager.check_conflicts(f, content)
        assert result is None

    def test_no_conflict_when_only_one_side_changed(self, conflict_manager, temp_dir):
        """If only remote changed (local == stored), no conflict"""
        content = "- [ ] task one\n"
        f = temp_dir / "test.todo"
        f.write_text(content)
        conflict_manager.update_checksum(f)
        # Remote is different, but local hasn't changed
        result = conflict_manager.check_conflicts(f, "- [ ] updated remotely\n")
        assert result is None

    def test_conflict_when_both_sides_changed(self, conflict_manager, temp_dir):
        original = "- [ ] task one\n"
        f = temp_dir / "test.todo"
        f.write_text(original)
        conflict_manager.update_checksum(f)
        # Now both sides change
        f.write_text("- [ ] local edit\n")
        result = conflict_manager.check_conflicts(f, "- [ ] remote edit\n")
        assert result is not None
        assert "CONFLICT" in result


class TestMergeFiles:

    def test_merge_adds_remote_only_tasks(self, conflict_manager, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] local task <!-- todo:id=aaa -->\n")
        result = conflict_manager.merge_files(
            f, "- [ ] remote task <!-- todo:id=bbb -->\n"
        )
        assert result["added"] == 1
        assert "local task" in result["merged_content"]
        assert "remote task" in result["merged_content"]

    def test_merge_local_wins_on_text_conflict(self, conflict_manager, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] local version <!-- todo:id=aaa -->\n")
        result = conflict_manager.merge_files(
            f, "- [ ] remote version <!-- todo:id=aaa -->\n"
        )
        assert len(result["conflicts"]) == 1
        # Local wins — merged content has local text
        assert "local version" in result["merged_content"]

    def test_merge_identical_is_noop(self, conflict_manager, temp_dir):
        content = "- [ ] same task <!-- todo:id=aaa -->\n"
        f = temp_dir / "test.todo"
        f.write_text(content)
        result = conflict_manager.merge_files(f, content)
        assert result["added"] == 0
        assert result["conflicts"] == []

    def test_merge_nonexistent_local(self, conflict_manager, temp_dir):
        f = temp_dir / "nonexistent.todo"
        result = conflict_manager.merge_files(
            f, "- [ ] remote task <!-- todo:id=aaa -->\n"
        )
        assert result["added"] == 1
        assert "remote task" in result["merged_content"]

    def test_merge_empty_remote(self, conflict_manager, temp_dir):
        f = temp_dir / "test.todo"
        f.write_text("- [ ] local task <!-- todo:id=aaa -->\n")
        result = conflict_manager.merge_files(f, "")
        assert result["added"] == 0
        assert "local task" in result["merged_content"]

    def test_parse_tasks_with_ids(self, conflict_manager):
        content = "- [ ] buy milk <!-- todo:id=abc123 -->\n- [x] done task <!-- todo:id=def456 -->\n"
        tasks = conflict_manager._parse_tasks(content)
        assert "abc123" in tasks
        assert "def456" in tasks

    def test_parse_tasks_without_ids(self, conflict_manager):
        content = "- [ ] no id task\n"
        tasks = conflict_manager._parse_tasks(content)
        assert "- [ ] no id task" in tasks
