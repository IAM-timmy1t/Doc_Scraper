"""
DocScraper: A comprehensive tool for downloading online documentation and converting it to Markdown.

This module allows users to scrape documentation websites, convert HTML content to Markdown,
and save files in a directory structure that matches the original site's organization.
"""

__version__ = "0.1.1"

# Import main components for easy access
from document_scraper.scraper import DocumentationScraper, scrape_documentation
from document_scraper.converter import HtmlToMarkdownConverter
from document_scraper.utils import (
    is_valid_url, 
    get_domain, 
    normalize_url, 
    clean_filename, 
    ensure_directory_exists,
    extract_path_segments,
    create_path_from_url
)

# Provide all components at the package level for easier imports
__all__ = [
    'DocumentationScraper',
    'scrape_documentation',
    'HtmlToMarkdownConverter',
    'is_valid_url',
    'get_domain',
    'normalize_url',
    'clean_filename',
    'ensure_directory_exists',
    'extract_path_segments',
    'create_path_from_url'
]
