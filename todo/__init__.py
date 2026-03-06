"""
Todo - Centralized TODO management with multi-device sync
"""

__version__ = "2.0.0"

from .core.manager import TodoManager
from .core.config import TodoConfig

__all__ = [
    'TodoManager',
    'TodoConfig',
]
