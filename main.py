"""
Command-line interface for the document_scraper module.

This module serves as the main entry point for the Document Scraper system,
providing a comprehensive command-line interface with interactive options,
progress reporting, and intelligent documentation detection capabilities.
"""

import os
import sys
import click
import logging
import colorama
import webbrowser
import subprocess
import traceback
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from urllib.parse import urlparse

# Import core components using the new architecture
from document_scraper.crawler import Crawler
from document_scraper.scraper import DocumentationScraper
from document_scraper.utils import (
    is_valid_url, 
    ensure_directory_exists,
    validate_url,
    setup_logging,
    discover_documentation_sections,
    prompt_documentation_selection,
    analyze_documentation_structure
)

# Initialize colorama for cross-platform color support
colorama.init()

# Configure logging
logger = logging.getLogger("document_scraper")


#---------------------------------------------------------------------------
# Command-Line Interface
#---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.version_option(version="0.3.0")
@click.pass_context
def cli(ctx):
    """Interactive documentation scraper with intelligent discovery."""
    if ctx.invoked_subcommand is None:
        click.clear()
        click.echo(click.style(r"""
  ____             _____                                 
 |  _ \  ___   ___|___ / _ __  ___ ___  ___ _ __ ___ 
 | | | |/ _ \ / __| |_ \| '__\/ __/ __|/ __| '__/ _ \
 | |_| | (_) | (__ ___) | |  \__ \__ \ (__| | |  __/
 |____/ \___/ \___|____/|_|  |___/___/\___|_|  \___|
""", fg="bright_blue"))
        
        click.echo(click.style("Documentation Scraper v0.3 - Interactive Mode\n", fg="bright_green"))
        click.echo("This tool helps you download and organize documentation websites.")
        click.echo("\nKey features of the enhanced architecture:")
        click.echo(click.style("  • Documentation prioritization", fg="bright_white"))
        click.echo(click.style("  • Intelligent link categorization", fg="bright_white"))
        click.echo(click.style("  • Interactive auxiliary content selection", fg="bright_white"))
        
        click.echo("\nTo get started, run one of these commands:")
        click.echo(click.style("  docscraper download", fg="bright_green") + " - Interactive documentation download")
        click.echo(click.style("  docscraper discover", fg="bright_yellow") + " - Preview available documentation sections")
        click.echo(click.style("  docscraper gui", fg="bright_cyan") + " - Launch the graphical user interface")
        click.echo(click.style("  docscraper --help", fg="bright_white") + " - Show all available options")


@cli.command(name="discover")
@click.option('--url', '-u',
              help='URL of the documentation website',
              callback=validate_url,
              prompt='\n📖 Enter documentation website URL to analyze')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed processing information')
def discover(url, verbose):
    """
    Preview available documentation sections with interactive exploration.
    
    This command analyzes the structure of a documentation website and provides
    information about available sections, link categorization, and content organization.
    """
    setup_logging(verbose)
    click.echo(f"\n🔍 Analyzing documentation structure at {url}")
    
    # Initialize a crawler just for discovery (no downloading)
    crawler = Crawler(
        base_url=url,
        max_depth=1,  # Limited depth for faster analysis
        delay=0.5,
        concurrent_requests=2,
        browser_mode=True,  # Enable browser mode for better JavaScript handling
        verbose=verbose
    )
    
    # Display discovery progress
    with click.progressbar(
        length=100,
        label="Analyzing structure",
        show_eta=True,
        show_percent=True
    ) as bar:
        # Perform initial page load
        html_content, links = crawler.download_url(url)
        bar.update(50)
        
        if html_content and links:
            # Get categorized links
            doc_links = links.get('doc', [])
            aux_links = links.get('aux', [])
            external_links = links.get('external', [])
            asset_links = links.get('asset', [])
            
            # Analyze documentation structure
            analysis = analyze_documentation_structure(doc_links)
            bar.update(50)
        else:
            click.echo(click.style("\n❌ Error: Failed to retrieve documentation structure.", fg="red"))
            sys.exit(1)
    
    # Display results
    click.echo(click.style("\n📊 Documentation Structure Analysis", fg="bright_blue"))
    click.echo(f"• Base URL: {click.style(url, fg='bright_green')}")
    click.echo(f"• Documentation Links: {click.style(str(len(doc_links)), fg='bright_green')}")
    click.echo(f"• Auxiliary Links: {click.style(str(len(aux_links)), fg='yellow')}")
    click.echo(f"• External Links: {click.style(str(len(external_links)), fg='cyan')}")
    click.echo(f"• Asset Links: {click.style(str(len(asset_links)), fg='magenta')}")
    
    # Show sections if available
    if analysis['sections']:
        click.echo(click.style("\n📁 Documentation Sections:", fg="bright_blue"))
        for section, count in sorted(analysis['sections'].items(), key=lambda x: x[1], reverse=True):
            click.echo(f"• {section}: {count} pages")
    
    # Show interactive options
    click.echo(click.style("\n🛠️ Available Actions:", fg="bright_blue"))
    options = [
        ("Download all documentation", "docscraper download --url " + url),
        ("Export link structure to file", "Export to JSON"),
        ("View in browser", "Open in browser"),
        ("Launch GUI", "docscraper gui")
    ]
    
    for i, (action, details) in enumerate(options, 1):
        click.echo(f"{i}. {click.style(action, fg='bright_white')}: {details}")
    
    choice = click.prompt(
        "\nSelect an action (or press Enter to exit)",
        type=click.Choice(['1', '2', '3', '4', '']),
        default=""
    )
    
    if choice == '1':
        # Launch download command
        click.echo("\nStarting download process...")
        os.system(f"docscraper download --url {url}")
    elif choice == '2':
        # Export links to file
        filename = click.prompt("Enter filename to save", default="doc_structure.json")
        
        import json
        with open(filename, 'w') as f:
            json.dump({
                "url": url,
                "timestamp": datetime.now().isoformat(),
                "documentation_links": doc_links,
                "auxiliary_links": aux_links,
                "external_links": external_links,
                "asset_links": asset_links,
                "structure_analysis": analysis
            }, f, indent=2)
        
        click.echo(click.style(f"✓ Exported to {filename}", fg="green"))
    elif choice == '3':
        # Open in browser
        click.echo(f"Opening {url} in browser...")
        webbrowser.open(url)
    elif choice == '4':
        # Launch GUI
        click.echo("Launching GUI...")
        os.system("docscraper gui")


@cli.command(name="download")
@click.option('--url', '-u',
              help='URL of the documentation website',
              callback=validate_url,
              prompt='\n📖 Enter documentation website URL to download')
@click.option('--output', '-o', default='./docs', help='Output directory',
              type=click.Path(file_okay=False, resolve_path=True))
@click.option('--doc-priority/--no-doc-priority',
              help='Prioritize documentation links (recommended)',
              default=True, show_default=True)
@click.option('--interactive/--no-interactive',
              help='Enable interactive mode for auxiliary content selection',
              default=True, show_default=True)
@click.option('--format',
              type=click.Choice(['markdown', 'html', 'text', 'json'], case_sensitive=False),
              default='markdown',
              prompt='\n📄 Output format (markdown, html, text, json)?')
@click.option('--depth', '-d',
              type=click.IntRange(1, 10),
              default=3,
              prompt='\n📊 Maximum link depth to follow (1-10)?')
@click.option('--concurrency', '-c',
              type=click.IntRange(1, 10),
              default=5,
              prompt='\n⚡ Concurrent downloads (1-10)?')
@click.option('--delay',
              help='Delay between requests in seconds',
              default=0.2, show_default=True, type=float)
@click.option('--max-pages', '-m',
              help='Maximum number of pages to download (0 = unlimited)',
              default=0, show_default=True, type=int)
@click.option('--include-assets/--no-assets',
              help='Download assets (images, CSS, JS)',
              default=False, show_default=True)
@click.option('--browser-mode/--no-browser-mode', '-b',
              help='Enable browser emulation for JavaScript-heavy sites',
              default=True, show_default=True)
@click.option('--user-agent',
              help='Custom user agent string',
              default=None)
@click.option('--proxy',
              help='HTTP/HTTPS proxy URL (e.g., http://user:pass@host:port)',
              default=None)
@click.option('--timeout',
              help='Request timeout in seconds',
              default=30, show_default=True, type=int)
@click.option('--retries',
              help='Number of retry attempts for failed downloads',
              default=3, show_default=True, type=int)
@click.option('--include-content',
              help='Only download pages containing this text pattern (regex)',
              multiple=True)
@click.option('--exclude-content',
              help='Skip pages containing this text pattern (regex)',
              multiple=True)
@click.option('--include-url',
              help='Only download URLs matching this pattern (regex)',
              multiple=True)
@click.option('--exclude-url',
              help='Skip URLs matching this pattern (regex)',
              multiple=True)
@click.option('--verbose', '-v', is_flag=True, help='Show detailed processing information')
def download(url, output, doc_priority, interactive, format, depth, concurrency, 
             delay, max_pages, include_assets, browser_mode, user_agent, proxy, 
             timeout, retries, include_content, exclude_content, include_url, 
             exclude_url, verbose):
    """
    Download documentation with intelligent crawling and content organization.
    
    This command downloads documentation from a website with a focus on documentation-related
    content first, and provides options for selectively including auxiliary content.
    """
    setup_logging(verbose)

    # Ensure output directory exists
    os.makedirs(output, exist_ok=True)

    # Convert max_pages=0 to None for unlimited
    max_pages_limit = None if max_pages == 0 else max_pages

    # Prepare proxy dictionary
    proxies = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    # --- Configuration Summary ---
    click.echo(click.style("\n✨ Scraper Configuration:", fg="bright_blue"))
    click.echo(f"• URL: {click.style(url, fg='bright_green')}")
    click.echo(f"• Output: {click.style(output, fg='bright_green')}")
    click.echo(f"• Format: {format}")
    click.echo(f"• Documentation Priority: {'Enabled' if doc_priority else 'Disabled'}")
    click.echo(f"• Interactive Mode: {'Enabled' if interactive else 'Disabled'}")
    click.echo(f"• Depth: {depth}")
    click.echo(f"• Concurrency: {concurrency}")
    click.echo(f"• Delay: {delay}s")
    click.echo(f"• Max Pages: {'Unlimited' if max_pages_limit is None else max_pages_limit}")
    click.echo(f"• Include Assets: {'Yes' if include_assets else 'No'}")
    click.echo(f"• Browser Mode: {'Enabled' if browser_mode else 'Disabled'}")
    click.echo(f"• Timeout: {timeout}s")
    click.echo(f"• Retries: {retries}")
    if user_agent: click.echo(f"• User Agent: {user_agent}")
    if proxy: click.echo(f"• Proxy: {proxy}")
    if include_content: click.echo(f"• Include Content Patterns: {', '.join(include_content)}")
    if exclude_content: click.echo(f"• Exclude Content Patterns: {', '.join(exclude_content)}")
    if include_url: click.echo(f"• Include URL Patterns: {', '.join(include_url)}")
    if exclude_url: click.echo(f"• Exclude URL Patterns: {', '.join(exclude_url)}")
    click.echo("")  # Newline for spacing

    if not click.confirm("Continue with these settings?", default=True):
        click.echo("Download cancelled.")
        return

    # --- Initialize Scraper ---
    scraper = DocumentationScraper(
        base_url=url,
        output_dir=output,
        max_depth=depth,
        delay=delay,
        max_pages=max_pages_limit,
        concurrent_requests=concurrency,
        include_assets=include_assets,
        browser_mode=browser_mode,
        output_format=format,
        user_agent=user_agent,
        proxies=proxies,
        timeout=timeout,
        retries=retries,
        content_include_patterns=list(include_content) if include_content else None,
        content_exclude_patterns=list(exclude_content) if exclude_content else None,
        url_include_patterns=list(include_url) if include_url else None,
        url_exclude_patterns=list(exclude_url) if exclude_url else None,
        verbose=verbose
    )

    # --- Start Download ---
    click.echo(f"\n📥 Starting documentation download from {url}...")
    
    # Create progress bar
    with click.progressbar(
        length=100 if max_pages_limit is None else max_pages_limit,
        label="Downloading documentation",
        show_eta=True,
        show_percent=True,
        item_show_func=lambda item: f"Pages: {scraper.pages_downloaded}"
    ) as bar:
        # Define a callback to update the progress bar
        def progress_callback(url, current, total):
            if total:
                bar.update(current / total * 100 if max_pages_limit is None else 1)
            else:
                # Just a small increment if total is unknown
                bar.update(0.1)
        
        # Set the callback
        scraper.crawler.progress_callback = progress_callback
        
        try:
            # Start scraping with the specified options
            total_pages_downloaded, total_assets_downloaded = scraper.crawl(
                interactive=interactive
            )
            
            # Final update to ensure bar completes
            bar.update(100)
            
        except KeyboardInterrupt:
            click.echo(click.style("\n⚠️ Download interrupted by user", fg="yellow"))
            sys.exit(130)
        except Exception as e:
            logger.error(f"An error occurred during download: {e}", exc_info=verbose)
            click.echo(click.style(f"\n❌ Download failed: {e}", fg="red"))
            if verbose:
                click.echo(traceback.format_exc())
            sys.exit(1)

    # --- Success Message ---
    click.echo(click.style("\n✅ Download completed!", fg="bright_green"))
    click.echo(f"• Downloaded {total_pages_downloaded} documentation pages")
    if include_assets:
        click.echo(f"• Downloaded {total_assets_downloaded} assets")
    click.echo(f"• Saved to {os.path.abspath(output)}")

    # --- Show failures if any ---
    if scraper.failed_urls:
        click.echo(click.style(f"\n⚠️ Failed to download {len(scraper.failed_urls)} URLs:", fg="yellow"))
        # Show first few failures
        for i, (url, error) in enumerate(list(scraper.failed_urls.items())[:5]):
            click.echo(f"  • {url}: {error}")
        
        if len(scraper.failed_urls) > 5:
            click.echo(f"  • ... and {len(scraper.failed_urls) - 5} more.")

    # --- Offer to open output directory ---
    if click.confirm('\nWould you like to open the downloaded documentation folder?'):
        try:
            if sys.platform == "win32":
                os.startfile(output)
            elif sys.platform == "darwin":
                subprocess.run(["open", output], check=True)
            else:
                subprocess.run(["xdg-open", output], check=True)
        except Exception as e:
            logger.warning(f"Could not open output directory automatically: {e}")
            click.echo(f"Could not open automatically. Please browse to: {output}")


@cli.command(name="gui")
@click.option('--debug', is_flag=True, help="Run GUI in debug mode with additional logging")
def launch_gui(debug):
    """
    Launch the graphical user interface for Document Scraper.
    
    Provides a user-friendly interface with visual link categorization,
    interactive crawling options, and comprehensive progress reporting.
    """
    try:
        # Configure logging for GUI mode
        if debug:
            setup_logging(verbose=True, log_file="gui_debug.log")
        
        # Find GUI directory
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        gui_path = os.path.join(script_dir, "doc_scrape_GUI")
        
        click.echo(f"Starting Document Scraper GUI...")
        
        # Add GUI directory to path
        if gui_path not in sys.path:
            sys.path.insert(0, script_dir)
        
        try:
            # Import and start the GUI
            from doc_scrape_GUI.gui import DocScraperApp
            click.echo("GUI components loaded successfully")
            
            # Create splash screen if in debug mode
            if debug:
                import tkinter as tk
                splash = tk.Tk()
                splash.title("DocScraper Starting")
                splash.geometry("300x100")
                label = tk.Label(splash, text="DocScraper GUI is starting...\nPlease wait.", font=("Arial", 12))
                label.pack(padx=20, pady=20)
                splash.update()
                
                app = DocScraperApp()
                
                splash.destroy()
                app.mainloop()
            else:
                # Regular startup
                app = DocScraperApp()
                app.mainloop()
                
        except ImportError as e:
            click.echo(click.style(f"Error: Could not load GUI components: {e}", fg="red"))
            click.echo("Make sure the 'doc_scrape_GUI' directory exists at the project root.")
            click.echo("\nAlternative: Use the command-line interface with 'docscraper download'")
            sys.exit(1)
            
    except Exception as e:
        click.echo(click.style(f"Error launching GUI: {e}", fg="red"))
        if debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


#---------------------------------------------------------------------------
# Main Entry Point
#---------------------------------------------------------------------------

def main():
    """
    Entry point for the Document Scraper command-line interface.
    
    Provides intelligent selection of interface mode based on provided arguments
    and offers guided experience for first-time users.
    """
    # If no arguments provided, offer to launch the GUI or show help
    if len(sys.argv) == 1:
        click.echo(click.style("\n🚀 Welcome to Document Scraper!", fg="bright_blue"))
        click.echo("\nThis tool helps you download and organize documentation websites.")
        click.echo("It intelligently prioritizes documentation content and provides")
        click.echo("structured organization of the downloaded content.")
        
        click.echo(click.style("\nHow would you like to use Document Scraper?", fg="bright_yellow"))
        click.echo("1. " + click.style("Graphical User Interface", fg="bright_green") + 
                  " - User-friendly GUI with visual feedback")
        click.echo("2. " + click.style("Command Line Interface", fg="bright_cyan") + 
                  " - Powerful CLI with advanced options")
        click.echo("3. " + click.style("Interactive Discovery", fg="bright_magenta") + 
                  " - Analyze documentation structure")
        
        choice = click.prompt(
            "\nSelect option",
            type=click.Choice(['1', '2', '3']), 
            default='1'
        )
        
        if choice == '1':
            # Launch GUI
            sys.argv = [sys.argv[0], "gui"]
        elif choice == '2':
            # Launch CLI download wizard
            sys.argv = [sys.argv[0], "download"]
        else:
            # Launch interactive discovery
            sys.argv = [sys.argv[0], "discover"]
    
    # Start CLI with the provided/modified arguments
    cli()


if __name__ == "__main__":
    main()