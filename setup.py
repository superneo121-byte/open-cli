"""
Packaging script for Open CLI.

Install from a local clone:
    pip install .

Install straight from GitHub:
    pip install git+https://github.com/YOUR_USERNAME/open-cli.git
"""

from pathlib import Path

from setuptools import setup

# Use the README as the long description (shown on PyPI / package metadata).
README = Path(__file__).parent / "README.md"
long_description = README.read_text(encoding="utf-8") if README.exists() else ""

setup(
    name="open-cli",
    version="1.0.0",
    description="Chat with any OpenAI-compatible AI model or provider from your terminal.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="YOUR_NAME",
    url="https://github.com/YOUR_USERNAME/open-cli",
    license="MIT",
    py_modules=["opencli"],
    python_requires=">=3.7",
    install_requires=["requests>=2.20.0"],
    # This creates the global `opencli` command, which calls opencli.main().
    entry_points={
        "console_scripts": [
            "opencli=opencli:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Utilities",
    ],
    keywords="cli ai llm openai groq ollama deepseek openrouter vllm chat streaming",
)
