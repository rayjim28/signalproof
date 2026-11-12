"""Compatibility entry point. Implementation: backend/performance.py."""
import sys as _sys
from backend import performance as _implementation
_sys.modules[__name__] = _implementation
if __name__ == '__main__':
    if hasattr(_implementation, 'main'):
        _implementation.main()
