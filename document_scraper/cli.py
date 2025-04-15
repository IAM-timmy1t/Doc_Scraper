"""
Enhanced Command-line interface for document scraping with intelligent
documentation prioritization and interactive features.

This module provides a sophisticated command-line interface for the document
scraper system, with specialized commands for documentation discovery,
selective downloading, and interactive content exploration.
"""
import os
import sys
import time
import click
import logging
import requests
import colorama
import webbrowser
import subprocess
import threading
from datetime import datetime
from tqdm import tqdm
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Any, Union, Tuple, Set
from urllib.parse import urlparse, urljoin

# Enhanced import handling for both direct and package execution
try:
    # Package mode imports
    if __package__ or "." in __name__:
        from .utils import (
            is_valid_url,
            validate_url, 
            setup_logging,
            prompt_documentation_selection,
            discover_documentation_sections,
            analyze_documentation_structure,
            categorize_url
        )
        from .crawler import Crawler
        from .scraper import DocumentationScraper
    else:
        # Direct execution mode - add project root to path
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from document_scraper.utils import (
            is_valid_url,
            validate_url, 
            setup_logging,
            prompt_documentation_selection,
            discover_documentation_sections,
            analyze_documentation_structure,
            categorize_url
        )
        from document_scraper.crawler import Crawler
        from document_scraper.scraper import DocumentationScraper
except ImportError as e:
    print(f"Import error: {str(e)}")
    raise

# Initialize colorama for cross-platform color support
colorama.init()

# Configure logging
logger = logging.getLogger("document_scraper")

#---------------------------------------------------------------------------
# Interactive Workflow Functions
#---------------------------------------------------------------------------

def explore_documentation_structure(url: str, verbose: bool = False) -> Dict[str, Any]:
    """
    Perform a comprehensive analysis of documentation structure.
    
    Args:
        url: The URL to analyze
        verbose: Whether to enable verbose logging
        
    Returns:
        Dictionary with analysis results including categorized links
    """
    logger.info(f"Exploring documentation structure at {url}")
    
    # Create a crawler instance configured for exploration mode
    crawler = Crawler(
        base_url=url,
        max_depth=1,
        delay=0.2,
        concurrent_requests=3,
        browser_mode=True,  # Enable browser mode for better JavaScript handling
        timeout=30,
        retries=2
    )
    
    # Get initial page content and links
    html_content, links = crawler.download_url(url)
    
    if not html_content or not links:
        logger.error(f"Failed to retrieve content from {url}")
        return {
            "status": "error",
            "message": "Failed to retrieve content"
        }
    
    # Extract and categorize links
    categorized_links = {
        "doc": links.get("doc", []),
        "aux": links.get("aux", []),
        "external": links.get("external", []),
        "asset": links.get("asset", [])
    }
    
    # Analyze documentation structure
    structure_analysis = analyze_documentation_structure(categorized_links["doc"])
    
    # Prepare result
    result = {
        "status": "success",
        "base_url": url,
        "timestamp": datetime.now().isoformat(),
        "links": categorized_links,
        "structure": structure_analysis,
        "stats": {
            "total_links": sum(len(links) for links in categorized_links.values()),
            "doc_links": len(categorized_links["doc"]),
            "aux_links": len(categorized_links["aux"]),
            "external_links": len(categorized_links["external"]),
            "asset_links": len(categorized_links["asset"])
        }
    }
    
    logger.info(f"Found {result['stats']['doc_links']} documentation links and {result['stats']['aux_links']} auxiliary links")
    
    return result

def select_documentation_sections(structure: Dict[str, Any]) -> List[str]:
    """
    Present the documentation structure and allow selection of sections.
    
    Args:
        structure: Result from explore_documentation_structure
        
    Returns:
        List of selected section URLs
    """
    click.echo(click.style("\nDocumentation Structure:", fg="bright_blue"))
    
    # Get categorized links
    doc_links = structure.get("links", {}).get("doc", [])
    aux_links = structure.get("links", {}).get("aux", [])
    
    # Display documentation sections
    sections = {}
    section_idx = 1
    
    # Group documentation links by path component
    for url in doc_links:
        path = urlparse(url).path.strip("/")
        if not path:
            section = "Main"
        else:
            section = path.split("/")[0].replace("-", " ").replace("_", " ").title()
        
        if section not in sections:
            sections[section] = []
        sections[section].append(url)
    
    # Display sections
    click.echo(click.style("\nAvailable Documentation Sections:", fg="bright_green"))
    displayed_sections = {}
    for section_name, urls in sorted(sections.items()):
        click.echo(f"{section_idx}. {click.style(section_name, fg='green')} ({len(urls)} pages)")
        displayed_sections[section_idx] = (section_name, urls)
        section_idx += 1
    
    # Display auxiliary content
    if aux_links:
        click.echo(click.style("\nAuxiliary Content:", fg="yellow"))
        click.echo(f"{section_idx}. {click.style('Auxiliary Pages', fg='yellow')} ({len(aux_links)} pages)")
        displayed_sections[section_idx] = ("Auxiliary", aux_links)
    
    # Prompt for selection
    click.echo(click.style("\nSelect sections to download:", fg="bright_white"))
    click.echo("Enter section numbers (comma-separated), 'all' for everything, or 'docs' for documentation only")
    
    selection = click.prompt("Selection", default="docs")
    
    if selection.lower() == "all":
        # Return all links
        return doc_links + aux_links
    elif selection.lower() == "docs":
        # Return only documentation links
        return doc_links
    else:
        # Parse selected sections
        selected_urls = []
        try:
            selected_indices = [int(idx.strip()) for idx in selection.split(",")]
            for idx in selected_indices:
                if idx in displayed_sections:
                    selected_urls.extend(displayed_sections[idx][1])
        except ValueError:
            click.echo(click.style("Invalid selection. Defaulting to documentation only.", fg="red"))
            return doc_links
        
        return selected_urls

def show_progress_spinner(stop_event: threading.Event, message: str):
    """
    Display a spinner animation with a message.
    
    Args:
        stop_event: Event to signal when to stop the spinner
        message: Message to display with the spinner
    """
    symbols = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    i = 0
    while not stop_event.is_set():
        symbol = symbols[i % len(symbols)]
        click.echo(f"\r{symbol} {message}", nl=False)
        i += 1
        time.sleep(0.1)
    
    # Clear the line when done
    click.echo("\r" + " " * (len(message) + 2) + "\r", nl=False)

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
        click.echo("This tool helps you download and organize documentation websites with:")
        click.echo(f"• {click.style('Intelligent prioritization', fg='bright_yellow')} of documentation content")
        click.echo(f"• {click.style('Interactive selection', fg='bright_yellow')} of content to download")
        click.echo(f"• {click.style('Structured organization', fg='bright_yellow')} of documentation files")
        
        click.echo("\nTo get started, run one of these commands:")
        click.echo(click.style("  docscraper download", fg="bright_green") + 
                   " - Interactive documentation download")
        click.echo(click.style("  docscraper discover", fg="bright_yellow") + 
                   " - Preview available documentation sections")
        click.echo(click.style("  docscraper gui", fg="bright_cyan") + 
                   " - Launch the graphical user interface")
        click.echo(click.style("  docscraper --help", fg="bright_white") + 
                   " - Show all available options")

@cli.command(name="discover")
@click.option('--url', '-u',
              help='URL of the documentation website',
              callback=validate_url,
              prompt='\n📖 Enter documentation website URL to analyze')
@click.option('--output', '-o',
              help='Save analysis to JSON file',
              type=click.Path(file_okay=True, dir_okay=False),
              default=None)
@click.option('--verbose', '-v', is_flag=True, help='Show detailed processing information')
def discover(url, output, verbose):
    """
    Preview available documentation sections with interactive Q&A.
    
    This command analyzes a documentation website to discover its structure,
    categorize links, and provide insights about the organization of content.
    It helps you understand what's available before starting a download.
    """
    setup_logging(verbose)
    click.echo(f"\n🔍 Analyzing documentation structure at {url}")
    
    # Start a spinner for visual feedback
    stop_spinner = threading.Event()
    spinner_thread = threading.Thread(
        target=show_progress_spinner,
        args=(stop_spinner, "Analyzing documentation structure...")
    )
    spinner_thread.daemon = True
    spinner_thread.start()
    
    try:
        # Analyze the documentation structure
        structure = explore_documentation_structure(url, verbose)
        
        # Stop the spinner
        stop_spinner.set()
        spinner_thread.join()
        
        # Check if analysis was successful
        if structure.get("status") != "success":
            click.echo(click.style(f"\n❌ {structure.get('message', 'Analysis failed')}", fg="red"))
            return
        
        # Display the results
        click.echo("\n" + "=" * 60)
        click.echo(click.style("📋 Documentation Structure Analysis", fg="bright_blue"))
        click.echo("=" * 60)
        
        click.echo(f"\n• Base URL: {click.style(url, fg='bright_green')}")
        click.echo(f"• Documentation Links: {click.style(str(structure['stats']['doc_links']), fg='bright_green')}")
        click.echo(f"• Auxiliary Links: {click.style(str(structure['stats']['aux_links']), fg='yellow')}")
        click.echo(f"• External Links: {click.style(str(structure['stats']['external_links']), fg='cyan')}")
        click.echo(f"• Asset Links: {click.style(str(structure['stats']['asset_links']), fg='magenta')}")
        
        # Show document sections if available
        if structure.get("structure", {}).get("sections"):
            click.echo(click.style("\n📂 Documentation Sections:", fg="bright_blue"))
            for section, count in sorted(structure["structure"]["sections"].items(), 
                                          key=lambda x: x[1], reverse=True):
                click.echo(f"• {section}: {count} pages")
        
        # Save to file if requested
        if output:
            import json
            with open(output, 'w', encoding='utf-8') as f:
                json.dump(structure, f, indent=2)
            click.echo(click.style(f"\n✓ Analysis saved to {output}", fg="green"))
        
        # Interactive options
        if structure['stats']['doc_links'] > 0:
            if click.confirm("\nWould you like to download this documentation now?"):
                # Prepare arguments for the download command
                args = ["docscraper", "download", "--url", url]
                
                if verbose:
                    args.append("--verbose")
                
                # Call the download command
                result = subprocess.run(args)
                if result.returncode != 0:
                    click.echo(click.style("\n❌ Download failed", fg="red"))
        
    except Exception as e:
        # Stop the spinner
        stop_spinner.set()
        if spinner_thread.is_alive():
            spinner_thread.join()
        
        logger.error(f"Error during discovery: {e}", exc_info=True)
        click.echo(click.style(f"\n❌ Analysis failed: {e}", fg="red"))

@cli.command(name="download")
@click.option('--url', '-u',
              help='URL of the documentation website',
              callback=validate_url,
              prompt='\n📖 Enter documentation website URL to download')
@click.option('--output', '-o', 
              help='Output directory',
              type=click.Path(file_okay=False),
              default=None)
@click.option('--mode',
              type=click.Choice(['auto', 'interactive', 'selective'], case_sensitive=False),
              default='interactive',
              help='Download mode (auto=all docs, interactive=prompt for sections, selective=choose specific URLs)')
@click.option('--doc-priority/--no-doc-priority',
              help='Prioritize documentation links over auxiliary content',
              default=True)
@click.option('--format',
              type=click.Choice(['markdown', 'html', 'text', 'json'], case_sensitive=False),
              default='markdown',
              help='Output format for downloaded content')
@click.option('--depth', '-d',
              type=click.IntRange(1, 10),
              default=3,
              help='Maximum link depth to follow (1-10)')
@click.option('--concurrency', '-c',
              type=click.IntRange(1, 10),
              default=5,
              help='Concurrent downloads (1-10)')
@click.option('--delay',
              help='Delay between requests in seconds',
              default=0.2, show_default=True, type=float)
@click.option('--max-pages', '-m',
              help='Maximum number of pages to download (0 = unlimited)',
              default=0, show_default=True, type=int)
@click.option('--include-assets/--no-assets',
              help='Download assets (images, CSS, JS)',
              default=False, show_default=True)
@click.option('--browser-mode/--no-browser',
              help='Enable browser emulation (needed for JavaScript-heavy sites)',
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
def download(url, output, mode, doc_priority, format, depth, concurrency, delay, 
             max_pages, include_assets, browser_mode, user_agent, proxy, 
             timeout, retries, include_content, exclude_content, 
             include_url, exclude_url, verbose):
    """
    Download documentation with intelligent prioritization and organization.
    
    This command provides a sophisticated workflow for downloading documentation
    websites with intelligent content categorization, prioritization of documentation
    content, and interactive selection of sections to download.
    """
    setup_logging(verbose)
    
    # Resolve output directory
    if not output:
        # Extract domain for naming
        domain = urlparse(url).netloc
        domain_parts = domain.split('.')
        if len(domain_parts) > 1:
            site_name = domain_parts[-2]  # e.g. "example" from "docs.example.com"
        else:
            site_name = domain
        
        # Default to ./docs/{site_name}_docs
        output = os.path.join(".", "docs", f"{site_name}_docs")
    
    # Ensure output directory exists
    os.makedirs(output, exist_ok=True)
    
    # Convert max_pages=0 to None for unlimited
    max_pages_limit = None if max_pages == 0 else max_pages
    
    # Prepare proxy dictionary
    proxies = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}
    
    # Display configuration header
    click.echo(click.style("\n✨ Scraper Configuration:", fg="bright_blue"))
    click.echo(f"• URL: {click.style(url, fg='bright_green')}")
    click.echo(f"• Output: {click.style(output, fg='bright_green')}")
    click.echo(f"• Mode: {click.style(mode, fg='bright_cyan')}")
    click.echo(f"• Format: {format}")
    click.echo(f"• Doc Priority: {'Yes' if doc_priority else 'No'}")
    click.echo(f"• Depth: {depth}")
    click.echo(f"• Concurrency: {concurrency}")
    click.echo(f"• Delay: {delay}s")
    click.echo(f"• Browser Mode: {'Enabled' if browser_mode else 'Disabled'}")
    
    # Show advanced options if provided
    advanced_options = []
    if max_pages_limit is not None:
        advanced_options.append(f"Max Pages: {max_pages_limit}")
    if include_assets:
        advanced_options.append("Include Assets: Yes")
    if user_agent:
        advanced_options.append(f"User Agent: Custom")
    if proxy:
        advanced_options.append(f"Proxy: Yes")
    if include_content:
        advanced_options.append(f"Content Filters: Yes")
    if include_url or exclude_url:
        advanced_options.append(f"URL Filters: Yes")
    
    if advanced_options:
        click.echo(click.style("\nAdvanced Options:", fg="bright_blue"))
        for option in advanced_options:
            click.echo(f"• {option}")
    
    # Interactive mode - discover and select content
    start_urls = []
    
    if mode == 'interactive' or mode == 'selective':
        click.echo(click.style("\n🔍 Analyzing documentation structure...", fg="bright_yellow"))
        
        # Start a spinner for visual feedback
        stop_spinner = threading.Event()
        spinner_thread = threading.Thread(
            target=show_progress_spinner,
            args=(stop_spinner, "Discovering documentation structure...")
        )
        spinner_thread.daemon = True
        spinner_thread.start()
        
        try:
            # Analyze the documentation structure
            structure = explore_documentation_structure(url, verbose)
            
            # Stop the spinner
            stop_spinner.set()
            spinner_thread.join()
            
            if structure.get("status") != "success":
                click.echo(click.style(f"\n❌ {structure.get('message', 'Analysis failed')}", fg="red"))
                return
            
            # Show basic statistics
            doc_count = structure['stats']['doc_links']
            aux_count = structure['stats']['aux_links']
            
            click.echo(click.style(f"\n📋 Found {doc_count} documentation pages and {aux_count} auxiliary pages", 
                                  fg="bright_green"))
            
            if mode == 'selective':
                # Select specific sections
                selected_urls = select_documentation_sections(structure)
                if not selected_urls:
                    click.echo(click.style("\n❌ No sections selected. Aborting.", fg="red"))
                    return
                    
                start_urls = selected_urls
                click.echo(click.style(f"\n✓ Selected {len(start_urls)} URLs to download", fg="green"))
            else:
                # Interactive mode - prompt for auxiliary content
                doc_links = structure.get("links", {}).get("doc", [])
                aux_links = structure.get("links", {}).get("aux", [])
                
                # Always include documentation links
                start_urls = doc_links
                
                # Ask if user wants auxiliary content
                if aux_links and click.confirm(
                    f"\nDo you want to include {len(aux_links)} auxiliary pages "
                    f"(like pricing, about, etc.)?",
                    default=False
                ):
                    start_urls.extend(aux_links)
                    click.echo(click.style("✓ Including auxiliary content", fg="green"))
                else:
                    click.echo(click.style("✓ Downloading documentation content only", fg="green"))
                
        except Exception as e:
            # Stop the spinner if it's running
            stop_spinner.set()
            if spinner_thread.is_alive():
                spinner_thread.join()
            
            logger.error(f"Error during discovery: {e}", exc_info=True)
            click.echo(click.style(f"\n❌ Discovery failed: {e}", fg="red"))
            
            if click.confirm("\nDo you want to continue with basic mode?", default=True):
                click.echo("Continuing with default download...")
            else:
                click.echo("Download aborted.")
                return
    
    # Initialize the scraper
    interactive_mode = mode == 'interactive'
    
    # Confirm before proceeding
    if not click.confirm("\nStart downloading documentation?", default=True):
        click.echo("Download aborted.")
        return
    
    click.echo(click.style("\n📥 Starting documentation download...", fg="bright_blue"))
    
    # Create a scraper instance
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
    
    # Define a progress callback
    progress_bar = None
    current_url = None
    
    def progress_callback(url, current, total):
        nonlocal progress_bar, current_url
        
        # Initialize progress bar if needed
        if progress_bar is None:
            progress_bar = tqdm(
                total=total or 100,
                desc="Downloading documentation",
                unit="page",
                dynamic_ncols=True
            )
        
        # Update the progress bar
        if total and current <= total:
            progress_bar.total = total
            progress_bar.n = current
        else:
            # Increment by 1 if total is unknown
            progress_bar.update(1)
        
        # Update description with current URL
        if url != current_url:
            current_url = url
            short_url = url[-40:] if len(url) > 40 else url
            progress_bar.set_description(f"Processing {short_url}")
        
        progress_bar.refresh()
    
    # Set the callback
    scraper.crawler.progress_callback = progress_callback
    
    try:
        # Start the download
        if start_urls:
            # Use the selected URLs
            total_pages, total_assets = scraper.crawler.crawl_selected(start_urls)
        else:
            # Regular crawl from base URL
            total_pages, total_assets = scraper.crawl(interactive=interactive_mode)
        
        # Close the progress bar if it was created
        if progress_bar:
            progress_bar.close()
        
        # Display success message
        click.echo(click.style("\n✅ Download Completed!", fg="bright_green"))
        click.echo(f"• Downloaded {total_pages} pages")
        if include_assets:
            click.echo(f"• Downloaded {total_assets} assets")
        click.echo(f"• Saved to {os.path.abspath(output)}")
        
        # Handle any failed downloads
        if scraper.failed_urls:
            click.echo(click.style(f"\n⚠️ Failed to download {len(scraper.failed_urls)} URLs:", fg="yellow"))
            # Show first 5 failures
            for i, (failed_url, error) in enumerate(list(scraper.failed_urls.items())[:5]):
                click.echo(f"  • {failed_url}: {error}")
            
            if len(scraper.failed_urls) > 5:
                click.echo(f"  • ...and {len(scraper.failed_urls) - 5} more")
        
        # Ask if user wants to open the directory
        if click.confirm("\nOpen the downloaded documentation folder?", default=True):
            try:
                # Platform-specific commands to open file explorer
                if sys.platform == "win32":
                    os.startfile(output)
                elif sys.platform == "darwin":
                    subprocess.run(["open", output], check=True)
                else:
                    subprocess.run(["xdg-open", output], check=True)
            except Exception as e:
                logger.warning(f"Could not open directory: {e}")
                click.echo(f"Manually open: {os.path.abspath(output)}")
        
    except KeyboardInterrupt:
        # Handle user interruption
        if progress_bar:
            progress_bar.close()
        
        click.echo(click.style("\n⚠️ Download interrupted by user", fg="yellow"))
        
        # Ask if user wants to save what's been downloaded so far
        if click.confirm("Save downloaded content so far?", default=True):
            try:
                # Create index file for downloaded content
                scraper.create_main_index()
                click.echo(click.style("✓ Saved downloaded content", fg="green"))
            except Exception as e:
                logger.error(f"Error saving content: {e}")
                click.echo(click.style(f"❌ Error saving content: {e}", fg="red"))
        
    except Exception as e:
        # Handle other errors
        if progress_bar:
            progress_bar.close()
        
        logger.error(f"Error during download: {e}", exc_info=True)
        click.echo(click.style(f"\n❌ Download failed: {e}", fg="red"))
        
        if verbose:
            import traceback
            click.echo(traceback.format_exc())

@cli.command(name="gui")
def launch_gui():
    """Launch the graphical user interface for DocScraper."""
    try:
        # Find GUI directory
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        gui_path = os.path.join(script_dir, "doc_scrape_GUI")
        
        click.echo(f"Starting Document Scraper GUI...")
        
        # Add GUI directory to path
        if gui_path not in sys.path:
            sys.path.insert(0, script_dir)
        
        try:
            from doc_scrape_GUI.gui import DocScraperApp
            app = DocScraperApp()
            app.mainloop()
            click.echo("GUI closed.")
        except ImportError as e:
            click.echo(click.style(f"Error importing GUI components: {e}", fg="red"))
            
            # Check if tkinter is available
            try:
                import tkinter
            except ImportError:
                click.echo(click.style("Tkinter is not available. GUI requires tkinter to be installed.", fg="red"))
                click.echo("On Debian/Ubuntu: sudo apt-get install python3-tk")
                click.echo("On Windows: Tkinter should be installed with Python")
                click.echo("On macOS: brew install python-tk")
                sys.exit(1)
            
            # Fall back to command-line interface
            click.echo(click.style("Falling back to command-line interface.", fg="yellow"))
            cli.get_command(None, "download")(obj={})
            
    except Exception as e:
        click.echo(click.style(f"Error launching GUI: {e}", fg="red"))
        import traceback
        traceback.print_exc()
        sys.exit(1)

#---------------------------------------------------------------------------
# Main Function and Entry Point
#---------------------------------------------------------------------------

def main():
    """Entry point for both CLI and GUI interfaces."""
    # If no arguments provided, offer to launch the GUI or show help
    if len(sys.argv) == 1:
        click.echo(click.style("\n🚀 Welcome to DocScraper!", fg="bright_blue"))
        click.echo("\nHow would you like to use DocScraper today?")
        click.echo(f"1. {click.style('Graphical User Interface', fg='bright_green')} - User-friendly GUI")
        click.echo(f"2. {click.style('Interactive Download', fg='bright_yellow')} - Guided command-line experience")
        click.echo(f"3. {click.style('Documentation Explorer', fg='bright_cyan')} - Analyze site structure")
        click.echo(f"4. {click.style('Command Help', fg='bright_white')} - Show available commands")
        
        choice = click.prompt(
            "\nSelect option",
            type=click.Choice(['1', '2', '3', '4']), 
            default='1'
        )
        
        if choice == '1':
            # Launch GUI
            sys.argv = [sys.argv[0], "gui"]
        elif choice == '2':
            # Start interactive download
            sys.argv = [sys.argv[0], "download"]
        elif choice == '3':
            # Launch discovery mode
            sys.argv = [sys.argv[0], "discover"]
        else:
            # Show help
            sys.argv = [sys.argv[0], "--help"]
    
    # Start CLI with the provided/modified arguments
    cli()

if __name__ == "__main__":
    main()