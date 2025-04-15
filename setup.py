"""
Installation script for the Document Scraper module.

This setup script supports creating wheel packages and proper installation.
To create a wheel file, run:
    python setup.py bdist_wheel

To install from the wheel file:
    pip install dist/document_scraper-x.y.z-py3-none-any.whl

To install in development mode:
    pip install -e .
"""

import os
import re
import sys
from setuptools import setup, find_packages, Commandfrom setuptools import setup, find_packages, Command setuptools import setup, find_packages, Commandfrom setuptools import setup, find_packages, Command setuptools import setup, find_packages, Commandfrom setuptools import setup, find_packages, Command setuptools import setup, find_packages, Commandfrom setuptools import setup, find_packages, Command

# Get the absolute path to the package directory
here = os.path.abspath(os.path.dirname(__file__))

# Read version from __init__.py to avoid duplication
with open(os.path.join(here, 'document_scraper', '__init__.py'), 'r', encoding='utf-8') as f:
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", f.read(), re.M)
    version = version_match.group(1) if version_match else '0.2.0'

# Read long description from README
with open(os.path.join(here, "README.md"), "r", encoding="utf-8") as fh:
    long_description = fh.read()

# Set up development dependencies
extra_requirements = {
    'dev': [
        'pytest>=7.0.0',
        'pytest-cov>=3.0.0',
        'black>=22.3.0',
        'isort>=5.10.0',
        'flake8>=4.0.1',
        'mypy>=0.950',
    ],
    'docs': [
        'sphinx>=4.5.0',
        'sphinx-rtd-theme>=1.0.0',
    ],
    'gui': [
        'tkinter>=8.6.0;python_version<"3.7"',  # tkinter is included in Python 3.7+
        'pillow>=9.0.0',  # For image handling in GUI
    ],
}

# Define custom commands
class BuildWheelCommand(Command):
    description = 'Build wheel package and show location'
    user_options = []
    
    def initialize_options(self):
        pass
        
    def finalize_options(self):
        pass
        
    def run(self):
        # First run the standard bdist_wheel command
        self.announce('Building wheel package...')
        self.run_command('bdist_wheel')
        
        # Then display information about the created wheel
        dist_dir = os.path.join(here, 'dist')
        if os.path.exists(dist_dir):
            wheels = [f for f in os.listdir(dist_dir) if f.endswith('.whl')]
            if wheels:
                newest_wheel = max(wheels, key=lambda x: os.path.getmtime(os.path.join(dist_dir, x)))
                wheel_path = os.path.join(dist_dir, newest_wheel)
                self.announce(f'\nWheel package created successfully: {wheel_path}')
                self.announce(f'\nTo install this package, run:')
                self.announce(f'pip install {wheel_path}\n')
            else:
                self.announce('No wheel packages found in dist directory.')
        else:
            self.announce('Dist directory not found.')


class CleanCommand(Command):
    """Custom clean command to tidy up the project root."""
    description = 'Remove build artifacts and cache directories'
    user_options = []
    
    def initialize_options(self):
        pass
        
    def finalize_options(self):
        pass
        
    def run(self):
        # Define paths to clean
        clean_paths = [
            './build',
            './dist',
            './*.egg-info',
            './*.egg',
            './__pycache__',
            './**/__pycache__',
            './**/*.pyc',
            './**/*.pyo',
            './**/*.pyd',
            './.pytest_cache',
            './.coverage',
            './htmlcov',
            './.tox',
        ]
        
        for path_pattern in clean_paths:
            path_pattern = os.path.normpath(path_pattern)
            # Handle glob patterns
            import glob
            for path in glob.glob(path_pattern, recursive=True):
                if os.path.exists(path):
                    self.announce(f'Removing {path}')
                    if os.path.isdir(path):
                        import shutil
                        shutil.rmtree(path)
                    else:
                        os.unlink(path)


class PublishCommand(Command):
    """Custom command to publish package to PyPI."""
    description = 'Build and publish the package to PyPI'
    user_options = [
        ('test', 't', 'Publish to TestPyPI instead of PyPI'),
    ]
    
    def initialize_options(self):
        self.test = False
        
    def finalize_options(self):
        pass
        
    def run(self):
        # Clean previous builds
        self.run_command('clean')
        
        # Build distributions
        self.run_command('sdist')
        self.run_command('bdist_wheel')
        
        # Upload to PyPI
        self.announce('Publishing package to PyPI...')
        try:
            # Check if twine is installed
            import subprocess
            cmd = [sys.executable, '-m', 'twine', 'check', 'dist/*']
            subprocess.check_call(cmd)
            
            # Upload with twine
            repository = 'testpypi' if self.test else 'pypi'
            cmd = [
                sys.executable, '-m', 'twine', 'upload', 
                f'--repository={repository}', 'dist/*'
            ]
            self.announce(f'Running: {" ".join(cmd)}')
            subprocess.check_call(cmd)
            
            self.announce(f'Successfully published package to {"Test" if self.test else ""}PyPI!')
        except Exception as e:
            self.announce(f'Error during upload: {e}')
            self.announce('\nPublishing failed. Please ensure you have twine installed:')
            self.announce('pip install twine')
            self.announce('\nAnd that you have configured your PyPI credentials.')
            raise

# Package configuration
setup(
    name="document-scraper",
    version=version,
    author="DocScraper Developer",
    author_email="developer@example.com",
    description="A tool for downloading documentation websites and converting them to Markdown",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/IAM_timmy1t/document_scraper",
    project_urls={
        "Bug Tracker": "https://github.com/IAM_timmy1t/document_scraper/issues",
        "Documentation": "https://github.com/IAM_timmy1t/document_scraper/blob/main/README.md",
        "Source Code": "https://github.com/IAM_timmy1t/document_scraper"
    },
    packages=find_packages(),
    include_package_data=True,
    package_data={
        'document_scraper': ['*.md', '*.txt'],
    },
    zip_safe=False,
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Documentation",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Text Processing :: Markup :: Markdown",
    ],
    install_requires=[
        "requests>=2.28.1",
        "beautifulsoup4>=4.11.1",
        "html2text>=2020.1.16",
        "click>=8.1.3",
        "tqdm>=4.64.1",
        "validators>=0.20.0",
        "python-slugify>=7.0.0",
        "colorama>=0.4.6",
        "urllib3>=1.26.0"
    ],
    entry_points={
        "console_scripts": [
            "docscraper=document_scraper.cli:main"
        ]
    },
    cmdclass={
        'make_wheel': BuildWheelCommand,
        'clean': CleanCommand,
        'publish': PublishCommand,
    },
    extras_require=extra_requirements,
    python_requires='>=3.7,<4.0',
)