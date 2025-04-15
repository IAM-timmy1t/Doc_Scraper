"""
Utility functions for the document_scraper module.

This module provides essential helper functions for URL handling, path management,
and other common operations needed across the document scraper ecosystem. Utilities
are organized into logical sections for URL processing, file operations, and
documentation-specific functionality.
"""

import os
import re
import logging
import time
from typing import List, Optional, Dict, Any, Tuple, Callable, Set, Union
from urllib.parse import urlparse, urljoin, urlunparse, parse_qs, urlencode
from slugify import slugify
import requests
from functools import wraps
import click
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("document_scraper")


#---------------------------------------------------------------------------
# Logging Configuration
#---------------------------------------------------------------------------

def setup_logging(verbose: bool = False, log_file: Optional[str] = None):
    """
    Configure logging based on verbosity and optional file output.
    
    Args:
        verbose: Whether to enable debug level logging
        log_file: Optional path to write logs to a file
    """
    log_level = logging.DEBUG if verbose else logging.INFO
    
    # Check if handlers already exist to avoid duplication
    if logger.hasHandlers():
        # Clear existing handlers if re-configuration is needed
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    logger.setLevel(log_level)
    
    # Create console handler with formatting
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    if verbose:
        logger.info("Verbose logging enabled")


#---------------------------------------------------------------------------
# URL Processing Functions
#---------------------------------------------------------------------------

def is_valid_url(url: str) -> bool:
    """
    Validate if a string is a properly formatted URL.
    
    Performs comprehensive validation of URL structure and scheme safety.
    
    Args:
        url: The URL string to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not url:
        return False
        
    try:
        result = urlparse(url)
        if not all([result.scheme, result.netloc]):
            return False
            
        # Only allow http and https schemes
        if result.scheme not in ('http', 'https'):
            return False
            
        # Reject potentially dangerous schemes
        if result.scheme in ('javascript', 'data', 'file'):
            return False
            
        return True
    except ValueError:
        return False


def get_domain(url: str) -> str:
    """
    Extract the domain from a URL.
    
    Args:
        url: The URL to extract domain from
        
    Returns:
        The domain of the URL including scheme (e.g., https://example.com)
    """
    parsed_url = urlparse(url)
    return f"{parsed_url.scheme}://{parsed_url.netloc}"


def normalize_url(url: str, base_url: str) -> Optional[str]:
    """
    Normalize a URL by joining it with the base URL if it's relative.
    
    Args:
        url: The URL to normalize
        base_url: The base URL to join with relative URLs
        
    Returns:
        The normalized URL or None if the URL should be skipped
    """
    # Skip URLs that are not part of the documentation
    if not url or url.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    
    # Remove fragments from URLs but keep query parameters
    if "#" in url and "?" not in url:
        url = url.split("#")[0]
    
    # Handle relative URLs
    if not bool(urlparse(url).netloc):
        return urljoin(base_url, url)
    
    return url


def clean_url(url: str) -> str:
    """
    Clean a URL by removing unnecessary query parameters and standardizing format.
    
    Args:
        url: The URL to clean
        
    Returns:
        A cleaned URL
    """
    # Parse the URL
    parsed = urlparse(url)
    
    # Clean the path - remove double slashes, etc.
    path = re.sub(r'/{2,}', '/', parsed.path)
    
    # Remove trailing slash from path unless it's the root
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    
    # Parse query parameters
    params = parse_qs(parsed.query)
    
    # Filter out common tracking parameters
    exclude_params = {
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
        'fbclid', 'gclid', 'ref', 'source', 'mc_cid', 'mc_eid', 'tracking',
        '__hstc', '__hssc', '__hsfp', '_ga', '_gl', '_hsenc', '_hsmi'
    }
    
    filtered_params = {k: v for k, v in params.items() if k.lower() not in exclude_params}
    
    # Reconstruct the URL
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        path,
        parsed.params,
        urlencode(filtered_params, doseq=True),
        ''  # Remove fragment
    ))


def is_same_domain(url1: str, url2: str) -> bool:
    """
    Check if two URLs belong to the same domain or subdomain.
    
    Args:
        url1: First URL to compare
        url2: Second URL to compare
        
    Returns:
        True if URLs are on the same domain or related subdomains
    """
    parsed1 = urlparse(url1)
    parsed2 = urlparse(url2)
    
    netloc1 = parsed1.netloc.lower()
    netloc2 = parsed2.netloc.lower()
    
    # Exact match
    if netloc1 == netloc2:
        return True
    
    # Extract domain parts
    parts1 = netloc1.split('.')
    parts2 = netloc2.split('.')
    
    # Check if one is a subdomain of the other
    if len(parts1) >= 2 and len(parts2) >= 2:
        # Get the main domain (last two parts typically)
        main_domain1 = '.'.join(parts1[-2:])
        main_domain2 = '.'.join(parts2[-2:])
        
        if main_domain1 == main_domain2:
            return True
    
    return False


def rate_limit(min_interval: float = 0.5):
    """
    Decorator to rate limit function calls.
    
    Args:
        min_interval: Minimum time between calls in seconds
        
    Returns:
        Decorated function
    """
    last_called = [0.0]  # Use a list for nonlocal mutability
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            result = func(*args, **kwargs)
            last_called[0] = time.time()
            return result
        return wrapper
    return decorator


#---------------------------------------------------------------------------
# File System Operations
#---------------------------------------------------------------------------

def clean_filename(title: str) -> str:
    """
    Clean and convert a title to a valid filename.
    
    Args:
        title: The title to clean
        
    Returns:
        A valid filename
    """
    # Handle empty or None titles
    if not title:
        return "untitled"
        
    # Replace problematic characters
    replacements = {
        ' ': '-',     # spaces to hyphens for readability
        '_': '-',     # normalize underscores to hyphens
        '/': '-',     # forward slashes
        '\\': '-',    # backslashes
        ':': '-',     # colons
        '*': '',      # asterisks
        '?': '',      # question marks
        '"': '',      # double quotes
        '<': '',      # less than
        '>': '',      # greater than
        '|': '-',     # pipes
        '\t': '-',    # tabs
        '\n': '-',    # newlines
    }
    
    # Apply replacements
    for char, replacement in replacements.items():
        title = title.replace(char, replacement)
    
    # Use slugify for unicode support and additional cleaning
    result = slugify(title)
    
    # Remove multiple consecutive hyphens
    result = re.sub(r'-+', '-', result)
    
    # Ensure the filename isn't too long (filesystems have limits)
    if len(result) > 80:
        result = result[:77] + '...'
        
    # Ensure we don't return an empty string
    if not result:
        return "untitled"
        
    return result


def ensure_directory_exists(directory: str) -> str:
    """
    Create a directory if it doesn't exist.
    
    Args:
        directory: The directory path to create
        
    Returns:
        The created directory path
    """
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        logger.info(f"Created directory: {directory}")
    return directory


def extract_path_segments(url: str, base_url: str) -> List[str]:
    """
    Extract path segments from a URL for directory structure creation.
    
    Args:
        url: The URL to process
        base_url: The base URL of the documentation
        
    Returns:
        List of path segments to create
    """
    # Extract base domain for comparison
    base_domain = urlparse(base_url).netloc
    url_domain = urlparse(url).netloc
    
    # Remove the domain from the URL to get the path
    parsed_url = urlparse(url)
    path = parsed_url.path
    
    # Handle cases where base_url includes a path
    base_parsed = urlparse(base_url)
    base_path = base_parsed.path.rstrip('/')
    
    # If the base URL has a path component, remove it from the URL path
    if base_path and path.startswith(base_path):
        path = path[len(base_path):]
    
    # Remove query parameters and fragments
    path = path.split("?")[0].split("#")[0]
    
    # Split path into segments
    segments = [seg for seg in path.strip('/').split("/") if seg]
    
    return segments


def create_path_from_url(url: str, base_url: str, output_dir: str) -> Tuple[str, str]:
    """
    Create a directory path and filename from a URL.
    
    Args:
        url: The URL to process
        base_url: The base URL of the documentation
        output_dir: The base output directory
        
    Returns:
        Tuple of (directory_path, filename)
    """
    # Get domain for proper site organization
    base_domain = urlparse(base_url).netloc
    url_domain = urlparse(url).netloc
    
    # Extract path segments from the URL
    segments = extract_path_segments(url, base_url)
    
    if not segments:
        # If no segments (root URL), use 'index'
        return output_dir, "index.md"
    
    # Create a more organized folder structure
    # First segment is often the main section (get-started, guides, etc.)
    if len(segments) > 1:
        # Create a nested folder structure to maintain organization
        # For paths like /get-started/installation, put in get-started/installation
        directory_path = os.path.join(output_dir, *[clean_filename(seg) for seg in segments[:-1]])
        filename = f"{clean_filename(segments[-1])}.md"
        
        # Special cases for common documentation sections
        if segments[0] in ['docs', 'documentation', 'doc']:
            # Handle /docs/section/page -> /section/page
            directory_path = os.path.join(output_dir, *[clean_filename(seg) for seg in segments[1:-1]])
            if not segments[1:-1]:  # If only /docs/page
                directory_path = output_dir
                
    else:
        # For simple paths like /page
        directory_path = output_dir
        filename = f"{clean_filename(segments[0])}.md"
    
    # Create directory if it doesn't exist
    ensure_directory_exists(directory_path)
    
    return directory_path, filename


#---------------------------------------------------------------------------
# Asset Handling Functions
#---------------------------------------------------------------------------

def get_file_extension(url: str) -> str:
    """
    Get the file extension from a URL.
    
    Args:
        url: The URL to extract extension from
        
    Returns:
        The file extension (without dot) or empty string if none
    """
    parsed_url = urlparse(url)
    path = parsed_url.path
    
    # Get the last component of the path
    filename = os.path.basename(path)
    
    # Get the extension
    _, ext = os.path.splitext(filename)
    
    # Remove the dot and return lowercase extension
    return ext[1:].lower() if ext else ""


def is_asset_url(url: str) -> bool:
    """
    Determine if a URL is an asset (image, CSS, JavaScript, etc.).
    
    Args:
        url: The URL to check
        
    Returns:
        True if the URL is an asset, False otherwise
    """
    # Common asset extensions
    asset_extensions = {
        # Images
        'jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'ico', 'bmp',
        # Styles
        'css', 'scss', 'less',
        # Scripts
        'js', 'mjs',
        # Fonts
        'woff', 'woff2', 'ttf', 'eot', 'otf',
        # Other
        'pdf', 'zip', 'xml', 'json'
    }
    
    # Check extension
    extension = get_file_extension(url)
    if extension in asset_extensions:
        return True
    
    # Check URL patterns
    asset_patterns = ['/assets/', '/static/', '/images/', '/img/', '/css/', '/js/', '/fonts/']
    return any(pattern in url.lower() for pattern in asset_patterns)


def create_assets_dir(output_dir: str) -> str:
    """
    Create a directory for assets relative to the output directory.
    
    Args:
        output_dir: Base output directory
        
    Returns:
        Path to the assets directory
    """
    assets_dir = os.path.join(output_dir, "assets")
    ensure_directory_exists(assets_dir)
    return assets_dir


def get_asset_path(url: str, output_dir: str) -> str:
    """
    Generate a path for saving an asset file.
    
    Args:
        url: URL of the asset
        output_dir: Base output directory
        
    Returns:
        Full path for saving the asset
    """
    assets_dir = create_assets_dir(output_dir)
    
    # Extract file extension and path elements
    parsed_url = urlparse(url)
    path = parsed_url.path.lstrip('/')
    
    # Determine subdirectory based on file type
    extension = get_file_extension(url)
    
    if extension in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'ico', 'bmp']:
        subdir = "images"
    elif extension in ['css', 'scss', 'less']:
        subdir = "css"
    elif extension in ['js', 'mjs']:
        subdir = "js"
    elif extension in ['woff', 'woff2', 'ttf', 'eot', 'otf']:
        subdir = "fonts"
    else:
        subdir = "other"
    
    # Create the subdirectory
    target_dir = os.path.join(assets_dir, subdir)
    ensure_directory_exists(target_dir)
    
    # Get the filename from the URL, ensuring it's unique and valid
    filename = os.path.basename(path)
    if not filename:
        # If no filename can be extracted, create one from the full URL
        filename = clean_filename(url)
        if extension:
            filename += f".{extension}"
    
    # Create full save path
    save_path = os.path.join(target_dir, filename)
    
    # Ensure uniqueness by adding a number if needed
    counter = 1
    name, ext = os.path.splitext(save_path)
    while os.path.exists(save_path):
        save_path = f"{name}_{counter}{ext}"
        counter += 1
    
    return save_path


#---------------------------------------------------------------------------
# Command-Line Interface Utilities
#---------------------------------------------------------------------------

def validate_url(ctx: Optional[click.Context], param: Optional[click.Parameter], value: Any) -> Optional[str]:
    """
    Validate and normalize a URL string for Click commands.
    
    Args:
        ctx: Click context
        param: Click parameter
        value: The URL value to validate
        
    Returns:
        The normalized URL if valid, None if empty
        
    Raises:
        click.BadParameter: If URL is invalid
    """
    if not value:
        return None
        
    try:
        if not is_valid_url(value):
            raise click.BadParameter(f"Invalid URL format: {value}")
            
        parsed = urlparse(value)
        normalized = parsed._replace(path=parsed.path.rstrip('/'))
        return normalized.geturl()
    except ValueError as e:
        raise click.BadParameter(f"Invalid URL: {str(e)}")


def discover_documentation_sections(url: str, verbose: bool = False) -> Dict[str, str]:
    """
    Discover available documentation sections from a documentation website.
    
    Args:
        url: The base URL of the documentation
        verbose: Whether to enable verbose logging
        
    Returns:
        Dictionary mapping section names to URLs
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        sections = {}
        
        # Find all links in the navigation
        nav_selectors = [
            'nav a', '.sidebar a', '.toc a', '.menu a', '.navigation a',
            '.doc-nav a', '.docusaurus-highlight-code-line a', 
            '.theme-doc-sidebar-item a', '.docs-sidebar a'
        ]
        
        for link in soup.select(', '.join(nav_selectors)):
            if 'href' in link.attrs:
                section_url = urljoin(url, link['href'])
                section_name = link.get_text().strip()
                if section_name and is_valid_url(section_url):
                    sections[section_name] = section_url
        
        if verbose:
            logger.debug(f"Discovered {len(sections)} documentation sections")
            
        return sections
    except Exception as e:
        logging.error(f"Error discovering documentation sections: {str(e)}")
        return {}


def prompt_documentation_selection(sections: Dict[str, str]) -> List[str]:
    """
    Prompt user to select documentation sections interactively.
    
    Args:
        sections: Available sections from discover_documentation_sections()
        
    Returns:
        List of selected URLs
    """
    click.echo(click.style("\nAvailable Documentation Sections:", fg="bright_blue"))
    for i, (name, url) in enumerate(sections.items(), 1):
        click.echo(f"  {i}. {name}: {url}")
    
    selected = click.prompt(
        "\nEnter section numbers to download (comma separated, or 'all')",
        default="all"
    )
    
    if selected.lower() == 'all':
        return list(sections.values())
        
    selected_urls = []
    for num in selected.split(','):
        try:
            idx = int(num.strip()) - 1
            if 0 <= idx < len(sections):
                selected_urls.append(list(sections.values())[idx])
        except ValueError:
            continue
            
    return selected_urls


#---------------------------------------------------------------------------
# Documentation-Specific Utilities
#---------------------------------------------------------------------------

def categorize_url(url: str, base_url: str) -> str:
    """
    Categorize a URL as documentation, auxiliary, external, or asset.
    
    Args:
        url: The URL to categorize
        base_url: The base URL of the documentation
        
    Returns:
        Category as string: 'doc', 'aux', 'external', or 'asset'
    """
    # Skip if URL is invalid or None
    if not url or not is_valid_url(url):
        return 'invalid'
        
    # Check if it's an asset URL first
    if is_asset_url(url):
        return 'asset'
        
    # Check if it's an external URL
    if not is_same_domain(url, base_url):
        return 'external'
    
    # Get path for further categorization
    path = urlparse(url).path.lower()
    
    # Documentation patterns
    doc_patterns = [
        '/docs/', '/doc/', '/documentation/', '/guide/', '/guides/', 
        '/reference/', '/api/', '/manual/', '/tutorial/', '/get-started/',
        '/learn/', '/howto/', '/usage/', '/examples/', '/quickstart/',
        '/sdk/', '/cli/', '/faq/', '/help/'
    ]
    
    # Check for documentation patterns
    for pattern in doc_patterns:
        if pattern in path:
            return 'doc'
    
    # Auxiliary patterns
    aux_patterns = [
        '/account/', '/profile/', '/settings/', '/user/',
        '/pricing/', '/billing/', '/subscription/', '/payment/', '/plans/',
        '/about/', '/company/', '/team/', '/contact/', '/support/',
        '/legal/', '/terms/', '/privacy/', '/blog/', '/news/'
    ]
    
    # Check for auxiliary patterns
    for pattern in aux_patterns:
        if pattern in path:
            return 'aux'
    
    # Default to documentation for same-domain URLs that don't match patterns
    return 'doc'


def extract_document_metadata(html_content: str, url: str) -> Dict[str, Any]:
    """
    Extract metadata from HTML document.
    
    Args:
        html_content: HTML content
        url: URL of the document
        
    Returns:
        Dictionary of metadata
    """
    metadata = {
        'url': url,
        'title': '',
        'description': '',
        'keywords': [],
        'author': '',
        'date': '',
        'headings': []
    }
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extract title
        title_tag = soup.find('title')
        if title_tag:
            metadata['title'] = title_tag.text.strip()
        
        # Extract metadata from meta tags
        for meta in soup.find_all('meta'):
            name = meta.get('name', meta.get('property', '')).lower()
            content = meta.get('content', '')
            
            if name == 'description':
                metadata['description'] = content
            elif name == 'keywords':
                metadata['keywords'] = [k.strip() for k in content.split(',')]
            elif name == 'author':
                metadata['author'] = content
            elif name in ['pubdate', 'publishdate', 'date', 'created']:
                metadata['date'] = content
        
        # Extract headings
        headings = []
        for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            level = int(tag.name[1])
            text = tag.get_text(strip=True)
            headings.append({'level': level, 'text': text})
        
        metadata['headings'] = headings
        
    except Exception as e:
        logger.debug(f"Error extracting metadata: {e}")
    
    return metadata


def analyze_documentation_structure(urls: List[str]) -> Dict[str, Any]:
    """
    Analyze the structure of documentation URLs to determine organization.
    
    Args:
        urls: List of URLs to analyze
        
    Returns:
        Dictionary with analysis results
    """
    # Initialize structure analysis
    analysis = {
        'total_urls': len(urls),
        'sections': {},
        'depth': {},
        'common_patterns': []
    }
    
    # Extract structural information
    for url in urls:
        parsed_url = urlparse(url)
        path = parsed_url.path.strip('/')
        
        if not path:
            # Root URL
            analysis['depth']['root'] = analysis['depth'].get('root', 0) + 1
            continue
            
        # Extract path segments
        segments = path.split('/')
        depth = len(segments)
        
        # Record depth
        analysis['depth'][depth] = analysis['depth'].get(depth, 0) + 1
        
        # Record section (first path component)
        if segments:
            section = segments[0]
            analysis['sections'][section] = analysis['sections'].get(section, 0) + 1
    
    # Identify common patterns
    common_prefixes = set()
    for url in urls:
        parsed_url = urlparse(url)
        path = parsed_url.path.strip('/')
        segments = path.split('/')
        
        if len(segments) >= 1:
            common_prefixes.add(segments[0])
    
    analysis['common_patterns'] = list(common_prefixes)
    
    return analysis