import pytest
from todo.utils.hash import FileHasher


class TestFileHasher:

    def test_hash_content_deterministic(self):
        h1 = FileHasher.hash_content("hello world")
        h2 = FileHasher.hash_content("hello world")
        assert h1 == h2

    def test_hash_content_different_inputs(self):
        h1 = FileHasher.hash_content("hello")
        h2 = FileHasher.hash_content("world")
        assert h1 != h2

    def test_hash_file(self, temp_dir):
        f = temp_dir / "test.txt"
        f.write_text("some content")
        h = FileHasher.hash_file(f)
        assert len(h) == 64  # SHA-256 hex digest

    def test_hash_file_matches_hash_content(self, temp_dir):
        content = "line1\nline2\n"
        f = temp_dir / "test.txt"
        f.write_text(content)
        assert FileHasher.hash_file(f) == FileHasher.hash_content(content)

    def test_hash_nonexistent_file(self, temp_dir):
        assert FileHasher.hash_file(temp_dir / "nope.txt") == ""

    def test_hash_empty_file(self, temp_dir):
        f = temp_dir / "empty.txt"
        f.write_text("")
        h = FileHasher.hash_file(f)
        assert h == FileHasher.hash_content("")
