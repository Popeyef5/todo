import hashlib
from pathlib import Path


class FileHasher:
    """Handle file hashing for conflict detection"""
    
    @staticmethod
    def hash_file(file_path: Path) -> str:
        """Generate SHA-256 hash of file content"""
        if not file_path.exists():
            return ""
        
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    @staticmethod
    def hash_content(content: str) -> str:
        """Generate SHA-256 hash of string content"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()