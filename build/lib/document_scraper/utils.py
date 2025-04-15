"""
Utility functions for the document_scraper module.

This module provides helper functions for URL handling, path management,
and other common operations needed by the scraper and converter components.
"""

import os
import re
import logging
import time
from typing import List, Optional, Dict, Any, Tuple, Callable
from urllib.parse import urlparse, urljoin, urlunparse, parse_qs, urlencode
from slugify import slugify
import requests
from functools import wraps

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("document_scraper")


def is_valid_url(url: str) -> bool:
    """
    Check if a URL is valid.
    
    Args:
        url: The URL to validate
        
    Returns:
        True if the URL is valid, False otherwise
    """
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def get_domain(url: str) -> str:
    """
    Extract the domain from a URL.
    
    Args:
        url: The URL to extract domain from
        
    Returns:
        The domain of the URL
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
        'fbclid', 'gclid', 'ref', 'source', 'mc_cid', 'mc_eid'
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


def clean_filename(title: str) -> str:
    """
    Clean and convert a title to a valid filename.
    
    Args:
        title: The title to clean
        
    Returns:
        A valid filename
    """
    # Remove special characters and convert spaces to hyphens
    return slugify(title)


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
    # Remove the domain from the URL to get the path
    base_domain = get_domain(base_url)
    path = url.replace(base_domain, "")
    
    # Remove query parameters and fragments
    path = path.split("?")[0].split("#")[0]
    
    # Split path into segments
    segments = [seg for seg in path.split("/") if seg and seg != "docs"]
    
    # Handle situations where the URL ends with a slash (directory)
    if url.endswith("/") and segments:
        segments[-1] = f"{segments[-1]}_index"
    
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
    segments = extract_path_segments(url, base_url)
    
    if not segments:
        # If no segments (root URL), use 'index'
        return output_dir, "index.md"
    
    # The last segment becomes the filename
    filename = f"{clean_filename(segments[-1])}.md"
    
    # The remaining segments form the directory path
    if len(segments) > 1:
        directory_path = os.path.join(output_dir, *[clean_filename(seg) for seg in segments[:-1]])
    else:
        directory_path = output_dir
    
    ensure_directory_exists(directory_path)
    return directory_path, filename


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
