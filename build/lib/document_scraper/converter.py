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
        Preprocess HTML content before conversion to handle special cases.
        
        Args:
            html_content: Raw HTML content
            
        Returns:
            Preprocessed HTML content
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Try to extract the main content div
            main_content = None
            for selector in [
                "main", 
                "article", 
                "#content", 
                ".content", 
                ".documentation", 
                ".doc-content",
                "#main-content",
                ".main-content"
            ]:
                main_content = soup.select_one(selector)
                if main_content:
                    break
            
            # If we found a main content container, use only that
            if main_content:
                # Extract title
                title_elem = soup.find("title")
                title = title_elem.get_text() if title_elem else ""
                
                # Find any h1 in the main content or the first heading
                h1 = main_content.find("h1")
                if not h1:
                    for tag in ["h2", "h3", "h4"]:
                        h1 = main_content.find(tag)
                        if h1:
                            break
                
                # Create a new document structure
                new_body = soup.new_tag("div")
                
                # Add the document title as H1 if not already present
                if title and (not h1 or h1.get_text() != title):
                    h1_tag = soup.new_tag("h1")
                    h1_tag.string = title
                    new_body.append(h1_tag)
                
                # Add the main content
                new_body.append(main_content)
                
                # Replace the original html with our new structure
                for tag in soup.find_all(["html", "body"]):
                    tag.clear()
                
                if soup.body:
                    soup.body.append(new_body)
                elif soup.html:
                    soup.html.append(new_body)
        
            # Fix relative links to include base_url
            if self.base_url:
                for link in soup.find_all("a", href=True):
                    href = link.get("href")
                    if href and not (href.startswith("http") or href.startswith("#") or href.startswith("mailto:")):
                        link["href"] = urljoin(self.base_url, href)
            
            # Fix relative image sources
            if self.base_url:
                for img in soup.find_all("img", src=True):
                    src = img.get("src")
                    if src and not src.startswith("http"):
                        img["src"] = urljoin(self.base_url, src)
        
            # Enhance code blocks to ensure proper Markdown conversion
            for pre in soup.find_all("pre"):
                code = pre.find("code")
                if code:
                    lang = ""
                    for class_name in code.get("class", []):
                        if class_name.startswith("language-"):
                            lang = class_name.replace("language-", "")
                            break
                    
                    code_text = code.get_text()
                    new_pre = soup.new_tag("pre")
                    new_pre.string = f"```{lang}\n{code_text}\n```"
                    pre.replace_with(new_pre)
        
            return str(soup)
        except Exception as e:
            logger.error(f"Error preprocessing HTML: {e}")
            return html_content  # Return original content on error
    
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
        Convert HTML content to Markdown.
        
        Args:
            html_content: Raw HTML content
            url: URL of the content for better link handling
            
        Returns:
            Converted Markdown content
        """
        try:
            # Preprocess the HTML
            processed_html = self.preprocess_html(html_content)
            
            # Convert to Markdown
            markdown_content = self.html2text_instance.handle(processed_html)
            
            # Postprocess the Markdown
            final_markdown = self.postprocess_markdown(markdown_content)
            
            return final_markdown
        except Exception as e:
            logger.error(f"Error converting HTML to Markdown: {e}")
            # If conversion fails, return a basic conversion
            basic_converter = html2text.HTML2Text()
            basic_converter.body_width = 0
            basic_converter.unicode_snob = True
            try:
                return basic_converter.handle(html_content)
            except Exception as fallback_error:
                logger.error(f"Even basic conversion failed: {fallback_error}")
                # Last resort: strip HTML tags and return plain text
                return BeautifulSoup(html_content, "html.parser").get_text()


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
