import pytest
from pathlib import Path

from todo.core.conflict import ConflictManager


class TestConflictManager:
    """Test ConflictManager functionality"""
    
    def test_checksum_storage_and_retrieval(self, conflict_manager):
        """Test storing and retrieving checksums"""
        checksums = {"file1": "hash1", "file2": "hash2"}
        conflict_manager.save_checksums(checksums)
        
        loaded = conflict_manager.load_checksums()
        assert loaded == checksums
    
    def test_no_conflict_new_file(self, temp_dir, conflict_manager):
        """Test no conflict for new file"""
        test_file = temp_dir / "test.todo"
        test_file.write_text("New content")
        
        conflict = conflict_manager.check_conflicts(test_file, "New content")
        assert conflict is None
    
    def test_no_conflict_matching_content(self, temp_dir, conflict_manager):
        """Test no conflict when file matches section content"""
        test_file = temp_dir / "test.todo"
        content = "Test content"
        test_file.write_text(content)
        
        # Update checksum
        conflict_manager.update_checksum(test_file)
        
        conflict = conflict_manager.check_conflicts(test_file, content)
        assert conflict is None
    
    def test_conflict_detection(self, temp_dir, conflict_manager):
        """Test conflict detection when file and section differ"""
        test_file = temp_dir / "test.todo"
        
        # Create initial file and record checksum
        test_file.write_text("Original content")
        conflict_manager.update_checksum(test_file)
        
        # Modify file
        test_file.write_text("Modified content")
        
        # Check conflict with different section content
        conflict = conflict_manager.check_conflicts(test_file, "Section content")
        
        assert conflict is not None
        assert "CONFLICT" in conflict