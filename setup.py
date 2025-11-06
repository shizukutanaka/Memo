#!/usr/bin/env python3
"""
Setup script for Enterprise Memo Management System
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding='utf-8')

# Read requirements
requirements = []
requirements_file = this_directory / "requirements.txt"
if requirements_file.exists():
    requirements = requirements_file.read_text().strip().split('\n')
    requirements = [req.strip() for req in requirements if req.strip() and not req.startswith('#')]

setup(
    name="enterprise-memo",
    version="1.0.0",
    description="Enterprise-grade secure memo management system",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Enterprise Development Team",
    author_email="",
    url="",
    license="MIT",

    # Package configuration
    py_modules=["memo_system", "config"],
    python_requires=">=3.8",
    install_requires=requirements,

    # Optional dependencies
    extras_require={
        "dev": [
            "pytest>=6.0.0",
            "pytest-cov>=2.10.0",
            "black>=21.0.0",
            "flake8>=3.8.0",
            "mypy>=0.800"
        ],
        "full": [
            "cryptography>=3.4.8",
            "bcrypt>=3.2.0",
            "whoosh>=2.7.4"
        ]
    },

    # Entry points for command line scripts
    entry_points={
        "console_scripts": [
            "memo-system=memo_system:main",
            "enterprise-memo=memo_system:main",
        ],
    },

    # Package classification
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Office/Business",
        "Topic :: Security",
        "Topic :: Database",
        "Topic :: Text Processing",
        "Environment :: Console",
    ],

    keywords="memo notes enterprise security government database encryption",

    # Package data
    include_package_data=True,
    zip_safe=False,

    # Project URLs
    project_urls={},
)