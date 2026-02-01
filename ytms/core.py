import os
import logging
from PIL import Image
from ytmusicapi import YTMusic
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError # type: ignore
from yt_dlp import YoutubeDL

# Default logger if none provided
default_logger = logging.getLogger("ytms")
default_logger.addHandler(logging.NullHandler())

class MusicDownloader:
    def __init__(self):
        self.ytmusic = YTMusic()

    def search(self, query):
        return self.ytmusic.search(query)

    def finalize_metadata(self, folder_path, main_artist, logger=None):
        """
        Sets 'Album Artist' and forces 'Track Number' from filename.
        """
        if not logger: logger = default_logger
        if not os.path.exists(folder_path): return

        logger.info(f"Finalizing Metadata for: {os.path.basename(folder_path)}")
        
        files = sorted([f for f in os.listdir(folder_path) if f.endswith(".mp3")])
        
        for filename in files:
            file_path = os.path.join(folder_path, filename)
            try:
                try:
                    audio = EasyID3(file_path)
                except ID3NoHeaderError:
                    audio = EasyID3()
                    audio.save(file_path)
                
                audio['albumartist'] = main_artist
                
                prefix = filename.split(" - ")[0]
                if prefix.isdigit():
                    audio['tracknumber'] = str(int(prefix))
                
                audio.save()
                logger.debug(f"Tagged: {filename}")
                
            except Exception as e:
                logger.error(f"Tag Error {filename}: {e}")

    def crop_images_in_folder(self, folder_path, logger=None):
        """
        Recursively scans folder for images that are wider than tall (pillarboxed) and crops them to a center square.
        """
        if not logger: logger = default_logger
        if not os.path.exists(folder_path): 
            logger.error(f"Path not found: {folder_path}")
            return

        logger.info(f"Recursively scanning for images to crop in: {folder_path}")
        
        count = 0
        scanned_files = 0
        scanned_folders = 0
        
        # Folders to ignore
        ignored_dirs = {'.git', '__pycache__', 'node_modules', 'venv', 'env', '.vscode', 'ytms.egg-info', 'build', 'dist'}

        for root, dirs, files in os.walk(folder_path):
            # Modify dirs in-place to skip ignored directories
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            
            scanned_folders += 1
            for file in files:
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    scanned_files += 1
                    image_path = os.path.join(root, file)
                    try:
                        with Image.open(image_path) as img:
                            width, height = img.size
                            # If width is significantly larger than height (e.g. > 5% difference), crop to square
                            if width > height * 1.05: 
                                new_width = height
                                left = int((width - new_width) / 2)
                                top = 0
                                right = int((width + new_width) / 2)
                                bottom = height
                                
                                img_cropped = img.crop((left, top, right, bottom))
                                img_cropped.save(image_path)
                                logger.info(f"Cropped: {file} ({width}x{height} -> {new_width}x{height})")
                                count += 1
                    except Exception as e:
                        logger.error(f"Error cropping {file}: {e}")
        
        logger.info(f"Finished. Scanned {scanned_folders} folders, {scanned_files} images. Cropped {count} images.")

    def download_item(self, data, download_path=None, logger=None, status_callback=None):
        """
        Downloads a song or album.
        
        Args:
            data (dict): The metadata object from search results.
            download_path (str, optional): Target directory. Defaults to CWD.
            logger (object, optional): Logger object with debug/info/warning/error methods.
            status_callback (callable, optional): Function to receive status strings (e.g. "Downloading...").
        """
        if not logger: logger = default_logger
        
        try:
            item_type = data['resultType']
            title = data.get('title', data.get('artist', 'Unknown'))
            
            # Determine Main Artist
            main_artist = "Unknown Artist"
            if 'artists' in data and data['artists']:
                main_artist = data['artists'][0]['name']
            elif 'artist' in data:
                main_artist = data['artist']

            # Setup Paths
            if download_path:
                base_dir = download_path
            else:
                base_dir = os.getcwd()
            
            cookie_path = os.path.join(os.getcwd(), "cookies.txt")
            has_cookies = os.path.exists(cookie_path)

            video_id = data.get('videoId')
            browse_id = data.get('browseId')
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'cookiefile': 'cookies.txt' if has_cookies else None,
                'postprocessors': [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
                    {'key': 'EmbedThumbnail'},
                    {'key': 'FFmpegMetadata'},
                ],
                'writethumbnail': True,
                'quiet': True,  # Important: We suppress stdout, use logger instead
                'logger': logger, # Route logs to Right Panel
            }

            target_folder = ""
            url = ""

            if item_type == "album":
                url = f"https://music.youtube.com/browse/{browse_id}"
                ydl_opts['outtmpl'] = f'{base_dir}/{main_artist}/{title}/%(playlist_index)02d - %(title)s.%(ext)s'
                target_folder = f'{base_dir}/{main_artist}/{title}'

            elif item_type == "song" or item_type == "video":
                url = f"https://music.youtube.com/watch?v={video_id}"
                
                album_data = data.get('album')
                if album_data and isinstance(album_data, dict):
                    album_name = album_data.get('name', 'Singles')
                else:
                    album_name = 'Singles'
                    
                ydl_opts['outtmpl'] = f'{base_dir}/{main_artist}/{album_name}/%(title)s.%(ext)s'
                target_folder = f'{base_dir}/{main_artist}/{album_name}'
            
            elif item_type == "artist":
                logger.error("Artist batch download not supported. Skipping.")
                return

            # Start Download
            if status_callback: status_callback("Downloading...")
            
            with YoutubeDL(ydl_opts) as ydl: # type: ignore
                ydl.download([url])            
            # Tagging
            if status_callback: status_callback("Finalizing Tags...")
            self.finalize_metadata(target_folder, main_artist, logger)
            
            logger.info(f"Completed: {title}")

        except Exception as e:
            logger.error(f"Error: {e}")
            raise e
