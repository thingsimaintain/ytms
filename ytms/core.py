import os
import logging
import io
from PIL import Image
from ytmusicapi import YTMusic
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, ID3NoHeaderError
from yt_dlp import YoutubeDL

# Default logger if none provided
default_logger = logging.getLogger("ytms")
default_logger.addHandler(logging.NullHandler())

def crop_center_square(image_path, logger=None):
    try:
        if logger: logger.debug(f"Cropping thumbnail: {image_path}")
        img = Image.open(image_path)
        width, height = img.size
        
        # Youtube Music adds bars to the sides
        if width == height:
            if logger: logger.debug("Image is already square.")
            return True
            
        new_dim = min(width, height)
        
        left = (width - new_dim)/2
        top = (height - new_dim)/2
        right = (width + new_dim)/2
        bottom = (height + new_dim)/2

        img = img.crop((left, top, right, bottom))
        img.save(image_path)
        return True
    except Exception as e:
        if logger: logger.error(f"Error cropping {image_path}: {e}")
        return False

class MusicDownloader:
    def __init__(self):
        self.ytmusic = YTMusic()

    def search(self, query):
        return self.ytmusic.search(query)

    def embed_artwork(self, folder_path, logger=None):
        if not logger: logger = default_logger
        if not os.path.exists(folder_path): return
        
        # Find all images
        images = [f for f in os.listdir(folder_path) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
        
        for img_name in images:
            img_path = os.path.join(folder_path, img_name)
            
            # Crop Image
            if crop_center_square(img_path, logger):
                # Find matching mp3
                base_name = os.path.splitext(img_name)[0]
                mp3_path = os.path.join(folder_path, base_name + ".mp3")
                
                if os.path.exists(mp3_path):
                    try:
                        audio = MP3(mp3_path, ID3=ID3)
                        try:
                            audio.add_tags()
                        except ID3NoHeaderError:
                            pass
                        
                        mime = 'image/jpeg'
                        if img_name.lower().endswith('.png'): mime = 'image/png'
                        elif img_name.lower().endswith('.webp'): mime = 'image/webp'
                        
                        with open(img_path, 'rb') as albumart:
                            audio.tags.add(
                                APIC(
                                    encoding=3,
                                    mime=mime,
                                    type=3, desc=u'Cover',
                                    data=albumart.read()
                                )
                            )
                        audio.save()
                        logger.debug(f"Embedded Artwork: {mp3_path}")
                        
                        # Cleanup image
                        os.remove(img_path)
                        
                    except Exception as e:
                        logger.error(f"Error embedding art for {base_name}: {e}")

    def fix_embedded_artwork(self, folder_path, logger=None):
        if not logger: logger = default_logger
        if not os.path.exists(folder_path): return
        
        files = [f for f in os.listdir(folder_path) if f.endswith(".mp3")]
        
        for filename in files:
            file_path = os.path.join(folder_path, filename)
            try:
                audio = MP3(file_path, ID3=ID3)
                
                # Check for existing APIC
                found_art = False
                if audio.tags:
                    for tag_key in audio.tags.keys():
                        if tag_key.startswith('APIC'):
                            tag = audio.tags[tag_key]
                            # Extract
                            img_data = tag.data
                            
                            try:
                                updated = False
                                with io.BytesIO(img_data) as buf:
                                    img = Image.open(buf)
                                    width, height = img.size
                                    if(abs(width - height) > 1): # Tolerance of 1px
                                        # Crop
                                        new_dim = min(width, height)
                                        left = (width - new_dim)/2
                                        top = (height - new_dim)/2
                                        right = (width + new_dim)/2
                                        bottom = (height + new_dim)/2
                                        
                                        img = img.crop((left, top, right, bottom))
                                        
                                        # Save back to bytes
                                        out_buf = io.BytesIO()
                                        # Determine format from mime or original
                                        fmt = 'JPEG'
                                        if tag.mime == 'image/png': fmt = 'PNG'
                                        if tag.mime == 'image/webp': fmt = 'WEBP'
                                        
                                        img.save(out_buf, format=fmt)
                                        tag.data = out_buf.getvalue()
                                        updated = True
                                        logger.info(f"Cropped art for {filename}")
                                
                                if updated:
                                    found_art = True
                            except Exception as ex:
                                logger.error(f"Error processing art for {filename}: {ex}")
                
                if found_art:
                    audio.save()
                    
            except Exception as e:
                logger.error(f"Error checking {filename}: {e}")

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
                    # We handle thumbnail embedding manually to crop it first
                    #{'key': 'EmbedThumbnail'}, 
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
            
            # Post-process artwork
            if status_callback: status_callback("Processing Artwork...")
            self.embed_artwork(target_folder, logger)
            
            # Tagging
            if status_callback: status_callback("Finalizing Tags...")
            self.finalize_metadata(target_folder, main_artist, logger)
            
            logger.info(f"Completed: {title}")

        except Exception as e:
            logger.error(f"Error: {e}")
            raise e
