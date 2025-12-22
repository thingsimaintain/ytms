import warnings
from ytms.core import MusicDownloader as _MusicDownloader
from ytms.cli import main as _main

# Backwards-compatibility shim
warnings.warn("'musicdl' package is deprecated; import from 'ytms' instead", DeprecationWarning)

def MusicDownloader(*args, **kwargs):
    """Compatibility wrapper: use ytms.MusicDownloader instead."""
    return _MusicDownloader(*args, **kwargs)

main = _main

__all__ = ["MusicDownloader", "main"]

__version__ = "0.1.0"
