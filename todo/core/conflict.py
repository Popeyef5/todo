import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from todo.utils.hash import FileHasher


class ConflictManager:
    """Detect and manage conflicts between local files and remote content"""
    
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.checksums_file = cache_dir / "checksums.json"
    
    def save_checksums(self, checksums: dict):
        """Save checksums map to checksums.json"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self.checksums_file, 'w') as f:
            json.dump(checksums, f, indent=2)
    
    def load_checksums(self) -> dict:
        """Load checksums map from checksums.json, return {} if not found"""
        if self.checksums_file.exists():
            try:
                with open(self.checksums_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}
    
    def update_checksum(self, file_path: Path):
        """Hash the file and store in checksums map keyed by file name"""
        checksums = self.load_checksums()
        checksums[file_path.name] = FileHasher.hash_file(file_path)
        self.save_checksums(checksums)
    
    def check_conflicts(self, file_path: Path, content: str) -> Optional[str]:
        """Check for conflicts between local file, remote content, and stored state.
        
        Returns None if no conflict, or a descriptive string containing 'CONFLICT'.
        """
        file_hash = FileHasher.hash_file(file_path)
        content_hash = FileHasher.hash_content(content)
        
        checksums = self.load_checksums()
        stored_hash = checksums.get(file_path.name)
        
        if stored_hash is None:
            return None
        
        if file_hash == content_hash:
            return None
        
        if file_hash != stored_hash and content_hash != stored_hash:
            return f"CONFLICT in {file_path.name}: local and remote have diverged"
        
        return None
    
    def merge_files(self, local_path: Path, remote_content: str) -> dict:
        """Task-level merge for .todo files.
        
        Parses both into task lists, matches by stable ID or text,
        and returns merge results. Local wins on conflicts.
        """
        local_content = ""
        if local_path.exists():
            local_content = local_path.read_text()
        
        local_tasks = self._parse_tasks(local_content)
        remote_tasks = self._parse_tasks(remote_content)
        
        conflicts: List[str] = []
        added = 0
        updated = 0
        
        merged = {}
        
        for task_id, task in local_tasks.items():
            merged[task_id] = task
        
        for task_id, task in remote_tasks.items():
            if task_id not in merged:
                merged[task_id] = task
                added += 1
            elif merged[task_id]["text"] != task["text"]:
                conflicts.append(
                    f"Task '{task_id}': local='{merged[task_id]['text']}' vs remote='{task['text']}'"
                )
                updated += 1
        
        merged_lines = [task["raw"] for task in merged.values()]
        merged_content = "\n".join(merged_lines)
        if merged_lines:
            merged_content += "\n"
        
        return {
            "merged_content": merged_content,
            "conflicts": conflicts,
            "added": added,
            "updated": updated,
        }
    
    def _parse_tasks(self, content: str) -> Dict[str, dict]:
        """Parse content into a dict of tasks keyed by stable ID or text."""
        tasks = {}
        id_pattern = re.compile(r'<!--\s*todo:id=(\S+)\s*-->')
        
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            
            match = id_pattern.search(stripped)
            if match:
                task_id = match.group(1)
                text = id_pattern.sub('', stripped).strip()
            else:
                task_id = stripped
                text = stripped
            
            tasks[task_id] = {"text": text, "raw": line}
        
        return tasks
