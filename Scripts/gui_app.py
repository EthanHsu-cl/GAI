#!/usr/bin/env python3
"""
Desktop GUI Application for the Automated Processing & Reporting Suite.

This module provides a user-friendly desktop interface for running API
processing and report generation tasks. It wraps the existing CLI
functionality in an accessible graphical interface suitable for
non-technical users.

Uses tkinter (built-in) for cross-platform compatibility.
"""

import copy
import json
import logging
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString, DoubleQuotedScalarString


def _is_frozen() -> bool:
    """Check if running as a PyInstaller bundle."""
    return getattr(sys, 'frozen', False)


def _get_script_dir() -> Path:
    """
    Get the script directory, handling both development and bundled modes.
    
    Returns:
        Path to the script directory (or equivalent in bundled app).
    """
    if _is_frozen():
        # Running in a PyInstaller bundle
        if hasattr(sys, '_MEIPASS'):
            return Path(sys._MEIPASS)
        else:
            return Path(sys.executable).parent
    else:
        # Running in normal Python environment
        return Path(__file__).parent


# Ensure we can import from core directory
script_dir = _get_script_dir()
core_dir = script_dir / "core"
sys.path.insert(0, str(core_dir))

from core.runall import run_automation, API_MAPPING, CONFIG_MAPPING
from core.config_loader import ConfigLoader, get_default_config_path

# Logger for this module
logger = logging.getLogger(__name__)


# =============================================================================
# API FIELD SCHEMAS
# Each API has different task fields. This defines the UI fields for each.
# Field types: 'text', 'multiline', 'dropdown', 'checkbox', 'number', 'folder'
# =============================================================================

API_FIELD_SCHEMAS = {
    'nano_banana': {
        'name': 'Nano Banana (Gemini Image Generation)',
        'fields': [
            {'key': 'folder', 'label': 'Task Folder', 'type': 'folder', 'required': True,
             'help': 'Folder with Source subfolder containing images'},
            {'key': 'model', 'label': 'Model', 'type': 'dropdown', 
             'options': ['gemini-2.5-flash-image', 'gemini-3-pro-image-preview'],
             'default': 'gemini-2.5-flash-image',
             'help': 'flash: max 3 images, faster | pro: max 14 images, better quality'},
            {'key': 'resolution', 'label': 'Resolution', 'type': 'dropdown',
             'options': ['1K', '2K'], 'default': '1K'},
            {'key': 'aspect_ratio', 'label': 'Aspect Ratio', 'type': 'dropdown',
             'options': ['', '1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9'],
             'default': '', 'help': 'Leave empty to auto-detect from source'},
            {'key': 'prompt', 'label': 'Prompt', 'type': 'multiline', 'height': 6, 'required': True},
            {'key': 'use_random_source_selection', 'label': 'Random Source Selection', 'type': 'checkbox', 'default': False,
             'help': 'Select N random images from Source folder per API call'},
            {'key': 'use_deterministic_random', 'label': 'Deterministic Random', 'type': 'checkbox', 'default': True,
             'help': 'Same folder = same selections every run (reproducible)'},
            {'key': 'random_seed', 'label': 'Random Seed', 'type': 'number', 'default': 42,
             'help': 'Seed for reproducible random selection'},
            {'key': 'min_images', 'label': 'Min Images', 'type': 'number', 'default': 1,
             'help': 'Minimum images per API call'},
            {'key': 'max_images', 'label': 'Max Images', 'type': 'number', 'default': 4,
             'help': 'Maximum images per API call (flash: 3, pro: 14)'},
            {'key': 'num_iterations', 'label': 'Iterations', 'type': 'number', 'default': 0,
             'help': 'Number of API calls (0 = use source file count)'},
        ]
    },
    'kling': {
        'name': 'Kling (Image-to-Video)',
        'fields': [
            {'key': 'folder', 'label': 'Task Folder', 'type': 'folder', 'required': True,
             'help': 'Folder with Source subfolder containing images'},
            {'key': 'mode', 'label': 'Mode', 'type': 'dropdown',
             'options': ['std', 'pro'], 'default': 'std'},
            {'key': 'prompt', 'label': 'Prompt', 'type': 'multiline', 'height': 4, 'required': True},
            {'key': 'negative_prompt', 'label': 'Negative Prompt', 'type': 'multiline', 'height': 2},
            {'key': 'duration', 'label': 'Duration (sec)', 'type': 'dropdown',
             'options': ['5', '10'], 'default': '5'},
            {'key': 'cfg', 'label': 'CFG Scale', 'type': 'number', 'default': 0.5,
             'help': 'Guidance scale (0.0-1.0)'},
            {'key': 'use_comparison_template', 'label': 'Use Comparison Template', 'type': 'checkbox', 'default': False},
            {'key': 'reference_folder', 'label': 'Reference Folder', 'type': 'folder',
             'help': 'Optional folder for comparison report'},
        ]
    },
    'kling_effects': {
        'name': 'Kling Effects (Premade Effects)',
        'fields': [
            {'key': 'custom_effect', 'label': 'Effect Name', 'type': 'text', 'required': True,
             'help': 'Effect name (used as subfolder name)'},
            {'key': 'effect', 'label': 'Preset Effect', 'type': 'dropdown',
             'options': ['', '3d_cartoon_1', '3d_cartoon_2', 'a_list_look', 'american_comics', 
                        'angel_wing', 'anime_figure', 'celebration', 'dark_wing', 'day_to_night',
                        'demon_transform', 'disappear', 'dollar_rain', 'emoji', 'expansion',
                        'new_year_greeting', 'prosperity', 'lantern_glow', 'lion_dance'],
             'default': '', 'help': 'Or choose a preset effect'},
            {'key': 'duration', 'label': 'Duration (sec)', 'type': 'dropdown',
             'options': ['5', '10'], 'default': '5'},
        ]
    },
    'kling_endframe': {
        'name': 'Kling Endframe (A→B Transitions)',
        'fields': [
            {'key': 'folder', 'label': 'Task Folder', 'type': 'folder', 'required': True,
             'help': 'Folder with Source subfolder (use A/B naming: Name_A.jpg, Name_B.jpg)'},
            {'key': 'prompt', 'label': 'Prompt', 'type': 'multiline', 'height': 3},
            {'key': 'negative_prompt', 'label': 'Negative Prompt', 'type': 'multiline', 'height': 2},
            {'key': 'mode', 'label': 'Mode', 'type': 'dropdown',
             'options': ['std', 'pro'], 'default': 'pro'},
            {'key': 'duration', 'label': 'Duration (sec)', 'type': 'dropdown',
             'options': ['5', '10'], 'default': '5'},
            {'key': 'cfg', 'label': 'CFG Scale', 'type': 'number', 'default': 0.5,
             'help': 'Guidance scale (0.0-1.0)'},
            {'key': 'generation_count', 'label': 'Generation Count', 'type': 'number', 'default': 1,
             'help': 'Number of videos per image pair'},
            {'key': 'pairing_mode', 'label': 'Pairing Mode', 'type': 'dropdown',
             'options': ['ab_naming', 'sequential'], 'default': 'ab_naming',
             'help': 'ab_naming: Name_A/Name_B pairs | sequential: first half → second half'},
        ]
    },
    'kling_ttv': {
        'name': 'Kling TTV (Text-to-Video)',
        'fields': [
            {'key': 'style_name', 'label': 'Style Name', 'type': 'text', 'required': True,
             'help': 'Name for the output video'},
            {'key': 'prompt', 'label': 'Prompt', 'type': 'multiline', 'height': 4, 'required': True},
            {'key': 'neg_prompt', 'label': 'Negative Prompt', 'type': 'multiline', 'height': 2},
            {'key': 'mode', 'label': 'Mode', 'type': 'dropdown',
             'options': ['std', 'pro'], 'default': 'pro'},
            {'key': 'duration', 'label': 'Duration (sec)', 'type': 'dropdown',
             'options': ['5', '10'], 'default': '5'},
            {'key': 'ratio', 'label': 'Aspect Ratio', 'type': 'dropdown',
             'options': ['1:1', '16:9', '9:16', '4:3', '3:4'], 'default': '1:1'},
            {'key': 'cfg', 'label': 'CFG Scale', 'type': 'number', 'default': 0.5,
             'help': 'Guidance scale (0.0-1.0)'},
            {'key': 'generation_count', 'label': 'Generation Count', 'type': 'number', 'default': 1,
             'help': 'Number of videos to generate'},
            {'key': 'sound_enabled', 'label': 'Enable Sound', 'type': 'checkbox', 'default': True},
        ]
    },
    'veo': {
        'name': 'Veo (Text-to-Video)',
        'fields': [
            {'key': 'style_name', 'label': 'Style Name', 'type': 'text', 'required': True,
             'help': 'Name for the output video'},
            {'key': 'output_folder', 'label': 'Output Folder', 'type': 'folder', 'required': True},
            {'key': 'prompt', 'label': 'Prompt', 'type': 'multiline', 'height': 4, 'required': True},
            {'key': 'negative_prompt', 'label': 'Negative Prompt', 'type': 'multiline', 'height': 2},
            {'key': 'model_id', 'label': 'Model', 'type': 'dropdown',
             'options': ['veo-3.1-generate-preview', 'veo-3.0-generate-preview'], 
             'default': 'veo-3.1-generate-preview'},
            {'key': 'duration_seconds', 'label': 'Duration (sec)', 'type': 'dropdown',
             'options': ['5', '6', '7', '8'], 'default': '6'},
            {'key': 'aspect_ratio', 'label': 'Aspect Ratio', 'type': 'dropdown',
             'options': ['16:9', '9:16', '1:1'], 'default': '16:9'},
            {'key': 'resolution', 'label': 'Resolution', 'type': 'dropdown',
             'options': ['720p', '1080p'], 'default': '1080p'},
            {'key': 'enhance_prompt', 'label': 'Enhance Prompt', 'type': 'checkbox', 'default': True},
            {'key': 'generate_audio', 'label': 'Generate Audio', 'type': 'checkbox', 'default': True},
            {'key': 'person_generation', 'label': 'Person Generation', 'type': 'dropdown',
             'options': ['allow_all', 'allow_adult', 'dont_allow'], 'default': 'allow_all'},
        ]
    },
    'veo_itv': {
        'name': 'Veo ITV (Image-to-Video)',
        'fields': [
            {'key': 'style_name', 'label': 'Style Name', 'type': 'text', 'required': True,
             'help': 'Name for the effect/style'},
            {'key': 'folder', 'label': 'Task Folder', 'type': 'folder', 'required': True,
             'help': 'Folder with Source subfolder'},
            {'key': 'prompt', 'label': 'Prompt', 'type': 'multiline', 'height': 4, 'required': True},
            {'key': 'negative_prompt', 'label': 'Negative Prompt', 'type': 'multiline', 'height': 2},
            {'key': 'model_id', 'label': 'Model', 'type': 'dropdown',
             'options': ['veo-3.1-generate-001', 'veo-3.0-generate-001'],
             'default': 'veo-3.1-generate-001'},
            {'key': 'duration_seconds', 'label': 'Duration (sec)', 'type': 'dropdown',
             'options': ['5', '6', '7', '8'], 'default': '8'},
            {'key': 'aspect_ratio', 'label': 'Aspect Ratio', 'type': 'dropdown',
             'options': ['16:9', '9:16', '1:1'], 'default': '16:9'},
            {'key': 'resolution', 'label': 'Resolution', 'type': 'dropdown',
             'options': ['720p', '1080p'], 'default': '1080p'},
            {'key': 'enhance_prompt', 'label': 'Enhance Prompt', 'type': 'checkbox', 'default': True},
            {'key': 'generate_audio', 'label': 'Generate Audio', 'type': 'checkbox', 'default': True},
            {'key': 'person_generation', 'label': 'Person Generation', 'type': 'dropdown',
             'options': ['allow_all', 'allow_adult', 'dont_allow'], 'default': 'allow_all'},
        ]
    },
    'pixverse': {
        'name': 'Pixverse (Effects)',
        'fields': [
            {'key': 'effect', 'label': 'Effect Name', 'type': 'text', 'required': True,
             'help': 'Effect name (used as subfolder name)'},
            {'key': 'custom_effect_id', 'label': 'Custom Effect ID', 'type': 'text',
             'help': 'Effect ID from Pixverse platform'},
            {'key': 'prompt', 'label': 'Prompt', 'type': 'multiline', 'height': 2},
            {'key': 'negative_prompt', 'label': 'Negative Prompt', 'type': 'multiline', 'height': 2},
            {'key': 'model', 'label': 'Model', 'type': 'dropdown',
             'options': ['v5.5', 'v4', 'v3.5'], 'default': 'v5.5'},
            {'key': 'duration', 'label': 'Duration', 'type': 'dropdown',
             'options': ['5s', '8s'], 'default': '5s'},
            {'key': 'quality', 'label': 'Quality', 'type': 'dropdown',
             'options': ['540p', '720p', '1080p'], 'default': '720p'},
            {'key': 'generate_audio', 'label': 'Generate Audio', 'type': 'checkbox', 'default': True},
        ]
    },
    'genvideo': {
        'name': 'GenVideo (Image Generation)',
        'fields': [
            {'key': 'folder', 'label': 'Task Folder', 'type': 'folder', 'required': True,
             'help': 'Folder with Source subfolder containing images'},
            {'key': 'img_prompt', 'label': 'Image Prompt', 'type': 'multiline', 'height': 4, 'required': True},
            {'key': 'model', 'label': 'Model', 'type': 'dropdown',
             'options': ['gpt-image-1'], 'default': 'gpt-image-1'},
            {'key': 'quality', 'label': 'Quality', 'type': 'dropdown',
             'options': ['low', 'medium', 'high'], 'default': 'medium'},
            {'key': 'use_comparison_template', 'label': 'Use Comparison Template', 'type': 'checkbox', 'default': False},
            {'key': 'reference_folder', 'label': 'Reference Folder', 'type': 'folder',
             'help': 'Optional folder for comparison report'},
        ]
    },
    'runway': {
        'name': 'Runway Gen4',
        'fields': [
            {'key': 'folder', 'label': 'Task Folder', 'type': 'folder', 'required': True,
             'help': 'Folder with Source Image and Source Video subfolders'},
            {'key': 'prompt', 'label': 'Prompt', 'type': 'multiline', 'height': 3, 'required': True},
            {'key': 'model', 'label': 'Model', 'type': 'dropdown',
             'options': ['gen4_aleph', 'gen3a_turbo'], 'default': 'gen4_aleph'},
            {'key': 'ratio', 'label': 'Aspect Ratio', 'type': 'dropdown',
             'options': ['1280:720', '720:1280', '1024:1024'], 'default': '1280:720'},
            {'key': 'pairing_strategy', 'label': 'Pairing Strategy', 'type': 'dropdown',
             'options': ['one_to_one', 'all_combinations'], 'default': 'all_combinations',
             'help': 'one_to_one: pair by index | all_combinations: every image × video'},
            {'key': 'use_comparison_template', 'label': 'Use Comparison Template', 'type': 'checkbox', 'default': False},
            {'key': 'reference_folder', 'label': 'Reference Folder', 'type': 'folder'},
        ]
    },
    'wan': {
        'name': 'Wan 2.2 (Image + Video)',
        'fields': [
            {'key': 'folder', 'label': 'Task Folder', 'type': 'folder', 'required': True,
             'help': 'Folder with Source Image and Source Video subfolders'},
            {'key': 'prompt', 'label': 'Prompt', 'type': 'multiline', 'height': 3},
            {'key': 'animation_mode', 'label': 'Animation Mode', 'type': 'dropdown',
             'options': ['move', 'mix'], 'default': 'move'},
            {'key': 'num_outputs', 'label': 'Num Outputs', 'type': 'number', 'default': 2,
             'help': 'Number of output variations'},
            {'key': 'seed', 'label': 'Seed', 'type': 'text', 'default': '-1',
             'help': '-1 for random seed'},
            {'key': 'embed', 'label': 'Embed', 'type': 'text', 'default': '',
             'help': 'Embedding parameter for the API'},
            {'key': 'use_comparison_template', 'label': 'Use Comparison Template', 'type': 'checkbox', 'default': False},
            {'key': 'reference_folder', 'label': 'Reference Folder', 'type': 'folder'},
        ]
    },
    'vidu_effects': {
        'name': 'Vidu Effects',
        'fields': [
            {'key': 'category', 'label': 'Category', 'type': 'text', 'default': 'Product',
             'help': 'Effect category (e.g., Product, Portrait)'},
            {'key': 'effect', 'label': 'Effect Name', 'type': 'text', 'required': True,
             'help': 'Effect name (must match subfolder name)'},
            {'key': 'prompt', 'label': 'Prompt', 'type': 'multiline', 'height': 3},
            {'key': 'model', 'label': 'Model', 'type': 'dropdown',
             'options': ['viduq2-pro', 'viduq1'], 'default': 'viduq2-pro'},
        ]
    },
    'vidu_reference': {
        'name': 'Vidu Reference',
        'fields': [
            {'key': 'effect', 'label': 'Effect/Style Name', 'type': 'text', 'required': True,
             'help': 'Effect name (must match subfolder name)'},
            {'key': 'prompt', 'label': 'Prompt', 'type': 'multiline', 'height': 3},
            {'key': 'model', 'label': 'Model', 'type': 'dropdown',
             'options': ['viduq1', 'viduq2-pro'], 'default': 'viduq1'},
            {'key': 'duration', 'label': 'Duration (sec)', 'type': 'dropdown',
             'options': ['4', '5', '8'], 'default': '5'},
            {'key': 'resolution', 'label': 'Resolution', 'type': 'dropdown',
             'options': ['720p', '1080p'], 'default': '1080p'},
            {'key': 'movement', 'label': 'Movement', 'type': 'dropdown',
             'options': ['auto', 'slow', 'normal', 'fast'], 'default': 'auto'},
        ]
    },
}


# Platform display names for the dropdown
PLATFORM_DISPLAY_NAMES = {
    'kling': 'Kling 2.1 (Image-to-Video)',
    'klingfx': 'Kling Effects (Premade Effects)',
    'kling_endframe': 'Kling Endframe (A→B Transitions)',
    'kling_ttv': 'Kling TTV (Text-to-Video)',
    'pixverse': 'Pixverse v4.5 (Effects)',
    'genvideo': 'GenVideo (Image Generation)',
    'nano': 'Nano Banana / Google Flash',
    'vidu': 'Vidu Effects',
    'viduref': 'Vidu Reference',
    'runway': 'Runway Gen4',
    'wan': 'Wan 2.2 (Image + Video)',
    'veo': 'Veo (Text-to-Video)',
    'veoitv': 'Veo ITV (Image-to-Video)',
    'all': '🔄 All Platforms',
}

ACTION_DISPLAY_NAMES = {
    'auto': 'Auto (Process + Report)',
    'process': 'Process Only',
    'report': 'Report Only',
}


class QueueHandler(logging.Handler):
    """
    Logging handler that sends log records to a queue.
    
    Used to safely pass log messages from background threads
    to the main GUI thread for display.
    """

    def __init__(self, log_queue: queue.Queue):
        """
        Initialize the queue handler.
        
        Args:
            log_queue: Queue to send log records to.
        """
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record by putting it in the queue.
        
        Args:
            record: Log record to emit.
        """
        self.log_queue.put(record)


class AutomationGUI:
    """
    Main GUI application for the Automated Processing Suite.
    
    Provides a user-friendly interface for selecting platforms, actions,
    config files, and optional runtime overrides.
    """

    def __init__(self, root: tk.Tk):
        """
        Initialize the GUI application.
        
        Args:
            root: The root Tk window.
        """
        self.root = root
        self.root.title("AI Video Processing Suite")
        self.root.geometry("900x800")
        self.root.minsize(700, 600)

        self._running = False
        self._job_thread: Optional[threading.Thread] = None
        self._log_queue: queue.Queue = queue.Queue()
        
        # Initialize task entry tracking
        self._task_entries: List[Dict[str, Any]] = []
        self._current_api_name: Optional[str] = None

        self._setup_logging()
        self._create_widgets()
        self._poll_log_queue()

    def _setup_logging(self) -> None:
        """Configure logging to capture messages for the GUI console."""
        self._queue_handler = QueueHandler(self._log_queue)
        self._queue_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S')
        )
        
        root_logger = logging.getLogger()
        root_logger.addHandler(self._queue_handler)
        root_logger.setLevel(logging.INFO)

    def _create_widgets(self) -> None:
        """Create all GUI widgets."""
        style = ttk.Style()
        style.configure('TLabel', padding=5)
        style.configure('TButton', padding=5)
        style.configure('Header.TLabel', font=('Helvetica', 12, 'bold'))

        # Create main scrollable container
        self._main_canvas = tk.Canvas(self.root)
        self._main_scrollbar = ttk.Scrollbar(self.root, orient="vertical", 
                                              command=self._main_canvas.yview)
        self._scrollable_main = ttk.Frame(self._main_canvas, padding="10")
        
        # Configure canvas scrolling
        self._scrollable_main.bind(
            "<Configure>",
            lambda e: self._main_canvas.configure(scrollregion=self._main_canvas.bbox("all"))
        )
        
        self._canvas_window = self._main_canvas.create_window((0, 0), window=self._scrollable_main, anchor="nw")
        self._main_canvas.configure(yscrollcommand=self._main_scrollbar.set)
        
        # Bind canvas resize to adjust inner frame width
        self._main_canvas.bind('<Configure>', self._on_canvas_configure)
        
        # Pack scrollbar and canvas
        self._main_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._main_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Bind mousewheel for scrolling
        self._bind_mousewheel()
        
        # Create sections in the scrollable frame
        main_frame = self._scrollable_main
        
        self._create_header(main_frame)
        self._create_platform_section(main_frame)
        self._create_action_section(main_frame)
        self._create_config_section(main_frame)
        self._create_working_dir_section(main_frame)
        self._create_folder_section(main_frame)
        self._create_options_section(main_frame)
        self._create_advanced_section(main_frame)
        self._create_control_buttons(main_frame)
        self._create_log_console(main_frame)
        self._create_status_bar(main_frame)

    def _on_canvas_configure(self, event) -> None:
        """Resize the inner frame to match the canvas width."""
        self._main_canvas.itemconfig(self._canvas_window, width=event.width)
    
    def _bind_mousewheel(self) -> None:
        """Bind mousewheel events for scrolling on all platforms."""
        # macOS - bind to both MouseWheel and trackpad/mouse scroll events
        self._main_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        # macOS two-finger scroll / external mouse scroll
        self._main_canvas.bind_all("<Button-4>", lambda e: self._main_canvas.yview_scroll(-3, "units"))
        self._main_canvas.bind_all("<Button-5>", lambda e: self._main_canvas.yview_scroll(3, "units"))
        
        # Also bind to the canvas and scrollable frame directly for better macOS support
        self._main_canvas.bind("<Enter>", self._bind_canvas_scroll)
        self._main_canvas.bind("<Leave>", self._unbind_canvas_scroll)
        self._scrollable_main.bind("<Enter>", self._bind_canvas_scroll)
        self._scrollable_main.bind("<Leave>", self._unbind_canvas_scroll)
    
    def _bind_canvas_scroll(self, event=None) -> None:
        """Bind scroll events when mouse enters the canvas area."""
        self._main_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        # macOS-specific scroll binding
        self._main_canvas.bind_all("<Shift-MouseWheel>", self._on_mousewheel)
    
    def _unbind_canvas_scroll(self, event=None) -> None:
        """Unbind scroll events when mouse leaves the canvas area."""
        # Don't unbind - keep scroll active everywhere
        pass

    def _create_header(self, parent: ttk.Frame) -> None:
        """Create the header section."""
        header = ttk.Label(
            parent,
            text="🎬 AI Video Processing Suite",
            style='Header.TLabel'
        )
        header.pack(pady=(0, 10))

        desc = ttk.Label(
            parent,
            text="Process images/videos through AI APIs and generate PowerPoint reports",
            foreground='gray'
        )
        desc.pack(pady=(0, 15))

    def _create_platform_section(self, parent: ttk.Frame) -> None:
        """Create the platform selection section."""
        frame = ttk.LabelFrame(parent, text="Platform", padding="5")
        frame.pack(fill=tk.X, pady=5)

        self._platform_var = tk.StringVar(value='kling')
        
        platform_values = list(PLATFORM_DISPLAY_NAMES.keys())
        platform_display = [PLATFORM_DISPLAY_NAMES[k] for k in platform_values]
        
        self._platform_combo = ttk.Combobox(
            frame,
            textvariable=self._platform_var,
            values=platform_values,
            state='readonly',
            width=50
        )
        self._platform_combo.pack(side=tk.LEFT, padx=5)
        self._platform_combo.bind('<<ComboboxSelected>>', self._on_platform_change)
        
        self._platform_label = ttk.Label(
            frame,
            text=PLATFORM_DISPLAY_NAMES.get('kling', ''),
            foreground='gray'
        )
        self._platform_label.pack(side=tk.LEFT, padx=10)

    def _create_action_section(self, parent: ttk.Frame) -> None:
        """Create the action selection section."""
        frame = ttk.LabelFrame(parent, text="Action", padding="5")
        frame.pack(fill=tk.X, pady=5)

        self._action_var = tk.StringVar(value='auto')

        for action, display in ACTION_DISPLAY_NAMES.items():
            rb = ttk.Radiobutton(
                frame,
                text=display,
                variable=self._action_var,
                value=action
            )
            rb.pack(side=tk.LEFT, padx=15)

    def _create_config_section(self, parent: ttk.Frame) -> None:
        """Create the config file selection section."""
        frame = ttk.LabelFrame(parent, text="Configuration File", padding="5")
        frame.pack(fill=tk.X, pady=5)

        self._config_var = tk.StringVar()
        
        self._config_entry = ttk.Entry(frame, textvariable=self._config_var, width=60)
        self._config_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        browse_btn = ttk.Button(
            frame,
            text="Browse...",
            command=self._browse_config
        )
        browse_btn.pack(side=tk.LEFT, padx=5)

        default_btn = ttk.Button(
            frame,
            text="Use Default",
            command=self._use_default_config
        )
        default_btn.pack(side=tk.LEFT, padx=5)

        self._use_default_config()

    def _create_working_dir_section(self, parent: ttk.Frame) -> None:
        """Create the working directory selection section."""
        frame = ttk.LabelFrame(parent, text="Working Directory (Base for Relative Paths)", padding="5")
        frame.pack(fill=tk.X, pady=5)

        self._working_dir_var = tk.StringVar()
        
        # Determine default working directory
        if _is_frozen():
            # When running as a bundled app, use the user's home directory
            # since the bundle's internal paths won't match config file relative paths
            default_working_dir = str(Path.home())
        else:
            # In development, default to the parent of Scripts folder (the GAI folder)
            default_working_dir = str(script_dir.parent)
        self._working_dir_var.set(default_working_dir)
        
        self._working_dir_entry = ttk.Entry(frame, textvariable=self._working_dir_var, width=60)
        self._working_dir_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        browse_btn = ttk.Button(
            frame,
            text="Browse...",
            command=self._browse_working_dir
        )
        browse_btn.pack(side=tk.LEFT, padx=5)

        # Add a warning label for bundled app
        if _is_frozen():
            ttk.Label(
                frame,
                text="⚠️ Set to your project folder where config paths resolve correctly",
                foreground='orange',
                font=('Helvetica', 9)
            ).pack(side=tk.LEFT, padx=5)
        else:
            ttk.Label(
                frame,
                text="📁 Relative paths in config are resolved from here",
                foreground='gray',
                font=('Helvetica', 9)
        ).pack(side=tk.LEFT, padx=5)

    def _create_folder_section(self, parent: ttk.Frame) -> None:
        """Create the task folder selection section."""
        frame = ttk.LabelFrame(parent, text="Task Folder (Optional)", padding="5")
        frame.pack(fill=tk.X, pady=5)

        self._folder_var = tk.StringVar()
        
        self._folder_entry = ttk.Entry(frame, textvariable=self._folder_var, width=60)
        self._folder_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        browse_btn = ttk.Button(
            frame,
            text="Browse...",
            command=self._browse_folder
        )
        browse_btn.pack(side=tk.LEFT, padx=5)

        ttk.Label(
            frame,
            text="Override task folder from config",
            foreground='gray'
        ).pack(side=tk.LEFT, padx=5)

    def _create_options_section(self, parent: ttk.Frame) -> None:
        """Create the options checkboxes section."""
        frame = ttk.LabelFrame(parent, text="Options", padding="5")
        frame.pack(fill=tk.X, pady=5)

        self._parallel_var = tk.BooleanVar(value=False)
        parallel_cb = ttk.Checkbutton(
            frame,
            text="Run in Parallel (for 'All Platforms')",
            variable=self._parallel_var
        )
        parallel_cb.pack(side=tk.LEFT, padx=15)

        self._verbose_var = tk.BooleanVar(value=False)
        verbose_cb = ttk.Checkbutton(
            frame,
            text="Verbose Logging",
            variable=self._verbose_var
        )
        verbose_cb.pack(side=tk.LEFT, padx=15)

    def _create_advanced_section(self, parent: ttk.Frame) -> None:
        """Create the collapsible advanced section with API-specific fields."""
        self._advanced_visible = tk.BooleanVar(value=False)
        
        toggle_frame = ttk.Frame(parent)
        toggle_frame.pack(fill=tk.X, pady=5)
        
        self._advanced_toggle = ttk.Button(
            toggle_frame,
            text="▶ Advanced Options (Task Overrides)",
            command=self._toggle_advanced
        )
        self._advanced_toggle.pack(side=tk.LEFT)

        # Container for the advanced section
        self._advanced_frame = ttk.LabelFrame(
            parent,
            text="Task Configuration (Runtime Overrides - Not Saved to File)",
            padding="10"
        )
        
        # Button frame for add/remove tasks - at the top
        btn_frame = ttk.Frame(self._advanced_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        self._add_task_btn = ttk.Button(
            btn_frame,
            text="➕ Add Task",
            command=self._add_task_entry
        )
        self._add_task_btn.pack(side=tk.LEFT, padx=5)
        
        self._clear_tasks_btn = ttk.Button(
            btn_frame,
            text="🗑 Clear All Tasks",
            command=self._clear_all_tasks
        )
        self._clear_tasks_btn.pack(side=tk.LEFT, padx=5)
        
        # Separator
        ttk.Separator(btn_frame, orient='vertical').pack(side=tk.LEFT, padx=10, fill='y')
        
        # Reload from config button
        self._reload_config_btn = ttk.Button(
            btn_frame,
            text="🔄 Reload Config",
            command=self._load_config_into_fields
        )
        self._reload_config_btn.pack(side=tk.LEFT, padx=5)
        
        # Save to config button
        self._save_config_btn = ttk.Button(
            btn_frame,
            text="💾 Save to Config",
            command=self._save_config_to_file
        )
        self._save_config_btn.pack(side=tk.LEFT, padx=5)
        
        # Help text
        ttk.Label(
            btn_frame,
            text="💡 Changes are temporary unless saved",
            foreground='gray',
            font=('Helvetica', 9)
        ).pack(side=tk.RIGHT, padx=5)
        
        # Simple container for task entries (no nested canvas)
        self._task_list_frame = ttk.Frame(self._advanced_frame)
        self._task_list_frame.pack(fill=tk.X, expand=False)
        
        # Store task widgets
        self._task_entries: List[Dict[str, Any]] = []
        self._current_api_name = None
        
    def _on_mousewheel(self, event) -> None:
        """Handle mousewheel scrolling for the main canvas."""
        # macOS returns delta in different units than Windows/Linux
        import platform
        if platform.system() == 'Darwin':
            # macOS: delta is typically 1 or -1 for each scroll tick
            # External mice may report larger values
            delta = event.delta
            if abs(delta) < 10:
                # Trackpad or mice reporting small deltas
                scroll_amount = -1 * delta
            else:
                # External mice reporting larger deltas (like 120)
                scroll_amount = int(-1 * (delta / 120))
            # Ensure minimum scroll of 1 unit
            if scroll_amount == 0:
                scroll_amount = -1 if delta > 0 else 1
            self._main_canvas.yview_scroll(scroll_amount, "units")
        else:
            # Windows/Linux
            self._main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _add_task_entry(self) -> None:
        """Add a new task entry based on the current platform."""
        platform = self._platform_var.get()
        api_name = API_MAPPING.get(platform, platform)
        
        schema = API_FIELD_SCHEMAS.get(api_name)
        if not schema:
            # Fall back to generic text override
            self._add_generic_task_entry()
            return
        
        task_index = len(self._task_entries)
        task_frame = ttk.LabelFrame(
            self._task_list_frame,
            text=f"Task {task_index + 1}",
            padding="10"
        )
        task_frame.pack(fill=tk.X, pady=5)
        
        # Remove button for this task
        header_frame = ttk.Frame(task_frame)
        header_frame.pack(fill=tk.X)
        
        ttk.Label(header_frame, text=schema['name'], foreground='blue').pack(side=tk.LEFT)
        
        remove_btn = ttk.Button(
            header_frame,
            text="✕ Remove",
            command=lambda f=task_frame, i=task_index: self._remove_task_entry(f, i),
            width=10
        )
        remove_btn.pack(side=tk.RIGHT)
        
        # Create field widgets
        field_widgets = {}
        
        for field in schema['fields']:
            field_frame = ttk.Frame(task_frame)
            field_frame.pack(fill=tk.X, pady=2)
            
            # Label with required indicator
            label_text = field['label']
            if field.get('required'):
                label_text += " *"
            
            label = ttk.Label(field_frame, text=label_text, width=20, anchor='e')
            label.pack(side=tk.LEFT, padx=(0, 5))
            
            # Create appropriate widget based on type
            widget = self._create_field_widget(field_frame, field)
            field_widgets[field['key']] = {'widget': widget, 'field': field}
            
            # Help text
            if field.get('help'):
                help_label = ttk.Label(field_frame, text=f"({field['help']})", 
                                       foreground='gray', font=('Helvetica', 8))
                help_label.pack(side=tk.LEFT, padx=5)
        
        self._task_entries.append({
            'frame': task_frame,
            'widgets': field_widgets,
            'api_name': api_name
        })
        
        # Scroll to show new task
        self.root.update_idletasks()
        self._main_canvas.configure(scrollregion=self._main_canvas.bbox("all"))
        self._main_canvas.yview_moveto(1.0)  # Scroll to bottom

    def _create_field_widget(self, parent: ttk.Frame, field: Dict) -> Any:
        """
        Create the appropriate widget for a field.
        
        Args:
            parent: Parent frame for the widget.
            field: Field definition dictionary.
            
        Returns:
            The created widget.
        """
        field_type = field.get('type', 'text')
        default = field.get('default', '')
        
        if field_type == 'text':
            var = tk.StringVar(value=str(default) if default else '')
            widget = ttk.Entry(parent, textvariable=var, width=50)
            widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
            widget.var = var
            return widget
            
        elif field_type == 'multiline':
            height = field.get('height', 3)
            widget = tk.Text(parent, height=height, width=50, font=('Courier', 9))
            widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
            if default:
                widget.insert('1.0', str(default))
            return widget
            
        elif field_type == 'dropdown':
            options = field.get('options', [])
            var = tk.StringVar(value=str(default) if default else '')
            widget = ttk.Combobox(parent, textvariable=var, values=options, width=30)
            widget.pack(side=tk.LEFT)
            widget.var = var
            return widget
            
        elif field_type == 'checkbox':
            var = tk.BooleanVar(value=bool(default))
            widget = ttk.Checkbutton(parent, variable=var)
            widget.pack(side=tk.LEFT)
            widget.var = var
            return widget
            
        elif field_type == 'number':
            var = tk.StringVar(value=str(default) if default is not None else '')
            widget = ttk.Entry(parent, textvariable=var, width=15)
            widget.pack(side=tk.LEFT)
            widget.var = var
            return widget
            
        elif field_type == 'folder':
            frame = ttk.Frame(parent)
            frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            var = tk.StringVar(value=str(default) if default else '')
            entry = ttk.Entry(frame, textvariable=var, width=40)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            browse_btn = ttk.Button(
                frame,
                text="...",
                width=3,
                command=lambda v=var: self._browse_field_folder(v)
            )
            browse_btn.pack(side=tk.LEFT, padx=2)
            
            entry.var = var
            return entry
        
        # Default to text
        var = tk.StringVar(value=str(default) if default else '')
        widget = ttk.Entry(parent, textvariable=var, width=50)
        widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
        widget.var = var
        return widget

    def _browse_field_folder(self, var: tk.StringVar) -> None:
        """Browse for a folder and set the variable."""
        folderpath = filedialog.askdirectory(title="Select Folder")
        if folderpath:
            var.set(folderpath)

    def _add_generic_task_entry(self) -> None:
        """Add a generic text-based task override entry."""
        task_index = len(self._task_entries)
        task_frame = ttk.LabelFrame(
            self._task_list_frame,
            text=f"Task {task_index + 1} (Generic Override)",
            padding="10"
        )
        task_frame.pack(fill=tk.X, pady=5)
        
        header_frame = ttk.Frame(task_frame)
        header_frame.pack(fill=tk.X)
        
        remove_btn = ttk.Button(
            header_frame,
            text="✕ Remove",
            command=lambda f=task_frame, i=task_index: self._remove_task_entry(f, i),
            width=10
        )
        remove_btn.pack(side=tk.RIGHT)
        
        ttk.Label(
            task_frame,
            text="Enter key=value pairs (one per line):",
            foreground='gray'
        ).pack(anchor=tk.W)
        
        text_widget = tk.Text(task_frame, height=4, width=60, font=('Courier', 9))
        text_widget.pack(fill=tk.X, pady=5)
        
        self._task_entries.append({
            'frame': task_frame,
            'widgets': {'_generic': {'widget': text_widget, 'field': {'type': 'generic'}}},
            'api_name': 'generic'
        })
        
        # Scroll to show new task
        self.root.update_idletasks()
        self._main_canvas.configure(scrollregion=self._main_canvas.bbox("all"))
        self._main_canvas.yview_moveto(1.0)

    def _remove_task_entry(self, frame: ttk.Frame, index: int) -> None:
        """Remove a task entry."""
        frame.destroy()
        
        # Find and remove from list
        self._task_entries = [t for t in self._task_entries if t['frame'].winfo_exists()]
        
        # Renumber remaining tasks
        for i, task in enumerate(self._task_entries):
            if task['frame'].winfo_exists():
                task['frame'].configure(text=f"Task {i + 1}")

    def _clear_all_tasks(self) -> None:
        """Clear all task entries."""
        for task in self._task_entries:
            if task['frame'].winfo_exists():
                task['frame'].destroy()
        self._task_entries = []

    def _rebuild_task_fields_for_platform(self) -> None:
        """Rebuild task fields when platform changes."""
        platform = self._platform_var.get()
        api_name = API_MAPPING.get(platform, platform)
        
        if api_name != self._current_api_name:
            # Platform changed, clear existing tasks
            self._clear_all_tasks()
            self._current_api_name = api_name

    def _create_control_buttons(self, parent: ttk.Frame) -> None:
        """Create the main control buttons."""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=10)

        self._run_btn = ttk.Button(
            frame,
            text="▶ Run",
            command=self._run_job,
            width=15
        )
        self._run_btn.pack(side=tk.LEFT, padx=5)

        self._stop_btn = ttk.Button(
            frame,
            text="⏹ Stop",
            command=self._stop_job,
            state=tk.DISABLED,
            width=15
        )
        self._stop_btn.pack(side=tk.LEFT, padx=5)

        self._clear_btn = ttk.Button(
            frame,
            text="🗑 Clear Log",
            command=self._clear_log,
            width=15
        )
        self._clear_btn.pack(side=tk.LEFT, padx=5)

        open_report_btn = ttk.Button(
            frame,
            text="📂 Open Report Folder",
            command=self._open_report_folder,
            width=20
        )
        open_report_btn.pack(side=tk.RIGHT, padx=5)

    def _create_log_console(self, parent: ttk.Frame) -> None:
        """Create the log console area."""
        frame = ttk.LabelFrame(parent, text="Log Output", padding="5")
        frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self._log_text = scrolledtext.ScrolledText(
            frame,
            height=12,
            font=('Courier', 10),
            state=tk.DISABLED,
            bg='#1e1e1e',
            fg='#d4d4d4',
            insertbackground='white'
        )
        self._log_text.pack(fill=tk.BOTH, expand=True)

        self._log_text.tag_configure('info', foreground='#d4d4d4')
        self._log_text.tag_configure('warning', foreground='#dcdcaa')
        self._log_text.tag_configure('error', foreground='#f14c4c')
        self._log_text.tag_configure('success', foreground='#4ec9b0')

    def _create_status_bar(self, parent: ttk.Frame) -> None:
        """Create the status bar at the bottom."""
        self._status_var = tk.StringVar(value="Ready")
        
        status_bar = ttk.Label(
            parent,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _toggle_advanced(self) -> None:
        """Toggle visibility of the advanced options section."""
        if self._advanced_visible.get():
            self._advanced_frame.pack_forget()
            self._advanced_toggle.config(text="▶ Advanced Options (Task Overrides)")
            self._advanced_visible.set(False)
        else:
            self._rebuild_task_fields_for_platform()
            self._advanced_frame.pack(fill=tk.BOTH, expand=True, pady=5, 
                                      after=self._advanced_toggle.master)
            self._advanced_toggle.config(text="▼ Advanced Options (Task Overrides)")
            self._advanced_visible.set(True)
            # Load current config values into fields
            self._load_config_into_fields()

    def _on_platform_change(self, event=None) -> None:
        """Handle platform selection change."""
        platform = self._platform_var.get()
        display = PLATFORM_DISPLAY_NAMES.get(platform, '')
        self._platform_label.config(text=display)
        self._use_default_config()
        
        # Rebuild task fields and load config if advanced section is visible
        if self._advanced_visible.get():
            self._rebuild_task_fields_for_platform()
            self._load_config_into_fields()

    def _browse_config(self) -> None:
        """Open file dialog to select a config file."""
        initial_dir = script_dir / "config"
        if not initial_dir.exists():
            initial_dir = script_dir
        
        filepath = filedialog.askopenfilename(
            title="Select Configuration File",
            initialdir=initial_dir,
            filetypes=[
                ("YAML files", "*.yaml *.yml"),
                ("JSON files", "*.json"),
                ("All files", "*.*")
            ]
        )
        if filepath:
            self._config_var.set(filepath)
            # Load config values into fields if advanced section is visible
            if self._advanced_visible.get():
                self._load_config_into_fields()

    def _browse_folder(self) -> None:
        """Open folder dialog to select a task folder."""
        folderpath = filedialog.askdirectory(
            title="Select Task Folder"
        )
        if folderpath:
            self._folder_var.set(folderpath)

    def _browse_working_dir(self) -> None:
        """Open folder dialog to select a working directory."""
        current_val = self._working_dir_var.get()
        if current_val and Path(current_val).exists():
            initial_dir = current_val
        elif _is_frozen():
            initial_dir = str(Path.home())
        else:
            initial_dir = str(script_dir.parent)
        folderpath = filedialog.askdirectory(
            title="Select Working Directory (Base for Relative Paths)",
            initialdir=initial_dir
        )
        if folderpath:
            self._working_dir_var.set(folderpath)

    def _use_default_config(self) -> None:
        """Set the config path to the default for the selected platform."""
        platform = self._platform_var.get()
        api_name = API_MAPPING.get(platform, platform)
        
        default_path = get_default_config_path(api_name)
        if default_path:
            self._config_var.set(default_path)
        else:
            rel_path = CONFIG_MAPPING.get(api_name, '')
            if rel_path:
                full_path = script_dir / rel_path
                self._config_var.set(str(full_path))
            else:
                self._config_var.set('')
        
        # Load config values into fields if advanced section is visible
        if hasattr(self, '_advanced_visible') and self._advanced_visible.get():
            self._load_config_into_fields()

    def _get_runtime_overrides(self) -> Optional[Dict[str, Any]]:
        """
        Parse runtime overrides from the advanced task entries.
        
        Returns:
            Dictionary of overrides, or None if empty.
        """
        overrides = {}
        
        # Collect task overrides from GUI entries
        tasks_override = []
        
        for task_entry in self._task_entries:
            if not task_entry['frame'].winfo_exists():
                continue
                
            task_data = {}
            widgets = task_entry['widgets']
            
            # Handle generic text entry
            if '_generic' in widgets:
                widget = widgets['_generic']['widget']
                text = widget.get('1.0', tk.END).strip()
                if text:
                    try:
                        parsed = ConfigLoader.parse_override_text(text)
                        task_data.update(parsed)
                    except Exception:
                        pass
            else:
                # Collect values from structured fields
                for key, info in widgets.items():
                    widget = info['widget']
                    field = info['field']
                    field_type = field.get('type', 'text')
                    
                    value = self._get_widget_value(widget, field_type)
                    
                    # Include all non-empty values (don't skip defaults - they're needed)
                    # For checkboxes, always include the value
                    # For numbers, include if not None
                    # For text/dropdown/folder, include if not empty string
                    if field_type == 'checkbox':
                        task_data[key] = value
                    elif field_type == 'number':
                        if value is not None:
                            task_data[key] = value
                    elif value is not None and value != '':
                        task_data[key] = value
                    elif field.get('required') and (value is None or value == ''):
                        # Required field is empty - mark task as incomplete
                        pass
            
            if task_data:
                tasks_override.append(task_data)
        
        if tasks_override:
            overrides['tasks'] = tasks_override
        
        # Add folder override from the folder section
        folder = self._folder_var.get().strip()
        if folder:
            if 'tasks' not in overrides:
                overrides['tasks'] = [{}]
            if overrides['tasks']:
                overrides['tasks'][0]['folder'] = folder
        
        return overrides if overrides else None

    def _get_widget_value(self, widget: Any, field_type: str) -> Any:
        """
        Get the value from a widget based on its type.
        
        Args:
            widget: The widget to get value from.
            field_type: The type of the field.
            
        Returns:
            The widget's value, appropriately typed.
        """
        try:
            if field_type == 'multiline':
                value = widget.get('1.0', tk.END).strip()
                return value if value else None
            elif field_type == 'checkbox':
                return widget.var.get()
            elif field_type == 'number':
                value = widget.var.get().strip()
                if value:
                    try:
                        if '.' in value:
                            return float(value)
                        return int(value)
                    except ValueError:
                        return value
                return None
            else:
                # text, dropdown, folder
                value = widget.var.get().strip()
                return value if value else None
        except Exception:
            return None

    def _set_widget_value(self, widget: Any, field_type: str, value: Any) -> None:
        """
        Set the value of a widget based on its type.
        
        Args:
            widget: The widget to set value on.
            field_type: The type of the field.
            value: The value to set.
        """
        if value is None:
            return
            
        try:
            if field_type == 'multiline':
                widget.delete('1.0', tk.END)
                widget.insert('1.0', str(value))
            elif field_type == 'checkbox':
                widget.var.set(bool(value))
            elif field_type == 'number':
                widget.var.set(str(value))
            else:
                # text, dropdown, folder
                widget.var.set(str(value))
        except Exception as e:
            logger.debug(f"Failed to set widget value: {e}")

    def _load_config_into_fields(self) -> None:
        """
        Load the current config file into the advanced options fields.
        
        This populates the task entries with values from the config file,
        making it easy to see and modify current settings.
        """
        config_path = self._config_var.get().strip()
        if not config_path or not Path(config_path).exists():
            return
        
        platform = self._platform_var.get()
        api_name = API_MAPPING.get(platform, platform)
        schema = API_FIELD_SCHEMAS.get(api_name)
        if not schema:
            return
        
        try:
            # Load the config file directly (no overrides, no path resolution)
            with open(config_path, 'r', encoding='utf-8') as f:
                if config_path.endswith('.json'):
                    config = json.load(f)
                else:
                    config = yaml.safe_load(f) or {}
            
            # Get tasks from config
            tasks = config.get('tasks', [])
            if not tasks:
                # For some APIs, the config might have a single task structure
                # Try to create one task from top-level fields
                tasks = [config]
            
            # Clear existing task entries
            self._clear_all_tasks()
            
            # Create task entries for each task in config
            for task_data in tasks:
                self._add_task_entry()
                
                # Get the just-added task entry
                if not self._task_entries:
                    continue
                task_entry = self._task_entries[-1]
                widgets = task_entry['widgets']
                
                # Populate widgets with config values
                for key, widget_info in widgets.items():
                    if key == '_generic':
                        continue
                    
                    widget = widget_info['widget']
                    field = widget_info['field']
                    field_type = field.get('type', 'text')
                    
                    # Get value from task data or top-level config
                    value = task_data.get(key)
                    if value is None:
                        value = config.get(key)
                    
                    if value is not None:
                        self._set_widget_value(widget, field_type, value)
            
            # If no tasks were in config, add one empty entry for user to fill
            if not self._task_entries:
                self._add_task_entry()
                # Still populate with top-level config values
                task_entry = self._task_entries[-1]
                widgets = task_entry['widgets']
                for key, widget_info in widgets.items():
                    if key == '_generic':
                        continue
                    widget = widget_info['widget']
                    field = widget_info['field']
                    field_type = field.get('type', 'text')
                    value = config.get(key)
                    if value is not None:
                        self._set_widget_value(widget, field_type, value)
            
            self._log_message(f"Loaded config values from: {Path(config_path).name}", 'info')
            
        except Exception as e:
            logger.debug(f"Failed to load config into fields: {e}")
            # Don't show error to user, just log it - config might be for different API

    def _save_config_to_file(self) -> None:
        """
        Save the current advanced options values to the config file.
        
        This writes the task entries back to the YAML config file,
        allowing users to persist their changes.
        """
        config_path = self._config_var.get().strip()
        if not config_path:
            messagebox.showwarning("No Config File", "Please select a configuration file first.")
            return
        
        config_path_obj = Path(config_path)
        if not config_path_obj.exists():
            messagebox.showwarning("File Not Found", f"Config file not found:\n{config_path}")
            return
        
        # Check if there are any task entries
        if not self._task_entries:
            messagebox.showwarning("No Tasks", "No task entries to save. Add at least one task first.")
            return
        
        try:
            # Load the existing config to preserve structure and comments
            with open(config_path, 'r', encoding='utf-8') as f:
                if config_path.endswith('.json'):
                    config = json.load(f)
                else:
                    config = yaml.safe_load(f) or {}
            
            # Build tasks list from GUI entries
            new_tasks = []
            
            for task_entry in self._task_entries:
                if not task_entry['frame'].winfo_exists():
                    continue
                
                task_data = {}
                widgets = task_entry['widgets']
                
                if '_generic' in widgets:
                    # Generic text entry - parse it
                    widget = widgets['_generic']['widget']
                    text = widget.get('1.0', tk.END).strip()
                    if text:
                        try:
                            task_data = ConfigLoader.parse_override_text(text)
                        except Exception:
                            pass
                else:
                    # Collect values from structured fields
                    for key, info in widgets.items():
                        widget = info['widget']
                        field = info['field']
                        field_type = field.get('type', 'text')
                        
                        value = self._get_widget_value(widget, field_type)
                        
                        # Include all values, even empty strings
                        if value is not None:
                            task_data[key] = value
                        elif field_type in ('text', 'multiline', 'dropdown'):
                            # For text fields, include empty string if empty
                            task_data[key] = ''
                
                if task_data:
                    new_tasks.append(task_data)
            
            if not new_tasks:
                messagebox.showwarning("No Data", "No task data to save.")
                return
            
            # Update config with new tasks
            config['tasks'] = new_tasks
            
            # Also update top-level fields that might be shared across tasks
            # (take from first task if present)
            first_task = new_tasks[0]
            platform = self._platform_var.get()
            api_name = API_MAPPING.get(platform, platform)
            schema = API_FIELD_SCHEMAS.get(api_name, {})
            
            # Some fields are typically top-level in config
            top_level_keys = ['model', 'model_version', 'mode', 'resolution', 
                             'aspect_ratio', 'duration', 'cfg', 'testbed']
            for key in top_level_keys:
                if key in first_task and key in config:
                    config[key] = first_task[key]
            
            # Write back to file
            with open(config_path, 'w', encoding='utf-8') as f:
                if config_path.endswith('.json'):
                    json.dump(config, f, indent=2)
                else:
                    # Use ruamel.yaml for proper formatting preservation
                    ruamel_yaml = YAML()
                    ruamel_yaml.default_flow_style = False
                    ruamel_yaml.preserve_quotes = True
                    ruamel_yaml.indent(mapping=2, sequence=4, offset=2)
                    ruamel_yaml.width = 1000  # Prevent line wrapping
                    
                    # Convert config to ruamel format with proper string styles
                    formatted_config = self._format_config_for_yaml(config)
                    ruamel_yaml.dump(formatted_config, f)
            
            self._log_message(f"✅ Saved config to: {config_path_obj.name}", 'info')
            messagebox.showinfo("Config Saved", f"Configuration saved to:\n{config_path_obj.name}")
            
        except Exception as e:
            error_msg = f"Failed to save config: {e}"
            self._log_message(error_msg, 'error')
            messagebox.showerror("Save Failed", error_msg)

    def _format_config_for_yaml(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format config dictionary for ruamel.yaml output with proper string styles.
        
        Uses LiteralScalarString for multiline prompts and DoubleQuotedScalarString
        for values that should be quoted (like aspect ratios, resolutions).
        
        Args:
            config: The configuration dictionary to format.
            
        Returns:
            Formatted configuration with proper ruamel.yaml string types.
        """
        from ruamel.yaml.comments import CommentedMap, CommentedSeq
        
        # Keys that should use double quotes
        quoted_keys = {'resolution', 'aspect_ratio', 'start_time', 'comment'}
        
        def format_value(key: str, value: Any) -> Any:
            """Format a single value with appropriate string style."""
            if isinstance(value, str):
                if '\n' in value:
                    # Use literal block style for multiline strings
                    return LiteralScalarString(value)
                elif key in quoted_keys:
                    # Use double quotes for specific keys
                    return DoubleQuotedScalarString(value)
                return value
            elif isinstance(value, dict):
                return format_dict(value)
            elif isinstance(value, list):
                return format_list(value, is_tasks=(key == 'tasks'))
            return value
        
        def format_dict(d: Dict[str, Any]) -> CommentedMap:
            """Format a dictionary with proper string styles."""
            result = CommentedMap()
            for k, v in d.items():
                result[k] = format_value(k, v)
            
            # Add blank line before 'comments' section
            if 'comments' in result:
                result.yaml_set_comment_before_after_key('comments', before='\n')
            return result
        
        def format_list(lst: List[Any], is_tasks: bool = False) -> CommentedSeq:
            """Format a list with proper string styles."""
            result = CommentedSeq()
            for idx, item in enumerate(lst):
                if isinstance(item, dict):
                    result.append(format_dict(item))
                else:
                    result.append(item)
            
            # Add blank lines between tasks (after all items are appended)
            if is_tasks and len(result) > 1:
                for idx in range(1, len(result)):
                    result.yaml_set_comment_before_after_key(idx, before='\n')
            return result
        
        return format_dict(config)

    def _run_job(self) -> None:
        """Start the automation job in a background thread."""
        if self._running:
            messagebox.showwarning("Already Running", "A job is already running.")
            return

        platform = self._platform_var.get()
        action = self._action_var.get()
        config_path = self._config_var.get().strip() or None
        working_dir = self._working_dir_var.get().strip() or None
        parallel = self._parallel_var.get()
        verbose = self._verbose_var.get()
        overrides = self._get_runtime_overrides()

        self._log_message(f"Starting: {PLATFORM_DISPLAY_NAMES.get(platform, platform)}", 'info')
        self._log_message(f"Action: {ACTION_DISPLAY_NAMES.get(action, action)}", 'info')
        if config_path:
            self._log_message(f"Config: {config_path}", 'info')
        if working_dir:
            self._log_message(f"Working Directory: {working_dir}", 'info')
        if overrides:
            self._log_message(f"Overrides: {overrides}", 'info')

        self._running = True
        self._run_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.NORMAL)
        self._status_var.set("Running...")

        def job_wrapper():
            try:
                exit_code = run_automation(
                    platform=platform,
                    action=action,
                    config_path=config_path,
                    parallel=parallel,
                    verbose=verbose,
                    runtime_overrides=overrides,
                    working_dir=working_dir,
                    progress_callback=self._progress_callback
                )
                
                self.root.after(0, lambda: self._on_job_complete(exit_code))
            except Exception as e:
                self.root.after(0, lambda: self._on_job_error(str(e)))

        self._job_thread = threading.Thread(target=job_wrapper, daemon=True)
        self._job_thread.start()

    def _stop_job(self) -> None:
        """Request to stop the running job."""
        messagebox.showinfo(
            "Stop Requested",
            "Stop has been requested. The current operation will complete, "
            "but no new operations will start.\n\n"
            "Note: Some API calls cannot be interrupted mid-request."
        )
        self._status_var.set("Stopping...")

    def _on_job_complete(self, exit_code: int) -> None:
        """Handle job completion in the main thread."""
        self._running = False
        self._run_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)

        if exit_code == 0:
            self._status_var.set("✅ Completed successfully")
            self._log_message("Job completed successfully!", 'success')
        else:
            self._status_var.set("❌ Completed with errors")
            self._log_message("Job completed with errors. Check log for details.", 'error')

    def _on_job_error(self, error: str) -> None:
        """Handle job error in the main thread."""
        self._running = False
        self._run_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)
        self._status_var.set("❌ Error")
        self._log_message(f"Error: {error}", 'error')
        messagebox.showerror("Error", f"An error occurred:\n\n{error}")

    def _progress_callback(self, message: str, level: str) -> None:
        """
        Callback for progress updates from the automation.
        
        Args:
            message: Progress message to display.
            level: Message level ('info', 'warning', 'error').
        """
        self.root.after(0, lambda: self._log_message(message, level))

    def _log_message(self, message: str, level: str = 'info') -> None:
        """
        Add a message to the log console.
        
        Args:
            message: Message to add.
            level: Message level for color coding.
        """
        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"{message}\n", level)
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _clear_log(self) -> None:
        """Clear the log console."""
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete('1.0', tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _poll_log_queue(self) -> None:
        """Poll the log queue and display messages."""
        while True:
            try:
                record = self._log_queue.get_nowait()
                
                level = 'info'
                if record.levelno >= logging.ERROR:
                    level = 'error'
                elif record.levelno >= logging.WARNING:
                    level = 'warning'
                elif '✅' in record.getMessage() or 'success' in record.getMessage().lower():
                    level = 'success'
                
                self._log_message(
                    f"{record.getMessage()}",
                    level
                )
            except queue.Empty:
                break

        self.root.after(100, self._poll_log_queue)

    def _open_report_folder(self) -> None:
        """Open the Report folder in the file explorer."""
        report_dir = script_dir.parent / "Report"
        if not report_dir.exists():
            report_dir = script_dir.parent
        
        if sys.platform == 'darwin':
            os.system(f'open "{report_dir}"')
        elif sys.platform == 'win32':
            os.startfile(str(report_dir))
        else:
            os.system(f'xdg-open "{report_dir}"')


def main():
    """Main entry point for the GUI application."""
    root = tk.Tk()
    
    if sys.platform == 'darwin':
        try:
            root.tk.call('tk::unsupported::MacWindowStyle', 'style', root._w, 'document')
        except tk.TclError:
            pass
    
    app = AutomationGUI(root)
    
    root.protocol("WM_DELETE_WINDOW", lambda: _on_close(root, app))
    
    root.mainloop()


def _on_close(root: tk.Tk, app: AutomationGUI) -> None:
    """Handle window close event."""
    if app._running:
        if not messagebox.askyesno(
            "Job Running",
            "A job is currently running. Are you sure you want to exit?\n\n"
            "The job will be terminated."
        ):
            return
    root.destroy()


if __name__ == "__main__":
    main()
