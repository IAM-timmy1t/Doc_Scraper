# Documentation Scraper User Guide

## Table of Contents
1. [Installation](#installation)
2. [Basic Commands](#basic-commands)
3. [Graphical User Interface](#graphical-user-interface)
4. [Advanced Configuration](#advanced-configuration)
5. [Troubleshooting](#troubleshooting)

## Installation
```bash
pip install -e .
```

## Basic Commands
```bash
# Download documentation
python -m document_scraper.cli download --url https://example.com/docs --output ./docs

# Update existing docs
python -m document_scraper.cli update --url https://example.com/docs --output ./existing_docs
```

## Graphical User Interface
Document Scraper includes a user-friendly GUI that makes it easy to configure and run scraping jobs.

There are multiple ways to launch the GUI:

```bash
# Option 1: Launch the GUI directly through the CLI
python -m document_scraper.cli gui

# Option 2: Run CLI without arguments to choose between GUI and CLI mode
python -m document_scraper.cli

# Option 3: Use the dedicated GUI launcher script
python doc_scrape_GUI/run_gui.py

# Option 4 (Windows): Use the batch file
run_gui.bat
```

If you're experiencing issues with the GUI not appearing:
1. Check for error messages in the terminal/console
2. Make sure tkinter is properly installed with your Python
3. Try running the test GUI script to verify tkinter works:
   ```bash
   python test_gui.py
   ```

The GUI provides access to all scraper settings with a simple form interface:
- Set the documentation URL and output directory
- Configure crawl depth and delay settings
- Apply content and URL filters
- Enable special options like browser emulation and asset downloading

## Advanced Configuration
See full configuration options in [CONFIGURATION.md](./CONFIGURATION.md)

## Troubleshooting
Common issues and solutions:
- **Timeout errors**: Increase `--timeout` value
- **429 errors**: Increase `--delay` between requests
- **Conversion issues**: Check skip list in `config/skip_urls.txt`
