import os
from setuptools import setup, find_packages

setup(
    name="ytms",
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
            "ytms=ytms.cli:main",
            "musicdl=ytms.cli:main",  # compatibility alias
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    author="Your Name",
    description="A Python package for downloading music from YouTube Music with metadata (previously 'musicdl').",
    long_description=open("README.md").read() if os.path.exists("README.md") else "",
    long_description_content_type="text/markdown",
)
