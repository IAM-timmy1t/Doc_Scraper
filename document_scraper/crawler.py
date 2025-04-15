"""
Advanced web crawler for documentation websites.

This module provides a specialized crawler for documentation sites,
with intelligent link prioritization and categorization.
"""

import os
import time
import logging
import re
import requests
import traceback
from tqdm import tqdm
import concurrent.futures
from bs4 import BeautifulSoup
from collections import deque
from urllib.parse import urlparse, urljoin, parse_qs, urlencode
from typing import List, Dict, Tuple, Set, Optional, Callable, Any, Union

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

from document_scraper.utils import (
    is_asset_url, clean_url, normalize_url, get_domain, is_valid_url,
    rate_limit, extract_path_segments
)

logger = logging.getLogger("document_scraper")

# Constants for URL categorization
DOC_PATTERNS = [
    '/docs/', '/doc/', '/documentation/', '/guide/', '/guides/', 
    '/reference/', '/api/', '/manual/', '/tutorial/', '/get-started/',
    '/learn/', '/howto/', '/usage/', '/examples/', '/quickstart/',
    '/sdk/', '/cli/', '/faq/', '/help/'
]

AUX_PATTERNS = [
    '/account/', '/profile/', '/settings/', '/user/',
    '/pricing/', '/billing/', '/subscription/', '/payment/', '/plans/',
    '/about/', '/company/', '/team/', '/contact/', '/support/',
    '/legal/', '/terms/', '/privacy/', '/blog/', '/news/'
]

class Crawler:
    """
    Advanced web crawler optimized for documentation websites.
    Prioritizes documentation-related links and intelligently categorizes content.
    """
    
    def __init__(self, 
                base_url: str, 
                max_depth: int = 5,
                delay: float = 0.5, 
                max_pages: Optional[int] = None,
                concurrent_requests: int = 5,
                timeout: int = 30,
                retries: int = 3,
                user_agent: Optional[str] = None,
                proxies: Optional[Dict[str, str]] = None,
                cookies: Optional[Dict[str, str]] = None,
                headers: Optional[Dict[str, str]] = None,
                browser_mode: bool = False,
                url_include_patterns: Optional[List[str]] = None,
                url_exclude_patterns: Optional[List[str]] = None,
                content_include_patterns: Optional[List[str]] = None,
                content_exclude_patterns: Optional[List[str]] = None,
                stop_event: Optional[Any] = None,
                progress_callback: Optional[Callable[[str, int, Optional[int]], None]] = None):
        """
        Initialize the crawler with configuration options.
        
        Args:
            base_url: The base URL to start crawling from
            max_depth: Maximum crawl depth
            delay: Delay between requests in seconds
            max_pages: Maximum number of pages to crawl (None for unlimited)
            concurrent_requests: Number of concurrent requests
            timeout: Request timeout in seconds
            retries: Number of times to retry failed requests
            user_agent: Custom user agent string
            proxies: Dictionary mapping protocol to proxy URL
            cookies: Dictionary of cookies to include with requests
            headers: Dictionary of headers to include with requests
            browser_mode: Whether to use browser emulation for JavaScript rendering
            url_include_patterns: Only crawl URLs matching these patterns
            url_exclude_patterns: Exclude URLs matching these patterns
            content_include_patterns: Only include pages with content matching these patterns
            content_exclude_patterns: Exclude pages with content matching these patterns
            stop_event: Event to signal that crawling should stop
            progress_callback: Callback for reporting progress
        """
        # Base configuration
        self.base_url = base_url.rstrip('/')
        self.domain = get_domain(base_url)
        self.base_path = urlparse(base_url).path.strip('/')
        self.base_path_segments = self.base_path.split('/') if self.base_path else []
        
        # Crawling parameters
        self.max_depth = max_depth
        self.delay = delay
        self.max_pages = max_pages
        self.concurrent_requests = concurrent_requests
        self.timeout = timeout
        self.retries = retries
        self.browser_mode = browser_mode
        
        # State tracking
        self.visited: Set[str] = set()
        self.queued: Set[str] = set()
        self.pages_downloaded = 0
        self.failed_urls: Dict[str, str] = {}
        self.stop_event = stop_event
        self.progress_callback = progress_callback
        
        # URL categorization
        self.doc_links: Set[str] = set()  # Primary documentation links
        self.aux_links: Set[str] = set()  # Auxiliary links (billing, pricing, etc.)
        self.external_links: Set[str] = set()  # External links
        self.asset_links: Set[str] = set()  # Asset links (images, CSS, JS)
        
        # Link patterns (compile for better performance)
        self.url_include_patterns = url_include_patterns or []
        self.url_exclude_patterns = url_exclude_patterns or []
        self.content_include_patterns = content_include_patterns or []
        self.content_exclude_patterns = content_exclude_patterns or []
        
        import re
        self.url_include_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.url_include_patterns]
        self.url_exclude_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.url_exclude_patterns]
        self.content_include_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.content_include_patterns]
        self.content_exclude_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.content_exclude_patterns]
        
        # Setup session
        self.session = requests.Session()
        
        # Default to a modern browser user agent if none provided
        if not user_agent:
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
            
        # Browser-like headers
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
            
        # Setup browser options if using browser mode
        if self.browser_mode:
            if not SELENIUM_AVAILABLE:
                logger.warning("Browser mode requested but Selenium is not available. "
                              "Install selenium and webdriver-manager packages to enable browser mode.")
                self.browser_mode = False
            self.active_browser_instances = []
        
        logger.info(f"Initialized crawler for {base_url}")
        logger.info(f"Base domain: {self.domain}")
        logger.info(f"Base path: /{self.base_path}")

    def categorize_url(self, url: str) -> str:
        """
        Categorize a URL as documentation, auxiliary, external, or asset.
        
        Args:
            url: The URL to categorize
            
        Returns:
            Category as string: 'doc', 'aux', 'external', or 'asset'
        """
        # Skip if URL is invalid or None
        if not url:
            return 'invalid'
            
        # Check if it's an asset URL first
        if is_asset_url(url):
            return 'asset'
            
        # Check if it's an external URL
        parsed_url = urlparse(url)
        if parsed_url.netloc and parsed_url.netloc != urlparse(self.domain).netloc:
            # Check for related documentation subdomains
            base_domain_parts = urlparse(self.domain).netloc.split('.')
            url_domain_parts = parsed_url.netloc.split('.')
            
            # Extract main domain (e.g., 'example.com' from 'docs.example.com')
            if len(base_domain_parts) >= 2 and len(url_domain_parts) >= 2:
                base_main_domain = '.'.join(base_domain_parts[-2:])
                url_main_domain = '.'.join(url_domain_parts[-2:])
                
                # If on same main domain but different subdomain, could be related
                if base_main_domain == url_main_domain:
                    # Check for documentation-related subdomains
                    if any(subdomain in ['docs', 'documentation', 'developer', 'api', 'guide', 'help', 'support', 'manual', 'learn'] 
                           for subdomain in url_domain_parts[:-2]):
                        return 'doc'
                
            return 'external'
        
        # Get path for further categorization
        path = parsed_url.path.lower()
        
        # First check for documentation patterns
        for pattern in DOC_PATTERNS:
            if pattern in path:
                return 'doc'
        
        # Check for URL continuation of base path
        if self.base_path and path.startswith(f"/{self.base_path}/"):
            return 'doc'
            
        # Check if the URL shares the initial path segments with the base URL
        if self.base_path_segments:
            url_path_segments = parsed_url.path.strip('/').split('/')
            if (len(url_path_segments) >= len(self.base_path_segments) and 
                url_path_segments[:len(self.base_path_segments)] == self.base_path_segments):
                return 'doc'
        
        # Check for auxiliary patterns
        for pattern in AUX_PATTERNS:
            if pattern in path:
                return 'aux'
        
        # Check for common "document-like" URL characteristics
        if re.search(r'\.(html|htm|md|pdf|txt)$', path):
            return 'doc'
            
        # Default to auxiliary for anything else on the same domain
        return 'aux'

    def extract_links(self, soup: BeautifulSoup, current_url: str) -> Dict[str, List[str]]:
        """
        Extract and categorize links from an HTML page.
        
        Args:
            soup: Parsed HTML content
            current_url: URL of the current page
            
        Returns:
            Dictionary with categorized links: {'doc': [...], 'aux': [...], 'external': [...], 'asset': [...]}
        """
        links = {
            'doc': [],
            'aux': [],
            'external': [],
            'asset': []
        }
        
        seen_urls = set()  # Track already processed URLs
        
        # Find all link elements with various selectors
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
            
            # Normalize the URL
            try:
                normalized_url = urljoin(current_url, href)
                cleaned_url = clean_url(normalized_url)
                
                # Skip if already processed
                if cleaned_url in seen_urls:
                    continue
                    
                seen_urls.add(cleaned_url)
                
                # Skip URLs not on the same domain if they're not related subdomains
                if not cleaned_url.startswith(self.domain):
                    domain_parts = urlparse(self.domain).netloc.split('.')
                    url_domain_parts = urlparse(cleaned_url).netloc.split('.')
                    
                    # Check if it's a related subdomain
                    if len(domain_parts) >= 2 and len(url_domain_parts) >= 2:
                        base_domain = '.'.join(domain_parts[-2:])
                        url_domain = '.'.join(url_domain_parts[-2:])
                        
                        if base_domain != url_domain:
                            links['external'].append(cleaned_url)
                            continue
                    else:
                        links['external'].append(cleaned_url)
                        continue
                
                # Apply URL filtering
                if not self._matches_url_filters(cleaned_url):
                    continue
                
                # Categorize the URL
                category = self.categorize_url(cleaned_url)
                if category in links:
                    links[category].append(cleaned_url)
                    
            except Exception as e:
                logger.debug(f"Error processing link '{href}': {e}")
                continue
        
        # Look for documentation-specific elements that might contain links
        self._extract_special_doc_links(soup, current_url, links, seen_urls)
        
        # Log summary of discovered links
        logger.info(f"Extracted links from {current_url}:")
        for category, category_links in links.items():
            logger.info(f"  - {category}: {len(category_links)} links")
            
        return links

    def _extract_special_doc_links(self, soup: BeautifulSoup, current_url: str, 
                                   links: Dict[str, List[str]], seen_urls: Set[str]):
        """
        Extract links from documentation-specific elements.
        
        Args:
            soup: Parsed HTML content
            current_url: URL of the current page
            links: Dictionary of already extracted links
            seen_urls: Set of already processed URLs
        """
        # Documentation-specific elements
        doc_selectors = [
            '.sidebar-item', '.menu-item', '.toc-item', '.nav-item',
            '.sidebar-link', '.doc-link', '[data-type="link"]',
            '.docusaurus-highlight-code-line', '.theme-doc-sidebar-item',
            '[data-sidebar-item]', '[data-menu-id]',
            # Common sidebar navigation elements
            '.sidebar-nav', '.doc-sidebar', '.docs-sidebar', 
            '.sidebar-menu', '.navigation-tree',
            '.docs-navigation', '.section-nav', '.page-toc'
        ]
        
        for menu_item in soup.select(', '.join(doc_selectors)):
            # Find clickable elements
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
                        url = urljoin(current_url, path)
                        cleaned_url = clean_url(url)
                        
                        if cleaned_url not in seen_urls:
                            seen_urls.add(cleaned_url)
                            
                            # Apply URL filtering
                            if not self._matches_url_filters(cleaned_url):
                                continue
                            
                            # Categorize the URL
                            category = self.categorize_url(cleaned_url)
                            if category in links:
                                links[category].append(cleaned_url)
                    except Exception as e:
                        logger.debug(f"Error processing special link '{path}': {e}")
                        continue
        
        # Special case for SPAs like Next.js, Gatsby, Nuxt
        for element in soup.select('[data-href], [data-url], [data-path], [href], [to]'):
            for attr in ['data-href', 'data-url', 'data-path', 'href', 'to']:
                if element.has_attr(attr) and element[attr] and not element[attr].startswith(('#', 'javascript:')):
                    try:
                        path = element[attr]
                        url = urljoin(current_url, path)
                        cleaned_url = clean_url(url)
                        
                        if cleaned_url not in seen_urls:
                            seen_urls.add(cleaned_url)
                            
                            # Apply URL filtering
                            if not self._matches_url_filters(cleaned_url):
                                continue
                            
                            # Categorize the URL
                            category = self.categorize_url(cleaned_url)
                            if category in links:
                                links[category].append(cleaned_url)
                    except Exception as e:
                        logger.debug(f"Error processing data attribute link '{path}': {e}")
                        continue

    def _matches_url_filters(self, url: str) -> bool:
        """
        Check if a URL matches the URL filtering patterns.
        
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
        
    def _download_with_retries(self, url: str) -> requests.Response:
        """
        Download a URL with retry logic, exponential backoff, and better error handling.
        
        Args:
            url: The URL to download
            
        Returns:
            Response object
            
        Raises:
            requests.exceptions.RequestException: On failure after retries
        """
        for attempt in range(self.retries):
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
                    logger.debug(f"Retry {attempt + 1}/{self.retries} for {url} in {wait_time:.2f}s")
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
                if attempt == self.retries - 1:
                    logger.error(f"Failed to download {url} after {self.retries} attempts: {e}")
                    raise
        
        # This should never be reached due to the raise in the exception handler
        raise requests.exceptions.RequestException(f"Failed to download {url} after {self.retries} attempts")

    def download_url(self, url: str) -> Tuple[Optional[str], Optional[Dict[str, List[str]]]]:
        """
        Download a URL and extract links from it.
        
        Args:
            url: URL to download
            
        Returns:
            Tuple of (HTML content, categorized links)
        """
        try:
            # Check for stop event before processing
            if self.stop_event and self.stop_event.is_set():
                logger.info(f"Skipping download of {url} due to stop event")
                return None, None
            
            # Use Selenium for browser mode to handle JavaScript-rendered pages
            if self.browser_mode and SELENIUM_AVAILABLE:
                html_content, links = self._download_with_browser(url)
                if html_content is not None:
                    return html_content, links
                else:
                    logger.warning(f"Browser mode failed for {url}, falling back to regular request")
            
            # Regular HTTP request
            response = self._download_with_retries(url)
            html_content = response.text
            
            # Check for stop event after HTTP request
            if self.stop_event and self.stop_event.is_set():
                logger.info(f"Stopping after HTTP request for {url}")
                return None, None
            
            # Apply content filtering before processing
            if not self._matches_content_filters(html_content):
                return None, None
            
            # Parse HTML - try multiple parsers for better compatibility
            try:
                # Try lxml parser first (faster)
                soup = BeautifulSoup(html_content, 'lxml')
            except Exception:
                try:
                    # Fall back to html.parser
                    soup = BeautifulSoup(html_content, 'html.parser')
                except Exception as e:
                    logger.error(f"Error parsing HTML: {e}")
                    return html_content, None
            
            # Final stop check before completing
            if self.stop_event and self.stop_event.is_set():
                logger.info(f"Stopping before completing processing for {url}")
                return None, None
            
            # Extract links
            links = self.extract_links(soup, url)
            logger.info(f"Regular mode: Extracted links from {url}")
            
            return html_content, links
            
        except requests.exceptions.HTTPError as e:
            if hasattr(e, 'response') and e.response and e.response.status_code == 404:
                logger.warning(f'Page not found (404): {url}')
                self.failed_urls[url] = "404 Not Found"
            else:
                logger.error(f"HTTP error downloading {url}: {e}")
                self.failed_urls[url] = f"HTTP Error: {e}"
            return None, None
            
        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")
            logger.debug(traceback.format_exc())
            self.failed_urls[url] = str(e)
            return None, None

    def _download_with_browser(self, url: str) -> Tuple[Optional[str], Optional[Dict[str, List[str]]]]:
        """
        Download a page using browser automation with Selenium.
        
        Args:
            url: URL to download
            
        Returns:
            Tuple of (HTML content, categorized links)
        """
        driver = None
        try:
            # Configure headless Chrome browser with improved options
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--ignore-certificate-errors")
            chrome_options.add_argument("--ignore-ssl-errors")
            chrome_options.add_argument("--incognito")
            chrome_options.add_argument(f"user-agent={self.session.headers.get('User-Agent')}")
            chrome_options.add_argument("--page-load-strategy=eager")  # Don't wait for all resources
            
            logger.debug(f"Browser mode: initializing Chrome driver for {url}")
            
            # Create a new browser instance for each page to avoid memory issues
            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=chrome_options
            )
            # Add to active browsers list for cleanup
            self.active_browser_instances.append(driver)
            
            # Set page load timeout - shorter timeout for faster response to stop events
            driver.set_page_load_timeout(min(10, self.timeout))
            
            # Check for stop event before loading page
            if self.stop_event and self.stop_event.is_set():
                logger.info(f"Stopping before loading {url}")
                driver.quit()
                if driver in self.active_browser_instances:
                    self.active_browser_instances.remove(driver)
                return None, None
                
            # Load the page
            logger.debug(f"Browser mode: loading page {url}")
            driver.get(url)
            
            # Check for stop event immediately after page load
            if self.stop_event and self.stop_event.is_set():
                logger.info(f"Stopping after initial page load of {url}")
                driver.quit()
                if driver in self.active_browser_instances:
                    self.active_browser_instances.remove(driver)
                return None, None
            
            # Wait for dynamic content to load
            try:
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
                time.sleep(1)  # Shorter fallback delay
            
            # Check for stop event again before processing content
            if self.stop_event and self.stop_event.is_set():
                logger.info(f"Stopping during page load of {url}")
                driver.quit()
                if driver in self.active_browser_instances:
                    self.active_browser_instances.remove(driver)
                return None, None
            
            # Get the page source after JavaScript execution
            html_content = driver.page_source
            
            if not html_content:
                logger.warning(f"Browser mode: empty page source for {url}")
                return None, None
            
            # Parse the HTML with fallback parsers
            logger.debug(f"Browser mode: parsing HTML content")
            try:
                soup = BeautifulSoup(html_content, 'lxml')
            except ImportError:
                logger.warning("lxml parser not available, falling back to html.parser")
                soup = BeautifulSoup(html_content, 'html.parser')
            except Exception as e:
                logger.error(f"Error parsing HTML with any parser: {e}")
                return None, None
            
            # Final stop check before link extraction
            if self.stop_event and self.stop_event.is_set():
                logger.info(f"Stopping before link extraction for {url}")
                driver.quit()
                if driver in self.active_browser_instances:
                    self.active_browser_instances.remove(driver)
                return None, None
            
            # Extract links
            links = self.extract_links(soup, url)
            logger.info(f"Browser mode: extracted links from {url}")
            
            return html_content, links
            
        except (TimeoutException, WebDriverException) as e:
            logger.warning(f"Browser automation error for {url}: {e}")
            return None, None
        except Exception as e:
            logger.error(f"Unexpected error in browser mode for {url}: {e}")
            logger.debug(traceback.format_exc())
            if "lxml" in str(e).lower():
                logger.error("The lxml parser is required. Install it with: pip install lxml")
            elif "chromedriver" in str(e).lower() or "webdriver" in str(e).lower():
                logger.error("ChromeDriver is required. Install with: pip install webdriver-manager")
            return None, None
        finally:
            # Always close the browser
            if driver:
                try:
                    driver.quit()
                    if driver in self.active_browser_instances:
                        self.active_browser_instances.remove(driver)
                    logger.debug(f"Browser mode: browser closed for {url}")
                except Exception as e:
                    logger.warning(f"Error closing browser: {e}")

    def crawl(self, callback: Optional[Callable[[str, str, Dict[str, List[str]]], None]] = None, 
              interactive: bool = False) -> Tuple[int, Dict[str, Set[str]]]:
        """
        Crawl the website starting from the base URL.
        
        Args:
            callback: Function to call for each downloaded page with (url, html_content, links)
            interactive: Whether to prompt user before crawling non-doc sections
            
        Returns:
            Tuple of (pages downloaded, categorized URLs {doc, aux, external, asset})
        """
        logger.info(f"Starting crawl from {self.base_url}")
        logger.info(f"Max depth: {self.max_depth}, Max pages: {self.max_pages or 'unlimited'}")
        
        # Reset counters
        self.pages_downloaded = 0
        self.visited.clear()
        self.queued.clear()
        self.failed_urls.clear()
        self.doc_links.clear()
        self.aux_links.clear()
        self.external_links.clear()
        self.asset_links.clear()
        
        # Initialize queues for priority crawling
        doc_queue = deque([(self.base_url, 0)])  # (url, depth)
        self.queued.add(self.base_url)
        
        # Setup progress tracking
        pbar = None
        if self.max_pages:
            pbar = tqdm(total=self.max_pages, desc="Crawling pages", unit="page")
        
        # Flag to track if we're in stopping state
        stopping = False
        
        # First phase: Process documentation pages
        logger.info("Phase 1: Crawling documentation pages...")
        while doc_queue and (self.max_pages is None or self.pages_downloaded < self.max_pages) and not stopping:
            # Check for stop event
            if self.stop_event and self.stop_event.is_set():
                logger.warning("Stop event detected, halting crawl...")
                stopping = True
                break
                
            # Process in batches for concurrent crawling
            batch = []
            for _ in range(min(self.concurrent_requests, len(doc_queue))):
                if not doc_queue:
                    break
                batch.append(doc_queue.popleft())
            
            if not batch:
                break
                
            logger.info(f"Processing batch of {len(batch)} documentation URLs")
            
            # Process batch concurrently
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrent_requests) as executor:
                future_to_url = {
                    executor.submit(self.download_url, url): (url, depth) 
                    for url, depth in batch if not stopping
                }
                
                for future in concurrent.futures.as_completed(future_to_url):
                    # Skip processing if stopping
                    if stopping:
                        continue
                        
                    url, depth = future_to_url[future]
                    
                    try:
                        html_content, links = future.result()
                        
                        # Add URL to visited set
                        self.visited.add(url)
                        
                        # If content was successfully downloaded
                        if html_content and links:
                            # Call callback if provided
                            if callback:
                                callback(url, html_content, links)
                                
                            # Count this as a downloaded page
                            self.pages_downloaded += 1
                            
                            # Update progress bar if available
                            if pbar:
                                pbar.update(1)
                                
                            # Call progress callback if provided
                            if self.progress_callback:
                                self.progress_callback(url, self.pages_downloaded, self.max_pages)
                                
                            # Log progress
                            logger.info(f"Downloaded page {self.pages_downloaded}: {url}")
                            
                            # Update categorized link sets
                            for category, category_links in links.items():
                                if category == 'doc':
                                    self.doc_links.update(category_links)
                                elif category == 'aux':
                                    self.aux_links.update(category_links)
                                elif category == 'external':
                                    self.external_links.update(category_links)
                                elif category == 'asset':
                                    self.asset_links.update(category_links)
                            
                            # Add new documentation links to the queue if not already processed
                            if depth < self.max_depth:
                                for doc_link in links.get('doc', []):
                                    if (doc_link not in self.visited and 
                                        doc_link not in self.queued and 
                                        not any(item[0] == doc_link for item in doc_queue)):
                                        doc_queue.append((doc_link, depth + 1))
                                        self.queued.add(doc_link)
                        
                    except Exception as e:
                        logger.error(f"Error processing {url}: {e}")
                        logger.debug(traceback.format_exc())
                        
            # Respect the delay between batches
            if self.delay > 0 and doc_queue and not stopping:
                time.sleep(self.delay)
                
        # Second phase: Process auxiliary pages if requested
        if not stopping and (self.max_pages is None or self.pages_downloaded < self.max_pages):
            # Get all undiscovered auxiliary links
            available_aux_links = {
                link for link in self.aux_links 
                if link not in self.visited and link not in self.queued
            }
            
            # If interactive mode and auxiliary links are found
            if interactive and available_aux_links:
                logger.info(f"Documentation crawling complete. Found {len(available_aux_links)} auxiliary pages.")
                logger.info("Sample auxiliary pages:")
                
                # Show some sample auxiliary links
                sample_links = list(available_aux_links)[:5]
                for i, aux_url in enumerate(sample_links):
                    logger.info(f"  {i+1}. {aux_url}")
                
                # Ask user if they want to crawl auxiliary pages
                import sys
                if len(available_aux_links) > 5:
                    logger.info(f"  ... and {len(available_aux_links) - 5} more.")
                
                logger.info("Would you like to crawl these auxiliary pages too? (yes/no)")
                
                # Let the caller handle the interactive prompt
                # This would be handled by the scraper which integrates with this crawler
                
                # For now, we'll assume "no" to skip auxiliary crawling
                process_aux = False
                
                # If user wants to crawl auxiliary pages
                if process_aux:
                    logger.info("Starting crawl of auxiliary pages...")
                    
                    # Create an auxiliary queue
                    aux_queue = deque([(link, 0) for link in available_aux_links])
                    
                    # Add all to queued set
                    self.queued.update(available_aux_links)
                    
                    # Similar crawling logic as above for auxiliary pages
                    # ...
                    # Since the logic is essentially the same, we'd just repeat the same processing
                    # with aux_queue instead of doc_queue
                    # ...
        
        # Close progress bar if open
        if pbar:
            pbar.close()
            
        # Cleanup browser instances if any are still active
        self._cleanup_browser_instances()
        
        # Return results
        categorized_urls = {
            'doc': self.doc_links,
            'aux': self.aux_links,
            'external': self.external_links,
            'asset': self.asset_links
        }
        
        logger.info(f"Crawling complete. Downloaded {self.pages_downloaded} pages.")
        logger.info(f"Documentation links: {len(self.doc_links)}")
        logger.info(f"Auxiliary links: {len(self.aux_links)}")
        logger.info(f"External links: {len(self.external_links)}")
        logger.info(f"Asset links: {len(self.asset_links)}")
        
        if self.failed_urls:
            logger.warning(f"Failed to download {len(self.failed_urls)} URLs")
            
        return self.pages_downloaded, categorized_urls
    
    def _cleanup_browser_instances(self):
        """Clean up any active browser instances to ensure proper shutdown."""
        if hasattr(self, 'active_browser_instances'):
            for driver in self.active_browser_instances:
                try:
                    driver.quit()
                    logger.debug("Browser instance closed during cleanup")
                except Exception as e:
                    logger.warning(f"Error closing browser instance: {e}")
            
            # Clear the list after cleanup
            self.active_browser_instances.clear()
    
    def get_interactive_response(self, question: str, default: bool = False) -> bool:
        """
        Get an interactive response from the user.
        
        Args:
            question: Question to ask the user
            default: Default response if the interactive mode isn't possible
            
        Returns:
            User's response as a boolean
        """
        # In a real implementation, this would show a prompt or use another mechanism
        # For now, we'll return the default
        return default