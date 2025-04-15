#!/usr/bin/env python
"""
Standalone GUI launcher for Document Scraper system.

This module provides a robust entry point for launching the Document Scraper
graphical user interface. It handles dependency verification, import path
configuration, and graceful error management to ensure consistent operation
across different environments.
"""

import os
import sys
import argparse
import traceback
import logging
import importlib.util
from typing import Dict, List, Tuple, Optional, Union, Any

# Configure basic logging for standalone operation
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("docscraper_gui")

# --- Dependency Management ---

CORE_DEPENDENCIES = {
    "tkinter": "Standard Python GUI toolkit",
    "document_scraper.crawler": "Document crawler component",
    "document_scraper.scraper": "Document processing component",
    "document_scraper.utils": "Utility functions"
}

OPTIONAL_DEPENDENCIES = {
    "selenium": "Required for browser-mode crawling",
    "webdriver_manager": "Required for automated webdriver management",
    "lxml": "Recommended for improved HTML parsing"
}

def check_dependencies(install_missing: bool = False) -> Tuple[bool, Dict[str, bool], Dict[str, bool]]:
    """
    Verify that all required dependencies are available.
    
    Args:
        install_missing: Whether to attempt installing missing dependencies
        
    Returns:
        Tuple containing:
        - Overall success status
        - Dictionary of core dependency status
        - Dictionary of optional dependency status
    """
    core_status = {}
    optional_status = {}
    all_core_available = True
    
    # Check core dependencies
    for module_name, description in CORE_DEPENDENCIES.items():
        # Handle the tkinter special case
        if module_name == "tkinter":
            try:
                import tkinter
                core_status[module_name] = True
            except ImportError:
                core_status[module_name] = False
                all_core_available = False
                logger.error(f"Critical dependency missing: {module_name} - {description}")
        else:
            # Handle document_scraper components
            parts = module_name.split('.')
            try:
                if len(parts) > 1:
                    # Try importing the specific module
                    parent = __import__(parts[0], fromlist=[parts[1]])
                    getattr(parent, parts[1])
                    core_status[module_name] = True
                else:
                    # Regular single module import
                    importlib.import_module(module_name)
                    core_status[module_name] = True
            except (ImportError, AttributeError):
                core_status[module_name] = False
                all_core_available = False
                logger.error(f"Critical dependency missing: {module_name} - {description}")
                
    # Check optional dependencies
    for module_name, description in OPTIONAL_DEPENDENCIES.items():
        try:
            importlib.import_module(module_name)
            optional_status[module_name] = True
        except ImportError:
            optional_status[module_name] = False
            logger.warning(f"Optional dependency missing: {module_name} - {description}")
    
    # Install missing dependencies if requested
    if install_missing and (not all_core_available or False in optional_status.values()):
        install_dependencies(core_status, optional_status)
        # Re-check after installation
        return check_dependencies(install_missing=False)
    
    return all_core_available, core_status, optional_status

def install_dependencies(core_status: Dict[str, bool], optional_status: Dict[str, bool]) -> bool:
    """
    Attempt to install missing dependencies.
    
    Args:
        core_status: Dictionary of core dependency status
        optional_status: Dictionary of optional dependency status
        
    Returns:
        Success status of installation attempts
    """
    try:
        import subprocess
        
        # Collect missing dependencies
        to_install = []
        
        # Handle missing core dependencies
        for dep, status in core_status.items():
            if not status and dep != "tkinter":  # tkinter requires special handling
                # Convert from module path to package name
                package_name = dep.split('.')[0] if '.' in dep else dep
                if package_name == "document_scraper":
                    logger.info("Document scraper modules missing - installing package...")
                    to_install.append("document_scraper")
                else:
                    to_install.append(package_name)
        
        # Handle missing optional dependencies
        for dep, status in optional_status.items():
            if not status:
                to_install.append(dep)
                
        # Install packages if needed
        if to_install:
            logger.info(f"Installing missing dependencies: {', '.join(to_install)}")
            
            # First try using pip as a module (recommended approach)
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install"] + to_install)
                logger.info("Dependencies installed successfully using pip module")
                return True
            except subprocess.CalledProcessError:
                logger.warning("Failed to install using pip module, trying pip directly...")
                
                # Fall back to direct pip call
                try:
                    subprocess.check_call(["pip", "install"] + to_install)
                    logger.info("Dependencies installed successfully using pip")
                    return True
                except subprocess.CalledProcessError:
                    logger.error("Failed to install dependencies using pip")
                    return False
        
        return True  # No dependencies needed installation
        
    except Exception as e:
        logger.error(f"Error installing dependencies: {e}")
        return False

def handle_tkinter_missing() -> None:
    """
    Provide platform-specific instructions for installing tkinter.
    """
    print("\n" + "=" * 60)
    print("CRITICAL ERROR: tkinter module is missing")
    print("=" * 60)
    print("\ntkinter is required for the Document Scraper GUI.")
    print("\nInstallation instructions:")
    
    if sys.platform.startswith('linux'):
        print("\nFor Debian/Ubuntu based systems:")
        print("  sudo apt-get update")
        print("  sudo apt-get install python3-tk")
        print("\nFor Red Hat/Fedora based systems:")
        print("  sudo dnf install python3-tkinter")
    elif sys.platform == 'darwin':
        print("\nFor macOS (using Homebrew):")
        print("  brew install python-tk")
        print("\nAlternatively, install the official Python installer from python.org")
        print("which includes tkinter by default.")
    elif sys.platform == 'win32':
        print("\nFor Windows:")
        print("  1. Download the official Python installer from python.org")
        print("  2. During installation, ensure 'tcl/tk and IDLE' is selected")
        print("  3. If Python is already installed, consider reinstalling with this option")
    
    print("\nAfter installing tkinter, run this program again.")
    print("=" * 60)

# --- Path Configuration ---

def configure_import_paths() -> bool:
    """
    Configure system paths to ensure proper imports.
    
    Returns:
        Success status
    """
    try:
        # Get the current script directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Add the project root to path (parent of script directory)
        project_root = os.path.dirname(script_dir)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
            logger.debug(f"Added to sys.path: {project_root}")
        
        # Ensure the document_scraper package is importable
        try:
            import document_scraper
            logger.debug("document_scraper package is importable")
        except ImportError:
            # Try adding parent directory if package not found
            parent_dir = os.path.dirname(project_root)
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)
                logger.debug(f"Added to sys.path: {parent_dir}")
                
            try:
                import document_scraper
                logger.debug("document_scraper package is now importable")
            except ImportError:
                logger.error("Could not import document_scraper package")
                return False
        
        # Ensure GUI directory is importable
        gui_path = os.path.join(project_root, "doc_scrape_GUI")
        if not os.path.exists(gui_path):
            logger.error(f"GUI directory not found at {gui_path}")
            return False
            
        if gui_path not in sys.path:
            sys.path.insert(0, gui_path)
            logger.debug(f"Added to sys.path: {gui_path}")
        
        return True
    except Exception as e:
        logger.error(f"Error configuring import paths: {e}")
        traceback.print_exc()
        return False

# --- GUI Initialization and Launch ---

def create_init_file_if_missing() -> None:
    """
    Create an __init__.py file in the GUI directory if it doesn't exist.
    """
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        gui_path = os.path.join(project_root, "doc_scrape_GUI")
        
        if os.path.exists(gui_path):
            init_file = os.path.join(gui_path, "__init__.py")
            if not os.path.exists(init_file):
                logger.info(f"Creating missing __init__.py in {gui_path}")
                
                with open(init_file, 'w') as f:
                    f.write('"""GUI package for document_scraper."""\n\n__version__ = "0.3.0"\n')
    except Exception as e:
        logger.warning(f"Error creating __init__.py file: {e}")
        # Non-critical error, continue execution

def start_gui(debug_mode: bool = False) -> int:
    """
    Initialize and start the GUI application.
    
    Args:
        debug_mode: Enable debug logging and additional diagnostics
        
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    try:
        if debug_mode:
            logger.setLevel(logging.DEBUG)
            logger.debug("Debug mode enabled")
        
        # Configure paths before imports
        if not configure_import_paths():
            print("Error: Failed to configure import paths.")
            return 1
        
        # Create __init__.py if missing
        create_init_file_if_missing()
        
        # Import the GUI application
        try:
            from doc_scrape_GUI.gui import DocScraperApp
            logger.info("Successfully imported DocScraperApp")
        except ImportError as e:
            logger.error(f"Error importing DocScraperApp: {e}")
            print(f"Error: Could not load GUI components: {e}")
            print("Make sure the document_scraper package is installed correctly.")
            return 1
        
        # Create a splash screen for better user experience
        if debug_mode:
            import tkinter as tk
            splash = tk.Tk()
            splash.title("DocScraper Starting")
            splash.geometry("400x150")
            
            frame = tk.Frame(splash, padx=20, pady=20)
            frame.pack(fill=tk.BOTH, expand=True)
            
            title = tk.Label(frame, text="Document Scraper", font=("Arial", 16, "bold"))
            title.pack(pady=(0, 10))
            
            message = tk.Label(frame, text="Starting GUI...\nPlease wait.", font=("Arial", 12))
            message.pack()
            
            splash.update()
        
        # Initialize and run the application
        logger.info("Starting DocScraperApp")
        app = DocScraperApp()
        
        # Close splash screen if it exists
        if debug_mode and 'splash' in locals():
            splash.destroy()
        
        # Start the main event loop
        app.mainloop()
        logger.info("GUI closed successfully")
        
        return 0
    except Exception as e:
        logger.error(f"Error starting GUI: {e}")
        traceback.print_exc()
        
        print(f"\nError: Failed to start the GUI: {e}")
        print("Check logs for more details.")
        
        return 1

# --- Main Entry Point ---

def main() -> int:
    """
    Main entry point for the GUI launcher.
    
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Launch the Document Scraper GUI")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--install-deps", action="store_true", help="Auto-install missing dependencies")
    args = parser.parse_args()
    
    try:
        # Check dependencies first
        core_available, core_status, optional_status = check_dependencies(install_missing=args.install_deps)
        
        # Handle missing tkinter specially (can't be pip installed)
        if not core_status.get("tkinter", False):
            handle_tkinter_missing()
            return 1
            
        # Check if any critical document_scraper components are missing
        if not core_available:
            missing_components = [comp for comp, status in core_status.items() if not status]
            print(f"\nError: Missing critical components: {', '.join(missing_components)}")
            print("Please ensure the document_scraper package is installed correctly.")
            
            if not args.install_deps:
                print("\nTry running with --install-deps to automatically install missing dependencies:")
                print(f"  {sys.executable} {sys.argv[0]} --install-deps")
            
            return 1
        
        # Alert about missing optional dependencies
        missing_optionals = [dep for dep, status in optional_status.items() if not status]
        if missing_optionals:
            print("\nWarning: Some optional features may be limited without these dependencies:")
            for dep in missing_optionals:
                print(f"  - {dep}: {OPTIONAL_DEPENDENCIES[dep]}")
            
            if not args.install_deps:
                print("\nTip: Run with --install-deps to automatically install these dependencies.")
            
            # Add a slight delay to ensure message is read
            import time
            time.sleep(2)
        
        # Start the GUI
        return start_gui(debug_mode=args.debug)
        
    except Exception as e:
        print(f"Unexpected error: {e}")
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())