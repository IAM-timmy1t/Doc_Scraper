"""
Output format handlers for Document Scraper.

This module provides formatters for converting HTML content to various output formats,
with specialized handling for documentation-specific structures and content organization.
"""

import os
import json
import logging
import html2text
import datetime
import re
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple, Union
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin, urlparse

from document_scraper.converter import HtmlToMarkdownConverter

logger = logging.getLogger("document_scraper")


class BaseFormatter(ABC):
    """
    Base class for all output formatters.
    
    This abstract class defines the interface for all content formatters,
    ensuring consistent behavior across different output formats.
    """
    
    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize the formatter.
        
        Args:
            base_url: Base URL for resolving relative links
        """
        self.base_url = base_url
    
    @abstractmethod
    def convert(self, html_content: str, url: Optional[str] = None) -> str:
        """
        Convert HTML content to the desired format.
        
        Args:
            html_content: Raw HTML content
            url: URL of the content for better link handling
            
        Returns:
            Converted content in the target format
        """
        pass
    
    @property
    @abstractmethod
    def file_extension(self) -> str:
        """
        Get the file extension for this format.
        
        Returns:
            File extension including the dot (e.g., '.md')
        """
        pass
    
    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """
        Get metadata about this formatter.
        
        Returns:
            Dictionary of metadata
        """
        pass
    
    def fix_relative_links(self, content: str, url: Optional[str] = None) -> str:
        """
        Fix relative links in the content to point to local files.
        
        This is a common operation needed by many formatters.
        
        Args:
            content: The content with links to fix
            url: Current URL for resolving relative links
            
        Returns:
            Content with fixed links
        """
        # Implementation depends on the specific format
        return content


class MarkdownFormatter(BaseFormatter):
    """
    Converts HTML to Markdown format.
    
    This formatter is specialized for documentation content with enhanced features:
    - Preserves document structure
    - Handles code blocks correctly
    - Creates clean, readable Markdown
    - Adds appropriate front matter
    """
    
    def __init__(self, base_url: Optional[str] = None):
        """Initialize the Markdown formatter."""
        super().__init__(base_url)
        self.converter = HtmlToMarkdownConverter(base_url=base_url)
    
    def convert(self, html_content: str, url: Optional[str] = None) -> str:
        """
        Convert HTML to Markdown with documentation-specific enhancements.
        
        Args:
            html_content: Raw HTML content
            url: URL of the content for better link handling
            
        Returns:
            Converted Markdown content
        """
        md_content = self.converter.convert(html_content, url)
        
        # Add front matter for better organization
        if url:
            url_path = urlparse(url).path.strip('/')
            page_id = url_path.replace('/', '-') or "index"
            
            # Extract title from the content
            title = self._extract_title(html_content, page_id)
            
            # Add YAML front matter
            front_matter = f"---\ntitle: {title}\nurl: {url}\n---\n\n"
            md_content = front_matter + md_content
        
        # Enhance code blocks - ensure language tags are correct
        md_content = self._enhance_code_blocks(md_content)
        
        # Fix links to point to local files
        md_content = self.fix_relative_links(md_content, url)
        
        return md_content
    
    def _extract_title(self, html_content: str, fallback: str) -> str:
        """Extract title from HTML content."""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            title_tag = soup.find('title')
            if title_tag:
                title = title_tag.text.strip()
                # Remove site name if present
                for separator in [' | ', ' - ', ' — ', ' – ', ' :: ']:
                    if separator in title:
                        title = title.split(separator)[0].strip()
                return title
            
            # Try heading tags
            for tag in ['h1', 'h2']:
                heading = soup.find(tag)
                if heading:
                    return heading.get_text().strip()
                    
            # Fallback to URL-based title
            return fallback.replace('-', ' ').replace('_', ' ').title()
        except Exception:
            return fallback.replace('-', ' ').replace('_', ' ').title()
    
    def _enhance_code_blocks(self, md_content: str) -> str:
        """Enhance code blocks with proper language tags and formatting."""
        # Fix code blocks with missing or incorrect language tags
        md_content = re.sub(r'```\s*\n', '```text\n', md_content)
        
        # Ensure proper spacing in code blocks
        md_content = re.sub(r'```([a-zA-Z0-9_-]+)\n\n', r'```\1\n', md_content)
        
        return md_content
        
    def fix_relative_links(self, content: str, url: Optional[str] = None) -> str:
        """
        Fix Markdown links to point to local files.
        
        Args:
            content: Markdown content
            url: Current URL for resolving relative links
            
        Returns:
            Markdown with fixed links
        """
        if not url or not self.base_url:
            return content
            
        # Regular expression to find Markdown links
        link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        
        def replace_link(match):
            link_text = match.group(1)
            link_url = match.group(2)
            
            # Skip links that are already local or anchors
            if link_url.startswith(('#', 'mailto:', 'tel:')) or not link_url.startswith(('http://', 'https://')):
                return match.group(0)
                
            # Only process links to the same domain
            parsed_url = urlparse(link_url)
            base_domain = urlparse(self.base_url).netloc
            
            if parsed_url.netloc == base_domain:
                # Convert to local path
                path = parsed_url.path.strip('/')
                if not path:
                    return f"[{link_text}](index.md)"
                    
                # Create a local path
                local_path = f"{path.replace('/', '-')}.md"
                return f"[{link_text}]({local_path})"
                
            return match.group(0)
            
        return re.sub(link_pattern, replace_link, content)
    
    @property
    def file_extension(self) -> str:
        """Get the file extension."""
        return ".md"
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get formatter metadata."""
        return {
            "name": "Markdown",
            "description": "GitHub Flavored Markdown",
            "extension": self.file_extension,
            "mime_type": "text/markdown",
            "features": [
                "Front matter",
                "Code block enhancements",
                "Local link resolution",
                "Document structure preservation"
            ]
        }


class HTMLFormatter(BaseFormatter):
    """
    Passes through HTML with optional cleaning and enhancements.
    
    This formatter allows saving HTML content with options to:
    - Clean and sanitize the HTML
    - Fix relative links
    - Remove scripts and tracking
    - Enhance readability
    """
    
    def __init__(self, base_url: Optional[str] = None, clean: bool = True, 
                 remove_scripts: bool = True, fix_links: bool = True):
        """
        Initialize the HTML formatter.
        
        Args:
            base_url: Base URL for resolving relative links
            clean: Whether to clean the HTML before saving
            remove_scripts: Whether to remove scripts and potential tracking
            fix_links: Whether to fix relative links
        """
        super().__init__(base_url)
        self.clean = clean
        self.remove_scripts = remove_scripts
        self.fix_links = fix_links
    
    def convert(self, html_content: str, url: Optional[str] = None) -> str:
        """
        Pass through or clean HTML based on configuration.
        
        Args:
            html_content: Raw HTML content
            url: URL of the content for better link handling
            
        Returns:
            Processed HTML content
        """
        if not self.clean:
            return html_content
        
        # Clean the HTML
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove script and style elements if configured
            if self.remove_scripts:
                for tag in soup(["script", "style", "iframe"]):
                    tag.decompose()
            
            # Fix relative links if configured
            if self.fix_links and self.base_url:
                self._fix_links_in_soup(soup, url)
            
            # Add metadata for better organization
            if url:
                meta_tag = soup.new_tag("meta")
                meta_tag["name"] = "source-url"
                meta_tag["content"] = url
                
                # Find or create head tag
                head = soup.find("head")
                if not head:
                    head = soup.new_tag("head")
                    if soup.html:
                        soup.html.insert(0, head)
                    else:
                        html = soup.new_tag("html")
                        html.append(head)
                        soup.append(html)
                
                head.append(meta_tag)
            
            return str(soup)
        except Exception as e:
            logger.error(f"Error cleaning HTML: {e}")
            return html_content
    
    def _fix_links_in_soup(self, soup: BeautifulSoup, url: Optional[str] = None) -> None:
        """Fix relative links in BeautifulSoup document."""
        # Fix links in various elements
        for element_type, attr_name in [
            ("a", "href"),
            ("img", "src"),
            ("link", "href"),
            ("script", "src")
        ]:
            for element in soup.find_all(element_type, attrs={attr_name: True}):
                attr_value = element[attr_name]
                if attr_value and not attr_value.startswith(("http://", "https://", "mailto:", "tel:", "#", "data:")):
                    if url:
                        element[attr_name] = urljoin(url, attr_value)
                    elif self.base_url:
                        element[attr_name] = urljoin(self.base_url, attr_value)
    
    @property
    def file_extension(self) -> str:
        """Get the file extension."""
        return ".html"
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get formatter metadata."""
        return {
            "name": "HTML",
            "description": "Clean HTML",
            "extension": self.file_extension,
            "mime_type": "text/html",
            "options": {
                "clean": self.clean,
                "remove_scripts": self.remove_scripts,
                "fix_links": self.fix_links
            }
        }


class TextFormatter(BaseFormatter):
    """
    Converts HTML to plain text.
    
    This formatter extracts clean, readable text from HTML content,
    preserving document structure and readability.
    """
    
    def convert(self, html_content: str, url: Optional[str] = None) -> str:
        """
        Convert HTML to plain text with enhanced readability.
        
        Args:
            html_content: Raw HTML content
            url: URL of the content (unused for text conversion)
            
        Returns:
            Plain text content
        """
        try:
            # Try using lxml for better parsing
            try:
                soup = BeautifulSoup(html_content, 'lxml')
            except ImportError:
                soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove script and style elements
            for tag in soup(["script", "style", "noscript", "iframe"]):
                tag.decompose()
            
            # Process headings with proper formatting
            for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                level = int(heading.name[1])
                heading_text = heading.get_text(strip=True)
                # Create heading with appropriate formatting
                new_text = f"\n{'#' * level} {heading_text}\n"
                heading.replace_with(BeautifulSoup(new_text, 'html.parser'))
            
            # Process lists with proper indentation
            for list_tag in soup.find_all(['ul', 'ol']):
                for i, item in enumerate(list_tag.find_all('li', recursive=False)):
                    prefix = "- " if list_tag.name == 'ul' else f"{i+1}. "
                    item_text = item.get_text(strip=True)
                    item.replace_with(BeautifulSoup(f"{prefix}{item_text}\n", 'html.parser'))
            
            # Extract text
            text = soup.get_text(separator='\n\n', strip=True)
            
            # Replace multiple newlines with double newlines
            text = re.sub(r'\n{3,}', '\n\n', text)
            
            # Ensure reasonable line width (80 chars)
            wrapped_lines = []
            for paragraph in text.split('\n\n'):
                if len(paragraph) > 80 and not paragraph.startswith(('#', '-', '•')):
                    # Simple word wrapping
                    words = paragraph.split()
                    line = []
                    line_length = 0
                    for word in words:
                        if line_length + len(word) + 1 > 80:
                            wrapped_lines.append(' '.join(line))
                            line = [word]
                            line_length = len(word)
                        else:
                            line.append(word)
                            line_length += len(word) + 1
                    if line:
                        wrapped_lines.append(' '.join(line))
                else:
                    wrapped_lines.append(paragraph)
            
            text = '\n\n'.join(wrapped_lines)
            
            return text
        except Exception as e:
            logger.error(f"Error converting HTML to text: {e}")
            # Last resort: use html2text
            h = html2text.HTML2Text()
            h.ignore_links = True
            h.ignore_images = True
            h.ignore_tables = True
            h.ignore_emphasis = True
            return h.handle(html_content)
    
    @property
    def file_extension(self) -> str:
        """Get the file extension."""
        return ".txt"
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get formatter metadata."""
        return {
            "name": "Plain Text",
            "description": "Clean plain text with preserved structure",
            "extension": self.file_extension,
            "mime_type": "text/plain",
            "features": [
                "Heading preservation",
                "List formatting",
                "Line wrapping",
                "Content structure"
            ]
        }


class JSONFormatter(BaseFormatter):
    """
    Converts HTML to a JSON representation with comprehensive metadata.
    
    This formatter creates a structured JSON representation of documentation
    with rich metadata for programmatic processing and integration.
    """
    
    def convert(self, html_content: str, url: Optional[str] = None) -> str:
        """
        Convert HTML to structured JSON with metadata.
        
        Args:
            html_content: Raw HTML content
            url: URL of the content for link resolution
            
        Returns:
            JSON string representation
        """
        try:
            # Try using lxml for better parsing
            try:
                soup = BeautifulSoup(html_content, 'lxml')
            except ImportError:
                soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract the title
            title_tag = soup.find('title')
            title = title_tag.text if title_tag else ""
            
            # Extract headings for table of contents
            headings = []
            for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                level = int(tag.name[1])
                text = tag.get_text(strip=True)
                # Get a unique ID for the heading
                heading_id = f"heading-{len(headings)}"
                if 'id' in tag.attrs:
                    heading_id = tag['id']
                
                headings.append({
                    "level": level,
                    "text": text,
                    "id": heading_id
                })
            
            # Extract links with metadata
            links = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                link_text = link.get_text(strip=True)
                
                # Skip empty or fragment-only links
                if not href or href.startswith('#'):
                    continue
                
                # Determine link type
                link_type = "external"
                if self.base_url and href.startswith(self.base_url):
                    link_type = "internal"
                elif not href.startswith(('http://', 'https://')):
                    link_type = "relative"
                    
                links.append({
                    "url": href,
                    "text": link_text,
                    "type": link_type,
                    "resolved": urljoin(url, href) if url and link_type == "relative" else href
                })
            
            # Extract metadata
            meta_tags = {}
            for meta in soup.find_all('meta'):
                if 'name' in meta.attrs and 'content' in meta.attrs:
                    meta_tags[meta['name']] = meta['content']
                elif 'property' in meta.attrs and 'content' in meta.attrs:
                    meta_tags[meta['property']] = meta['content']
            
            # Extract main content
            main_content = ""
            for selector in ["main", "article", "#content", ".content", "[role=main]"]:
                main_element = soup.select_one(selector)
                if main_element:
                    main_content = main_element.get_text(strip=True)
                    break
            
            if not main_content:
                # Fallback to full text
                main_content = soup.get_text(strip=True)
            
            # Create JSON structure
            data = {
                "url": url,
                "title": title,
                "metadata": meta_tags,
                "headings": headings,
                "links": links,
                "content": main_content,
                "timestamp": {
                    "captured": datetime.now().isoformat()
                }
            }
            
            # Convert to JSON string
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error converting HTML to JSON: {e}")
            return json.dumps({
                "url": url,
                "error": str(e),
                "partial_content": html_content[:1000] + "..." if len(html_content) > 1000 else html_content
            }, ensure_ascii=False)
    
    @property
    def file_extension(self) -> str:
        """Get the file extension."""
        return ".json"
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get formatter metadata."""
        return {
            "name": "JSON",
            "description": "Structured JSON with comprehensive metadata",
            "extension": self.file_extension,
            "mime_type": "application/json",
            "features": [
                "Document structure",
                "Heading hierarchy",
                "Link analysis",
                "Metadata extraction"
            ]
        }


# Registry of available formatters
FORMATTERS = {
    "markdown": MarkdownFormatter,
    "html": HTMLFormatter,
    "text": TextFormatter,
    "json": JSONFormatter
}


def get_formatter(format_name: str, base_url: Optional[str] = None, **kwargs) -> BaseFormatter:
    """
    Get a formatter by name.
    
    Args:
        format_name: Name of the formatter to get
        base_url: Base URL for resolving relative links
        **kwargs: Additional options for the formatter
        
    Returns:
        Formatter instance
        
    Raises:
        ValueError: If the formatter name is not recognized
    """
    formatter_cls = FORMATTERS.get(format_name.lower())
    if not formatter_cls:
        raise ValueError(f"Unknown formatter: {format_name}. Available formatters: {', '.join(FORMATTERS.keys())}")
    
    return formatter_cls(base_url=base_url, **kwargs)


def get_available_formats() -> List[Dict[str, Any]]:
    """
    Get information about all available output formats.
    
    Returns:
        List of dictionaries with format metadata
    """
    return [
        {
            "id": format_id,
            "metadata": formatter_cls().get_metadata()
        }
        for format_id, formatter_cls in FORMATTERS.items()
    ]


def convert_document(html_content: str, url: str, output_format: str = "markdown", 
                    base_url: Optional[str] = None, **kwargs) -> str:
    """
    Convenience function to convert an HTML document to the specified format.
    
    Args:
        html_content: HTML content to convert
        url: URL of the document
        output_format: Target format (markdown, html, text, json)
        base_url: Base URL for resolving relative links
        **kwargs: Additional formatter-specific options
        
    Returns:
        Converted content in the target format
    """
    formatter = get_formatter(output_format, base_url=base_url or get_domain(url), **kwargs)
    return formatter.convert(html_content, url)