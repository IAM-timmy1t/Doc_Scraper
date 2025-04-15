"""
Tests for validation utilities (unittest version).
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import unittest
from document_scraper.utils import is_valid_url, validate_url
import click

class TestValidation(unittest.TestCase):
    # Test cases for is_valid_url
    VALID_URLS = [
        "https://example.com",
        "http://example.com/path",
        "https://sub.example.com?query=param",
        "http://localhost:8000",
        "https://example.com#fragment"
    ]

    INVALID_URLS = [
        "example.com",          # Missing scheme
        "http:///path",         # Missing host
        "https://",             # Empty host
        "ftp://example.com",    # Unsupported scheme
        "javascript:alert(1)",  # Dangerous scheme
        ""                      # Empty string
    ]

    def test_valid_urls(self):
        """Test valid URLs return True."""
        for url in self.VALID_URLS:
            with self.subTest(url=url):
                self.assertTrue(is_valid_url(url))

    def test_invalid_urls(self):
        """Test invalid URLs return False."""
        for url in self.INVALID_URLS:
            with self.subTest(url=url):
                self.assertFalse(is_valid_url(url))

    # Test cases for validate_url
    NORMALIZATION_CASES = [
        ("https://example.com/", "https://example.com"),
        ("http://example.com/path/", "http://example.com/path"),
        ("https://example.com/?query=param", "https://example.com?query=param")
    ]

    def test_url_normalization(self):
        """Test URL normalization."""
        for input_url, expected in self.NORMALIZATION_CASES:
            with self.subTest(input=input_url):
                self.assertEqual(validate_url(None, None, input_url), expected)

    def test_invalid_url_validation(self):
        """Test invalid URLs raise BadParameter."""
        for url in self.INVALID_URLS:  
            with self.subTest(url=url):
                if url == "":
                    self.assertIsNone(validate_url(None, None, url))
                else:
                    with self.assertRaises(click.BadParameter):
                        validate_url(None, None, url)

    def test_empty_url_returns_none(self):
        """Test empty URL returns None."""
        self.assertIsNone(validate_url(None, None, ""))

if __name__ == "__main__":
    unittest.main()
