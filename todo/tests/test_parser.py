import pytest

from todo.utils.parser import SectionParser
from todo.core.config import TodoConfig


class TestSectionParser:
    """Test SectionParser functionality"""
    
    def test_extract_sections_basic(self):
        """Test basic section extraction"""
        content = """# Header
<!-- BEGIN test/file.todo -->
This is test content
<!-- END test/file.todo -->

<!-- BEGIN another.todo -->
Another section
<!-- HASH: sha256:abcdef123456 -->
<!-- END another.todo -->"""
        
        sections = SectionParser.extract_sections(content)
        
        assert len(sections) == 2
        assert "test/file.todo" in sections
        assert "another.todo" in sections
        assert sections["test/file.todo"]["content"] == "This is test content"
        assert sections["another.todo"]["hash"] == "abcdef123456"
    
    def test_build_section_with_hash(self):
        """Test building a section with hash"""
        content = "Test todo content"
        section = SectionParser.build_section("test.todo", content, "abc123")
        
        assert "<!-- BEGIN test.todo -->" in section
        assert "<!-- END test.todo -->" in section
        assert "<!-- HASH: sha256:abc123 -->" in section
        assert content in section
    
    def test_build_toc_simple(self, temp_dir):
        """Test TOC generation in simple mode"""
        config_path = temp_dir / "config.json"
        config = TodoConfig(config_path)
        config.config["toc_mode"] = "simple"
        
        sections = {
            "app/feature.todo": {"content": "test"},
            "docs/readme.todo": {"content": "docs"}
        }
        
        toc = SectionParser.build_toc(sections, config)
        
        assert "# Table of Contents" in toc
        assert "- app/feature.todo" in toc
        assert "- docs/readme.todo" in toc
        assert "](#" not in toc  # No anchor links in simple mode
    
    def test_build_toc_anchors(self, temp_dir):
        """Test TOC generation with anchor links"""
        config_path = temp_dir / "config.json"
        config = TodoConfig(config_path)
        config.config["toc_mode"] = "anchors"
        
        sections = {"test.todo": {"content": "test"}}
        toc = SectionParser.build_toc(sections, config)
        
        assert "[test.todo](#test-todo)" in toc