"""
Command-line interface for the document_scraper module.

This module provides a user-friendly CLI for scraping documentation websites
and saving them as organized Markdown files.
"""

import os
import sys
import click
import logging
from urllib.parse import urlparse
import colorama
from tqdm import tqdm

from document_scraper.scraper import DocumentationScraper
from document_scraper.utils import is_valid_url, ensure_directory_exists

# Initialize colorama for cross-platform color support
colorama.init()

# Configure logging
logger = logging.getLogger("document_scraper")


def setup_logging(verbose=False):
    """Configure logging based on verbosity."""
    log_level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(log_level)
    
    # Create console handler with formatting
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def validate_url(ctx, param, value):
    """Validates the URL parameter."""
    if not value:
        return None
    if not is_valid_url(value):
        raise click.BadParameter(f"Invalid URL: {value}")
    return value


@click.group(invoke_without_command=True)
@click.version_option(version="0.2.0")
@click.pass_context
def cli(ctx):
    """DocScraper: Download and convert documentation websites to Markdown."""
    # If no command is provided, show help or run the default command
    if ctx.invoked_subcommand is None:
        # Direct the user to the download command by default
        click.echo(click.style("Welcome to DocScraper!", fg="bright_blue", bold=True))
        click.echo("This tool helps you download documentation websites and convert them to Markdown.")
        click.echo("\nTo get started, run the download command:")
        click.echo(click.style("  docscraper download", fg="bright_green"))
        click.echo("\nOr see available options:")
        click.echo(click.style("  docscraper download --help", fg="bright_green"))
        click.echo("\nFor more information, visit: https://github.com/username/document_scraper")


@cli.command(name="download")
@click.option('--url', '-u', 
              help='URL of the documentation website (e.g., https://docs.python.org/3/)',
              callback=validate_url,
              prompt='Documentation website URL')
@click.option('--output', '-o', 
              default=os.path.join(os.getcwd(), 'scraped_docs'),
              help='Output directory for the documentation files',
              type=click.Path(file_okay=False),
              prompt='Output directory')
@click.option('--max-depth', '-d', 
              help='Maximum crawl depth',
              default=5, show_default=True, type=int)
@click.option('--delay', 
              help='Delay between requests in seconds',
              default=0.5, show_default=True, type=float)
@click.option('--max-pages', '-m', 
              help='Maximum number of pages to download (0 = unlimited)',
              default=0, show_default=True, type=int)
@click.option('--concurrent', '-c', 
              help='Number of concurrent requests',
              default=5, show_default=True, type=int)
@click.option('--include-assets/--no-assets', 
              help='Download assets (images, CSS, JS)',
              default=False, show_default=True)
@click.option('--timeout', '-t',
              help='Request timeout in seconds',
              default=30, show_default=True, type=int)
@click.option('--retries', '-r',
              help='Number of retries for failed requests',
              default=3, show_default=True, type=int)
@click.option('--verbose', '-v', 
              help='Enable verbose logging',
              is_flag=True, default=False)
def download(url, output, max_depth, delay, max_pages, concurrent, include_assets, timeout, retries, verbose):
    """
    Download a documentation website and convert it to Markdown files.
    
    The tool will crawl the website starting from the given URL, following links
    within the same domain, and save each page as a Markdown file. The directory
    structure will match the URL structure of the website.
    """
    setup_logging(verbose)
    
    # If URL was provided via prompt and is invalid
    if not is_valid_url(url):
        click.echo(click.style("Error: Invalid URL format", fg="red"))
        sys.exit(1)
        
    # Create a default directory name based on the domain if needed
    if output == os.path.join(os.getcwd(), 'scraped_docs'):
        domain = urlparse(url).netloc
        suggested_dir = f"docs_{domain.replace('.', '_')}"
        if click.confirm(f"Use suggested directory name '{suggested_dir}' instead of 'scraped_docs'?", default=True):
            output = os.path.join(os.getcwd(), suggested_dir)
    
    # Convert max_pages=0 to None for unlimited
    max_pages = None if max_pages == 0 else max_pages
    
    click.echo(click.style("\n✨ DocScraper Configuration:", fg="bright_blue"))
    click.echo(f"• Documentation URL: {click.style(url, fg='bright_green')}")
    click.echo(f"• Output directory: {click.style(output, fg='bright_green')}")
    click.echo(f"• Maximum depth: {max_depth}")
    click.echo(f"• Request delay: {delay} seconds")
    click.echo(f"• Maximum pages: {'Unlimited' if max_pages is None else max_pages}")
    click.echo(f"• Concurrent requests: {concurrent}")
    click.echo(f"• Include assets: {'Yes' if include_assets else 'No'}")
    click.echo(f"• Timeout: {timeout} seconds")
    click.echo(f"• Retries: {retries}")
    click.echo("")
    
    if not click.confirm("Continue with these settings?", default=True):
        click.echo("Aborted.")
        sys.exit(0)
    
    # Create output directory
    ensure_directory_exists(output)
    
    # Start the scraper
    try:
        click.echo(click.style("\n🚀 Starting documentation download...", fg="bright_blue"))
        
        # Progress callback for CLI
        def progress_callback(url, current, total):
            if verbose:
                click.echo(f"Processing: {url} [{current}/{total if total else 'unknown'}]")
        
        scraper = DocumentationScraper(
            base_url=url,
            output_dir=output,
            max_depth=max_depth,
            delay=delay,
            max_pages=max_pages,
            concurrent_requests=concurrent,
            include_assets=include_assets,
            timeout=timeout,
            retries=retries,
            progress_callback=progress_callback
        )
        
        pages_downloaded, assets_downloaded = scraper.crawl()
        
        # Show success message
        click.echo("")
        click.echo(click.style("✅ Download completed!", fg="bright_green"))
        click.echo(f"• Downloaded {click.style(str(pages_downloaded), fg='bright_yellow')} documentation pages")
        if include_assets:
            click.echo(f"• Downloaded {click.style(str(assets_downloaded), fg='bright_yellow')} assets")
        click.echo(f"• Saved to {click.style(os.path.abspath(output), fg='bright_green')}")
        
    except KeyboardInterrupt:
        click.echo(click.style("\n⚠️ Download interrupted by user", fg="yellow"))
        sys.exit(130)
    except Exception as e:
        click.echo(click.style(f"\n❌ Error: {e}", fg="red"))
        if verbose:
            import traceback
            click.echo(traceback.format_exc())
        sys.exit(1)


@cli.command(name="version")
def version():
    """Display the version of DocScraper."""
    click.echo("DocScraper version 0.2.0")


def main():
    """Entry point for the command-line interface."""
    try:
        cli()
    except Exception as e:
        click.echo(click.style(f"\n❌ Error: {e}", fg="red"))
        click.echo("If the problem persists, please report the issue at:")
        click.echo(click.style("https://github.com/username/document_scraper/issues", fg="bright_blue", underline=True))
        sys.exit(1)


if __name__ == "__main__":
    main()
