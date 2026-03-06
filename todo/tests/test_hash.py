import pytest
from pathlib import Path

from todo.utils.hash import FileHasher


class TestFileHasher:
    """Test FileHasher utility class"""
    
    def test_hash_file_content(self, temp_dir):
        """Test file content hashing"""
        test_file = temp_dir / "test.txt"
        content = "Hello, World!"
        test_file.write_text(content)
        
        file_hash = FileHasher.hash_file(test_file)
        content_hash = FileHasher.hash_content(content)
        
        assert file_hash == content_hash
        assert len(file_hash) == 64  # SHA-256 produces 64-char hex
    
    def test_hash_nonexistent_file(self, temp_dir):
        """Test hashing non-existent file returns empty string"""
        nonexistent = temp_dir / "nonexistent.txt"
        assert FileHasher.hash_file(nonexistent) == ""
    
    def test_hash_consistency(self):
        """Test that same content produces same hash"""
        content = "Test content for hashing"
        hash1 = FileHasher.hash_content(content)
        hash2 = FileHasher.hash_content(content)
        assert hash1 == hash2
