import os
from setuptools import setup, find_packages

# Read the package version from the package (without importing it)
import re

def _read_version():
    here = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(here, "ytms", "__init__.py"), "r", encoding="utf-8") as f:
        data = f.read()
    m = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", data, re.M)
    return m.group(1) if m else "0.0.0"

setup(
    name="ytms",
    version=_read_version(),
    packages=find_packages(),
    license="MIT",
    author="Your Name",
    author_email="you@example.com",
    url="https://github.com/<owner>/ytms",
    project_urls={
        "Source": "https://github.com/<owner>/ytms",
        "Tracker": "https://github.com/<owner>/ytms/issues",
    },
    install_requires=[
        "ytmusicapi",
        "yt-dlp",
        "mutagen",
        "rich",
        "Pillow",
        "Flask",
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
    description="A Python package for downloading music from YouTube Music with metadata (previously 'musicdl').",
    long_description=open("README.md").read() if os.path.exists("README.md") else "",
    long_description_content_type="text/markdown",
)
