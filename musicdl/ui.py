from collections import deque
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich import box

class UIManager:
    def __init__(self):
        self.console = Console()
        self.log_buffer = deque(maxlen=20)
        self.current_status_info = {
            "title": "Waiting...",
            "artist": "...",
            "type": "...",
            "status": "Idle"
        }

    def update_status(self, title=None, artist=None, item_type=None, status=None):
        if title: self.current_status_info['title'] = title
        if artist: self.current_status_info['artist'] = artist
        if item_type: self.current_status_info['type'] = item_type
        if status: self.current_status_info['status'] = status

    def add_log(self, msg):
        clean_msg = msg.replace('[download]', '').strip()
        if clean_msg:
            self.log_buffer.append(clean_msg)

    def generate_layout(self):
        layout = Layout()
        layout.split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1)
        )
        
        # Left: Status
        status_text = Text()
        status_text.append(f"\nCurrently Downloading:\n", style="bold underline green")
        status_text.append(f"{self.current_status_info['title']}\n", style="bold white")
        status_text.append(f"\nArtist:\n", style="bold underline green")
        status_text.append(f"{self.current_status_info['artist']}\n", style="white")
        status_text.append(f"\nType:\n", style="bold underline green")
        status_text.append(f"{self.current_status_info['type'].upper()}\n", style="yellow")
        status_text.append(f"\nStatus:\n", style="bold underline green")
        status_text.append(f"{self.current_status_info['status']}", style="cyan blink")

        left_panel = Panel(
            status_text,
            title="[bold green]Current Selection[/]",
            border_style="green",
            box=box.ROUNDED
        )

        # Right: Logs
        log_content = "\n".join(self.log_buffer)
        right_panel = Panel(
            log_content,
            title="[bold blue]Process Logs[/]",
            border_style="blue",
            box=box.ROUNDED
        )

        layout["left"].update(left_panel)
        layout["right"].update(right_panel)
        
        return layout

class RichLogger:
    def __init__(self, ui_manager):
        self.ui_manager = ui_manager

    def debug(self, msg):
        # Filter out verbose debugs, keep relevant download info
        if not msg.startswith('[debug] '):
            self.ui_manager.add_log(f"[dim]{msg}[/]")

    def info(self, msg):
        self.ui_manager.add_log(f"[blue]{msg}[/]")

    def warning(self, msg):
        self.ui_manager.add_log(f"[yellow]{msg}[/]")

    def error(self, msg):
        self.ui_manager.add_log(f"[red bold]{msg}[/]")
