"""
Core scraping functionality for the document_scraper module.

This module handles the scraping of documentation websites, extracting
content, discovering links, and organizing the download structure.
"""

import os
import time
import logging
import requests
from urllib.parse import urlparse, urljoin, parse_qs, urlencode
from bs4 import BeautifulSoup
from tqdm import tqdm
import concurrent.futures
from collections import deque
from typing import List, Dict, Tuple, Set, Optional, Callable, Any, Union
import traceback

from document_scraper.utils import (
    is_valid_url, get_domain, normalize_url, clean_url,
    create_path_from_url, ensure_directory_exists,
    is_asset_url, get_asset_path, rate_limit
)
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
                 progress_callback: Optional[Callable[[str, int, Optional[int]], None]] = None):
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
        """
        # Configuration
        self.base_url = base_url.rstrip('/')
        self.output_dir = output_dir
        self.max_depth = max_depth
        self.delay = delay
        self.max_pages = max_pages
        self.concurrent_requests = concurrent_requests
        self.include_assets = include_assets
        self.timeout = timeout
        self.retries = retries
        self.proxies = proxies
        self.progress_callback = progress_callback
        
        # State tracking
        self.visited: Set[str] = set()
        self.queued: Set[str] = set()
        self.pages_downloaded = 0
        self.assets_downloaded = 0
        self.domain = get_domain(base_url)
        self.converter = HtmlToMarkdownConverter(base_url=self.domain)
        self.failed_urls: Dict[str, str] = {}  # URL -> error message
        
        # Setup session for persistent connections
        self.session = requests.Session()
        
        # Set default user agent if none provided
        if not user_agent:
            user_agent = f'Mozilla/5.0 (compatible; DocScraper/{__import__("document_scraper").__version__}; +https://github.com/docscraper)'
        
        self.session.headers.update({
            'User-Agent': user_agent
        })
        
        # Set cookies if provided
        if cookies:
            self.session.cookies.update(cookies)
            
        # Set proxies if provided
        if proxies:
            self.session.proxies.update(proxies)
        
        # Create output directory
        ensure_directory_exists(output_dir)
        
        logger.info(f"Initialized scraper for {base_url}")
        logger.info(f"Output directory: {output_dir}")
    
    def _is_same_domain(self, url: str) -> bool:
        """
        Check if a URL belongs to the same domain as the base URL.
        
        Args:
            url: URL to check
            
        Returns:
            Whether the URL is from the same domain
        """
        try:
            base_domain = urlparse(self.base_url).netloc
            url_domain = urlparse(url).netloc
            return base_domain == url_domain
        except Exception:
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
    
    def is_valid_doc_url(self, url: str) -> bool:
        """
        Determine if a URL is a valid documentation page to scrape.
        
        Args:
            url: The URL to check
            
        Returns:
            Whether the URL should be scraped
        """
        if not url or not self._is_valid_url(url):
            return False
        
        # Only process URLs from the same domain
        if not url.startswith(self.domain):
            return False
        
        # Skip asset files if we're not including assets
        if not self.include_assets and is_asset_url(url):
            return False
        
        # Skip common exclusion patterns
        exclusion_patterns = [
            '/api/', '/auth/', '/login/', '/logout/', '/signup/', 
            '/account/', '/admin/', '/download/', '/search?', '/cdn-cgi/'
        ]
        
        if any(pattern in url.lower() for pattern in exclusion_patterns):
            return False
            
        return True
    
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
        Extract links from the page content.
        
        Args:
            soup: Parsed HTML
            current_url: URL of the current page
            
        Returns:
            List of normalized URLs found
        """
        links = []
        
        # Find all <a> tags
        for link in soup.find_all('a', href=True):
            href = link.get('href')
            
            # Normalize the URL (handle relative URLs, etc.)
            normalized_url = self._normalize_url(href, current_url)
            
            # Skip invalid or already processed URLs
            if not normalized_url or normalized_url in self.visited or normalized_url in self.queued:
                continue
                
            # Only process URLs that belong to the documentation
            if self.is_valid_doc_url(normalized_url):
                # Clean the URL to standardize format and remove tracking params
                cleaned_url = clean_url(normalized_url)
                
                # Add to links if not already added
                if cleaned_url not in links:
                    links.append(cleaned_url)
                    self.queued.add(cleaned_url)
        
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
    
    def download_with_retry(self, url: str) -> requests.Response:
        """
        Download a URL with retry logic.
        
        Args:
            url: URL to download
            
        Returns:
            Response object
            
        Raises:
            RequestError: If the download fails after retries
        """
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                
                # Raise exception for 4xx/5xx status codes
                response.raise_for_status()
                return response
                
            except requests.RequestException as e:
                if attempt == self.retries:
                    error_msg = f"Failed to download {url} after {self.retries} attempts: {str(e)}"
                    logger.error(error_msg)
                    self.failed_urls[url] = error_msg
                    raise RequestError(error_msg) from e
                    
                # Exponential backoff for retries
                wait_time = 1 * (2 ** attempt)
                logger.warning(f"Attempt {attempt + 1}/{self.retries + 1} failed for {url}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
    
    def download_page(self, url: str) -> Tuple[str, str, List[str]]:
        """
        Download a page and extract its title, content, and links.
        
        Args:
            url: URL to download
            
        Returns:
            Tuple of (title, html_content, links)
        """
        if url in self.visited:
            return "", "", []
            
        logger.debug(f"Downloading {url}")
        
        try:
            # Get the page content
            response = self.download_with_retry(url)
            html_content = response.text
            
            # Parse HTML
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract title
            title_tag = soup.find('title')
            title = title_tag.text if title_tag else url.split('/')[-1]
            
            # Extract links
            links = []
            for a_tag in soup.find_all('a', href=True):
                link = a_tag['href']
                
                # Skip invalid URLs
                if not self._is_valid_url(link):
                    continue
                
                # Normalize the URL
                normalized_link = self._normalize_url(link, url)
                
                # Only add links from the same domain
                if normalized_link and normalized_link.startswith(self.base_url):
                    # Check if this is a documentation-related link
                    # This helps with capturing all documentation pages
                    base_path = urlparse(self.base_url).path.rstrip('/')
                    link_path = urlparse(normalized_link).path
                    
                    # Special handling for documentation links
                    if base_path and link_path.startswith(base_path):
                        links.append(normalized_link)
                        
                    # Also include links that are in the same directory level or below
                    # This helps capture related documentation sections
                    elif not base_path or link_path.startswith(base_path.rsplit('/', 1)[0] + '/'):
                        links.append(normalized_link)
            
            # Extract assets if needed
            if self.include_assets:
                assets = self.extract_assets(soup, url)
                if assets:
                    self.download_assets(assets)
            
            return title, html_content, links
            
        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")
            return "", "", []
    
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
                response = self.download_with_retry(url)
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
    
    def save_markdown(self, url: str, title: str, html_content: str) -> bool:
        """
        Convert HTML to Markdown and save to file.
        
        Args:
            url: URL of the page
            title: Title of the page
            html_content: HTML content
            
        Returns:
            Whether the save was successful
        """
        try:
            # Convert HTML to Markdown
            markdown_content = self.converter.convert(html_content, url)
            
            # Create directory structure based on URL
            directory, filename = create_path_from_url(url, self.base_url, self.output_dir)
            
            # Save the Markdown file
            file_path = os.path.join(directory, filename)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            
            logger.debug(f"Saved {url} to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving Markdown for {url}: {e}")
            return False
    
    def crawl(self) -> Tuple[int, int]:
        """
        Crawl the documentation site and save pages as Markdown.
        
        Returns:
            Tuple of (pages_downloaded, assets_downloaded)
        """
        logger.info(f"Starting crawl from {self.base_url}")
        
        # Queue to track URLs to visit and their depth
        queue = deque([(self.base_url, 0)])
        self.queued.add(self.base_url)
        
        with tqdm(desc="Downloading pages", unit="page") as pbar:
            while queue and (self.max_pages is None or self.pages_downloaded < self.max_pages):
                # Get the next batch of URLs to process
                batch = []
                for _ in range(min(self.concurrent_requests, len(queue))):
                    if not queue:
                        break
                    batch.append(queue.popleft())
                
                if not batch:
                    break
                
                # Process the batch with concurrent requests
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrent_requests) as executor:
                    future_to_url = {
                        executor.submit(self.download_page, url): (url, depth) 
                        for url, depth in batch
                    }
                    
                    for future in concurrent.futures.as_completed(future_to_url):
                        url, depth = future_to_url[future]
                        self.visited.add(url)
                        
                        title, html_content, links = future.result()
                        if title and html_content:
                            success = self.save_markdown(url, title, html_content)
                            if success:
                                self.pages_downloaded += 1
                                pbar.update(1)
                                pbar.set_postfix(
                                    url=url.split("/")[-1],
                                    queued=len(queue) + len(self.queued) - len(self.visited)
                                )
                                
                                # Call progress callback if provided
                                if self.progress_callback:
                                    total = len(queue) + len(self.visited) if queue else None
                                    self.progress_callback(url, self.pages_downloaded, total)
                        
                        # Add new links to the queue if we haven't reached max depth
                        if depth < self.max_depth:
                            for link in links:
                                if (link not in self.visited and 
                                    link not in self.queued and
                                    link not in [u for u, _ in queue]):
                                    queue.append((link, depth + 1))
                                    self.queued.add(link)
                
                # Respect the delay between batches
                if self.delay > 0 and queue:
                    time.sleep(self.delay)
        
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
