"""Compatibility entry point. Implementation: backend/app.py."""
import sys as _sys
from backend import app as _implementation
_sys.modules[__name__] = _implementation
if __name__ == '__main__':
    if hasattr(_implementation, 'main'):
        _implementation.main()
