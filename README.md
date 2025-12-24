![ytms](logo.png)

A Python package for downloading music from YouTube Music with metadata.

## Installation

```bash
pip install .
```

## Usage

### CLI Usage

```bash
ytms
# compatibility alias
musicdl
```

### Python Usage

```python
from ytms import MusicDownloader
import logging

# Initialize
md = MusicDownloader()

# Search
results = md.search("Nothing Matters Vince Staples")
song_data = results[0]

# Download
# You can pass a standard Python logger and a callback function for status updates
md.download_item(
    song_data, 
    download_path="/path/to/downloads", 
    logger=logging.getLogger(__name__),
    status_callback=lambda msg: print(f"Status: {msg}")
)
```

## Features

- Search for songs and albums on YouTube Music.
- Download high-quality audio.
- Automatically tag files with metadata (Artist, Album, Track Number).
- Rich TUI interface.
- It can also be referenced programatically

## Web UI (Flask) ✅

A simple web interface is provided in `webapp.py` that mimics the CLI flow: search, queue items, and download in the background. To run:

```bash
pip install -r requirements.txt
python webapp.py
```

Open http://127.0.0.1:5000 in your browser. The UI supports quick downloads, queueing multiple items, and shows basic status (polling).
