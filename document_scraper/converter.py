"""
HTML to Markdown converter for the document_scraper module.

This module handles the conversion of HTML content to clean Markdown format,
with special handling for documentation-specific elements.
"""

import re
import html2text
import logging
from typing import Optional, List, Dict, Any, Union
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin

logger = logging.getLogger("document_scraper")


class HtmlToMarkdownConverter:
    """
    Converts HTML content to Markdown with enhanced documentation formatting.
    """
    
    def __init__(self, base_url: Optional[str] = None) -> None:
        """
        Initialize the converter with optional settings.
        
        Args:
            base_url: Base URL for fixing relative links
        """
        self.base_url = base_url
        self.html2text_instance = html2text.HTML2Text()
        
        # Configure html2text
        self.html2text_instance.ignore_links = False
        self.html2text_instance.ignore_images = False
        self.html2text_instance.ignore_tables = False
        self.html2text_instance.body_width = 0  # Don't wrap lines
        self.html2text_instance.protect_links = True
        self.html2text_instance.unicode_snob = True
        self.html2text_instance.mark_code = True
        
        # Additional options for better markdown output
        self.html2text_instance.pad_tables = True
        self.html2text_instance.single_line_break = False
        
        if base_url:
            self.html2text_instance.baseurl = base_url
    
    def preprocess_html(self, html_content: str) -> str:
        """
        Improved HTML preprocessing to better handle complex modern web content.
        
        Args:
            html_content: Raw HTML content
            
        Returns:
            Preprocessed HTML content
        """
        # Try parsing with lxml first (faster and more lenient)
        try:
            soup = BeautifulSoup(html_content, 'lxml')
            if soup.find():
                return self._extract_main_content(soup)
        except Exception as e:
            logger.debug(f"lxml parser failed, falling back: {e}")
        
        # Fallback to html.parser if lxml fails
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            if soup.find():
                return self._extract_main_content(soup)
        except Exception as e:
            logger.debug(f"html.parser failed, falling back: {e}")
        
        # Last resort: return original content
        return html_content
        
    def _extract_main_content(self, soup: BeautifulSoup) -> str:
        """Enhanced helper to extract main content from parsed HTML with special cases."""
        # Look for common documentation content containers
        # Try many common selectors used by popular doc sites
        selectors = [
            "main", "article", "#content", ".content", 
            "#main-content", ".main-content", "#docs-content", ".documentation",
            ".doc-content", ".markdown-body", ".article-content", ".post-content",
            "[role='main']", "[role='article']", ".page-content", ".site-content",
            # For Cursor.com documentation specifically
            ".prose", ".markdown", ".mdx-content", ".docs-container",
            # Fallback general containers
            ".container", ".wrapper", "#container", "#wrapper",
            "body"  # Final fallback
        ]
        
        for selector in selectors:
            try:
                content = soup.select_one(selector)
                if content and len(content.get_text(strip=True)) > 100:  # Must have substantial text
                    # Create clean document structure
                    new_doc = BeautifulSoup(features="html.parser")
                    new_doc.append(content)
                    return str(new_doc)
            except Exception:
                continue
            
        # If we couldn't find a container, try to remove obvious non-content areas
        # like headers, footers, navigation before returning
        for noise in soup.select('header, footer, nav, .sidebar, .nav, .menu, .toolbar, .banner'):
            noise.decompose()
        
        return str(soup)
    
    def postprocess_markdown(self, markdown_content: str) -> str:
        """
        Postprocess Markdown content after conversion to enhance formatting.
        
        Args:
            markdown_content: Raw Markdown content
            
        Returns:
            Enhanced Markdown content
        """
        try:
            # Fix code blocks that might have been incorrectly formatted
            markdown_content = re.sub(r"```\n```([a-zA-Z0-9_-]+)", r"```\1", markdown_content)
            
            # Fix unnecessary newlines in code blocks
            markdown_content = re.sub(r"```([a-zA-Z0-9_-]+)\n\n", r"```\1\n", markdown_content)
            
            # Ensure consistent heading styles (ATX-style with space after #)
            for i in range(6, 0, -1):
                hashes = "#" * i
                markdown_content = re.sub(f"{hashes}([^#\n])", f"{hashes} \\1", markdown_content)
            
            # Fix reference-style links
            markdown_content = re.sub(r"\n\s*\[\d+\]:\s*", "\n", markdown_content)
            
            # Fix excess newlines
            markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content)
            
            # Ensure the document starts with a heading if it doesn't already
            if not markdown_content.startswith("#"):
                lines = markdown_content.split("\n")
                for i, line in enumerate(lines):
                    if line.strip() and not line.startswith("#"):
                        lines[i] = f"# {line}"
                        break
                markdown_content = "\n".join(lines)
        
            return markdown_content.strip()
        except Exception as e:
            logger.error(f"Error postprocessing Markdown: {e}")
            return markdown_content.strip()  # Return stripped original content on error
    
    def convert(self, html_content: str, url: Optional[str] = None) -> str:
        """
        Convert HTML content to Markdown with robust error handling.
        
        Args:
            html_content: Raw HTML content
            url: URL of the content for better link handling
            
        Returns:
            Converted Markdown content (or fallback text if conversion fails)
        """
        try:
            # First try full conversion pipeline
            processed_html = self.preprocess_html(html_content)
            markdown_content = self.html2text_instance.handle(processed_html)
            return self.postprocess_markdown(markdown_content)
            
        except Exception as e:
            logger.warning(f"Error in HTML conversion pipeline: {e}")
            
            # Fallback 1: Try direct conversion without preprocessing
            try:
                basic_md = self.html2text_instance.handle(html_content)
                return basic_md
            except Exception as e:
                logger.warning(f"Basic conversion failed: {e}")
                
                # Fallback 2: Extract text content only
                try:
                    soup = BeautifulSoup(html_content, 'html.parser')
                    return soup.get_text()
                except Exception as e:
                    logger.error(f"Complete conversion failure: {e}")
                    return "[Error converting content]"
        
        # Ensure we always return a string
        return ""


def convert_html_to_markdown(html_content: str, base_url: Optional[str] = None) -> str:
    """
    Convenience function to convert HTML to Markdown.
    
    Args:
        html_content: HTML content to convert
        base_url: Optional base URL for resolving relative links
        
    Returns:
        Converted Markdown content
    """
    converter = HtmlToMarkdownConverter(base_url=base_url)
    return converter.convert(html_content)
