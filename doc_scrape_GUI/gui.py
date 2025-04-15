"""
Graphical user interface for the Document Scraper system.

This module provides a user-friendly GUI for controlling the document scraper,
with advanced options for intelligent documentation-focused crawling and
interactive selection of content types.
"""

import os
import sys
import queue
import logging
import threading
import traceback
import tkinter as tk
from urllib.parse import urlparse
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
import json
from collections import deque
import glob
import time
from datetime import datetime

# Setup a file logger for diagnostics
log_file = os.path.join(os.path.dirname(__file__), "gui_debug.log")
file_handler = logging.FileHandler(log_file, mode="w", encoding='utf-8')
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(file_handler)
root_logger.info("GUI startup - logging initialized")

# Adjust sys.path if necessary to find the document_scraper module
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from document_scraper.crawler import Crawler  # Import the new Crawler component
    from document_scraper.scraper import DocumentationScraper
    from document_scraper.utils import is_valid_url, ensure_directory_exists
except ImportError as e:
    # Use tk._default_root to show error if main window isn't up yet
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Import Error", 
                            f"Could not import document_scraper components. Make sure it's installed and accessible.\nError: {e}", 
                            parent=root)
        root.destroy()
    except tk.TclError:  # In case tkinter isn't available at all
         print(f"Import Error: {e}", file=sys.stderr)
    sys.exit(1)

# --- Logging Setup ---
# Queue handler to forward log records to the GUI thread
log_queue = queue.Queue()

class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        # Ensure record is formatted before putting in queue
        msg = self.format(record)
        self.log_queue.put(msg)


logger = logging.getLogger("document_scraper")
# Keep existing handlers if cli.py might still be used, or clear them
logger.setLevel(logging.INFO)  # Default level
queue_handler = QueueHandler(log_queue)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
queue_handler.setFormatter(formatter)

# Prevent adding handler multiple times if script re-runs in some contexts
if not any(isinstance(h, QueueHandler) for h in logger.handlers):
    logger.addHandler(queue_handler)
if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
     pass


# --- GUI Application Class ---
class DocScraperApp:
    def __init__(self, root=None):
        self.root = root if root else tk.Tk()
        self.is_standalone = not bool(root)  # True if no root was passed

        if self.is_standalone:
            self.root.title("Document Scraper GUI")
            self.root.geometry("800x750")
            self.container = self.root
        else:  # Embedded case
            # Assume parent (root) handles title/geometry
            self.frame = ttk.Frame(self.root)
            self.frame.pack(fill=tk.BOTH, expand=True)
            self.container = self.frame  # Widgets go into the frame

        # Ensure window comes to foreground and is visible
        try:
            self.root.attributes("-topmost", True)
            self.root.update()
            self.root.attributes("-topmost", False)
            self.root.lift()
            self.root.focus_force()
        except tk.TclError as e:
             logger.warning(f"Could not bring window to foreground (may be expected on some platforms): {e}")
        except Exception as e:
            logger.warning(f"Error setting window attributes: {e}")

        logger.info("DocScraperApp initialized successfully")

        # --- Variables ---
        self.url = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.max_depth = tk.IntVar(value=5)
        self.delay = tk.DoubleVar(value=0.5)
        self.max_pages = tk.IntVar(value=0)  # 0 means unlimited
        self.concurrent = tk.IntVar(value=5)
        self.include_assets = tk.BooleanVar(value=False)
        self.browser_mode = tk.BooleanVar(value=True)  # Set to TRUE by default for better scraping
        self.interactive_mode = tk.BooleanVar(value=True)  # New option for interactive crawling
        self.doc_priority = tk.BooleanVar(value=True)  # New option to prioritize documentation links
        self.user_agent = tk.StringVar()
        self.proxy = tk.StringVar()
        self.timeout = tk.IntVar(value=30)
        self.retries = tk.IntVar(value=3)
        self.include_content = tk.StringVar()  # Comma-separated
        self.exclude_content = tk.StringVar()  # Comma-separated
        self.include_url = tk.StringVar()  # Comma-separated
        self.exclude_url = tk.StringVar()  # Comma-separated
        self.verbose = tk.BooleanVar(value=False)
        self.advanced_options_visible = tk.BooleanVar(value=False)

        # State tracking
        self.scraper_thread = None
        self.stop_event = threading.Event()
        self.doc_links = []  # To store discovered documentation links
        self.aux_links = []  # To store discovered auxiliary links
        self.external_links = []  # To store discovered external links
        self.asset_links = []  # To store discovered asset links

        # --- History and Settings ---
        self.recent_urls = deque(maxlen=10)
        self.settings_file = os.path.join(script_dir, "scraper_settings.json")
        self.load_settings()  # Load previous settings and history

        # --- GUI Layout ---
        self.configure_styles()  # Configure styles before creating widgets
        self.create_widgets()

        # Start polling the log queue
        self.check_log_queue()  # Use check instead of poll to avoid confusion

        # Add to __init__ after variables section
        self.presets_dir = os.path.join(script_dir, "presets")
        if not os.path.exists(self.presets_dir):
            os.makedirs(self.presets_dir, exist_ok=True)

    def configure_styles(self):
        style = ttk.Style(self.root)
        # Ensure theme exists, fallback if needed
        available_themes = style.theme_names()
        desired_theme = 'clam'  # 'vista' on windows often looks good too
        if desired_theme not in available_themes:
             if 'vista' in available_themes:
                  desired_theme = 'vista'
             elif 'default' in available_themes:
                  desired_theme = 'default'
             else:
                  desired_theme = available_themes[0]  # Pick first available
        try:
            style.theme_use(desired_theme)
            logger.info(f"Using theme: {desired_theme}")
        except tk.TclError:
            logger.warning(f"Failed to set theme {desired_theme}, using default.")
            style.theme_use(style.theme_names()[0])  # Use the actual default

        # Default styles
        style.configure('TFrame', background='#f0f0f0')
        style.configure('TLabel', background='#f0f0f0', font=('Segoe UI', 10))
        style.configure('TButton', font=('Segoe UI', 10), padding=5)
        style.configure('TEntry', font=('Segoe UI', 10), padding=5)
        style.configure('TCheckbutton', background='#f0f0f0', font=('Segoe UI', 10))
        
        # Accent button - for the Start button
        style.configure('Accent.TButton', 
                       font=('Segoe UI', 10, 'bold'), 
                       foreground='white', 
                       background='#0078D4', 
                       padding=5)
        style.map('Accent.TButton', 
                 background=[('active', '#005A9E'), ('disabled', '#A0A0A0')])
        
        # Headers and sections
        style.configure('Header.TLabel', 
                       font=('Segoe UI', 12, 'bold'), 
                       background='#f0f0f0')
        
        style.configure('Section.TFrame', 
                       background='#e0e0e0', 
                       borderwidth=1, 
                       relief='groove', 
                       padding=10)
        
        # Status indicators
        style.configure('StatusGood.TLabel', 
                       foreground='green', 
                       font=('Segoe UI', 10, 'bold'))
        
        style.configure('StatusWarning.TLabel', 
                       foreground='orange', 
                       font=('Segoe UI', 10, 'bold'))
        
        style.configure('StatusBad.TLabel', 
                       foreground='red', 
                       font=('Segoe UI', 10, 'bold'))
        
        # Documentation category styles
        style.configure('DocLink.TLabel', 
                       foreground='#0066cc', 
                       font=('Segoe UI', 9))
        
        style.configure('AuxLink.TLabel', 
                       foreground='#cc6600', 
                       font=('Segoe UI', 9))
        
        style.configure('ExtLink.TLabel', 
                       foreground='#999999', 
                       font=('Segoe UI', 9))
        
        style.configure('AssetLink.TLabel', 
                       foreground='#009900', 
                       font=('Segoe UI', 9))
        
        # Notebook styling
        style.configure('TNotebook', 
                       background='#f0f0f0', 
                       tabmargins=[0, 0, 0, 0])
        
        style.configure('TNotebook.Tab', 
                       font=('Segoe UI', 9), 
                       padding=[10, 2], 
                       background='#e0e0e0')
        
        style.map('TNotebook.Tab', 
                  background=[('selected', '#0078D4')],
                  foreground=[('selected', 'white')])
        
        # Treeview (for page list)
        style.configure('Treeview', 
                       font=('Segoe UI', 9),
                       rowheight=22)
        
        style.configure('Treeview.Heading', 
                       font=('Segoe UI', 9, 'bold'))

    def create_widgets(self):
        main_frame = ttk.Frame(self.container, padding="10 10 10 10", style='TFrame')
        main_frame.pack(expand=True, fill=tk.BOTH)
        main_frame.columnconfigure(0, weight=1)  # Allow content to expand horizontally

        # --- Helper Functions ---
        def create_tooltip(widget, text):
            """Create a tooltip for a widget."""
            def enter(event):
                x, y, _, _ = widget.bbox("insert")
                x += widget.winfo_rootx() + 25
                y += widget.winfo_rooty() + 25
                
                # Create a toplevel window
                tip_window = tk.Toplevel(widget)
                tip_window.wm_overrideredirect(True)
                tip_window.wm_geometry(f"+{x}+{y}")
                
                # Add the tooltip text
                label = ttk.Label(tip_window, text=text, justify=tk.LEFT,
                                  background="#FFFFAA", relief=tk.SOLID, borderwidth=1,
                                  wraplength=300, font=("Segoe UI", 9))
                label.pack(padx=2, pady=2)
                
                widget.tooltip = tip_window
                
            def leave(event):
                if hasattr(widget, "tooltip"):
                    widget.tooltip.destroy()
            
            widget.bind("<Enter>", enter)
            widget.bind("<Leave>", leave)

        # --- Input Section ---
        input_frame = ttk.LabelFrame(main_frame, text=" Input Configuration ", padding="10", style='Section.TFrame')
        input_frame.grid(row=0, column=0, pady=(0, 10), sticky=tk.EW)  # Use grid for main sections too
        input_frame.columnconfigure(1, weight=1)

        # URL input with combobox for history
        url_frame = ttk.Frame(input_frame)
        url_frame.grid(row=0, column=0, columnspan=3, padx=5, pady=5, sticky=tk.EW)
        url_frame.columnconfigure(1, weight=1)

        ttk.Label(url_frame, text="Documentation URL:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.url_combo = ttk.Combobox(url_frame, textvariable=self.url, width=60)
        self.url_combo.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.url_combo['values'] = list(self.recent_urls)
        # Allow typing custom values
        self.url_combo['state'] = 'normal'

        # Clear history button
        clear_history_button = ttk.Button(
            url_frame,
            text="🗑️",
            command=self.clear_recent_urls,
            width=3
        )
        clear_history_button.grid(row=0, column=2, padx=5, pady=5)
        create_tooltip(clear_history_button, "Clear URL history")

        # Output directory
        ttk.Label(input_frame, text="Output Directory:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.output_entry = ttk.Entry(input_frame, textvariable=self.output_dir, width=50)
        self.output_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Button(input_frame, text="Browse...", command=self.browse_output_dir).grid(row=1, column=2, padx=5, pady=5)

        # Add tooltips to important controls
        create_tooltip(self.url_combo, "Select a URL from history or enter a new one")
        create_tooltip(self.output_entry, "Directory where downloaded documentation will be saved")

        # --- Crawling Strategy Section (New) ---
        self.crawl_strategy_frame = ttk.LabelFrame(main_frame, text=" Crawling Strategy ", padding="10", style='Section.TFrame')
        self.crawl_strategy_frame.grid(row=1, column=0, pady=10, sticky=tk.EW)
        self.crawl_strategy_frame.columnconfigure(0, weight=1)

        # Documentation priority
        doc_priority_btn = ttk.Checkbutton(
            self.crawl_strategy_frame, 
            text="Prioritize Documentation Links (Recommended)", 
            variable=self.doc_priority
        )
        doc_priority_btn.grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        create_tooltip(doc_priority_btn, 
                      "Focus on downloading documentation pages first before auxiliary content (recommended)")

        # Interactive mode
        interactive_mode_btn = ttk.Checkbutton(
            self.crawl_strategy_frame, 
            text="Interactive Mode (Ask before crawling non-documentation content)", 
            variable=self.interactive_mode
        )
        interactive_mode_btn.grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        create_tooltip(interactive_mode_btn, 
                      "Prompt before crawling auxiliary content like pricing pages, settings, etc.")

        # --- Basic Options Section ---
        self.basic_options_frame = ttk.LabelFrame(main_frame, text=" Basic Options ", padding="10", style='Section.TFrame')
        self.basic_options_frame.grid(row=2, column=0, pady=10, sticky=tk.EW)
        self.basic_options_frame.columnconfigure(1, weight=1)
        self.basic_options_frame.columnconfigure(3, weight=1)

        ttk.Label(self.basic_options_frame, text="Max Depth:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        depth_spinbox = ttk.Spinbox(self.basic_options_frame, from_=1, to=100, textvariable=self.max_depth, width=5)
        depth_spinbox.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)

        ttk.Label(self.basic_options_frame, text="Delay (sec):").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        delay_spinbox = ttk.Spinbox(self.basic_options_frame, from_=0.0, to=10.0, increment=0.1, format="%.1f", textvariable=self.delay, width=5)
        delay_spinbox.grid(row=0, column=3, padx=5, pady=5, sticky=tk.W)

        ttk.Label(self.basic_options_frame, text="Max Pages (0=inf):").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        pages_spinbox = ttk.Spinbox(self.basic_options_frame, from_=0, to=100000, textvariable=self.max_pages, width=7)
        pages_spinbox.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)

        ttk.Label(self.basic_options_frame, text="Concurrent Req:").grid(row=1, column=2, padx=5, pady=5, sticky=tk.W)
        concurrent_spinbox = ttk.Spinbox(self.basic_options_frame, from_=1, to=50, textvariable=self.concurrent, width=5)
        concurrent_spinbox.grid(row=1, column=3, padx=5, pady=5, sticky=tk.W)

        # --- Advanced Options Section (Initially Hidden) ---
        self.adv_frame = ttk.LabelFrame(main_frame, text=" Advanced Options ", padding="10", style='Section.TFrame')
        self.adv_frame.columnconfigure(1, weight=1)  # Allow user agent/proxy fields to expand

        ttk.Checkbutton(self.adv_frame, text="Include Assets (Images, CSS, JS)", variable=self.include_assets).grid(row=0, column=0, columnspan=4, padx=5, pady=5, sticky=tk.W)  # Span all columns
        browser_mode_btn = ttk.Checkbutton(self.adv_frame, text="Browser Mode (Required for JavaScript/React sites)", variable=self.browser_mode)
        browser_mode_btn.grid(row=1, column=0, columnspan=4, padx=5, pady=5, sticky=tk.W)  # Span all columns
        create_tooltip(browser_mode_btn, "Enable to render JavaScript and scrape modern web apps.\nRequired for websites built with React, Vue, Next.js, etc.\nSlower but more accurate.")

        ttk.Label(self.adv_frame, text="User Agent:").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(self.adv_frame, textvariable=self.user_agent, width=50).grid(row=2, column=1, columnspan=3, padx=5, pady=5, sticky=tk.EW)  # Span remaining columns

        ttk.Label(self.adv_frame, text="Proxy URL:").grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(self.adv_frame, textvariable=self.proxy, width=50).grid(row=3, column=1, columnspan=3, padx=5, pady=5, sticky=tk.EW)  # Span remaining columns

        ttk.Label(self.adv_frame, text="Timeout (sec):").grid(row=4, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Spinbox(self.adv_frame, from_=5, to=300, textvariable=self.timeout, width=5).grid(row=4, column=1, padx=5, pady=5, sticky=tk.W)

        ttk.Label(self.adv_frame, text="Retries:").grid(row=4, column=2, padx=5, pady=5, sticky=tk.W)  # Placed next to timeout
        ttk.Spinbox(self.adv_frame, from_=0, to=10, textvariable=self.retries, width=5).grid(row=4, column=3, padx=5, pady=5, sticky=tk.W)

        ttk.Checkbutton(self.adv_frame, text="Verbose Logging", variable=self.verbose, command=self.toggle_verbose).grid(row=5, column=0, columnspan=4, padx=5, pady=5, sticky=tk.W)  # Span all columns

        # --- Filtering Section (Initially Hidden) ---
        self.filter_frame = ttk.LabelFrame(main_frame, text=" Filtering (Comma-separated Regex Patterns) ", padding="10", style='Section.TFrame')
        self.filter_frame.columnconfigure(1, weight=1)

        ttk.Label(self.filter_frame, text="Include Content:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.include_content_entry = ttk.Entry(self.filter_frame, textvariable=self.include_content, width=50)
        self.include_content_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        create_tooltip(self.include_content_entry, "Regex patterns for content to include (e.g., introduction, api_reference)")

        ttk.Label(self.filter_frame, text="Exclude Content:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.exclude_content_entry = ttk.Entry(self.filter_frame, textvariable=self.exclude_content, width=50)
        self.exclude_content_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        create_tooltip(self.exclude_content_entry, "Regex patterns for content to exclude (e.g., comments, footer)")

        ttk.Label(self.filter_frame, text="Include URLs:").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        self.include_url_entry = ttk.Entry(self.filter_frame, textvariable=self.include_url, width=50)
        self.include_url_entry.grid(row=2, column=1, padx=5, pady=5, sticky=tk.EW)
        create_tooltip(self.include_url_entry, "Regex patterns for URLs to include (e.g., /docs/, /guides/)")

        ttk.Label(self.filter_frame, text="Exclude URLs:").grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)
        self.exclude_url_entry = ttk.Entry(self.filter_frame, textvariable=self.exclude_url, width=50)
        self.exclude_url_entry.grid(row=3, column=1, padx=5, pady=5, sticky=tk.EW)
        create_tooltip(self.exclude_url_entry, "Regex patterns for URLs to exclude (e.g., /blog/, /search)")

        # --- Control Buttons ---
        control_frame = ttk.Frame(main_frame, padding="5 10 5 10", style='TFrame')
        control_frame.grid(row=3, column=0, pady=(10, 0), sticky=tk.EW)

        # Add nested frames to organize buttons
        action_buttons = ttk.Frame(control_frame)
        action_buttons.pack(side=tk.LEFT, padx=10)

        utility_buttons = ttk.Frame(control_frame)
        utility_buttons.pack(side=tk.RIGHT, padx=10)

        # Create styled buttons
        self.start_button = ttk.Button(
            action_buttons, 
            text="▶ START SCRAPING", 
            command=self.start_download, 
            style='Accent.TButton', 
            width=20
        )
        self.start_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.stop_button = ttk.Button(
            action_buttons, 
            text="■ STOP", 
            command=self.stop_download, 
            state=tk.DISABLED, 
            width=15
        )
        self.stop_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Add "Advanced Options..." button to action_buttons
        self.advanced_options_button = ttk.Button(
            action_buttons,
            text="⚙️ Advanced...",
            command=self.toggle_advanced_options,
            width=15
        )
        self.advanced_options_button.pack(side=tk.LEFT, padx=5, pady=5)
        create_tooltip(self.advanced_options_button, "Show/Hide advanced scraping options")

        # Add Open Output button
        self.open_output_button = ttk.Button(
            utility_buttons,
            text="📂 Open Output",
            command=self.open_output_dir,
            width=15
        )
        self.open_output_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Save and Load preset buttons
        save_preset_button = ttk.Button(
            utility_buttons,
            text="💾 Save Preset",
            command=self.save_preset,
            width=15
        )
        save_preset_button.pack(side=tk.LEFT, padx=5, pady=5)
        
        load_preset_button = ttk.Button(
            utility_buttons,
            text="📋 Load Preset",
            command=self.load_preset,
            width=15
        )
        load_preset_button.pack(side=tk.LEFT, padx=5, pady=5)
        
        # Add a help button
        help_button = ttk.Button(
            utility_buttons,
            text="?",
            command=self.show_help,
            width=3
        )
        help_button.pack(side=tk.LEFT, padx=5, pady=5)
        
        # Now that all buttons are defined, add tooltips to them
        create_tooltip(self.start_button, "Begin the documentation scraping process")
        create_tooltip(self.stop_button, "Stop the currently running scraping process")
        create_tooltip(self.open_output_button, "Open the output directory in file explorer")
        create_tooltip(save_preset_button, "Save current settings as a preset")
        create_tooltip(load_preset_button, "Load settings from a saved preset")
        create_tooltip(help_button, "Show help information about using the scraper")
        
        # Add tooltips for options
        create_tooltip(depth_spinbox, "Maximum crawl depth from the start URL\nHigher values download more pages but take longer")
        create_tooltip(delay_spinbox, "Delay between requests in seconds\nIncrease to be more respectful to the server")
        create_tooltip(pages_spinbox, "Maximum number of pages to download\nSet to 0 for unlimited")
        create_tooltip(concurrent_spinbox, "Number of simultaneous requests\nHigher values download faster but increase server load")

        # --- Progress & Log Area ---
        status_frame = ttk.LabelFrame(main_frame, text=" Progress & Logs ", padding="10", style='Section.TFrame')
        status_frame.grid(row=4, column=0, pady=10, sticky=tk.NSEW)  # Row 4 instead of 5
        status_frame.columnconfigure(0, weight=1)
        status_frame.rowconfigure(1, weight=1)  # Allow scrolledtext to expand vertically

        # Make main_frame's row 4 expand vertically
        main_frame.rowconfigure(4, weight=1)

        # Status display
        status_bar = ttk.Frame(status_frame)
        status_bar.grid(row=0, column=0, sticky=tk.EW, pady=(0, 5))
        status_bar.columnconfigure(1, weight=1)

        self.pages_count_label = ttk.Label(status_bar, text="Pages: 0")
        self.pages_count_label.grid(row=0, column=0, padx=(0, 10), sticky=tk.W)

        self.assets_count_label = ttk.Label(status_bar, text="Assets: 0")
        self.assets_count_label.grid(row=0, column=1, padx=(0, 10), sticky=tk.W)

        self.status_label = ttk.Label(status_bar, text="Status: Ready")
        self.status_label.grid(row=0, column=2, sticky=tk.E)

        # Create a notebook for logs and page list
        self.notebook = ttk.Notebook(status_frame)
        self.notebook.grid(row=1, column=0, sticky=tk.NSEW)

        # Create log text area
        log_frame = ttk.Frame(self.notebook)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, width=90, state=tk.DISABLED, wrap=tk.WORD, font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.notebook.add(log_frame, text="Logs")

        # Create page list area with more columns
        pages_frame = ttk.Frame(self.notebook)
        self.pages_list = ttk.Treeview(
            pages_frame, 
            columns=("url", "status", "type", "size", "category"),  # Added category column
            show="headings",
            selectmode="browse"
        )

        # Configure columns
        self.pages_list.heading("url", text="URL")
        self.pages_list.heading("status", text="Status")
        self.pages_list.heading("type", text="Type")
        self.pages_list.heading("size", text="Size")
        self.pages_list.heading("category", text="Category")  # New column

        # Set column widths
        self.pages_list.column("url", width=300)
        self.pages_list.column("status", width=80)
        self.pages_list.column("type", width=70)
        self.pages_list.column("size", width=70)
        self.pages_list.column("category", width=80)  # New column

        # Add right-click menu for the page list
        self.page_context_menu = tk.Menu(self.pages_list, tearoff=0)
        self.page_context_menu.add_command(label="Copy URL", command=self.copy_selected_url)
        self.page_context_menu.add_command(label="Open in Browser", command=self.open_selected_url)
        self.pages_list.bind("<Button-3>", self.show_page_context_menu)

        # Add double-click to open the file
        self.pages_list.bind("<Double-1>", self.open_selected_file)

        self.pages_list.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        # Add scrollbar to page list
        pages_scrollbar = ttk.Scrollbar(pages_frame, orient=tk.VERTICAL, command=self.pages_list.yview)
        pages_scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.pages_list.configure(yscrollcommand=pages_scrollbar.set)

        self.notebook.add(pages_frame, text="Crawled Pages")
        
        # Create links tab to show categorized links
        links_frame = ttk.Frame(self.notebook)
        
        # Create notebook for link categories
        links_notebook = ttk.Notebook(links_frame)
        links_notebook.pack(fill=tk.BOTH, expand=True)
        
        # Documentation links tab
        doc_links_frame = ttk.Frame(links_notebook)
        self.doc_links_list = tk.Listbox(doc_links_frame, font=('Segoe UI', 9))
        doc_links_scrollbar = ttk.Scrollbar(doc_links_frame, orient=tk.VERTICAL, command=self.doc_links_list.yview)
        self.doc_links_list.configure(yscrollcommand=doc_links_scrollbar.set)
        self.doc_links_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        doc_links_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        links_notebook.add(doc_links_frame, text="Documentation Links")
        
        # Auxiliary links tab
        aux_links_frame = ttk.Frame(links_notebook)
        self.aux_links_list = tk.Listbox(aux_links_frame, font=('Segoe UI', 9))
        aux_links_scrollbar = ttk.Scrollbar(aux_links_frame, orient=tk.VERTICAL, command=self.aux_links_list.yview)
        self.aux_links_list.configure(yscrollcommand=aux_links_scrollbar.set)
        self.aux_links_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        aux_links_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        links_notebook.add(aux_links_frame, text="Auxiliary Links")
        
        # External links tab
        ext_links_frame = ttk.Frame(links_notebook)
        self.ext_links_list = tk.Listbox(ext_links_frame, font=('Segoe UI', 9))
        ext_links_scrollbar = ttk.Scrollbar(ext_links_frame, orient=tk.VERTICAL, command=self.ext_links_list.yview)
        self.ext_links_list.configure(yscrollcommand=ext_links_scrollbar.set)
        self.ext_links_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ext_links_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        links_notebook.add(ext_links_frame, text="External Links")
        
        # Asset links tab
        asset_links_frame = ttk.Frame(links_notebook)
        self.asset_links_list = tk.Listbox(asset_links_frame, font=('Segoe UI', 9))
        asset_links_scrollbar = ttk.Scrollbar(asset_links_frame, orient=tk.VERTICAL, command=self.asset_links_list.yview)
        self.asset_links_list.configure(yscrollcommand=asset_links_scrollbar.set)
        self.asset_links_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        asset_links_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        links_notebook.add(asset_links_frame, text="Asset Links")
        
        # Add right-click menu for link lists
        self.link_context_menu = tk.Menu(self.root, tearoff=0)
        self.link_context_menu.add_command(label="Copy URL", command=self.copy_selected_link)
        self.link_context_menu.add_command(label="Open in Browser", command=self.open_selected_link)
        
        # Bind right-click menu to all link lists
        self.doc_links_list.bind("<Button-3>", lambda event: self.show_link_context_menu(event, self.doc_links_list))
        self.aux_links_list.bind("<Button-3>", lambda event: self.show_link_context_menu(event, self.aux_links_list))
        self.ext_links_list.bind("<Button-3>", lambda event: self.show_link_context_menu(event, self.ext_links_list))
        self.asset_links_list.bind("<Button-3>", lambda event: self.show_link_context_menu(event, self.asset_links_list))
        
        # Add links tab to main notebook
        self.notebook.add(links_frame, text="Discovered Links")

        self.progress = ttk.Progressbar(status_frame, orient=tk.HORIZONTAL, length=300, mode='determinate')
        self.progress.grid(row=2, column=0, pady=(5,0), sticky=tk.EW)  # Span horizontally
        # Hide progress bar initially
        self.progress.grid_remove()

        # Create dashboard tab
        dashboard_frame = ttk.Frame(self.notebook)
        dashboard_frame.columnconfigure(0, weight=1)
        dashboard_frame.rowconfigure(2, weight=1)

        # Summary section
        summary_frame = ttk.Frame(dashboard_frame, padding=10)
        summary_frame.grid(row=0, column=0, sticky=tk.EW, padx=10, pady=10)

        ttk.Label(summary_frame, text="Scraping Summary", font=('Segoe UI', 12, 'bold')).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        # Stats boxes
        stats_frame = ttk.Frame(dashboard_frame)
        stats_frame.grid(row=1, column=0, sticky=tk.EW, padx=10)
        stats_frame.columnconfigure(0, weight=1)
        stats_frame.columnconfigure(1, weight=1)
        stats_frame.columnconfigure(2, weight=1)
        stats_frame.columnconfigure(3, weight=1)  # Added new column for doc links

        # Pages stats
        pages_stats = ttk.LabelFrame(stats_frame, text="Pages", padding=10)
        pages_stats.grid(row=0, column=0, padx=5, pady=5, sticky=tk.EW)
        self.dashboard_pages_count = ttk.Label(pages_stats, text="0", font=('Segoe UI', 18, 'bold'))
        self.dashboard_pages_count.pack(pady=5)
        ttk.Label(pages_stats, text="Documents Downloaded").pack()

        # Doc links stats
        doc_stats = ttk.LabelFrame(stats_frame, text="Doc Links", padding=10)
        doc_stats.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.dashboard_doc_count = ttk.Label(doc_stats, text="0", font=('Segoe UI', 18, 'bold'))
        self.dashboard_doc_count.pack(pady=5)
        ttk.Label(doc_stats, text="Documentation Links").pack()

        # Assets stats
        assets_stats = ttk.LabelFrame(stats_frame, text="Assets", padding=10)
        assets_stats.grid(row=0, column=2, padx=5, pady=5, sticky=tk.EW)
        self.dashboard_assets_count = ttk.Label(assets_stats, text="0", font=('Segoe UI', 18, 'bold'))
        self.dashboard_assets_count.pack(pady=5)
        ttk.Label(assets_stats, text="Images, CSS, JS Files").pack()

        # Time stats
        time_stats = ttk.LabelFrame(stats_frame, text="Duration", padding=10)
        time_stats.grid(row=0, column=3, padx=5, pady=5, sticky=tk.EW)
        self.dashboard_time = ttk.Label(time_stats, text="0:00", font=('Segoe UI', 18, 'bold'))
        self.dashboard_time.pack(pady=5)
        ttk.Label(time_stats, text="Time Elapsed").pack()

        # Recent jobs list
        jobs_frame = ttk.LabelFrame(dashboard_frame, text="Recent Jobs", padding=10)
        jobs_frame.grid(row=2, column=0, padx=10, pady=10, sticky=tk.NSEW)
        jobs_frame.columnconfigure(0, weight=1)
        jobs_frame.rowconfigure(0, weight=1)

        self.jobs_list = ttk.Treeview(
            jobs_frame, 
            columns=("date", "url", "pages", "assets", "time"), 
            show="headings",
            selectmode="browse"
        )

        # Configure columns
        self.jobs_list.heading("date", text="Date")
        self.jobs_list.heading("url", text="URL")
        self.jobs_list.heading("pages", text="Pages")
        self.jobs_list.heading("assets", text="Assets")
        self.jobs_list.heading("time", text="Duration")

        # Set column widths
        self.jobs_list.column("date", width=150)
        self.jobs_list.column("url", width=200)
        self.jobs_list.column("pages", width=80)
        self.jobs_list.column("assets", width=80)
        self.jobs_list.column("time", width=80)

        self.jobs_list.grid(row=0, column=0, sticky=tk.NSEW)

        # Add scrollbar
        jobs_scrollbar = ttk.Scrollbar(jobs_frame, orient=tk.VERTICAL, command=self.jobs_list.yview)
        jobs_scrollbar.grid(row=0, column=1, sticky=tk.NS)
        self.jobs_list.configure(yscrollcommand=jobs_scrollbar.set)

        # Add the dashboard tab to the notebook
        self.notebook.add(dashboard_frame, text="Dashboard")

    def browse_output_dir(self):
        try:
            directory = filedialog.askdirectory(parent=self.root)  # Ensure dialog is parented
            if directory:
                self.output_dir.set(directory)
                logger.debug(f"Output directory selected: {directory}")
                # Verify directory is writable
                if not os.access(directory, os.W_OK):
                    messagebox.showwarning("Permission Error", 
                                         f"You may not have write permission to the selected directory:\n{directory}\n\n"
                                         "Please choose a different directory or run the application with higher privileges.", 
                                         parent=self.root)
        except Exception as e:
            logger.error(f"Error selecting directory: {e}")
            messagebox.showerror("Error", 
                                f"Could not select directory: {str(e)}\n\n"
                                "Try selecting a different directory or running the application with administrator privileges.", 
                                parent=self.root)

    def toggle_verbose(self):
        if self.verbose.get():
            logger.setLevel(logging.DEBUG)
            self.log_message("Verbose logging enabled.", logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)
            self.log_message("Verbose logging disabled.", logging.INFO)

    def log_message(self, message, level=logging.INFO):
        """Use the logger to send messages to the queue."""
        logger.log(level, message)

    def update_log_text(self, message):
        """Appends message to the log text area in a thread-safe way."""
        try:
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, message + "\n")  # Add newline here
            self.log_text.see(tk.END)  # Scroll to the end
            self.log_text.config(state=tk.DISABLED)
        except tk.TclError as e:
             logger.error(f"Error updating log text: {e}")  # Log GUI errors

    def check_log_queue(self):
        """Checks the queue for messages and schedules the next check."""
        while True:
            try:
                record = log_queue.get(block=False)
                self.update_log_text(record)
            except queue.Empty:
                break
            except Exception as e:
                # Log exceptions during queue processing
                print(f"Error processing log queue: {e}", file=sys.stderr)
                traceback.print_exc()

        # Reschedule polling using `after` - crucial for Tkinter GUI responsiveness
        self.root.after(100, self.check_log_queue)


    def parse_patterns(self, pattern_string):
        if not pattern_string or not pattern_string.strip():
            return None
        # Return list directly, handle potential regex errors later if needed
        return [p.strip() for p in pattern_string.split(',') if p.strip()]

    def start_download(self):
        url = self.url.get()
        output = self.output_dir.get()

        if not url or not is_valid_url(url):
            messagebox.showerror("Error", "Please enter a valid URL.", parent=self.root)
            return
        if not output:
            messagebox.showerror("Error", "Please select an output directory.", parent=self.root)
            return

        # Check required dependencies for browser mode
        if self.browser_mode.get() and not self.check_browser_mode_dependencies():
            return

        # Add current URL to history
        self.add_to_recent_urls(url)

        # Validate output path before potentially creating it
        output = os.path.abspath(output)  # Ensure absolute path
        if not os.path.isdir(os.path.dirname(output)) and os.path.dirname(output) != '':
             messagebox.showerror("Error", f"Parent directory for '{output}' does not exist.", parent=self.root)
             return

        if not os.path.exists(output):
             if messagebox.askyesno("Create Directory?", f"Output directory '{output}' does not exist. Create it?", parent=self.root):
                 try:
                     os.makedirs(output, exist_ok=True)
                     self.log_message(f"Created directory: {output}", logging.INFO)
                     
                     # Verify the directory was actually created and is writable
                     if not os.path.exists(output):
                         messagebox.showerror("Error", 
                                            f"Failed to create directory '{output}'. The path may be invalid or you may not have permission.", 
                                            parent=self.root)
                         return
                     
                     if not os.access(output, os.W_OK):
                         messagebox.showerror("Permission Error", 
                                            f"The directory was created but you don't have permission to write to it:\n{output}\n\n"
                                            "Please choose a different directory or run the application with higher privileges.", 
                                            parent=self.root)
                         return
                 except OSError as e:
                     messagebox.showerror("Error", f"Could not create directory: {e}", parent=self.root)
                     return
             else:
                 self.log_message("Directory creation cancelled.", logging.WARNING)
                 return  # User chose not to create
        elif not os.path.isdir(output):
             messagebox.showerror("Error", f"Output path '{output}' exists but is not a directory.", parent=self.root)
             return
        elif not os.access(output, os.W_OK):
             messagebox.showerror("Permission Error", 
                                f"You don't have permission to write to the selected directory:\n{output}\n\n"
                                "Please choose a different directory or run the application with higher privileges.", 
                                parent=self.root)
             return

        # Disable start button, enable stop button
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        
        # Clear the log and page list
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete('1.0', tk.END)  # Clear previous logs
        self.log_text.config(state=tk.DISABLED)
        
        # Clear page list
        for item in self.pages_list.get_children():
            self.pages_list.delete(item)
        
        # Clear link lists
        self.doc_links_list.delete(0, tk.END)
        self.aux_links_list.delete(0, tk.END)
        self.ext_links_list.delete(0, tk.END)
        self.asset_links_list.delete(0, tk.END)
        
        # Reset status labels
        self.pages_count_label.config(text="Pages: 0")
        self.assets_count_label.config(text="Assets: 0")
        self.status_label.config(text="Status: Starting...")
        
        # Reset dashboard
        self.dashboard_pages_count.config(text="0")
        self.dashboard_doc_count.config(text="0")
        self.dashboard_assets_count.config(text="0")
        self.dashboard_time.config(text="0:00")
        
        # Start timer
        self.start_time = time.time()
        self.update_dashboard_timer()
        
        # Select logs tab for initial progress view
        self.notebook.select(0)
        
        self.log_message(f"Starting download from: {url}", logging.INFO)
        self.stop_event.clear()  # Reset stop event

        # Reset and show progress bar
        self.progress['value'] = 0
        self.progress.grid()  # Make progress bar visible

        # Save current settings
        self.save_settings()

        # Gather options
        max_p = self.max_pages.get()
        
        # Get interactive_mode value from the GUI thread before starting the worker thread
        interactive_mode = self.interactive_mode.get()
        
        # Configure the scraper with our options
        scraper_options = {
            "base_url": url,
            "output_dir": output,
            "max_depth": self.max_depth.get(),
            "delay": self.delay.get(),
            "max_pages": None if max_p == 0 else max_p,
            "concurrent_requests": self.concurrent.get(),
            "include_assets": self.include_assets.get(),
            "browser_mode": self.browser_mode.get(),
            "user_agent": self.user_agent.get().strip() or None,
            "proxies": {"http": self.proxy.get().strip(), "https": self.proxy.get().strip()} if self.proxy.get().strip() else None,
            "timeout": self.timeout.get(),
            "retries": self.retries.get(),
            "content_include_patterns": self.parse_patterns(self.include_content.get()),
            "content_exclude_patterns": self.parse_patterns(self.exclude_content.get()),
            "url_include_patterns": self.parse_patterns(self.include_url.get()),
            "url_exclude_patterns": self.parse_patterns(self.exclude_url.get()),
            "stop_event": self.stop_event,
            "progress_callback": self.update_progress_safe,
            "verbose": self.verbose.get(),
            "interactive_mode": interactive_mode  # Pass the interactive mode to the thread
        }

        # Validate patterns (basic check for now)
        for key, patterns in scraper_options.items():
             if "patterns" in key and patterns:
                 logger.debug(f"Using {key}: {patterns}")

        # Run scraper in a separate thread
        self.scraper_thread = threading.Thread(target=self.run_scraper, args=(scraper_options,), daemon=True)
        self.scraper_thread.start()

    def check_browser_mode_dependencies(self):
        """Check if required dependencies for browser mode are installed."""
        missing_deps = []
        
        # Check for selenium
        try:
            import selenium
        except ImportError:
            missing_deps.append("selenium")
            
        # Check for webdriver_manager
        try:
            import webdriver_manager
        except ImportError:
            missing_deps.append("webdriver-manager")
            
        # Check for lxml
        try:
            import lxml
        except ImportError:
            missing_deps.append("lxml")
            
        if missing_deps:
            deps_str = ", ".join(missing_deps)
            install_cmd = "pip install " + " ".join(missing_deps)
            
            msg = f"Browser mode requires additional dependencies: {deps_str}\n\n" \
                  f"Would you like to install them now?\n\n" \
                  f"Command: {install_cmd}"
                  
            if messagebox.askyesno("Missing Dependencies", msg, parent=self.root):
                try:
                    self.log_message(f"Installing dependencies: {deps_str}", logging.INFO)
                    import subprocess
                    subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing_deps)
                    self.log_message("Dependencies installed successfully", logging.INFO)
                    return True
                except Exception as e:
                    error_msg = f"Failed to install dependencies: {e}\n\n" \
                                f"Please install them manually by running:\n{install_cmd}"
                    messagebox.showerror("Installation Error", error_msg, parent=self.root)
                    return False
            else:
                # User chose not to install - offer to continue with browser mode disabled
                if messagebox.askyesno("Continue?", 
                                       "Would you like to continue with Browser Mode disabled?\n\n"
                                       "Note: This may result in empty or incomplete results for JavaScript-based sites.", 
                                       parent=self.root):
                    self.browser_mode.set(False)
                    return True
                return False
                
        return True  # All dependencies are installed

    def run_scraper(self, options):
        """Run the DocumentationScraper with the given options."""
        try:
            # Log detailed options
            logger.info("-" * 20)
            logger.info("Starting scraper with options:")
            for key, value in options.items():
                 if key not in ['cookies', 'proxies'] or value is None:
                     logger.info(f"  {key}: {value}")
                 else:
                     logger.info(f"  {key}: [REDACTED]")
            logger.info("-" * 20)
            
            # Create the scraper
            # Extract and remove interactive_mode from options before passing to DocumentationScraper
            interactive_mode = options.pop("interactive_mode", False)
            scraper = DocumentationScraper(**options)
            
            # Define callbacks for updating the UI with categorized links
            def link_discovery_callback(links_dict):
                """Callback for updating UI with discovered links."""
                if links_dict.get('doc'):
                    self.update_link_list_safe(self.doc_links_list, links_dict['doc'])
                    self.doc_links.extend(links_dict['doc'])
                if links_dict.get('aux'):
                    self.update_link_list_safe(self.aux_links_list, links_dict['aux'])
                    self.aux_links.extend(links_dict['aux'])
                if links_dict.get('external'):
                    self.update_link_list_safe(self.ext_links_list, links_dict['external'])
                    self.external_links.extend(links_dict['external'])
                if links_dict.get('asset'):
                    self.update_link_list_safe(self.asset_links_list, links_dict['asset'])
                    self.asset_links.extend(links_dict['asset'])
                
                # Update dashboard counts
                self.root.after(0, self.update_dashboard_counts, 
                               len(self.doc_links), len(self.asset_links))
                
                # Update notebook tab texts with counts
                self.root.after(0, self.update_link_tabs,
                               len(self.doc_links), len(self.aux_links),
                               len(self.external_links), len(self.asset_links))
            
            # Set up a callback for the crawler to report discovered links
            scraper.crawler.link_discovery_callback = link_discovery_callback
            
            # Start the crawling process with the interactive mode parameter
            pages_downloaded, assets_downloaded = scraper.crawl(interactive=interactive_mode)
            
            # Update the UI on the main thread
            self.root.after(0, self.download_complete, pages_downloaded, assets_downloaded, options["output_dir"], options["include_assets"])
            
        except Exception as e:
            # Log full traceback and display error
            logger.exception("Scraper error occurred:")
            self.root.after(0, self.download_error, e)
        finally:
            # Always reset UI
            self.root.after(0, self.reset_ui_after_run)

    def update_link_list_safe(self, listbox, links):
        """Thread-safe update of a link listbox."""
        # Use after() to schedule the update on the main thread
        self.root.after(0, self._update_link_list, listbox, links)
    
    def _update_link_list(self, listbox, links):
        """Update a listbox with links on the main thread."""
        # Add new links if they're not already in the list
        current_links = listbox.get(0, tk.END)
        for link in links:
            if link not in current_links:
                listbox.insert(tk.END, link)

    def update_link_tabs(self, doc_count, aux_count, ext_count, asset_count):
        """Update notebook tab texts with counts."""
        try:
            # Find the links notebook
            links_notebook = self.notebook.winfo_children()[2].winfo_children()[0]
            
            # Update tab texts
            links_notebook.tab(0, text=f"Documentation Links ({doc_count})")
            links_notebook.tab(1, text=f"Auxiliary Links ({aux_count})")
            links_notebook.tab(2, text=f"External Links ({ext_count})")
            links_notebook.tab(3, text=f"Asset Links ({asset_count})")
        except Exception as e:
            logger.error(f"Error updating link tabs: {e}")

    def update_progress_safe(self, url, current, total):
        """Thread-safe wrapper to schedule progress bar update on GUI thread."""
        self.root.after(0, self.update_progress, url, current, total)

    def update_progress(self, url, current, total):
        """Update progress bar and page list with current scraping status."""
        # Update status counters
        self.pages_count_label.config(text=f"Pages: {current}")
        
        # Update main status label with current action/URL
        if url:
            # Shorten URL for display if needed
            display_url = url if len(url) < 50 else "..." + url[-47:]
            current_status_text = f"Processing: {display_url}"
        else:
            # If no URL provided (e.g., start/end), use generic status
            current_status_text = f"Status: {current} pages scraped"

        # Add page to the list if it's a new one
        if url:
            # Get file type and size information (estimated)
            file_type = "HTML"
            category = "Unknown"
            
            # Determine file type based on URL extension
            if url.endswith(('.jpg', '.jpeg', '.png', '.gif')):
                file_type = "Image"
                category = "Asset"
            elif url.endswith(('.css')):
                file_type = "CSS"
                category = "Asset"
            elif url.endswith(('.js')):
                file_type = "JS"
                category = "Asset"
            
            # Try to determine category based on our link lists
            if url in self.doc_links:
                category = "Doc"
            elif url in self.aux_links:
                category = "Aux"
            elif url in self.external_links:
                category = "External"
            elif url in self.asset_links:
                category = "Asset"
            
            # Estimated size - in a real implementation, you'd get the actual file size
            size = "?"
            
            # Check if URL already exists in the list
            existing_items = self.pages_list.get_children()
            for item in existing_items:
                if self.pages_list.item(item, 'values')[0] == url:
                    # Update status if already exists
                    self.pages_list.item(item, values=(url, "Completed", file_type, size, category))
                    break
            else:
                # Add new item if not found
                self.pages_list.insert('', 'end', values=(url, "Completed", file_type, size, category))
                # Auto-scroll to the bottom to show latest entries
                self.pages_list.see(self.pages_list.get_children()[-1])
                
                # Update notebook tab to show new page count
                current_pages = len(self.pages_list.get_children())
                self.notebook.tab(1, text=f"Crawled Pages ({current_pages})")
        
        # Update progress bar and potentially override status label text
        if total and total > 0:
            self.progress['maximum'] = total
            self.progress['value'] = current
            # Use the total count status if available, otherwise keep the current URL status
            pct = int((current / total) * 100)
            current_status_text = f"Status: {current}/{total} pages ({pct}%)"
        else:
            # Handle indeterminate mode if total is unknown
            self.progress.config(mode='indeterminate')
            if not self.progress.winfo_ismapped():  # Check if already started
                self.progress.start(10)

        self.status_label.config(text=current_status_text)  # Update status label
        
        # Update dashboard counts too
        self.dashboard_pages_count.config(text=str(current))

    def download_complete(self, pages, assets, output_dir, included_assets):
        """Handle successful completion of download."""
        # Calculate elapsed time
        elapsed_time = time.time() - self.start_time if hasattr(self, 'start_time') else 0
        
        # Update dashboard
        self.update_dashboard_counts(pages, assets if included_assets else 0)
        self.add_job_to_history(self.url.get(), pages, assets if included_assets else 0, elapsed_time)
        
        # Update dashboard with link counts
        self.dashboard_doc_count.config(text=str(len(self.doc_links)))
        
        # Switch to the dashboard tab
        self.notebook.select(3)  # Index of dashboard tab
        
        self.log_message("\n✅ Download completed!", logging.INFO)
        self.log_message(f"• Downloaded {pages} documentation pages", logging.INFO)
        
        # Update asset count
        if included_assets:
            self.log_message(f"• Downloaded {assets} assets", logging.INFO)
            self.assets_count_label.config(text=f"Assets: {assets}")
        
        self.log_message(f"• Saved to {os.path.abspath(output_dir)}", logging.INFO)
        self.log_message(f"• Time elapsed: {int(elapsed_time // 60)}m {int(elapsed_time % 60)}s", logging.INFO)
        
        # Update status with success style
        self.status_label.config(text=f"Status: Completed ({pages} pages)", style="StatusGood.TLabel")
        
        # Show completion dialog with option to open directory
        if messagebox.askyesno("Success", 
                         f"Download completed!\n"
                         f"- {pages} pages downloaded\n"
                         f"- {assets if included_assets else 0} assets downloaded\n"
                         f"- Discovered {len(self.doc_links)} documentation links\n"
                         f"- Time elapsed: {int(elapsed_time // 60)}m {int(elapsed_time % 60)}s\n"
                         f"- Saved to: {os.path.abspath(output_dir)}\n\n"
                         f"Would you like to open the output directory now?", 
                         parent=self.root):
            self.open_output_dir()

    def download_stopped(self):
        """Handle user-initiated download stop."""
        self.log_message("\n🛑 Download stopped by user.", logging.WARNING)
        self.status_label.config(text="Status: Stopped by user")
        
        # Ensure index.md is created for the content scraped so far
        self.root.after(0, self._create_final_index)
        
        # No need for a messagebox here as the stop was initiated by the user
        # But we still want to update the UI state
        self.reset_ui_after_run()
        
    def _create_final_index(self):
        """Create a final index for the scraped content when stopping."""
        output_dir = self.output_dir.get()
        if not output_dir or not os.path.exists(output_dir):
            return
            
        try:
            # Path to the index file
            index_file = os.path.join(output_dir, "index.md")
            
            # If index already exists, we're done
            if os.path.exists(index_file):
                self.log_message("Index file already exists, no need to create it", logging.INFO)
                return
                
            # Create a basic index file if none exists
            with open(index_file, 'w', encoding='utf-8') as f:
                f.write("# Documentation Index\n\n")
                f.write("This index was automatically generated by Document Scraper after stopping.\n\n")
                
                # Add the scraped pages from the tree view
                pages = []
                for item_id in self.pages_list.get_children():
                    item = self.pages_list.item(item_id)
                    url = item['values'][0]
                    if url:
                        # Try to extract a title from the URL
                        title = url.split('/')[-1]
                        if not title:
                            title = url
                        pages.append((url, title))
                
                # Organize by sections
                sections = {}
                for url, title in pages:
                    # Parse URL to determine section
                    parsed_url = urlparse(url)
                    path_parts = parsed_url.path.strip('/').split('/')
                    
                    # Determine section based on URL structure
                    section = path_parts[0] if path_parts else "General"
                    section = section.replace('-', ' ').replace('_', ' ').title()
                    
                    if section not in sections:
                        sections[section] = []
                    sections[section].append((url, title))
                
                # Write each section
                for section_name, entries in sorted(sections.items()):
                    f.write(f"## {section_name}\n\n")
                    for url, title in entries:
                        # Get the expected path for this file
                        # Create a simple path for linking
                        url_path = urlparse(url).path.strip('/')
                        expected_path = url_path.replace('/', '-') + ".md"
                        f.write(f"- [{title}]({expected_path})\n")
                    f.write("\n")
            
            self.log_message("Created index file with links to all scraped pages", logging.INFO)
            
            # Open the directory
            if messagebox.askyesno("Scraping Stopped", 
                                 f"Scraping was stopped. {len(self.pages_list.get_children())} pages were downloaded.\n\n"
                                 f"Would you like to open the output directory?", 
                                 parent=self.root):
                self.open_output_dir()
                
        except Exception as e:
            self.log_message(f"Error creating index file: {e}", logging.ERROR)

    def download_error(self, error):
        """Handle errors during download."""
        # Update status display
        self.status_label.config(text="Status: Error", style="StatusBad.TLabel")
        
        # Format error nicely
        error_message = f"❌ Scraper Error: {str(error)}"
        self.log_message(error_message, logging.ERROR)
        
        # Add more detailed instructions
        self.log_message("See gui_debug.log for detailed error information.", logging.INFO)
        self.log_message("Try checking your internet connection and URL.", logging.INFO)
        
        # Show error dialog with more helpful information
        messagebox.showerror(
            "Scraper Error", 
            f"An error occurred during download:\n\n{str(error)}\n\n"
            "Possible solutions:\n"
            "• Check your internet connection\n"
            "• Verify the URL is accessible in your browser\n"
            "• Try increasing the timeout value\n"
            "• Check gui_debug.log for technical details", 
            parent=self.root
        )

    def prompt_auxiliary_crawl(self, aux_links):
        """
        Show a prompt to ask the user if they want to crawl auxiliary links.
        
        Args:
            aux_links: List of auxiliary links discovered
            
        Returns:
            Boolean indicating whether to proceed with auxiliary crawling
        """
        if not aux_links:
            return False
            
        # Create a dialog to show auxiliary links and prompt for crawling
        aux_dialog = tk.Toplevel(self.root)
        aux_dialog.title("Auxiliary Links Found")
        aux_dialog.transient(self.root)
        aux_dialog.grab_set()
        aux_dialog.geometry("600x400")
        
        # Add message explaining the situation
        ttk.Label(
            aux_dialog, 
            text="Documentation crawling complete. Auxiliary links were found.\n"
                 "Would you like to crawl these non-documentation pages as well?",
            font=('Segoe UI', 10),
            wraplength=550,
            justify=tk.CENTER
        ).pack(pady=(20, 10))
        
        # Create a frame for the link list
        list_frame = ttk.Frame(aux_dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Add a scrolled list to show the links
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        link_list = tk.Listbox(list_frame, font=('Segoe UI', 9), yscrollcommand=scrollbar.set)
        link_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=link_list.yview)
        
        # Insert links with a limit to avoid overwhelming the dialog
        shown_links = list(aux_links)[:100]  # Limit to 100 links for display
        for link in shown_links:
            link_list.insert(tk.END, link)
            
        if len(aux_links) > len(shown_links):
            link_list.insert(tk.END, f"... and {len(aux_links) - len(shown_links)} more links")
        
        # Add info label showing count
        ttk.Label(
            aux_dialog,
            text=f"Found {len(aux_links)} auxiliary links"
        ).pack(pady=(0, 10))
        
        # Add buttons
        button_frame = ttk.Frame(aux_dialog)
        button_frame.pack(fill=tk.X, padx=20, pady=(0, 20))
        
        # Variable to store the result
        result = [False]  # Use list to avoid nonlocal declaration
        
        def on_yes():
            result[0] = True
            aux_dialog.destroy()
            
        def on_no():
            result[0] = False
            aux_dialog.destroy()
        
        ttk.Button(button_frame, text="Yes, crawl auxiliary pages", command=on_yes, style="Accent.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="No, skip auxiliary pages", command=on_no).pack(side=tk.RIGHT, padx=5)
        
        # Center the dialog on the parent window
        aux_dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - aux_dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - aux_dialog.winfo_height()) // 2
        aux_dialog.geometry(f"+{x}+{y}")
        
        # Wait for dialog to close
        self.root.wait_window(aux_dialog)
        
        return result[0]

    def stop_download(self):
        if self.scraper_thread and self.scraper_thread.is_alive():
            self.log_message("Attempting to stop download...", logging.WARNING)
            self.stop_button.config(state=tk.DISABLED)  # Disable stop button immediately
            self.status_label.config(text="Status: Stopping...", style="StatusWarning.TLabel")
            
            # Set stop event and wait for the scraper thread to finish gracefully
            self.stop_event.set()  # Signal the scraper thread to stop
            
            # Show a message about stopping and finalizing
            messagebox.showinfo("Stopping Scraper", 
                            "Stopping the scraper and finalizing downloaded content...\n\n"
                            "The application will save all documents scraped so far and generate a navigation index.", 
                            parent=self.root)
            
            # Wait for the scraper thread to finish (maximum 5 seconds)
            self.scraper_thread.join(timeout=5)
            
            # If thread is still alive after timeout, show warning
            if self.scraper_thread.is_alive():
                self.log_message("Scraper thread is taking longer than expected to stop. Waiting for completion...", logging.WARNING)
                # Wait one more second
                self.scraper_thread.join(timeout=1)
                
                # If still alive, we'll have to proceed anyway
                if self.scraper_thread.is_alive():
                    self.log_message("Forced termination of scraper thread.", logging.WARNING)
                    # We can't forcibly terminate a thread in Python, but we can continue UI updates
            
            # Update UI to indicate stopping is complete
            self.download_stopped()
            
        else:
            self.log_message("No active download to stop.", logging.INFO)
            
    def reset_ui_after_run(self):
        """Resets buttons and UI elements after run completes or fails."""
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.progress.grid_remove()  # Hide progress bar
        self.progress.stop()  # Stop indeterminate animation if it was running
        self.stop_event.clear()  # Reset event for the next run
        self.scraper_thread = None  # Clear thread reference
        
        # Reset status labels
        self.status_label.config(text="Status: Ready")
        
        # Select logs tab when done
        self.notebook.select(0)

    def show_help(self):
        """Show a help dialog with information about using the scraper."""
        help_text = """
Document Scraper Help

Overview:
This tool downloads documentation websites and converts them to markdown or other formats for offline use.

Getting Started:
1. Enter the URL of the documentation site you want to download
2. Select an output directory where files will be saved
3. Adjust options as needed
4. Click "START SCRAPING" to begin

Key Options:
- Max Depth: Controls how many levels of links to follow from the start page
- Max Pages: Maximum number of pages to download (0 = unlimited)
- Delay: Time to wait between requests (be respectful to servers)
- Concurrent Requests: Number of simultaneous downloads

Crawling Strategy:
- Prioritize Documentation: Focus on downloading documentation-related pages first
- Interactive Mode: Asks before crawling non-documentation content like pricing pages

Advanced Features:
- Include Assets: Download images, CSS, and JavaScript files
- Browser Emulation: Better for JavaScript-heavy sites but slower
- Filtering: Use regex patterns to include/exclude content or URLs

Troubleshooting:
- If downloads fail, try increasing the timeout or retries
- Check the logs tab for detailed information
- For JavaScript-heavy sites, enable Browser Emulation Mode
"""
        # Create a custom dialog
        help_dialog = tk.Toplevel(self.root)
        help_dialog.title("Document Scraper Help")
        help_dialog.geometry("600x500")
        help_dialog.minsize(400, 300)
        
        # Make it modal
        help_dialog.transient(self.root)
        help_dialog.grab_set()
        
        # Add a text area with the help content
        help_text_widget = scrolledtext.ScrolledText(
            help_dialog, 
            wrap=tk.WORD, 
            font=('Segoe UI', 10),
            padx=10,
            pady=10
        )
        help_text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        help_text_widget.insert(tk.END, help_text)
        help_text_widget.config(state=tk.DISABLED)
        
        # Add a close button
        close_button = ttk.Button(
            help_dialog, 
            text="Close", 
            command=help_dialog.destroy,
            width=10
        )
        close_button.pack(pady=(0, 10))
        
        # Center the dialog on the parent window
        help_dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - help_dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - help_dialog.winfo_height()) // 2
        help_dialog.geometry(f"+{x}+{y}")

    def copy_selected_url(self):
        """Copy the selected URL to clipboard."""
        selected = self.pages_list.selection()
        if selected:
            url = self.pages_list.item(selected[0], 'values')[0]
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            self.status_label.config(text="URL copied to clipboard")

    def open_selected_url(self):
        """Open the selected URL in default browser."""
        import webbrowser
        selected = self.pages_list.selection()
        if selected:
            url = self.pages_list.item(selected[0], 'values')[0]
            webbrowser.open(url)

    def open_selected_file(self, event):
        """Open the selected file when double-clicked."""
        import webbrowser
        selected = self.pages_list.selection()
        if selected:
            url = self.pages_list.item(selected[0], 'values')[0]
            output_dir = self.output_dir.get()
            
            # Find the file using the improved method
            file_path = self.find_downloaded_file(url, output_dir)
            if file_path:
                self.log_message(f"Opening: {file_path}", logging.INFO)
                webbrowser.open('file://' + os.path.abspath(file_path))
            else:
                # If not found, just open the output directory
                self.open_output_dir()

    def show_page_context_menu(self, event):
        """Show the context menu for the page list."""
        if self.pages_list.identify_row(event.y):
            # Set the selection to the item the user clicked on
            self.pages_list.selection_set(self.pages_list.identify_row(event.y))
            self.page_context_menu.post(event.x_root, event.y_root)

    def show_link_context_menu(self, event, listbox):
        """Show the context menu for link lists."""
        try:
            # Find the nearest item to the click
            index = listbox.nearest(event.y)
            listbox.selection_clear(0, tk.END)
            listbox.selection_set(index)
            self.link_context_menu.post(event.x_root, event.y_root)
        except Exception:
            pass

    def copy_selected_link(self):
        """Copy selected link from any of the link lists."""
        for listbox in [self.doc_links_list, self.aux_links_list, self.ext_links_list, self.asset_links_list]:
            if listbox.curselection():
                index = listbox.curselection()[0]
                url = listbox.get(index)
                self.root.clipboard_clear()
                self.root.clipboard_append(url)
                self.status_label.config(text="URL copied to clipboard")
                break

    def open_selected_link(self):
        """Open selected link from any of the link lists in browser."""
        import webbrowser
        for listbox in [self.doc_links_list, self.aux_links_list, self.ext_links_list, self.asset_links_list]:
            if listbox.curselection():
                index = listbox.curselection()[0]
                url = listbox.get(index)
                webbrowser.open(url)
                break

    def open_output_dir(self):
        """Open the output directory in the default file explorer."""
        import os
        import webbrowser
        output_dir = self.output_dir.get()
        
        if output_dir and os.path.exists(output_dir):
            # Open the directory using the default file manager
            webbrowser.open('file://' + os.path.abspath(output_dir))
        else:
            messagebox.showinfo("Directory Not Found", 
                              "The output directory doesn't exist yet. It will be created when you start scraping.",
                              parent=self.root)

    # Add a mainloop method for standalone mode
    def mainloop(self):
        if self.is_standalone:
            # Ensure log queue checking is running before mainloop
            # self.check_log_queue() # Already called in __init__
            self.root.mainloop()

    def save_settings(self):
        """Save current settings to a JSON file for persistence between runs."""
        try:
            settings = {
                "recent_urls": list(self.recent_urls),
                "last_url": self.url.get(),
                "output_dir": self.output_dir.get(),
                "max_depth": self.max_depth.get(),
                "delay": self.delay.get(),
                "max_pages": self.max_pages.get(),
                "concurrent_requests": self.concurrent.get(),
                "include_assets": self.include_assets.get(),
                "browser_mode": self.browser_mode.get(),
                "interactive_mode": self.interactive_mode.get(),  # Save new settings
                "doc_priority": self.doc_priority.get(),  # Save new settings
                "user_agent": self.user_agent.get(),
                "proxy": self.proxy.get(),
                "timeout": self.timeout.get(),
                "retries": self.retries.get(),
                "include_content": self.include_content.get(),
                "exclude_content": self.exclude_content.get(),
                "include_url": self.include_url.get(),
                "exclude_url": self.exclude_url.get(),
                "verbose": self.verbose.get()
            }
            
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
            logger.debug("Settings saved successfully")
        except Exception as e:
            logger.error(f"Error saving settings: {e}")

    def load_settings(self):
        """Load settings from JSON file if it exists."""
        if not os.path.exists(self.settings_file):
            logger.debug("No settings file found, using defaults")
            return
        
        try:
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)
                
            # Load recent URLs
            if "recent_urls" in settings:
                self.recent_urls = deque(settings["recent_urls"], maxlen=10)
            
            # Load last used values if available
            if "last_url" in settings and settings["last_url"]:
                self.url.set(settings["last_url"])
            if "output_dir" in settings and settings["output_dir"]:
                self.output_dir.set(settings["output_dir"])
            if "max_depth" in settings:
                self.max_depth.set(settings["max_depth"])
            if "delay" in settings:
                self.delay.set(settings["delay"])
            if "max_pages" in settings:
                self.max_pages.set(settings["max_pages"])
            if "concurrent_requests" in settings:
                self.concurrent.set(settings["concurrent_requests"])
            if "include_assets" in settings:
                self.include_assets.set(settings["include_assets"])
            if "browser_mode" in settings:
                self.browser_mode.set(settings["browser_mode"])
            if "interactive_mode" in settings:
                self.interactive_mode.set(settings["interactive_mode"])
            if "doc_priority" in settings:
                self.doc_priority.set(settings["doc_priority"])
            if "user_agent" in settings:
                self.user_agent.set(settings["user_agent"])
            if "proxy" in settings:
                self.proxy.set(settings["proxy"])
            if "timeout" in settings:
                self.timeout.set(settings["timeout"])
            if "retries" in settings:
                self.retries.set(settings["retries"])
            if "include_content" in settings:
                self.include_content.set(settings["include_content"])
            if "exclude_content" in settings:
                self.exclude_content.set(settings["exclude_content"])
            if "include_url" in settings:
                self.include_url.set(settings["include_url"])
            if "exclude_url" in settings:
                self.exclude_url.set(settings["exclude_url"])
            if "verbose" in settings:
                self.verbose.set(settings["verbose"])
                # Apply verbose setting to logger
                if settings["verbose"]:
                    logger.setLevel(logging.DEBUG)
            
            logger.debug("Settings loaded successfully")
        except Exception as e:
            logger.error(f"Error loading settings: {e}")

    def add_to_recent_urls(self, url):
        """Add a URL to the recent URLs list and update the combobox."""
        if url in self.recent_urls:
            self.recent_urls.remove(url)  # Remove to add it at the front
        self.recent_urls.appendleft(url)
        self.url_combo['values'] = list(self.recent_urls)
        self.save_settings()

    def clear_recent_urls(self):
        """Clear the list of recent URLs."""
        if messagebox.askyesno("Clear History", 
                             "Are you sure you want to clear your URL history?",
                             parent=self.root):
            self.recent_urls.clear()
            self.url_combo['values'] = []
            self.save_settings()
            self.log_message("URL history cleared", logging.INFO)

    def save_preset(self):
        """Save current settings as a named preset."""
        preset_name = simpledialog.askstring(
            "Save Preset", 
            "Enter a name for this preset:",
            parent=self.root
        )
        
        if not preset_name:
            return  # User cancelled
        
        # Clean up the name to be used as a filename
        preset_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in preset_name)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        preset_file = os.path.join(self.presets_dir, f"{preset_name}_{timestamp}.json")
        
        try:
            settings = {
                "name": preset_name,
                "created": timestamp,
                "max_depth": self.max_depth.get(),
                "delay": self.delay.get(),
                "max_pages": self.max_pages.get(),
                "concurrent_requests": self.concurrent.get(),
                "include_assets": self.include_assets.get(),
                "browser_mode": self.browser_mode.get(),
                "interactive_mode": self.interactive_mode.get(),
                "doc_priority": self.doc_priority.get(),
                "user_agent": self.user_agent.get(),
                "timeout": self.timeout.get(),
                "retries": self.retries.get(),
                "include_content": self.include_content.get(),
                "exclude_content": self.exclude_content.get(),
                "include_url": self.include_url.get(),
                "exclude_url": self.exclude_url.get(),
                "verbose": self.verbose.get()
            }
            
            with open(preset_file, 'w') as f:
                json.dump(settings, f, indent=2)
            
            self.log_message(f"Preset '{preset_name}' saved successfully", logging.INFO)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save preset: {e}", parent=self.root)

    def load_preset(self):
        """Load settings from a saved preset."""
        # Get list of preset files
        preset_files = glob.glob(os.path.join(self.presets_dir, "*.json"))
        if not preset_files:
            messagebox.showinfo("No Presets", "No saved presets found.", parent=self.root)
            return
        
        # Extract names and timestamps
        presets = []
        for preset_file in preset_files:
            try:
                with open(preset_file, 'r') as f:
                    data = json.load(f)
                    name = data.get("name", os.path.basename(preset_file))
                    created = data.get("created", "Unknown")
                    presets.append((name, created, preset_file))
            except:
                # Skip invalid files
                continue
        
        if not presets:
            messagebox.showinfo("No Presets", "No valid presets found.", parent=self.root)
            return
        
        # Create a dialog to select a preset
        preset_dialog = tk.Toplevel(self.root)
        preset_dialog.title("Load Preset")
        preset_dialog.transient(self.root)
        preset_dialog.grab_set()
        
        # Center on parent
        preset_dialog.geometry("400x300")
        preset_dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - preset_dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - preset_dialog.winfo_height()) // 2
        preset_dialog.geometry(f"+{x}+{y}")
        
        # Create listbox for presets
        ttk.Label(preset_dialog, text="Select a preset to load:", padding=10).pack(anchor=tk.W)
        
        preset_frame = ttk.Frame(preset_dialog)
        preset_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Scrollbar for listbox
        scrollbar = ttk.Scrollbar(preset_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        preset_list = tk.Listbox(preset_frame, yscrollcommand=scrollbar.set, font=('Segoe UI', 10))
        preset_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=preset_list.yview)
        
        # Add presets to listbox
        for name, created, _ in presets:
            preset_list.insert(tk.END, f"{name} (Created: {created})")
        
        # Add selection commands

        # Add selection commands
        def on_load():
            selection = preset_list.curselection()
            if selection:
                idx = selection[0]
                _, _, preset_file = presets[idx]
                self._apply_preset(preset_file)
                preset_dialog.destroy()
        
        def on_delete():
            selection = preset_list.curselection()
            if selection:
                idx = selection[0]
                name, _, preset_file = presets[idx]
                if messagebox.askyesno("Delete Preset", f"Are you sure you want to delete preset '{name}'?", parent=preset_dialog):
                    try:
                        os.remove(preset_file)
                        preset_list.delete(idx)
                        del presets[idx]
                        if not presets:  # If no more presets, close dialog
                            preset_dialog.destroy()
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to delete preset: {e}", parent=preset_dialog)
        
        # Add buttons
        button_frame = ttk.Frame(preset_dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(button_frame, text="Load", command=on_load).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Delete", command=on_delete).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=preset_dialog.destroy).pack(side=tk.RIGHT, padx=5)

    def _apply_preset(self, preset_file):
        """Apply settings from a preset file."""
        try:
            with open(preset_file, 'r') as f:
                settings = json.load(f)
                
            # Apply settings
            if "max_depth" in settings:
                self.max_depth.set(settings["max_depth"])
            if "delay" in settings:
                self.delay.set(settings["delay"])
            if "max_pages" in settings:
                self.max_pages.set(settings["max_pages"])
            if "concurrent_requests" in settings:
                self.concurrent.set(settings["concurrent_requests"])
            if "include_assets" in settings:
                self.include_assets.set(settings["include_assets"])
            if "browser_mode" in settings:
                self.browser_mode.set(settings["browser_mode"])
            if "interactive_mode" in settings:
                self.interactive_mode.set(settings["interactive_mode"])
            if "doc_priority" in settings:
                self.doc_priority.set(settings["doc_priority"])
            if "user_agent" in settings:
                self.user_agent.set(settings["user_agent"])
            if "timeout" in settings:
                self.timeout.set(settings["timeout"])
            if "retries" in settings:
                self.retries.set(settings["retries"])
            if "include_content" in settings:
                self.include_content.set(settings["include_content"])
            if "exclude_content" in settings:
                self.exclude_content.set(settings["exclude_content"])
            if "include_url" in settings:
                self.include_url.set(settings["include_url"])
            if "exclude_url" in settings:
                self.exclude_url.set(settings["exclude_url"])
            if "verbose" in settings:
                self.verbose.set(settings["verbose"])
                self.toggle_verbose()  # Update logger level
            
            name = settings.get("name", os.path.basename(preset_file))
            self.log_message(f"Preset '{name}' loaded successfully", logging.INFO)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load preset: {e}", parent=self.root)

    def find_downloaded_file(self, url: str, output_dir: str) -> str:
        """
        Find a downloaded file based on the URL.
        
        Args:
            url: The URL of the file
            output_dir: The output directory
            
        Returns:
            The path to the downloaded file, or None if not found
        """
        if not output_dir or not os.path.exists(output_dir):
            return None
        
        # Extract path components from URL
        url_parts = urlparse(url)
        path = url_parts.path.strip('/')
        segments = path.split('/')
        
        # Try different ways to find the file
        potential_names = []
        
        # Simple filename from the end of URL
        if segments:
            # Last part of the URL path
            filename = segments[-1] or 'index'
            potential_names.append(filename)
        else:
            # If path is empty, use the hostname
            potential_names.append(url_parts.netloc.split('.')[0])
            potential_names.append('index')
        
        # Try with different extensions
        for base_name in potential_names:
            for ext in ['.md', '.html', '.txt', '.json']:
                # Try direct file
                direct_file = os.path.join(output_dir, base_name + ext)
                if os.path.exists(direct_file):
                    return direct_file
                
                # Try directories based on path components
                for i in range(len(segments) - 1, -1, -1):
                    # Create paths of increasing depth
                    path_part = os.path.join(*segments[:i]) if i > 0 else ''
                    file_path = os.path.join(output_dir, path_part, base_name + ext)
                    if os.path.exists(file_path):
                        return file_path
        
        # If all else fails, return the output dir to let the user find the file
        return output_dir

    def update_dashboard_timer(self):
        """Update the elapsed time display during scraping."""
        if hasattr(self, 'start_time') and self.scraper_thread and self.scraper_thread.is_alive():
            elapsed = time.time() - self.start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self.dashboard_time.config(text=f"{minutes}:{seconds:02d}")
            # Schedule next update in 1 second
            self.root.after(1000, self.update_dashboard_timer)

    def update_dashboard_counts(self, pages, assets):
        """Update the dashboard counts."""
        self.dashboard_pages_count.config(text=str(pages))
        self.dashboard_assets_count.config(text=str(assets))
        # Update doc links count based on current doc links list
        self.dashboard_doc_count.config(text=str(len(self.doc_links)))

    def add_job_to_history(self, url, pages, assets, elapsed_time):
        """Add a completed job to the history list."""
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        minutes = int(elapsed_time // 60)
        seconds = int(elapsed_time % 60)
        time_str = f"{minutes}:{seconds:02d}"
        
        self.jobs_list.insert('', 0, values=(date_str, url, pages, assets, time_str))
        
        # Keep only the most recent 50 jobs
        items = self.jobs_list.get_children()
        if len(items) > 50:
            for i in items[50:]:
                self.jobs_list.delete(i)
                
    def toggle_advanced_options(self):
        """Show or hide the advanced configuration sections."""
        if self.advanced_options_visible.get():
            # Hide sections
            self.adv_frame.grid_remove()
            self.filter_frame.grid_remove()
            # Update button text
            self.advanced_options_button.config(text="⚙️ Advanced...")
            self.advanced_options_visible.set(False)
            logger.debug("Advanced options hidden")
            
            # Move control and status frames up
            main_frame = self.container.winfo_children()[0]
            main_frame.grid_rowconfigure(3, weight=0)  # control_frame row
            main_frame.grid_rowconfigure(4, weight=1)  # status_frame row
        else:
            # Show sections
            self.adv_frame.grid(row=3, column=0, pady=10, sticky=tk.EW)
            self.filter_frame.grid(row=4, column=0, pady=10, sticky=tk.EW)
            # Update button text
            self.advanced_options_button.config(text="⚙️ Hide Advanced")
            self.advanced_options_visible.set(True)
            logger.debug("Advanced options shown")
            
            # Move control and status frames down
            main_frame = self.container.winfo_children()[0]
            main_frame.grid_rowconfigure(5, weight=0)  # Updated control_frame row
            main_frame.grid_rowconfigure(6, weight=1)  # Updated status_frame row
            # Update grid positions
            control_frame_idx = [i for i, child in enumerate(main_frame.winfo_children()) 
                                if isinstance(child, ttk.Frame) and child.winfo_class() == 'TFrame'][0]
            status_frame_idx = control_frame_idx + 1
            main_frame.winfo_children()[control_frame_idx].grid(row=5)
            main_frame.winfo_children()[status_frame_idx].grid(row=6)