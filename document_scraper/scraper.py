"""
Core scraping functionality for the document_scraper module.

This module handles the scraping of documentation websites, extracting
content, discovering links, and organizing the download structure.
"""

import os
import time
import logging
import requests
import traceback
from tqdm import tqdm
import concurrent.futures
from bs4 import BeautifulSoup
from collections import deque
from urllib.parse import urlparse, urljoin, parse_qs, urlencode
from typing import List, Dict, Tuple, Set, Optional, Callable, Any, Union
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, WebDriverException

from document_scraper.utils import (
    is_asset_url, get_asset_path, rate_limit,
    create_path_from_url, ensure_directory_exists,
    is_valid_url, get_domain, normalize_url, clean_url,
)
from document_scraper.formats import get_formatter
from document_scraper.converter import HtmlToMarkdownConverter

logger = logging.getLogger("document_scraper")


class RequestError(Exception):
    """Exception raised for request-related errors."""
    pass


class DocumentationScraper:
    """
    Scrapes documentation websites and saves content as Markdown files.
    """
    
    def __init__(self, 
                 base_url: str, 
                 output_dir: str, 
                 max_depth: int = 5,
                 delay: float = 0.5, 
                 max_pages: Optional[int] = None,
                 concurrent_requests: int = 5,
                 include_assets: bool = False,
                 timeout: int = 30,
                 retries: int = 3,
                 user_agent: Optional[str] = None,
                 proxies: Optional[Dict[str, str]] = None,
                 cookies: Optional[Dict[str, str]] = None,
                 headers: Optional[Dict[str, str]] = None,
                 browser_mode: bool = False,
                 output_format: str = "markdown",
                 content_include_patterns: Optional[List[str]] = None,
                 content_exclude_patterns: Optional[List[str]] = None,
                 url_include_patterns: Optional[List[str]] = None,
                 url_exclude_patterns: Optional[List[str]] = None,
                 progress_callback: Optional[Callable[[str, int, Optional[int]], None]] = None,
                 max_retries: int = 3,
                 stop_event: Optional[Any] = None,
                 verbose: bool = False):
        """
        Initialize the scraper with configuration options.
        
        Args:
            base_url: The base URL of the documentation site
            output_dir: Directory where to save the downloaded files
            max_depth: Maximum crawl depth. Defaults to 5.
            delay: Delay between requests in seconds. Defaults to 0.5.
            max_pages: Maximum number of pages to download. Defaults to None (unlimited).
            concurrent_requests: Number of concurrent requests. Defaults to 5.
            include_assets: Whether to download assets (images, CSS, JS). Defaults to False.
            timeout: Request timeout in seconds. Defaults to 30.
            retries: Number of times to retry failed downloads. Defaults to 3.
            user_agent: Custom user agent string. Defaults to DocScraper default.
            proxies: Dictionary mapping protocol to proxy URL. Defaults to None.
            cookies: Dictionary of cookies to include with requests. Defaults to None.
            progress_callback: Optional callback function for progress updates.
                               Takes (url, current_count, total_count) as arguments.
            stop_event: Optional event to signal the scraper to stop processing.
        """
        # Known problematic URLs to skip
        self.skip_urls = {
            "https://ai.google.dev/gemini-api/docs/gemini-api/docs/models",
            "https://ai.google.dev/gemini-api/docs/experimental-models"
        }
        
        # Configuration
        self.base_url = base_url.rstrip('/')
        self.domain = get_domain(base_url)
        
        # Create a dedicated folder for this scrape based on the domain
        domain_name = urlparse(self.base_url).netloc
        
        # Extract the main site name (e.g., "cursor" from "docs.cursor.com")
        parts = domain_name.split('.')
        if len(parts) >= 2:
            # Handle common documentation domain patterns
            if parts[0] == 'docs' or parts[0] == 'documentation' or parts[0] == 'api':
                site_name = parts[1]  # Use the second part (e.g., "cursor" from "docs.cursor.com")
            else:
                site_name = parts[0]  # Use the first part otherwise
        else:
            site_name = domain_name
            
        self.site_folder = f"{site_name}_docs"
        self.output_dir = os.path.join(output_dir, self.site_folder)
        
        # Stop event for managing graceful termination
        self.stop_event = stop_event
        
        self.max_depth = max_depth
        self.delay = delay
        self.max_pages = max_pages
        self.concurrent_requests = concurrent_requests
        self.include_assets = include_assets
        self.timeout = timeout
        self.retries = retries
        self.proxies = proxies
        self.progress_callback = progress_callback
        self.max_retries = max_retries
        
        # State tracking
        self.visited: Set[str] = set()
        self.queued: Set[str] = set()
        self.pages_downloaded = 0
        self.assets_downloaded = 0
        self.output_format = output_format.lower()
        self.formatter = get_formatter(output_format, base_url=self.domain)
        self.failed_urls: Dict[str, str] = {}  # URL -> error message
        
        # Currently active browser instances and futures for proper cleanup
        self.active_browser_instances = []
        self.active_futures = []
        
        # Content and URL filtering patterns
        self.content_include_patterns = content_include_patterns or []
        self.content_exclude_patterns = content_exclude_patterns or []
        self.url_include_patterns = url_include_patterns or []
        self.url_exclude_patterns = url_exclude_patterns or []
        
        # Compile regex patterns for better performance
        import re
        self.content_include_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.content_include_patterns]
        self.content_exclude_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.content_exclude_patterns]
        self.url_include_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.url_include_patterns]
        self.url_exclude_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.url_exclude_patterns]
        
        # Setup session for persistent connections
        self.session = requests.Session()
        
        # Configure realistic browser-like behavior
        self.browser_mode = browser_mode
        
        # Default to a modern browser user agent if none provided
        if not user_agent:
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
            
        # Browser-like headers to avoid detection
        default_headers = {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
            'DNT': '1'
        }
        
        # Apply default headers
        self.session.headers.update(default_headers)
        
        # Apply custom headers if provided
        if headers:
            self.session.headers.update(headers)
        
        # Set referrer to base URL
        self.session.headers.update({
            'Referer': self.base_url
        })
        
        # Apply cookies if provided
        if cookies:
            self.session.cookies.update(cookies)
            
        # Apply proxies if provided
        if proxies:
            self.session.proxies.update(proxies)
        
        # Create output directory
        ensure_directory_exists(output_dir)
        ensure_directory_exists(self.output_dir)
        
        # Create a simple crawler attribute to handle link discovery callbacks
        class SimpleCrawler:
            def __init__(self):
                self.link_discovery_callback = None
                
        self.crawler = SimpleCrawler()
        
        # Set logging level based on verbose flag
        if verbose:
            logger.setLevel(logging.DEBUG)
            logger.debug("Verbose logging enabled for scraper")
        
        logger.info(f"Initialized scraper for {base_url}")
        logger.info(f"Output directory: {self.output_dir}")
        logger.info(f"Site-specific folder: {self.site_folder}")
    
    def _is_same_domain(self, url: str) -> bool:
        """
        Improved domain comparison to handle subdomains and common doc site patterns.
        
        Args:
            url: URL to check
            
        Returns:
            Whether the URL is from the same domain
        """
        try:
            base_parsed = urlparse(self.base_url)
            url_parsed = urlparse(url)
            
            base_domain = base_parsed.netloc
            url_domain = url_parsed.netloc
            
            # Exact domain match
            if base_domain == url_domain:
                return True
            
            # Subdomain check
            base_parts = base_domain.split('.')
            url_parts = url_domain.split('.')
            
            # Compare base domains (e.g., example.com matches with docs.example.com)
            if len(base_parts) >= 2 and len(url_parts) >= 2:
                base_root = '.'.join(base_parts[-2:])  # e.g., example.com
                url_root = '.'.join(url_parts[-2:])    # e.g., example.com
                
                if base_root == url_root:
                    return True
                
            # Documentation specific: special cases for known doc platforms
            doc_patterns = ['docs.', 'documentation.', 'help.', 'support.', 'guide.', 'developer.']
            
            # Check if the URL is a docs subdomain of the base domain
            for pattern in doc_patterns:
                if url_domain.startswith(pattern) and url_domain.endswith(base_domain[base_domain.find('.'):]):
                    return True
                
            # Check if the base is a docs subdomain of the URL domain
            for pattern in doc_patterns:
                if base_domain.startswith(pattern) and base_domain.endswith(url_domain[url_domain.find('.'):]):
                    return True
                
            return False
        except Exception as e:
            logger.debug(f"Domain comparison error: {e}")
            return False
            
    def _is_valid_url(self, url: str) -> bool:
        """
        Check if a URL is valid and should be crawled.
        
        Args:
            url: URL to check
            
        Returns:
            Whether the URL should be crawled
        """
        # Skip fragment-only URLs
        if url.startswith('#'):
            return False
            
        # Skip mailto links
        if url.startswith('mailto:'):
            return False
            
        # Check if it's a full URL or relative path
        if '://' in url:
            return self._is_same_domain(url)
        else:
            return True

    def _normalize_url(self, url: str, base_url: str) -> str:
        """
        Normalize a URL by resolving it against the base URL.
        
        Args:
            url: URL to normalize
            base_url: Base URL to resolve against
            
        Returns:
            Normalized URL
        """
        try:
            # Handle URL parameters more intelligently
            full_url = urljoin(base_url, url)
            
            # Parse the URL to get its components
            parsed = urlparse(full_url)
            
            # Handle common URL parameters that don't change content
            query_params = parse_qs(parsed.query)
            
            # Keep important content-related parameters (like lang, version)
            # but remove tracking parameters
            content_params = ['lang', 'version', 'v', 'platform']
            filtered_params = {
                k: v for k, v in query_params.items() 
                if k.lower() in content_params
            }
            
            # Rebuild the query string with only content params
            if filtered_params:
                query_string = urlencode(filtered_params, doseq=True)
                # Rebuild the URL with the filtered query string
                parsed = parsed._replace(query=query_string)
            else:
                # If no important params, remove the query string
                parsed = parsed._replace(query='')
                
            # Remove fragments (anchors) from URLs
            parsed = parsed._replace(fragment='')
            
            # Recreate the URL
            normalized_url = parsed.geturl()
            
            return normalized_url
        except Exception as e:
            logger.error(f"Error normalizing URL {url}: {e}")
            return url
    
    def _matches_url_filters(self, url: str) -> bool:
        """
        Check if a URL matches the filtering patterns.
        
        Args:
            url: URL to check
            
        Returns:
            True if URL should be included, False if it should be excluded
        """
        # If include patterns are specified, URL must match at least one
        if self.url_include_regex and not any(pattern.search(url) for pattern in self.url_include_regex):
            logger.debug(f"URL excluded (no include match): {url}")
            return False
            
        # If URL matches any exclude pattern, it's excluded
        if any(pattern.search(url) for pattern in self.url_exclude_regex):
            logger.debug(f"URL excluded (exclude match): {url}")
            return False
            
        return True
    
    def is_valid_doc_url(self, url: str) -> bool:
        """
        Enhanced URL validation with more permissive rules for documentation sites.
        """
        if not url:
            logger.debug(f"URL invalid (empty): {url}")
            return False

        # More permissive URL validation - many doc sites have strange URL structures
        try:
            parsed = urlparse(url)
            if not parsed.scheme and not parsed.netloc:
                logger.debug(f"URL invalid (no scheme/domain): {url}")
                return False
                
            # Get domain and path parts safely
            base_domain = urlparse(self.base_url).netloc
            url_domain = parsed.netloc
            
            # Get path parts safely - ensure we have lists
            base_path = urlparse(self.base_url).path.strip('/')
            url_path = parsed.path.strip('/')
            
            base_path_parts = base_path.split('/') if base_path else []
            url_path_parts = url_path.split('/') if url_path else []
            
            # Check if this is a strict documentation URL check
            # The base domain must match exactly or be a direct subdomain relationship
            domain_match = (
                url_domain == base_domain or 
                (url_domain.endswith(f".{base_domain}") and "docs" in url_domain) or
                (base_domain.endswith(f".{url_domain}") and "docs" in base_domain)
            )
            
            if not domain_match:
                logger.debug(f"URL invalid (different domain): {url} vs {base_domain}")
                return False
    
            # Skip asset files if we're not including assets
            if not self.include_assets and is_asset_url(url):
                logger.debug(f"URL invalid (asset, assets not included): {url}")
                return False
    
            # Enforce documentation path patterns
            # If the base URL has a specific path prefix (like /get-started/),
            # require that the scraped URLs maintain a similar structure
            if base_path_parts and url_domain == base_domain:
                doc_prefixes = ['docs', 'guide', 'documentation', 'help', 'reference', 'api', 'get-started', 'guides']
                
                # Check for valid documentation paths
                path_match = False
                
                # Check if URL starts with the same base path component
                if url_path_parts and url_path_parts[0] == base_path_parts[0]:
                    path_match = True
                
                # Check if URL contains a documentation path pattern
                for prefix in doc_prefixes:
                    if f"/{prefix}/" in url.lower():
                        path_match = True
                        break
                
                # Check if URL's first path component is a documentation prefix
                if url_path_parts and url_path_parts[0].lower() in doc_prefixes:
                    path_match = True
                
                if not path_match:
                    logger.debug(f"URL invalid (not in documentation path): {url}")
                    return False
    
            # Less restrictive common exclusion - only exclude obvious non-doc paths
            exclusion_patterns = [
                '/auth/', '/login/', '/logout/', '/signup/',
                '/admin/', '/account/', '/billing/', '/pricing/'
            ]
            
            # Add logging for troubleshooting
            for pattern in exclusion_patterns:
                if pattern in url.lower():
                    logger.debug(f"URL invalid (matches exclusion pattern {pattern}): {url}")
                    return False
    
            # Apply custom URL filters if provided
            if not self._matches_url_filters(url):
                return False
    
            # Skip known problematic URLs
            if url in self.skip_urls:
                logger.debug(f"URL invalid (in hardcoded skip list): {url}")
                return False
    
            logger.debug(f"URL valid for processing: {url}")
            return True
            
        except Exception as e:
            logger.warning(f"Error validating URL {url}: {e}")
            return False
    
    def extract_title(self, soup: BeautifulSoup) -> str:
        """
        Extract the title of the page from HTML.
        
        Args:
            soup: Parsed HTML
            
        Returns:
            Page title
        """
        # First try to find the <title> tag
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text().strip()
            # Often title contains site name after a separator - remove it
            for separator in [' | ', ' - ', ' — ', ' – ', ' :: ', ' // ']:
                if separator in title:
                    title = title.split(separator)[0].strip()
            return title
            
        # Look for main heading
        for heading in ['h1', 'h2']:
            heading_tag = soup.find(heading)
            if heading_tag:
                return heading_tag.get_text().strip()
        
        # Fall back to URL-based title
        parsed_url = urlparse(self.base_url)
        path = parsed_url.path.strip('/')
        return path.split('/')[-1].replace('-', ' ').replace('_', ' ').title() if path else "Documentation"
    
    def extract_links(self, soup: BeautifulSoup, current_url: str) -> List[str]:
        """
        Extract links with improved handling for modern documentation sites.
        """
        links = []
        added_links: Set[str] = set()
        
        # Prepare categorized links for callback
        doc_links = []
        aux_links = []
        external_links = []
        asset_links = []

        # Special handling for cursor.com documentation
        if 'cursor.com' in current_url or 'docs.cursor.com' in current_url:
            logger.info("Detected Cursor documentation site - using special handling")
            
            # Find sidebar navigation links - specific to cursor.com docs
            sidebar_links = self._extract_cursor_docs_links(soup, current_url)
            if sidebar_links:
                for link in sidebar_links:
                    if link not in added_links:
                        links.append(link)
                        added_links.add(link)
                        doc_links.append(link)  # Categorize as documentation links
                        logger.debug(f"Found Cursor docs link: {link}")

        # Find all <a> tags with more comprehensive selectors
        selectors = [
            'a[href]',                   # Standard links
            '[role="link"]',             # Accessibility links
            '.nav-link',                 # Bootstrap navigation
            '.sidebar a',                # Sidebar navigation links
            '.menu a',                   # Menu links
            '.toc a',                    # Table of contents links
            'nav a',                     # Navigation links
            '.navigation a',             # Another navigation pattern
            '.doc-nav a',                # Documentation navigation
            '.mdx-content a',            # MDX content links
            '.md-content a',             # Markdown content links
            '.prose a',                  # Common prose/content links
            '[data-testid*="link"]',     # React Testing Library patterns
            '[data-testid*="nav"]',      # React Testing Library navigation
            '.MuiLink-root',             # Material UI links
            '.chakra-link',              # Chakra UI links
            'header a',                  # Header links
            'footer a',                  # Footer links
            '.header-link',              # Header links for anchors
        ]
        
        link_elements = soup.select(', '.join(selectors))
        logger.debug(f"Found {len(link_elements)} potential link elements")
        
        for link in link_elements:
            href = None
            
            # Extract href from different attribute patterns
            if link.has_attr('href'):
                href = link['href']
            elif link.has_attr('data-href'):
                href = link['data-href']
            elif link.has_attr('data-url'):
                href = link['data-url']
            elif link.has_attr('to'):  # React Router links
                href = link['to']
            
            if not href:
                continue

            # Skip common non-content links
            if href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue
            
            # Handle relative URLs more thoroughly
            try:
                # First try standard normalization
                normalized_url = self._normalize_url(href, current_url)
                
                # If that fails, try other common patterns
                if not normalized_url:
                    if href.startswith('/'):
                        # Absolute path relative to domain
                        normalized_url = f"{self.domain}{href}"
                    elif href.startswith('./'):
                        # Explicit relative path
                        normalized_url = urljoin(current_url, href[2:])
                    
                if not normalized_url:
                    continue
                
                # Check if it's an external link
                is_external = not normalized_url.startswith(self.domain)
                
                # If external, add to external links and continue
                if is_external:
                    if normalized_url not in added_links:
                        external_links.append(normalized_url)
                        added_links.add(normalized_url)
                    continue
                
                # Clean URL
                cleaned_url = clean_url(normalized_url)
                
                # Add URL with proper scheme if missing
                if not cleaned_url.startswith(('http://', 'https://')):
                    base_scheme = urlparse(self.base_url).scheme
                    if cleaned_url.startswith('//'):
                        cleaned_url = f"{base_scheme}:{cleaned_url}"
                    elif cleaned_url.startswith('/'):
                        cleaned_url = f"{self.domain}{cleaned_url}"
                    else:
                        cleaned_url = urljoin(current_url, cleaned_url)
                
                # Check if we've already processed this link in this function call
                if cleaned_url not in added_links:
                    # Categorize the link
                    if is_asset_url(cleaned_url):
                        asset_links.append(cleaned_url)
                    else:
                        # Try to determine if this is a documentation or auxiliary link
                        is_doc_link = self._is_documentation_link(cleaned_url)
                        if is_doc_link:
                            doc_links.append(cleaned_url)
                        else:
                            aux_links.append(cleaned_url)
                    
                    links.append(cleaned_url)
                    added_links.add(cleaned_url)
                    logger.debug(f"Found link: {cleaned_url}")
                
            except Exception as e:
                logger.debug(f"Error processing link '{href}': {e}")
                continue

        # Also look for documentation-specific elements that might contain links
        doc_selectors = [
            '.sidebar-item', '.menu-item', '.toc-item', '.nav-item',
            '.sidebar-link', '.doc-link', '[data-type="link"]',
            '.docusaurus-highlight-code-line', '.theme-doc-sidebar-item',
            '[data-sidebar-item]', '[data-menu-id]'
        ]
        
        for menu_item in soup.select(', '.join(doc_selectors)):
            # Many doc sites have clickable elements that aren't standard <a> tags
            for clickable in menu_item.select('[class*="link"], [class*="item"], [data-path], [href], [to]'):
                path = None
                if clickable.has_attr('data-path'):
                    path = clickable['data-path']
                elif clickable.has_attr('data-target'):
                    path = clickable['data-target']
                elif clickable.has_attr('href'):
                    path = clickable['href']
                elif clickable.has_attr('to'):
                    path = clickable['to']
                    
                if path and not path.startswith(('#', 'javascript:')):
                    try:
                        url = urljoin(self.domain, path)
                        if url not in added_links:
                            # Special case - these are almost always documentation links
                            doc_links.append(url)
                            links.append(url)
                            added_links.add(url)
                            logger.debug(f"Found menu link: {url}")
                    except Exception:
                        pass

        # Special case for SPAs like Next.js, Gatsby, Nuxt
        # Look for data attributes containing paths
        for element in soup.select('[data-href], [data-url], [data-path], [href], [to]'):
            for attr in ['data-href', 'data-url', 'data-path', 'href', 'to']:
                if element.has_attr(attr) and element[attr] and not element[attr].startswith(('#', 'javascript:')):
                    try:
                        path = element[attr]
                        url = urljoin(self.domain, path)
                        if url not in added_links and url.startswith(self.domain):
                            # For SPA links, check if it's a documentation link
                            is_doc_link = self._is_documentation_link(url)
                            if is_doc_link:
                                doc_links.append(url)
                            else:
                                aux_links.append(url)
                                
                            links.append(url)
                            added_links.add(url)
                            logger.debug(f"Found SPA link: {url}")
                    except Exception:
                        pass

        logger.info(f"Extracted {len(links)} potential links from {current_url}")
        
        # If we have a link discovery callback, call it with the categorized links
        if hasattr(self, 'crawler') and self.crawler and hasattr(self.crawler, 'link_discovery_callback') and self.crawler.link_discovery_callback:
            # Call the callback with the categorized links
            self.crawler.link_discovery_callback({
                'doc': doc_links,
                'aux': aux_links,
                'external': external_links,
                'asset': asset_links
            })
        
        return links
    
    def _extract_cursor_docs_links(self, soup: BeautifulSoup, current_url: str) -> List[str]:
        """Special handling for Cursor documentation site links."""
        links = []
        
        # Known sections in the Cursor documentation
        known_sections = [
            "/get-started/welcome",
            "/get-started/introduction",
            "/get-started/installation",
            "/faq",
            "/guides/migration/vscode",
            "/guides/migration/jetbrains",
            "/guides/languages/python",
            "/guides/languages/javascript",
            "/guides/languages/swift",
            "/guides/languages/java",
            "/guides/ai/chat",
            "/guides/ai/commands",
            "/guides/ai/documentation",
        ]
        
        # Add all known pages explicitly
        for section in known_sections:
            if section != "/faq":  # Skip FAQ if it's in excluded patterns
                url = f"https://docs.cursor.com{section}"
                links.append(url)
                
        # Extract any link with href attribute containing 'cursor.com'
        for link in soup.select('a[href*="cursor.com"], a[href^="/"]'):
            if link.has_attr('href'):
                href = link['href']
                if href.startswith('/'):
                    url = f"https://docs.cursor.com{href}"
                else:
                    url = href
                    
                if url not in links and 'cursor.com' in url:
                    links.append(url)
        
        return links
    
    def extract_assets(self, soup: BeautifulSoup, current_url: str) -> List[str]:
        """
        Extract asset URLs from the page content.
        
        Args:
            soup: Parsed HTML
            current_url: URL of the current page
            
        Returns:
            List of asset URLs found
        """
        if not self.include_assets:
            return []
            
        assets = []
        
        # Extract image sources
        for img in soup.find_all('img', src=True):
            src = img.get('src')
            normalized_url = self._normalize_url(src, current_url)
            if normalized_url and normalized_url not in self.visited and is_asset_url(normalized_url):
                assets.append(normalized_url)
                self.queued.add(normalized_url)
        
        # Extract stylesheet links
        for link in soup.find_all('link', rel='stylesheet', href=True):
            href = link.get('href')
            normalized_url = self._normalize_url(href, current_url)
            if normalized_url and normalized_url not in self.visited and is_asset_url(normalized_url):
                assets.append(normalized_url)
                self.queued.add(normalized_url)
        
        # Extract script sources
        for script in soup.find_all('script', src=True):
            src = script.get('src')
            normalized_url = self._normalize_url(src, current_url)
            if normalized_url and normalized_url not in self.visited and is_asset_url(normalized_url):
                assets.append(normalized_url)
                self.queued.add(normalized_url)
        
        return assets
    
    def _download_with_retries(self, url: str) -> requests.Response:
        """Download a URL with retry logic, exponential backoff, and better error handling."""
        for attempt in range(self.max_retries):
            try:
                # Customize headers for each request to look more like a browser
                custom_headers = {
                    'User-Agent': self.session.headers.get('User-Agent', 
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Referer': self.base_url,
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Cache-Control': 'max-age=0',
                    'TE': 'Trailers',
                }
                
                # Add a slightly randomized delay to appear more human-like
                import random
                if attempt > 0:
                    jitter = random.uniform(0.1, 0.5)
                    wait_time = min((2 ** attempt) * 0.5 + jitter, 10)
                    logger.debug(f"Retry {attempt + 1}/{self.max_retries} for {url} in {wait_time:.2f}s")
                    time.sleep(wait_time)
                
                response = self.session.get(
                    url,
                    headers=custom_headers,
                    timeout=self.timeout,
                    allow_redirects=True
                )
                
                # Handle common status codes
                if response.status_code == 429:  # Too Many Requests
                    logger.warning(f"Rate limited on {url}, retrying after longer delay")
                    time.sleep(min(30, 5 * (attempt + 1)))  # Longer delay for rate limiting
                    continue
                    
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                if attempt == self.max_retries - 1:
                    logger.error(f"Failed to download {url} after {self.max_retries} attempts: {e}")
                    raise
        
        # This should never be reached due to the raise in the exception handler
        raise requests.exceptions.RequestException(f"Failed to download {url} after {self.max_retries} attempts")
    
    def download_page(self, url: str) -> Tuple[str, str, List[str]]:
        try:
            # Check for stop event before processing
            stop_event = self.stop_event
            if stop_event and stop_event.is_set():
                logger.info(f"Skipping download of {url} due to stop event")
                return "", "", []
            
            # Use Selenium for browser mode to handle JavaScript-rendered pages
            if self.browser_mode:
                logger.info(f"Using browser mode for {url}")
                
                try:
                    # Early bail-out if stop requested during setup
                    if stop_event and stop_event.is_set():
                        logger.info(f"Stopping before browser setup for {url}")
                        return "", "", []
                    
                    # Configure headless Chrome browser with improved options
                    chrome_options = Options()
                    chrome_options.add_argument("--headless")
                    chrome_options.add_argument("--no-sandbox")
                    chrome_options.add_argument("--disable-dev-shm-usage")
                    chrome_options.add_argument("--disable-gpu")
                    chrome_options.add_argument("--ignore-certificate-errors")  # Handle SSL issues
                    chrome_options.add_argument("--ignore-ssl-errors")          # Handle SSL issues
                    chrome_options.add_argument("--incognito")                  # Avoid cookie banners
                    chrome_options.add_argument(f"user-agent={self.session.headers.get('User-Agent')}")
                    # Add a short timeout to allow faster browser closure
                    chrome_options.add_argument("--page-load-strategy=eager")  # Don't wait for all resources
                    
                    logger.debug(f"Browser mode: initializing Chrome driver for {url}")
                    
                    # Create a new browser instance for each page to avoid memory issues
                    try:
                        driver = webdriver.Chrome(
                            service=Service(ChromeDriverManager().install()),
                            options=chrome_options
                        )
                        # Add to active browsers list for cleanup
                        self.active_browser_instances.append(driver)
                    except Exception as e:
                        logger.error(f"Error initializing Chrome driver: {e}")
                        logger.info("Falling back to regular request mode")
                        raise  # Will be caught by outer exception handler
                    
                    # Set page load timeout - shorter timeout for faster response to stop events
                    driver.set_page_load_timeout(min(10, self.timeout))
                    
                    try:
                        # Check for stop event again before loading page
                        if stop_event and stop_event.is_set():
                            logger.info(f"Stopping before loading {url}")
                            driver.quit()
                            if driver in self.active_browser_instances:
                                self.active_browser_instances.remove(driver)
                            return "", "", []
                            
                        # Load the page
                        logger.debug(f"Browser mode: loading page {url}")
                        driver.get(url)
                        
                        # Check for stop event immediately after page load
                        if stop_event and stop_event.is_set():
                            logger.info(f"Stopping after initial page load of {url}")
                            driver.quit()
                            if driver in self.active_browser_instances:
                                self.active_browser_instances.remove(driver)
                            return "", "", []
                        
                        # Wait for dynamic content to load - more sophisticated approach
                        try:
                            from selenium.webdriver.common.by import By
                            from selenium.webdriver.support.ui import WebDriverWait
                            from selenium.webdriver.support import expected_conditions as EC
                            
                            # Wait for typical documentation page elements to load
                            logger.debug(f"Browser mode: waiting for page elements to load")
                            WebDriverWait(driver, 5).until(  # Shorter timeout for faster stop response
                                EC.presence_of_element_located((By.CSS_SELECTOR, 
                                    ".content, main, article, .documentation, .doc-content, .markdown-body, nav, .sidebar, h1"))
                            )
                            logger.debug(f"Browser mode: page elements loaded")
                        except Exception as e:
                            # If timeout or other error, just use what we have
                            logger.warning(f"Browser mode: timed out waiting for page elements on {url}: {e}")
                            # Add a small fallback delay to ensure at least some content is loaded
                            time.sleep(1)  # Shorter sleep for faster stop response
                        
                        # Check for stop event again before processing content
                        if stop_event and stop_event.is_set():
                            logger.info(f"Stopping during page load of {url}")
                            driver.quit()
                            if driver in self.active_browser_instances:
                                self.active_browser_instances.remove(driver)
                            return "", "", []
                        
                        # Get the page source after JavaScript execution
                        html_content = driver.page_source
                        
                        if not html_content:
                            logger.warning(f"Browser mode: empty page source for {url}")
                            return "", "", []
                        
                        # Parse the HTML with fallback parsers
                        logger.debug(f"Browser mode: parsing HTML content")
                        try:
                            soup = BeautifulSoup(html_content, 'lxml')
                        except ImportError:
                            logger.warning("lxml parser not available, falling back to html.parser")
                            soup = BeautifulSoup(html_content, 'html.parser')
                        except Exception as e:
                            logger.error(f"Error parsing HTML with any parser: {e}")
                            return "", "", []
                        
                        # Final stop check before link extraction
                        if stop_event and stop_event.is_set():
                            logger.info(f"Stopping before link extraction for {url}")
                            driver.quit()
                            if driver in self.active_browser_instances:
                                self.active_browser_instances.remove(driver)
                            return "", "", []
                        
                        # Extract title
                        title = driver.title
                        if not title:
                            title_tag = soup.find('title')
                            title = title_tag.text if title_tag else url.split('/')[-1]
                            
                        logger.debug(f"Browser mode: extracted title: {title}")
                        
                        # Extract links after JavaScript has run
                        links = self.extract_links(soup, url)
                        logger.info(f"Browser mode: extracted {len(links)} links from {url}")
                        
                        # Extract assets if needed and not stopping
                        if self.include_assets and (not stop_event or not stop_event.is_set()):
                            assets = self.extract_assets(soup, url)
                            if assets:
                                self.download_assets(assets)
                        
                        return title, html_content, links
                        
                    finally:
                        # Always close the browser
                        try:
                            driver.quit()
                            if driver in self.active_browser_instances:
                                self.active_browser_instances.remove(driver)
                            logger.debug(f"Browser mode: browser closed for {url}")
                        except Exception as e:
                            logger.warning(f"Error closing browser: {e}")
                        
                except (TimeoutException, WebDriverException) as e:
                    logger.warning(f"Browser automation error for {url}: {e}. Falling back to regular request.")
                    # Fall back to regular request if browser automation fails
                except Exception as e:
                    logger.error(f"Unexpected error in browser mode for {url}: {e}")
                    # Try to provide more helpful error information for common issues
                    if "lxml" in str(e).lower():
                        logger.error("The lxml parser is required. Install it with: pip install lxml")
                    elif "chromedriver" in str(e).lower() or "webdriver" in str(e).lower():
                        logger.error("ChromeDriver is required. Install with: pip install webdriver-manager")
                    return "", "", []
            
            # Check for stop event before HTTP request
            if stop_event and stop_event.is_set():
                logger.info(f"Skipping HTTP request for {url} due to stop event")
                return "", "", []
                
            # Regular HTTP request (existing code)
            response = self._download_with_retries(url)
            html_content = response.text
            
            # Check for stop event after HTTP request
            if stop_event and stop_event.is_set():
                logger.info(f"Stopping after HTTP request for {url}")
                return "", "", []
            
            # Apply content filtering before processing
            if not self._matches_content_filters(html_content):
                return "", "", []
            
            # Parse HTML - try multiple parsers for better compatibility
            try:
                soup = BeautifulSoup(html_content, 'lxml')
            except ImportError:
                logger.warning("lxml parser not available, falling back to html.parser")
                soup = BeautifulSoup(html_content, 'html.parser')
            except Exception as e:
                logger.error(f"Error parsing HTML: {e}")
                soup = BeautifulSoup(html_content, 'html.parser')
            
            # Final stop check before completing
            if stop_event and stop_event.is_set():
                logger.info(f"Stopping before completing processing for {url}")
                return "", "", []
            
            # Extract title
            title_tag = soup.find('title')
            title = title_tag.text if title_tag else url.split('/')[-1]
            
            # Extract links
            links = self.extract_links(soup, url)
            logger.info(f"Regular mode: Extracted {len(links)} links from {url}")
            
            # Extract assets if needed and not stopping
            if self.include_assets and (not stop_event or not stop_event.is_set()):
                assets = self.extract_assets(soup, url)
                if assets:
                    self.download_assets(assets)
            
            return title, html_content, links
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f'Page not found (404): {url}')
                return None, None, None
            raise
            
        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")
            return "", "", []
    
    def _matches_content_filters(self, html_content: str) -> bool:
        """
        Check if page content matches the filtering patterns.
        
        Args:
            html_content: HTML content to check
            
        Returns:
            True if content should be included, False if it should be excluded
        """
        # If include patterns exist, content must match at least one
        if self.content_include_regex:
            if not any(pattern.search(html_content) for pattern in self.content_include_regex):
                logger.debug("Content excluded (no include match)")
                return False
                
        # If content matches any exclude pattern, it's excluded
        if any(pattern.search(html_content) for pattern in self.content_exclude_regex):
            logger.debug("Content excluded (exclude match)")
            return False
            
        return True
    
    def download_assets(self, assets: List[str]) -> None:
        """
        Download a list of asset files in the background.
        
        Args:
            assets: List of asset URLs to download
        """
        if not assets or not self.include_assets:
            return
            
        def download_asset_worker(url):
            try:
                response = self._download_with_retries(url)
                save_path = get_asset_path(url, self.output_dir)
                
                # Save the asset
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                    
                logger.debug(f"Saved asset: {url} -> {save_path}")
                self.assets_downloaded += 1
                
                if self.progress_callback:
                    self.progress_callback(url, self.assets_downloaded, None)
                    
                return True
            except Exception as e:
                logger.error(f"Error downloading asset {url}: {e}")
                return False
        
        # Use a thread pool to download assets concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrent_requests) as executor:
            futures = [executor.submit(download_asset_worker, url) for url in assets]
            concurrent.futures.wait(futures)
    
    def save_content(self, url: str, title: str, html_content: str) -> bool:
        """
        Convert HTML to the desired output format and save to file.
        
        Args:
            url: URL of the page
            title: Title of the page
            html_content: HTML content
            
        Returns:
            Whether the save was successful
        """
        try:
            # Convert HTML to the specified format
            converted_content = self.formatter.convert(html_content, url)
            
            # Create directory structure based on URL
            directory, filename = create_path_from_url(url, self.base_url, self.output_dir)
            
            # Update filename with the correct extension
            filename_base = os.path.splitext(filename)[0]
            filename = f"{filename_base}{self.formatter.file_extension}"
            
            # Create a separate metadata file with URL and title information
            # This helps with navigation and rebuilding the content
            metadata = {
                "url": url,
                "title": title,
                "date_downloaded": time.strftime("%Y-%m-%d %H:%M:%S"),
                "original_domain": self.domain,
            }
            
            # Create a _metadata directory to store metadata files
            metadata_dir = os.path.join(self.output_dir, "_metadata")
            ensure_directory_exists(metadata_dir)
            
            # Save metadata
            metadata_filename = f"{filename_base}.json"
            metadata_path = os.path.join(metadata_dir, metadata_filename)
            with open(metadata_path, 'w', encoding='utf-8') as f:
                import json
                json.dump(metadata, f, indent=2)
            
            # Create a summary index file to help navigate the documentation
            self._update_summary_index(url, title, directory, filename)
            
            # Detect language using langdetect
            from langdetect import detect, LangDetectException
            try:
                lang = detect(converted_content[:1000])
                logger.info(f"Language detected for {url}: {lang}")
            except LangDetectException:
                lang = 'unknown'
                logger.warning(f"Could not detect language for {url}")
            if lang != 'en':
                logger.info(f"Skipped non-English page: {url} (detected: {lang})")
                return False

            # Save the content file in the selected format
            file_path = os.path.join(directory, filename)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(yaml_frontmatter)
                f.write(converted_content)
            
            logger.info(f"Saved English page: {url} as {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving content for {url}: {e}")
            return False

    def _update_summary_index(self, url: str, title: str, directory: str, filename: str):
        """
        Update or create the summary index file for navigation, using a hierarchical nested structure.
        """
        try:
            import collections
            from datetime import datetime
            import os
            index_file = os.path.join(self.output_dir, "index.md")
            entries_file = os.path.join(self.output_dir, ".index_entries")
            relative_path = os.path.relpath(os.path.join(directory, filename), self.output_dir)
            entry = (url, title, relative_path)

            # Load or initialize the entries list
            entries = []
            if os.path.exists(entries_file):
                with open(entries_file, 'r', encoding='utf-8') as ef:
                    for line in ef:
                        url_, title_, rel_path_ = line.rstrip('\n').split('\t')
                        entries.append((url_, title_, rel_path_))
            if entry not in entries:
                entries.append(entry)
                with open(entries_file, 'a', encoding='utf-8') as ef:
                    ef.write(f"{url}\t{title}\t{relative_path}\n")
                logger.debug(f"Indexed document: {title} ({relative_path}) [URL: {url}]")

            # Build a tree structure from paths
            TreeNode = lambda: collections.defaultdict(TreeNode)
            tree = TreeNode()
            node_titles = {}
            for url_, title_, rel_path_ in entries:
                parts = rel_path_.split(os.sep)
                cur = tree
                for part in parts[:-1]:
                    cur = cur[part]
                cur[parts[-1]] = (title_, rel_path_)
                node_titles[rel_path_] = title_

            # Helper to render the tree as nested markdown
            def render_tree(node, depth=0):
                lines = []
                for key in sorted(node.keys()):
                    val = node[key]
                    if isinstance(val, dict):
                        # Section or folder
                        lines.append(f"{'  '*depth}- **{key.replace('-', ' ').replace('_', ' ').title()}**")
                        lines.extend(render_tree(val, depth+1))
                    else:
                        title_, rel_path_ = val
                        lines.append(f"{'  '*depth}- [{title_}]({rel_path_})")
                return lines

            # Header
            new_content = "# Documentation Index\n\n"
            new_content += f"**Source:** {self.base_url}\n\n"
            new_content += f"**Date Scraped:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            new_content += f"**Total Pages:** {len(entries)}\n\n"
            new_content += "---\n\n## Table of Contents\n\n"

            lines = render_tree(tree)
            new_content += '\n'.join(lines)
            new_content += '\n\n---\n\nThis index was automatically generated by Document Scraper.\n'

            with open(index_file, 'w', encoding='utf-8') as f:
                f.write(new_content)

        except Exception as e:
            logger.warning(f"Error updating index file: {e}")
            pass
    
    # Alias for backward compatibility
    save_markdown = save_content
    
    def crawl(self, start_urls: Optional[List[str]] = None, interactive: bool = False) -> Tuple[int, int]:
        """
        Crawl the documentation site starting from base_url or provided start_urls.
        
        Args:
            start_urls: Optional list of URLs to start crawling from. 
                        If None, defaults to the instance's base_url.
            interactive: Whether to enable interactive mode for user confirmation.

        Returns:
            Tuple of (pages_downloaded, assets_downloaded)
        """
        logger.info(f"Starting crawl from {self.base_url}")
        logger.info(f"Saving to site-specific folder: {self.site_folder}")
        logger.info(f"Interactive mode: {'enabled' if interactive else 'disabled'}")
        
        # Use the stop_event from the instance
        stop_event = self.stop_event
        
        # Clear any previously active futures/browsers for clean state
        self.active_futures = []
        self.active_browser_instances = []
        
        # Track if we should prompt for auxiliary content
        should_prompt_for_aux = interactive
        aux_links_to_prompt = set()
        
        # Determine starting points
        initial_urls = start_urls if start_urls else [self.base_url]
        if not initial_urls:
            logger.warning("No valid start URLs provided. Aborting crawl.")
            return 0, 0

        logger.info(f"Crawl targets: {initial_urls}")
        logger.info(f"Base domain for crawl: {self.domain}") # Log the identified domain

        # Queue to track URLs to visit and their depth
        queue = deque()
        valid_initial_urls = []
        for url in initial_urls:
            # Apply strict documentation URL validation even for initial URLs
            is_valid_initial = self.is_valid_doc_url(url)
            logger.info(f"Checking initial URL '{url}': Is valid doc URL? {is_valid_initial}")
            if is_valid_initial:
                 # Add initial URL to the queue regardless of filters at this stage
                 logger.info(f"Queueing initial URL: {url}")
                 queue.append((url, 0))
                 valid_initial_urls.append(url)
            else:
                logger.warning(f"Skipping initial URL '{url}' because it's not a valid documentation URL.")

        self.queued.update(valid_initial_urls) # Use the filtered list

        # Reset counters for this crawl session if called multiple times
        self.pages_downloaded = 0
        self.assets_downloaded = 0
        self.visited.clear() # Clear visited set for a fresh crawl
        self.failed_urls.clear()

        # Flag to track if we're in stopping state
        stopping = False
        
        with tqdm(total=self.max_pages, desc="Downloading pages", unit="page", disable=self.max_pages is None) as pbar:
            logger.info(f"Starting crawl with {len(queue)} URLs in queue")
            
            while queue and (self.max_pages is None or self.pages_downloaded < self.max_pages) and not stopping:
                # Check if we need to stop - do this at the beginning of each loop
                if stop_event and stop_event.is_set():
                    logger.warning("Stop event detected, halting crawl immediately...")
                    stopping = True
                    # Clear the queue to prevent further processing
                    queue.clear()
                    # Cancel any active futures and clean up browser instances
                    for future in self.active_futures:
                        future.cancel()
                    self._cleanup_browser_instances()
                    break
                    
                # Get the next batch of URLs to process
                batch = []
                for _ in range(min(self.concurrent_requests, len(queue))):
                    if not queue:
                        break
                    batch.append(queue.popleft())
                
                if not batch:
                    logger.warning("Queue is empty, ending crawl.")
                    break
                
                logger.info(f"Processing batch of {len(batch)} URLs")
                
                # Process the batch with concurrent requests
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrent_requests) as executor:
                    future_to_url = {
                        executor.submit(self.download_page, url): (url, depth) 
                        for url, depth in batch if not stopping
                    }
                    
                    # Store active futures for proper cancellation if needed
                    self.active_futures.extend(future_to_url.keys())
                    
                    for future in concurrent.futures.as_completed(future_to_url):
                        # Remove from active futures once completed
                        if future in self.active_futures:
                            self.active_futures.remove(future)
                        
                        # Check for stop event after each completion
                        if stop_event and stop_event.is_set():
                            logger.warning("Stop event detected during batch processing, halting immediately...")
                            stopping = True
                            # Cancel remaining futures in this batch
                            for remaining_future in list(future_to_url.keys()):
                                if remaining_future != future:  # Don't cancel the one we just completed
                                    remaining_future.cancel()
                            # Clear the queue
                            queue.clear()
                            break
                            
                        # Skip processing if we're stopping
                        if stopping:
                            continue
                            
                        url, depth = future_to_url[future]
                        self.visited.add(url)
                        
                        try:
                            title, html_content, links = future.result()
                            if title and html_content:
                                success = self.save_content(url, title, html_content)
                                if success:
                                    self.pages_downloaded += 1
                                    pbar.update(1)
                                    logger.info(f"Downloaded page {self.pages_downloaded}: {url}")
                                    logger.info(f"  Found {len(links)} links on this page")
                                    
                                    # Call progress callback if provided
                                    if self.progress_callback:
                                        total = self.max_pages # Use max_pages as total if set
                                        self.progress_callback(url, self.pages_downloaded, total)
                            else:
                                logger.warning(f"No content or title for {url}")
                        except Exception as e:
                            logger.error(f"Error processing {url}: {e}")
                        
                        # Only add new links if we're not stopping
                        if depth < self.max_depth and not stopping:
                            added_count = 0
                            doc_links_added = 0
                            aux_links_added = 0
                            
                            for link in links:
                                # Skip if we're stopping
                                if stopping:
                                    break
                                    
                                # Full validation check with strict documentation validation
                                if (link not in self.visited and
                                    link not in self.queued and
                                    self.is_valid_doc_url(link)):
                                    
                                    # Check if link already exists in the queue
                                    if not any(item[0] == link for item in queue):
                                        # Check if this is a documentation or auxiliary link
                                        is_doc_link = self._is_documentation_link(link)
                                        
                                        # Add to the queue and track for stats
                                        queue.append((link, depth + 1))
                                        self.queued.add(link)
                                        added_count += 1
                                        
                                        if is_doc_link:
                                            doc_links_added += 1
                                        else:
                                            aux_links_added += 1
                                            # Track auxiliary links for interactive mode
                                            if should_prompt_for_aux:
                                                aux_links_to_prompt.add(link)
                                        
                                        logger.debug(f"Queued new link: {link} ({'doc' if is_doc_link else 'aux'})")
                            
                            # Log stats about newly added links
                            logger.info(f"Added {added_count} new links to queue from {url} ({doc_links_added} doc, {aux_links_added} aux)")
                            logger.info(f"Queue now has {len(queue)} URLs")
                
                # Check for stop event before delay
                if stop_event and stop_event.is_set():
                    logger.warning("Stop event detected before delay, halting immediately...")
                    stopping = True
                    queue.clear()
                    break
                
                # If in interactive mode and we have enough auxiliary links to prompt for,
                # notify through the link discovery callback
                if should_prompt_for_aux and len(aux_links_to_prompt) >= 5 and hasattr(self, 'crawler') and self.crawler.link_discovery_callback:
                    logger.info(f"Found {len(aux_links_to_prompt)} auxiliary links, notifying for interactive decision")
                    self.crawler.link_discovery_callback({
                        'aux': list(aux_links_to_prompt),
                        'doc': [],
                        'external': [],
                        'asset': []
                    })
                    # Clear the set after notification
                    aux_links_to_prompt.clear()
                
                # Respect the delay between batches, but don't delay if we're stopping
                if self.delay > 0 and queue and not stopping:
                    time.sleep(self.delay)
            
            # If we're stopping or finished naturally, clean up resources
            if stopping or not queue:
                logger.warning("Cleaning up resources...")
                # Cancel all remaining futures
                for future in self.active_futures:
                    future.cancel()
                # Close any active browser instances
                self._cleanup_browser_instances()
        
        # Create main index file before finishing
        self.create_main_index()
        
        # Report results
        logger.info(f"Crawl completed: {self.pages_downloaded} pages downloaded")
        if self.include_assets:
            logger.info(f"{self.assets_downloaded} assets downloaded")
        
        # Log any failures
        if self.failed_urls:
            logger.warning(f"Failed to download {len(self.failed_urls)} URLs")
            for url, error in list(self.failed_urls.items())[:10]:  # Show first 10 failures
                logger.warning(f"  {url}: {error}")
        
        return self.pages_downloaded, self.assets_downloaded
    
    def _cleanup_browser_instances(self):
        """Clean up any active browser instances to ensure proper shutdown."""
        for driver in self.active_browser_instances:
            try:
                driver.quit()
                logger.debug("Browser instance closed during cleanup")
            except Exception as e:
                logger.warning(f"Error closing browser instance: {e}")
        
        # Clear the list after cleanup
        self.active_browser_instances.clear()
    
    def create_main_index(self):
        """
        Create a main index file that provides navigation for scraped documentation.
        """
        try:
            # Create an index.md file at the root of the output directory
            index_path = os.path.join(self.output_dir, "index.md")
            
            # Define sections based on documentation structure
            sections = {}
            
            # Go through all successfully saved pages
            metadata_dir = os.path.join(self.output_dir, "_metadata")
            if os.path.exists(metadata_dir):
                import json
                import glob
                
                # Find all metadata files
                metadata_files = glob.glob(os.path.join(metadata_dir, "*.json"))
                
                for file_path in metadata_files:
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                            
                        url = metadata.get('url', '')
                        title = metadata.get('title', '')
                        
                        if url and title:
                            # Determine section based on URL structure
                            parsed_url = urlparse(url)
                            path_parts = parsed_url.path.strip('/').split('/')
                            
                            # First path part often indicates section
                            section = path_parts[0] if path_parts else "General"
                            section = section.replace('-', ' ').replace('_', ' ').title()
                            
                            # Store info in sections dict
                            if section not in sections:
                                sections[section] = []
                                
                            # Get the relative file path from metadata
                            # This assumes create_path_from_url produces deterministic results
                            rel_path = file_path.replace(metadata_dir, '').replace('.json', '.md').lstrip('\\/')
                            
                            # Get actual file path
                            file_parts = path_parts[:-1] if len(path_parts) > 1 else []
                            file_name = path_parts[-1] if path_parts else "index"
                            actual_path = os.path.join(*(file_parts + [file_name])) if file_parts else file_name
                            actual_path = f"{actual_path}.md"
                            
                            sections[section].append((title, actual_path, url))
                    except Exception as e:
                        logger.warning(f"Error processing metadata file {file_path}: {e}")
                        continue
            
            # If no metadata files, use URLs directly
            if not sections and self.visited:
                # Structure by the first URL path component
                for url in sorted(self.visited):
                    parsed = urlparse(url)
                    path_parts = parsed.path.strip('/').split('/')
                    
                    # Determine section
                    section = path_parts[0] if path_parts else "General"
                    section = section.replace('-', ' ').replace('_', ' ').title()
                    
                    # Get a title from URL
                    title = path_parts[-1] if path_parts else "Index"
                    title = title.replace('-', ' ').replace('_', ' ').title()
                    
                    # Store in sections
                    if section not in sections:
                        sections[section] = []
                        
                    # Use a filename derived from URL
                    filename = f"{path_parts[-1] if path_parts else 'index'}.md"
                    sections[section].append((title, filename, url))
            
            # Create the index file
            with open(index_path, 'w', encoding='utf-8') as f:
                # Write header
                f.write("# Documentation Index\n\n")
                f.write(f"Documentation for {self.domain}, scraped on {time.strftime('%Y-%m-%d')}.\n\n")
                
                # Write each section
                for section_name, entries in sorted(sections.items()):
                    f.write(f"## {section_name}\n\n")
                    
                    for title, path, url in sorted(entries, key=lambda x: x[0]):
                        f.write(f"- [{title}]({path})\n")
                    
                    f.write("\n")
                    
                # Write a summary
                f.write(f"---\n\n")
                f.write(f"**Total Pages:** {self.pages_downloaded}\n\n")
                f.write(f"**Date Scraped:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"**Source:** {self.base_url}\n\n")
                
            logger.info(f"Created main index file at {index_path}")
            
        except Exception as e:
            logger.error(f"Error creating main index file: {e}")
            # Don't raise the exception, just log it

    def _is_documentation_link(self, url: str) -> bool:
        """
        Check if a URL is likely to be a documentation link.
        
        Args:
            url: URL to check
            
        Returns:
            True if URL is likely a documentation link, False otherwise
        """
        # Get the path part of the URL
        path = urlparse(url).path.lower()
        
        # Check for documentation-related path patterns
        doc_patterns = [
            '/docs/', '/documentation/', '/guide/', '/guides/', '/reference/',
            '/api/', '/manual/', '/tutorial/', '/tutorials/', '/learn/',
            '/help/', '/faq/', '/support/', '/get-started/', '/quick-start/',
            '/examples/', '/how-to/', '-reference', '/concepts/', '/overview/'
        ]
        
        for pattern in doc_patterns:
            if pattern in path:
                return True
                
        # Check for documentation-related terms in the path's last segment
        last_segment = path.split('/')[-1]
        doc_terms = [
            'overview', 'intro', 'introduction', 'reference', 'guide', 'tutorial',
            'example', 'usage', 'started', 'setup', 'config', 'configuration',
            'install', 'migration', 'api', 'docs', 'doc', 'manual', 'faq', 'help'
        ]
        
        for term in doc_terms:
            if term in last_segment:
                return True
                
        # If path seems like a documentation structure (e.g., /docs/section/page)
        path_parts = path.strip('/').split('/')
        if len(path_parts) >= 2 and path_parts[0] in ['docs', 'documentation', 'guide', 'guides', 'reference']:
            return True
            
        # Default to False - if none of the patterns matched
        return False


def scrape_documentation(base_url: str, output_dir: str, **kwargs) -> Tuple[int, int]:
    """
    Convenience function to scrape documentation with default settings.
    
    Args:
        base_url: The base URL of the documentation site
        output_dir: Directory where to save the downloaded files
        **kwargs: Additional arguments to pass to DocumentationScraper
        
    Returns:
        Tuple of (pages_downloaded, assets_downloaded)
    """
    scraper = DocumentationScraper(base_url, output_dir, **kwargs)
    return scraper.crawl()
