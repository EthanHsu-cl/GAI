"""
GUI Launcher for GAI Scripts.

Provides a graphical interface for running video processing and report generation
tasks across multiple platforms (Kling, Vidu, Runway, etc.).

This module wraps the command-line runall.py functionality in a user-friendly
tkinter-based GUI suitable for users unfamiliar with terminal commands.
"""

import os
import sys
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
from pathlib import Path

# Ensure core module is importable
SCRIPT_DIR = Path(__file__).parent
CORE_DIR = SCRIPT_DIR / "core"
sys.path.insert(0, str(CORE_DIR))


class TextRedirector:
    """Redirect stdout/stderr to a tkinter Text widget via a queue."""

    def __init__(self, text_widget: scrolledtext.ScrolledText, output_queue: queue.Queue):
        """
        Initialize the text redirector.

        Args:
            text_widget: The ScrolledText widget to redirect output to.
            output_queue: Thread-safe queue for passing messages to the GUI thread.
        """
        self.text_widget = text_widget
        self.output_queue = output_queue

    def write(self, message: str) -> None:
        """
        Write a message to the output queue.

        Args:
            message: The message to write.
        """
        self.output_queue.put(message)

    def flush(self) -> None:
        """Flush method required for file-like interface."""
        pass


class GAILauncherApp:
    """Main GUI application for GAI Scripts launcher."""

    # Platform display names and their corresponding API names
    PLATFORMS = {
        "Kling (Image-to-Video)": "kling",
        "Kling Effects": "klingfx",
        "Kling Endframe": "kling_endframe",
        "Kling Text-to-Video": "kling_ttv",
        "Vidu Effects": "vidu",
        "Vidu Reference": "viduref",
        "Nano Banana (Google Flash)": "nano",
        "Runway": "runway",
        "GenVideo": "genvideo",
        "Pixverse": "pixverse",
        "Wan 2.2": "wan",
        "Veo (Text-to-Video)": "veo",
        "Veo (Image-to-Video)": "veoitv",
        "All Platforms": "all",
    }

    ACTIONS = {
        "Auto (Process + Report)": "auto",
        "Process Only": "process",
        "Report Only": "report",
    }

    # Default config files for each platform
    CONFIG_MAPPING = {
        "kling": "config/batch_kling_config.yaml",
        "klingfx": "config/batch_kling_effects_config.yaml",
        "kling_effects": "config/batch_kling_effects_config.yaml",
        "kling_endframe": "config/batch_kling_endframe_config.yaml",
        "kling_ttv": "config/batch_kling_ttv_config.yaml",
        "vidu": "config/batch_vidu_effects_config.yaml",
        "viduref": "config/batch_vidu_reference_config.yaml",
        "nano": "config/batch_nano_banana_config.yaml",
        "runway": "config/batch_runway_config.yaml",
        "genvideo": "config/batch_genvideo_config.yaml",
        "pixverse": "config/batch_pixverse_config.yaml",
        "wan": "config/batch_wan_config.yaml",
        "veo": "config/batch_veo_config.yaml",
        "veoitv": "config/batch_veo_itv_config.yaml",
    }

    def __init__(self, root: tk.Tk):
        """
        Initialize the GAI Launcher application.

        Args:
            root: The root Tkinter window.
        """
        self.root = root
        self.root.title("GAI Scripts Launcher")
        self.root.geometry("700x600")
        self.root.minsize(600, 500)

        # Queue for thread-safe output
        self.output_queue = queue.Queue()

        # Track if a process is running
        self.is_running = False

        self._setup_styles()
        self._create_widgets()
        self._check_output_queue()

    def _setup_styles(self) -> None:
        """Configure ttk styles for the application."""
        style = ttk.Style()
        style.configure("Header.TLabel", font=("Helvetica", 14, "bold"))
        style.configure("Run.TButton", font=("Helvetica", 11, "bold"))

    def _create_widgets(self) -> None:
        """Create and layout all GUI widgets."""
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        header_label = ttk.Label(
            main_frame,
            text="GAI Video Processing Launcher",
            style="Header.TLabel"
        )
        header_label.pack(pady=(0, 15))

        # Settings frame
        settings_frame = ttk.LabelFrame(main_frame, text="Settings", padding="10")
        settings_frame.pack(fill=tk.X, pady=(0, 10))

        # Platform selection
        platform_frame = ttk.Frame(settings_frame)
        platform_frame.pack(fill=tk.X, pady=5)

        ttk.Label(platform_frame, text="Platform:", width=12).pack(side=tk.LEFT)
        self.platform_var = tk.StringVar(value=list(self.PLATFORMS.keys())[0])
        platform_combo = ttk.Combobox(
            platform_frame,
            textvariable=self.platform_var,
            values=list(self.PLATFORMS.keys()),
            state="readonly",
            width=35
        )
        platform_combo.pack(side=tk.LEFT, padx=(5, 0))
        platform_combo.bind("<<ComboboxSelected>>", self._on_platform_changed)

        # Action selection
        action_frame = ttk.Frame(settings_frame)
        action_frame.pack(fill=tk.X, pady=5)

        ttk.Label(action_frame, text="Action:", width=12).pack(side=tk.LEFT)
        self.action_var = tk.StringVar(value=list(self.ACTIONS.keys())[0])
        action_combo = ttk.Combobox(
            action_frame,
            textvariable=self.action_var,
            values=list(self.ACTIONS.keys()),
            state="readonly",
            width=35
        )
        action_combo.pack(side=tk.LEFT, padx=(5, 0))

        # Config file selection
        config_frame = ttk.Frame(settings_frame)
        config_frame.pack(fill=tk.X, pady=5)

        ttk.Label(config_frame, text="Config File:", width=12).pack(side=tk.LEFT)
        self.config_var = tk.StringVar(value="")
        self.config_entry = ttk.Entry(config_frame, textvariable=self.config_var, width=40)
        self.config_entry.pack(side=tk.LEFT, padx=(5, 5))

        # Set initial default config
        self._update_default_config()

        browse_btn = ttk.Button(config_frame, text="Browse...", command=self._browse_config)
        browse_btn.pack(side=tk.LEFT)

        reset_btn = ttk.Button(config_frame, text="Reset", command=self._clear_config)
        reset_btn.pack(side=tk.LEFT, padx=(5, 0))

        # Options frame
        options_frame = ttk.Frame(settings_frame)
        options_frame.pack(fill=tk.X, pady=5)

        ttk.Label(options_frame, text="Options:", width=12).pack(side=tk.LEFT)

        self.verbose_var = tk.BooleanVar(value=False)
        verbose_check = ttk.Checkbutton(
            options_frame,
            text="Verbose Logging",
            variable=self.verbose_var
        )
        verbose_check.pack(side=tk.LEFT, padx=(5, 10))

        self.parallel_var = tk.BooleanVar(value=False)
        parallel_check = ttk.Checkbutton(
            options_frame,
            text="Parallel (for All Platforms)",
            variable=self.parallel_var
        )
        parallel_check.pack(side=tk.LEFT)

        # Buttons frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)

        self.run_button = ttk.Button(
            button_frame,
            text="▶ Run",
            style="Run.TButton",
            command=self._run_process
        )
        self.run_button.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_button = ttk.Button(
            button_frame,
            text="⏹ Stop",
            command=self._stop_process,
            state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT, padx=(0, 10))

        clear_log_btn = ttk.Button(
            button_frame,
            text="Clear Log",
            command=self._clear_log
        )
        clear_log_btn.pack(side=tk.LEFT)

        # Status label
        self.status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(button_frame, textvariable=self.status_var)
        status_label.pack(side=tk.RIGHT)

        # Output log frame
        log_frame = ttk.LabelFrame(main_frame, text="Output Log", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            font=("Consolas", 10),
            state=tk.DISABLED,
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#ffffff"
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Configure text tags for colored output
        self.log_text.tag_configure("success", foreground="#4ec9b0")
        self.log_text.tag_configure("error", foreground="#f14c4c")
        self.log_text.tag_configure("warning", foreground="#cca700")
        self.log_text.tag_configure("info", foreground="#3794ff")

    def _browse_config(self) -> None:
        """Open file dialog to select a config file."""
        initial_dir = SCRIPT_DIR / "config"
        if not initial_dir.exists():
            initial_dir = SCRIPT_DIR

        filepath = filedialog.askopenfilename(
            title="Select Config File",
            initialdir=str(initial_dir),
            filetypes=[
                ("YAML files", "*.yaml *.yml"),
                ("JSON files", "*.json"),
                ("All files", "*.*")
            ]
        )
        if filepath:
            self.config_var.set(filepath)

    def _clear_config(self) -> None:
        """Reset to the default config file for the current platform."""
        self._update_default_config()

    def _on_platform_changed(self, event=None) -> None:
        """Handle platform selection change by updating the default config."""
        self._update_default_config()

    def _update_default_config(self) -> None:
        """Update the config field with the default config for the selected platform."""
        platform_display = self.platform_var.get()
        platform = self.PLATFORMS.get(platform_display, "")

        if platform in self.CONFIG_MAPPING:
            config_path = SCRIPT_DIR / self.CONFIG_MAPPING[platform]
            self.config_var.set(str(config_path))
        elif platform == "all":
            self.config_var.set("(uses default config for each platform)")
        else:
            self.config_var.set("")

    def _clear_log(self) -> None:
        """Clear the output log."""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _log_message(self, message: str) -> None:
        """
        Append a message to the log with appropriate coloring.

        Args:
            message: The message to log.
        """
        self.log_text.config(state=tk.NORMAL)

        # Determine tag based on message content
        tag = None
        if "✅" in message or "success" in message.lower():
            tag = "success"
        elif "❌" in message or "error" in message.lower() or "failed" in message.lower():
            tag = "error"
        elif "⚠️" in message or "warning" in message.lower():
            tag = "warning"
        elif "🔄" in message or "📊" in message or "processing" in message.lower():
            tag = "info"

        if tag:
            self.log_text.insert(tk.END, message, tag)
        else:
            self.log_text.insert(tk.END, message)

        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _check_output_queue(self) -> None:
        """Check the output queue and update the log widget."""
        try:
            while True:
                message = self.output_queue.get_nowait()
                self._log_message(message)
        except queue.Empty:
            pass

        # Schedule next check
        self.root.after(100, self._check_output_queue)

    def _run_process(self) -> None:
        """Start the processing task in a background thread."""
        if self.is_running:
            return

        self.is_running = True
        self.run_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_var.set("Running...")

        # Get selected values
        platform_display = self.platform_var.get()
        platform = self.PLATFORMS.get(platform_display, "kling")

        action_display = self.action_var.get()
        action = self.ACTIONS.get(action_display, "auto")

        config_file = self.config_var.get() or None
        verbose = self.verbose_var.get()
        parallel = self.parallel_var.get()

        # Log the command
        self._log_message(f"\n{'='*60}\n")
        self._log_message(f"🚀 Starting: {platform_display}\n")
        self._log_message(f"   Action: {action_display}\n")
        if config_file:
            self._log_message(f"   Config: {config_file}\n")
        self._log_message(f"{'='*60}\n\n")

        # Run in background thread
        thread = threading.Thread(
            target=self._execute_process,
            args=(platform, action, config_file, verbose, parallel),
            daemon=True
        )
        thread.start()

    def _execute_process(
        self,
        platform: str,
        action: str,
        config_file: str | None,
        verbose: bool,
        parallel: bool
    ) -> None:
        """
        Execute the processing task.

        Args:
            platform: The platform API name.
            action: The action to perform.
            config_file: Optional path to config file.
            verbose: Whether to enable verbose logging.
            parallel: Whether to run platforms in parallel.
        """
        # Redirect stdout/stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        redirector = TextRedirector(self.log_text, self.output_queue)
        sys.stdout = redirector
        sys.stderr = redirector

        try:
            # Change to core directory for imports
            original_cwd = os.getcwd()
            os.chdir(str(CORE_DIR))

            # Import and run the main logic
            # Note: runall is in core/ directory, added to sys.path at module load
            from runall import (  # type: ignore[import-not-found]
                API_MAPPING,
                CONFIG_MAPPING,
                run_processor,
                run_report_generator,
                get_platforms_to_run
            )

            platforms_to_run = get_platforms_to_run(platform)

            for plat in platforms_to_run:
                if not self.is_running:
                    print("\n⏹ Process stopped by user.\n")
                    break

                api_name = API_MAPPING.get(plat, plat)

                # Determine config file
                cfg = config_file
                if not cfg and api_name in CONFIG_MAPPING:
                    cfg = CONFIG_MAPPING[api_name]

                # Run based on action
                if action in ["process", "auto"]:
                    success, skip_report = run_processor(api_name, cfg)
                    if action == "auto" and not skip_report:
                        run_report_generator(api_name, cfg)
                elif action == "report":
                    run_report_generator(api_name, cfg)

            print("\n✅ All tasks completed.\n")

        except Exception as e:
            print(f"\n❌ Error: {e}\n")
            import traceback
            traceback.print_exc()

        finally:
            # Restore stdout/stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr

            # Restore working directory
            os.chdir(original_cwd)

            # Update UI (thread-safe)
            self.root.after(0, self._process_finished)

    def _process_finished(self) -> None:
        """Reset UI state after process completion."""
        self.is_running = False
        self.run_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.status_var.set("Ready")

    def _stop_process(self) -> None:
        """Signal the running process to stop."""
        if self.is_running:
            self.is_running = False
            self.status_var.set("Stopping...")
            self.output_queue.put("\n⚠️ Stop requested. Waiting for current task to finish...\n")


def main() -> None:
    """Entry point for the GUI launcher application."""
    root = tk.Tk()

    # Set icon if available
    icon_path = SCRIPT_DIR / "assets" / "icon.ico"
    if icon_path.exists():
        try:
            root.iconbitmap(str(icon_path))
        except tk.TclError:
            pass

    app = GAILauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
