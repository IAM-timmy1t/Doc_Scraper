# DocScraper (v0.2.0)



## Features

- **Intelligent Crawling**: Automatically crawls documentation websites starting from a base URL, respecting the site's structure
- **Smart HTML to Markdown Conversion**: Converts HTML content to clean, well-formatted Markdown
- **Structure Preservation**: Maintains the original website's directory structure in the output
- **Concurrent Processing**: Downloads multiple pages simultaneously for faster completion
- **Asset Management**: Optionally download and organize related assets (images, CSS, JS)
- **Configurable**: Customize depth, speed, and scope of the crawl
- **User-Friendly CLI**: Simple command-line interface with interactive options
- **Enhanced Error Handling**: Robust error recovery with automatic retries
- **Rate Limiting**: Built-in protection against overloading servers
- **Type Annotations**: Full type hints throughout the codebase for better IDE integration

## Installation

### Using pip (recommended)
```bash
pip install document-scraper
```

### From Source (for latest/dev version)
```bash
git clone https://github.com/IAM_timmy1t/document_scraper.git
cd document_scraper
pip install -e .
```

#### With GUI support (Tkinter & Pillow)
```bash
pip install .[gui]
```

---

## Quick Start

### Command-Line Interface

```bash
# Download an entire documentation site
docscraper download --url https://mcp-framework.com/docs --output ./mcp-docs

# Interactive mode (prompts for options)
docscraper download

# Discover available sections
docscraper discover --url https://docs.python.org/3/
```

#### Common CLI Options
- `--url, -u`: Documentation site URL
- `--output, -o`: Output directory
- `--max-depth, -d`: Crawl depth (default: 5)
- `--delay`: Delay between requests (seconds)
- `--concurrent, -c`: Number of concurrent requests
- `--include-assets`: Download images, CSS, JS
- `--verbose, -v`: Verbose output

### Graphical User Interface (GUI)

```bash
# Launch the GUI
python -m document_scraper.cli gui
# or
python main.py
```

- Visual site structure exploration
- Select sections and assets interactively
- Progress bars and logs

---

## Execution Methods

### Recommended (Package Mode)
```bash
# Primary entry point
python -m document_scraper.cli

# Alternative entry point
python main.py
```

### Direct Script Execution
```bash
python document_scraper/cli.py
```

Note: Direct execution requires the package to be installed first (`pip install -e .`)

## Usage Examples

### Discover Documentation Sections
```bash
python -m document_scraper.cli discover --url https://example.com/docs
```

### Interactive Download
```bash
python -m document_scraper.cli download \
    --url https://example.com/docs \
    --output ./my_docs \
    --mode select
```

## Practical Examples

### Example 1: Basic Discovery
```bash
# Discover sections from Python docs
python -m document_scraper.cli discover --url https://docs.python.org/3/

# Sample Output:
# 1. Tutorial: https://docs.python.org/3/tutorial/
# 2. Library Reference: https://docs.python.org/3/library/
# 3. Language Reference: https://docs.python.org/3/reference/
```

### Example 2: Selective Download
```bash
# Download only specific sections
python -m document_scraper.cli download \
    --url https://docs.python.org/3/ \
    --output ./python_docs \
    --mode select

# Then enter: 1,3  (to download Tutorial and Language Reference)
```

### Example 3: Full Archive
```bash
# Download entire documentation
python -m document_scraper.cli download \
    --url https://docs.djangoproject.com/en/stable/ \
    --output ./django_docs \
    --mode full
```

### Example 4: Custom Selection
```bash
# Custom selection with verbose output
python -m document_scraper.cli download \
    --url https://fastapi.tiangolo.com/ \
    --output ./fastapi_docs \
    --mode custom \
    --verbose
```

## Advanced Usage

### Custom Selector Configuration
```python
from document_scraper.scraper import DocumentationScraper

# Configure custom CSS selectors for different documentation sites
config = {
    "python": {
        "section_selector": "div.section > h2",
        "link_selector": "div.toctree-wrapper a.internal"
    },
    "django": {
        "section_selector": "div.section h1",
        "link_selector": "div.section ul li a"
    }
}

scraper = DocumentationScraper(
    output_dir="./custom_docs",
    selectors=config["python"]  # Use Python docs selectors
)
scraper.download_section("https://docs.python.org/3/tutorial/")
```

### Parallel Downloading
```python
from concurrent.futures import ThreadPoolExecutor
from document_scraper.utils import discover_documentation_sections
from document_scraper.scraper import DocumentationScraper

sections = discover_documentation_sections("https://docs.djangoproject.com/en/stable/")
scraper = DocumentationScraper(output_dir="./django_parallel")

with ThreadPoolExecutor(max_workers=5) as executor:
    executor.map(scraper.download_section, sections.values())
```

### Custom Processing Pipeline
```python
from bs4 import BeautifulSoup
from document_scraper.scraper import DocumentationScraper

def process_html(content: str) -> str:
    """Custom HTML processor that removes navbars"""
    soup = BeautifulSoup(content, 'html.parser')
    for nav in soup.find_all('nav'):
        nav.decompose()
    return str(soup)

scraper = DocumentationScraper(
    output_dir="./processed_docs",
    postprocessor=process_html  # Add custom processing
)
scraper.download_section("https://fastapi.tiangolo.com/tutorial/")
```

### Error Handling & Retries
```python
from tenacity import retry, stop_after_attempt
from document_scraper.scraper import DocumentationScraper

@retry(stop=stop_after_attempt(3))
def download_with_retries(scraper, url):
    try:
        return scraper.download_section(url)
    except Exception as e:
        print(f"Failed to download {url}: {str(e)}")
        raise

scraper = DocumentationScraper(output_dir="./retry_docs")
download_with_retries(scraper, "https://unstable-docs.example.com")
```

## Validation Rules

The scraper validates URLs to ensure:
- Only HTTP/HTTPS schemes are allowed
- Proper URL format with scheme and netloc
- Rejection of potentially dangerous schemes (javascript, data, etc.)
- Empty URLs return None rather than raising errors

## Development

```bash
# Run tests
python -m unittest discover

# Lint code
flake8 document_scraper
```

## Programmatic Usage

You can also use DocScraper as a Python library:

```python
from document_scraper.scraper import scrape_documentation

scrape_documentation(
    base_url="https://mcp-framework.com/docs",
    output_dir="./mcp-docs",
    max_depth=3,
    delay=0.5,
    max_pages=None,  # No limit
    concurrent_requests=5,
    include_assets=False,
    timeout=30,
    retries=3
)

# You can also use individual components directly
from document_scraper.scraper import DocumentationScraper
from document_scraper.converter import HtmlToMarkdownConverter
from document_scraper.utils import create_path_from_url, is_valid_url

# Create a custom scraper with more options
scraper = DocumentationScraper(
    base_url="https://example.com/docs",
    output_dir="./output",
    user_agent="Custom User Agent",
    cookies={"session": "value"},
    proxies={"http": "http://proxy.example.com:8080"}
)

# Start the crawling process
pages_downloaded, assets_downloaded = scraper.crawl()
```

## Programmatic API Usage

### Basic Discovery
```python
from document_scraper.utils import discover_documentation_sections

# Get all sections from documentation
sections = discover_documentation_sections("https://docs.python.org/3/")
print(f"Found {len(sections)} documentation sections")
```

### Custom Downloader
```python
from document_scraper.utils import (
    discover_documentation_sections,
    prompt_documentation_selection
)
from document_scraper.scraper import DocumentationScraper

# 1. Discover sections
sections = discover_documentation_sections("https://docs.djangoproject.com/en/stable/")

# 2. Custom filtering (only sections containing 'model')
filtered = {k:v for k,v in sections.items() if 'model' in k.lower()}

# 3. Download selected sections
scraper = DocumentationScraper(output_dir="./django_models")
for url in filtered.values():
    scraper.download_section(url)
```

### Integration Example
```python
import requests
from document_scraper.scraper import DocumentationScraper

# Download docs and process with requests
scraper = DocumentationScraper(output_dir="./processed_docs")
downloaded = scraper.download_section("https://fastapi.tiangolo.com/tutorial/")

# Analyze downloaded content
for file in downloaded:
    with open(file) as f:
        content = f.read()
    if "async" in content:
        print(f"Found async content in {file}")
```

## API Reference

### Core Functions

#### `discover_documentation_sections(url: str) -> Dict[str, str]`
Discovers the main sections of a documentation site.
```python
from document_scraper.utils import discover_documentation_sections
sections = discover_documentation_sections("https://example.com/docs")
```

#### `prompt_documentation_selection(sections: Dict[str, str]) -> List[str]`
Prompts user to select sections interactively (CLI/GUI).
```python
from document_scraper.utils import prompt_documentation_selection
selected = prompt_documentation_selection(sections)
```

#### `DocumentationScraper`
Main class for downloading and converting documentation.
```python
from document_scraper.scraper import DocumentationScraper
scraper = DocumentationScraper(output_dir="./docs")
scraper.download_section("https://example.com/docs/intro")
```

---


### Core Functions

#### `discover_documentation_sections(url: str) -> Dict[str, str]`
```python
from document_scraper.utils import discover_documentation_sections

sections = discover_documentation_sections("https://example.com/docs")
# Returns: {'Introduction': 'https://example.com/docs/intro', ...}
```

**Parameters**:
- `url`: Base URL of documentation website

**Returns**:
Dictionary mapping section names to their URLs

---

#### `prompt_documentation_selection(sections: Dict[str, str]) -> List[str]`
```python
from document_scraper.utils import prompt_documentation_selection

selected = prompt_documentation_selection(sections)
# Returns: ['https://example.com/docs/intro', ...]
```

**Parameters**:
- `sections`: Dictionary from `discover_documentation_sections()`

**Returns**:
List of selected URLs

---

### CLI Components

#### `@cli.command(name="discover")`
```python
@click.option('--url', help='Documentation URL', callback=validate_url)
def discover(url):
    """Preview available documentation sections"""
```

#### `@cli.command(name="download")`
```python
@click.option('--url', help='Documentation URL', callback=validate_url)
@click.option('--output', help='Output directory', default='./scraped_docs')
def download(url, output):
    """Download documentation sections"""
```

### Utility Functions

#### `validate_url(ctx, param, value) -> Optional[str]`
Validates and normalizes URLs

#### `is_valid_url(url: str) -> bool`
Checks if URL has valid format and scheme

## Output Structure

Downloaded docs match the original website’s structure:
```
my_docs/
├── index.md
├── introduction.md
├── installation.md
├── tools/
│   ├── tools-overview.md
│   └── specific-tool.md
└── assets/
    ├── images/
    └── css/
```

---


The downloaded documentation will be organized to match the structure of the original website. For example:

```
mcp-docs/
├── index.md                   # https://mcp-framework.com/docs
├── introduction.md            # https://mcp-framework.com/docs/introduction
├── installation.md            # https://mcp-framework.com/docs/installation
├── tools/
│   ├── tools-overview.md      # https://mcp-framework.com/docs/tools/tools-overview
│   └── specific-tool.md       # https://mcp-framework.com/docs/tools/specific-tool
└── assets/                    # Only if --include-assets is used
    ├── images/
    │   └── logo.png
    └── css/
        └── style.css
```

## Requirements
- Python 3.7+
- requests, beautifulsoup4, html2text, click, tqdm, validators, python-slugify, colorama, urllib3
- For GUI: tkinter (included with Python), pillow

---


- Python 3.7+
- Dependencies: requests, beautifulsoup4, html2text, click, tqdm, validators, python-slugify, colorama, urllib3

## Development & Contributing

Contributions are welcome! Please open issues or pull requests.

### Development Setup
```bash
git clone https://github.com/IAM_timmy1t/document_scraper.git
cd document_scraper
pip install -e .[dev,gui]
```

#### Run Tests
```bash
python -m unittest discover
```

#### Lint & Type Check
```bash
flake8 document_scraper
mypy document_scraper
```

---

## Acknowledgements
- [html2text](https://github.com/Alir3z4/html2text) for HTML→Markdown
- [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) for parsing
- [Click](https://click.palletsprojects.com/) for CLI
- [tqdm](https://github.com/tqdm/tqdm) for progress bars
- [validators](https://github.com/python-validators/validators) for URL validation

---

## License
MIT License. See [LICENSE](./LICENSE) for details.
