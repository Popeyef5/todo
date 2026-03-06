"""Background sync - runs full sync in a daemon thread without blocking the UI"""

import io
import sys
import threading
from typing import Callable, List, Optional


class SyncState:
    """Thread-safe state shared between background sync thread and main thread"""

    def __init__(self):
        self._lock = threading.Lock()
        self._needs_apply = False
        self._sync_conflicts: List[str] = []
        self._last_error: Optional[str] = None
        self._check_in_progress = False

    @property
    def needs_apply(self) -> bool:
        with self._lock:
            return self._needs_apply

    @property
    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error

    @property
    def check_in_progress(self) -> bool:
        with self._lock:
            return self._check_in_progress

    def set_sync_complete(self, has_new_data: bool, conflicts: list = None):
        """Called by background thread after a full sync."""
        with self._lock:
            if has_new_data:
                self._needs_apply = True
            self._sync_conflicts = conflicts or []
            self._check_in_progress = False
            self._last_error = None

    def set_remote_update(self, remote_sha: str):
        """Called by background thread when new remote data is detected (fetch-only mode)."""
        with self._lock:
            self._needs_apply = True
            self._last_error = None

    def set_error(self, error: str):
        """Called by background thread on check failure"""
        with self._lock:
            self._last_error = error
            self._check_in_progress = False

    def set_check_started(self):
        with self._lock:
            self._check_in_progress = True

    def set_check_finished(self):
        with self._lock:
            self._check_in_progress = False

    def mark_applied(self) -> List[str]:
        """Called by main thread after refreshing tasks. Returns any conflicts."""
        with self._lock:
            self._needs_apply = False
            conflicts = self._sync_conflicts
            self._sync_conflicts = []
            return conflicts

    def set_up_to_date(self):
        """Called by background thread when no changes detected"""
        with self._lock:
            self._check_in_progress = False
            self._last_error = None


class BackgroundSync:
    """Runs periodic sync in a daemon thread.

    Two modes:
    - Full sync mode (sync_fn provided): calls sync_fn() which handles push+pull.
    - Fetch-only mode (no sync_fn): calls main_sync.smart_fetch() to detect remote changes.
    """

    def __init__(self, main_sync, interval: int = 60,
                 sync_fn: Callable[[], dict] = None):
        """
        Args:
            main_sync: MainSync instance (used for is_sync_enabled and fetch-only mode)
            interval: Seconds between checks
            sync_fn: Optional callable that runs a full sync and returns a result dict
                     with keys 'sync' (dict with 'pulled') and 'conflicts' (list).
        """
        self.main_sync = main_sync
        self.interval = interval
        self.sync_fn = sync_fn
        self.state = SyncState()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        """Start the background sync thread"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the background sync thread"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        """Main loop for the background thread"""
        self._check_once()

        while not self._stop_event.is_set():
            if self._stop_event.wait(timeout=self.interval):
                break
            self._check_once()

    def _check_once(self):
        """Run a single sync cycle"""
        self.state.set_check_started()
        try:
            if not self.main_sync.is_sync_enabled():
                self.state.set_check_finished()
                return

            if self.sync_fn:
                self._do_full_sync()
            else:
                self._do_fetch_only()

        except Exception as e:
            self.state.set_error(str(e))

    def _do_full_sync(self):
        """Full sync mode: push local + pull remote in background."""
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            result = self.sync_fn()
        except Exception:
            result = {"sync": {"status": "error"}, "conflicts": []}
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        sync_info = result.get("sync", {})
        pulled = sync_info.get("pulled", False)
        conflicts = result.get("conflicts", [])
        self.state.set_sync_complete(pulled, conflicts)

    def _do_fetch_only(self):
        """Fetch-only mode: just detect remote changes."""
        result = self.main_sync.smart_fetch()

        if result["status"] == "error":
            self.state.set_error("fetch failed")
            return

        if result["status"] in ("behind", "diverged"):
            self.state.set_remote_update(result["remote_sha"])
        else:
            self.state.set_up_to_date()

        self.state.set_check_finished()
