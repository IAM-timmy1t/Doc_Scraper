@echo off
echo Starting Document Scraper GUI...
python doc_scrape_GUI/run_gui.py
if errorlevel 1 (
    echo Failed to start GUI. See error message above.
    pause
    exit /b 1
) 