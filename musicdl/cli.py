import sys
import time
import os
import argparse
from rich.console import Console
from rich.live import Live
from .core import MusicDownloader
from .ui import UIManager, RichLogger

console = Console()
downloader = MusicDownloader()

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

current_download_path = None

def process_queue(queue):
    """
    Iterates through the queue and downloads items inside the Rich Live UI.
    """
    clear_screen()
    
    ui_manager = UIManager()
    
    # Setup the Rich Live display
    with Live(ui_manager.layout, refresh_per_second=4, screen=True) as live:
        
        # Instantiate our custom logger
        ui_logger = RichLogger(ui_manager)

        for index, data in enumerate(queue):
            item_type = data['resultType']
            title = data.get('title', data.get('artist', 'Unknown'))
            
            # Determine Main Artist
            main_artist = "Unknown Artist"
            if 'artists' in data and data['artists']:
                main_artist = data['artists'][0]['name']
            elif 'artist' in data:
                main_artist = data['artist']

            # Update UI State (Left Panel)
            ui_manager.update_status(
                title=title,
                artist=main_artist,
                item_type=item_type,
                status="Initializing..."
            )
            # live.update() is not needed as we are updating the layout object directly

            try:
                # Pass live update callback if needed, but currently core updates status via ui_manager
                # However, we need to trigger live.update() when ui_manager changes.
                # Since core runs synchronously, we might not see updates unless we thread or callback.
                # For now, let's just rely on the fact that core calls logger which updates buffer, 
                # and we might need to hook into that or just update periodically.
                # Actually, the original code updated live inside the loop.
                # We can pass a callback to core or just let core update ui_manager and we update live here?
                # No, core blocks. 
                
                # To fix this properly without major refactor to async/threads:
                # We can pass a 'tick' function to core that updates the live display?
                # Or just pass the live object to core? Passing UI concerns to core is bad practice.
                # But for this simple app, let's just do the download in core and let core call logger.
                # The logger updates the buffer.
                # But the live display needs to be refreshed.
                # The original code did `live.update(generate_layout())` inside the loop.
                # But `ydl.download` blocks. `RichLogger` is called by `ydl`.
                # So inside `RichLogger.add_log`, we should probably trigger a refresh if we could.
                # But `RichLogger` doesn't have access to `live`.
                
                # Let's modify RichLogger in ui.py to accept a callback or the live object?
                # Or better, just pass the live context to the logger?
                # For now, let's just keep it simple. The original code didn't update live inside logger, 
                # it just updated it before and after download steps.
                # Wait, `ydl` calls logger methods. If we want real-time logs, we need to update live there.
                # The original code:
                # `with Live(...) as live:`
                # `   ...`
                # `   ydl_opts = { ..., 'logger': ui_logger }`
                # `   with YoutubeDL(ydl_opts) as ydl: ydl.download(...)`
                #
                # It seems the original code ONLY updated `live.update()` explicitly in the loop, 
                # NOT inside the logger. So the logs panel probably only updated when `live` auto-refreshed?
                # `Live(..., refresh_per_second=4)` handles the auto-refresh!
                # So as long as `ui_manager.generate_layout()` returns the new state, it works.
                # So we just need to make sure `ui_manager` is updated.
                
                # We need to pass a way for core to update the status text (Downloading, Tagging etc).
                # We passed `ui_manager` to `download_item`.
                
                downloader.download_item(data, ui_manager, ui_logger, download_path=current_download_path)

            except Exception as e:
                # Error is already logged in core
                time.sleep(2) 

        # Finished all
        ui_manager.update_status(
            title="All Tasks",
            artist="Completed",
            item_type="-",
            status="Done"
        )
        # live.update() not needed
        time.sleep(2)

def search_and_queue():
    global current_download_path
    queue = []
    
    while True:
        clear_screen()
        console.print(f"[bold cyan]=== musicdl ===[/]")
        if current_download_path:
            console.print(f"Download Path: [bold yellow]{current_download_path}[/]")
        else:
            console.print(f"Download Path: [bold yellow]Current Directory[/]")
            
        console.print(f"Current Queue: [bold green]{len(queue)} items[/]")
        for i, item in enumerate(queue):
            console.print(f"  {i+1}. {item.get('title')} ({item['resultType']})")
        
        print("\nOptions:")
        print("1. Search and Add to Queue")
        print("2. Start Download")
        print("3. Set Download Path")
        print("4. Quit")
        
        main_choice = input("\nSelect: ")
        
        if main_choice == '4':
            sys.exit()
            
        if main_choice == '3':
            path = input("\nEnter new download path: ").strip()
            if path:
                if os.path.exists(path):
                    current_download_path = path
                    print("Path updated.")
                else:
                    print("Path does not exist. Creating it...")
                    try:
                        os.makedirs(path, exist_ok=True)
                        current_download_path = path
                        print("Path created and updated.")
                    except Exception as e:
                        print(f"Error creating path: {e}")
            time.sleep(1)
            continue

        if main_choice == '2':
            if not queue:
                print("Queue is empty!")
                time.sleep(1)
                continue
            process_queue(queue)
            # Clear queue after processing
            queue = []
            input("\nBatch finished. Press Enter to continue...")
            continue

        if main_choice == '1':
            query = input("\nSearch for (Artist, Album, or Song): ")
            if not query: continue
            
            print("Searching...")
            try:
                results = downloader.search(query)
            except Exception as e:
                print(f"Error connecting: {e}")
                time.sleep(2)
                continue
            
            valid_results = [r for r in results if r['resultType'] in ['song', 'album']] # Filtered out 'artist' for now
            
            if not valid_results:
                print("No results found.")
                time.sleep(1)
                continue

            print(f"\nResults for '{query}':")
            for i, res in enumerate(valid_results[:10]):
                kind = res['resultType'].upper()
                title = res.get('title', res.get('artist', 'Unknown'))
                artist_display = ""
                if 'artists' in res and res['artists']:
                    artist_display = f"- {res['artists'][0]['name']}"
                elif 'artist' in res:
                    artist_display = f"- {res['artist']}"
                
                print(f"{i+1}. [{kind}] {title} {artist_display}")

            choice = input("\nEnter number to Add to Queue (or 'b' to back): ")
            if choice.lower() == 'b': continue
                
            try:
                selection_index = int(choice) - 1
                if 0 <= selection_index < len(valid_results):
                    selected = valid_results[selection_index]
                    queue.append(selected)
                    print(f"Added '{selected.get('title')}' to queue.")
                    time.sleep(1)
                else:
                    print("Invalid number.")
                    time.sleep(1)
            except ValueError:
                print("Invalid input.")
                time.sleep(1)

def main():
    global current_download_path
    parser = argparse.ArgumentParser(description="Music Downloader")
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument("--interactive", "-i", action="store_true", help="Run in interactive mode")
    parser.add_argument("--output", "-o", help="Output directory")
    args = parser.parse_args()

    if args.output:
        current_download_path = args.output
        if not os.path.exists(current_download_path):
            try:
                os.makedirs(current_download_path, exist_ok=True)
            except Exception as e:
                print(f"Error creating output directory: {e}")
                return

    if args.interactive or not args.query:
        try:
            search_and_queue()
        except KeyboardInterrupt:
            print("\nExiting...")
            sys.exit()
    else:
        # Quick search and download first result
        print(f"Searching for '{args.query}'...")
        try:
            results = downloader.search(args.query)
            valid_results = [r for r in results if r['resultType'] in ['song', 'album']]
            
            if not valid_results:
                print("No results found.")
                return

            # Pick first result
            selected = valid_results[0]
            print(f"Found: {selected.get('title')} ({selected['resultType']})")
            
            process_queue([selected])
            
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
