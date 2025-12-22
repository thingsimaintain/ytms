import os
from setuptools import setup, find_packages

setup(
    name="musicdl",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "ytmusicapi",
        "yt-dlp",
        "mutagen",
        "rich",
    ],
    entry_points={
        "console_scripts": [
            "musicdl=musicdl.cli:main",
        ],
    },
    author="Your Name",
    description="A Python package for downloading music from YouTube Music with metadata.",
    long_description=open("README.md").read() if os.path.exists("README.md") else "",
    long_description_content_type="text/markdown",
)
