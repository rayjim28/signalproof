"""Compatibility entry point. Implementation: backend/quality_signals.py."""
import sys as _sys
from backend import quality_signals as _implementation
_sys.modules[__name__] = _implementation
if __name__ == '__main__':
    if hasattr(_implementation, 'main'):
        _implementation.main()
