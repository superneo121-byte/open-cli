#!/usr/bin/env python3
"""
Open CLI 1.0
A universal command-line interface for chatting with ANY AI model or provider
that supports the OpenAI chat completions schema (Gemini, OpenAI, Groq, Ollama,
DeepSeek, OpenRouter, vLLM, ...). Streams tokens live to your terminal.

Quick start:
    export GEMINI_API_KEY=your_key        # or: opencli --set-key your_key
    opencli "Hello world"
    cat script.py | opencli "refactor this"
    opencli --set-url http://localhost:11434/v1 --set-model llama3 --set-key ""
    opencli --config

API key lookup order (first match wins):
    1. --key                      (this request only)
    2. api_key in the config file (set with --set-key)
    3. OPENCLI_API_KEY            (any provider)
    4. GEMINI_API_KEY / GOOGLE_API_KEY   (only when the URL is a googleapis.com host)
    5. OPENAI_API_KEY             (only when the URL host is api.openai.com)
Provider-specific variables are only sent to their own provider, so a key for
one service is never leaked to another by accident.
"""

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    sys.stderr.write(
        "Error: the 'requests' library is required. Install it with:\n"
        "    pip install requests\n"
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0"
CONFIG_DIR = Path.home() / ".config" / "open-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "api_key": "",
    "model": "gemini-4-hydrogen",
}

GEMINI_KEY_PAGE = "https://aistudio.google.com/apikey"

# (connect timeout, read timeout) in seconds. The read timeout applies to the
# gap between received chunks, so long streams are fine as long as tokens flow.
REQUEST_TIMEOUT = (10, 120)


# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

def setup_stdio() -> None:
    """Force UTF-8 on stdio so non-ASCII text works in minimal terminals (e.g. Termux)."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass  # older Python or an unusual stream; carry on with defaults


def err(message: str) -> None:
    sys.stderr.write(message + "\n")


# ---------------------------------------------------------------------------
# Configuration management
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load settings from disk, falling back to defaults for anything missing."""
    config = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                # Only accept known string keys so a hand-edited file can't inject junk.
                for key in DEFAULT_CONFIG:
                    if isinstance(saved.get(key), str):
                        config[key] = saved[key]
            else:
                err("Warning: config file is not a JSON object. Using defaults.")
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            err(f"Warning: could not read config file ({exc}). Using defaults.")
    return config


def save_config(config: dict) -> None:
    """Persist settings to disk. Permissions are restricted since it may hold an API key."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        try:
            os.chmod(CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)  # best effort
        except OSError:
            pass
    except OSError as exc:
        err(f"Error: could not save config file: {exc}")
        sys.exit(1)


def mask_key(key: str) -> str:
    """Hide most of an API key when displaying it."""
    if not key:
        return "(not set)"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


def get_host(url: str) -> str:
    """Return the lowercase hostname of a URL, or '' if it can't be parsed."""
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_google_host(url: str) -> bool:
    host = get_host(url)
    return host == "googleapis.com" or host.endswith(".googleapis.com")


def resolve_api_key(base_url: str, config_key: str, cli_key) -> Tuple[str, str]:
    """
    Work out which API key to use. Returns (key, source_description).
    An explicit empty --key means "send no key" (handy for local servers).
    """
    if cli_key is not None:
        return cli_key.strip(), "--key flag"
    if config_key:
        return config_key, "config file"

    env_key = os.environ.get("OPENCLI_API_KEY", "").strip()
    if env_key:
        return env_key, "OPENCLI_API_KEY"

    host = get_host(base_url)
    if is_google_host(base_url):
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            value = os.environ.get(name, "").strip()
            if value:
                return value, name
    elif host == "api.openai.com":
        value = os.environ.get("OPENAI_API_KEY", "").strip()
        if value:
            return value, "OPENAI_API_KEY"

    return "", "none"


def show_config(config: dict) -> None:
    """Print the saved configuration and where the effective key would come from."""
    key, source = resolve_api_key(config["base_url"], config["api_key"], None)
    print(f"Open CLI {VERSION} configuration")
    print(f"  Config file : {CONFIG_FILE} ({'found' if CONFIG_FILE.exists() else 'not created yet, using defaults'})")
    print(f"  base_url    : {config['base_url']}")
    print(f"  model       : {config['model']}")
    print(f"  api_key     : {mask_key(key)}  (source: {source})")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opencli",
        description="Open CLI: chat with any OpenAI-compatible AI model from your terminal.",
        epilog='Tip: pipe in content with  cat file.py | opencli "refactor this"',
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="The prompt to send to the model (quote it, or pass multiple words).",
    )

    save_group = parser.add_argument_group("permanent settings (saved to config)")
    save_group.add_argument("--set-url", metavar="URL", help="Save the API base URL.")
    save_group.add_argument("--set-key", metavar="KEY", help="Save the API key (use \"\" to clear it).")
    save_group.add_argument("--set-model", metavar="MODEL", help="Save the model name.")

    override_group = parser.add_argument_group("one-time overrides (not saved)")
    override_group.add_argument("--url", metavar="URL", help="Override base URL for this request.")
    override_group.add_argument("--key", metavar="KEY", help="Override API key for this request (\"\" = send none).")
    override_group.add_argument("--model", metavar="MODEL", help="Override model for this request.")

    parser.add_argument("--config", action="store_true", help="Show current configuration.")
    parser.add_argument("--version", action="version", version=f"Open CLI {VERSION}")
    return parser


# ---------------------------------------------------------------------------
# API communication & streaming
# ---------------------------------------------------------------------------

def explain_http_error(response: "requests.Response") -> str:
    """Build a friendly message for a non-2xx HTTP response."""
    status = response.status_code
    hints = {
        400: "Bad request. Check the model name and request format (a wrong API key can also cause this on some providers).",
        401: "Unauthorized. Your API key is missing or invalid (use --set-key).",
        403: "Forbidden. Your key doesn't have access to this model or resource.",
        404: "Not found. Check the base URL (--set-url) and the model name.",
        408: "The server timed out waiting for the request. Try again.",
        413: "Input too large. Try sending less content.",
        429: "Rate limit or quota exceeded. Wait a moment or check your plan.",
        500: "The server hit an internal error. Try again later.",
        502: "Bad gateway. The provider may be down.",
        503: "Service unavailable. The provider may be overloaded.",
        504: "Gateway timeout. The provider took too long to respond.",
    }
    message = hints.get(status, f"The server returned an error ({response.reason}).")

    # Surface the provider's own error message when there is one.
    detail = ""
    try:
        body = response.json()
        if isinstance(body, list) and body:
            body = body[0]  # Google sometimes wraps errors in a list
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message", ""))
            elif isinstance(error, str):
                detail = error
            else:
                detail = str(body.get("message", ""))
    except (ValueError, AttributeError):
        text = response.text.strip()
        detail = text[:300] if text else ""

    result = f"HTTP {status}: {message}"
    if detail:
        result += f"\nServer says: {detail[:500]}"
    return result


def stream_chat(base_url: str, api_key: str, model: str, prompt: str) -> int:
    """
    Send the prompt to {base_url}/chat/completions and stream the reply to stdout.
    Returns a process exit code (0 on success).
    """
    endpoint = base_url.rstrip("/") + "/chat/completions"

    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }

    response = None
    try:
        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            stream=True,
            timeout=REQUEST_TIMEOUT,
        )

        if not response.ok:
            err(f"Error: {explain_http_error(response)}")
            return 1

        # Providers often omit the charset; without this requests may guess Latin-1.
        response.encoding = "utf-8"

        received_any = False
        skipped_chunks = 0

        # iter_lines yields the SSE stream line by line as bytes arrive.
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue  # blank line = SSE event separator
            line = raw_line.strip()

            # Ignore SSE comments/keep-alives (": ping") and non-data fields.
            if not line.startswith("data:"):
                continue

            data = line[5:].strip()
            if data == "[DONE]":
                break  # clean termination signal
            if not data:
                continue

            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                skipped_chunks += 1
                continue

            # Some providers report errors mid-stream as a JSON object.
            if isinstance(chunk, dict) and "error" in chunk:
                e = chunk["error"]
                msg = e.get("message", str(e)) if isinstance(e, dict) else str(e)
                err(f"\nError from server: {msg}")
                return 1

            try:
                choices = chunk.get("choices") or []
                if not choices:
                    continue  # e.g. usage-only chunks
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
            except (AttributeError, IndexError, TypeError):
                skipped_chunks += 1
                continue

            if content:
                received_any = True
                sys.stdout.write(content)
                sys.stdout.flush()  # tokens appear immediately

        sys.stdout.write("\n")
        sys.stdout.flush()

        if not received_any:
            if skipped_chunks:
                err(
                    "Error: the server's response could not be parsed. "
                    "Does this endpoint support the OpenAI streaming format?"
                )
            else:
                err("Warning: the model returned an empty response.")
            return 1
        return 0

    except requests.exceptions.MissingSchema:
        err(f"Error: invalid URL '{base_url}'. Include the scheme, e.g. https://api.openai.com/v1")
    except requests.exceptions.InvalidSchema:
        err(f"Error: unsupported URL scheme in '{base_url}'. Use http:// or https://")
    except requests.exceptions.InvalidURL:
        err(f"Error: the URL '{base_url}' is not valid.")
    except requests.exceptions.ConnectTimeout:
        err(f"Error: timed out connecting to {base_url}.")
    except requests.exceptions.ReadTimeout:
        err("\nError: the server stopped responding (read timeout).")
    except requests.exceptions.SSLError as exc:
        err(f"Error: SSL/TLS problem while connecting: {exc}")
    except requests.exceptions.ConnectionError:
        err(
            f"Error: could not connect to {base_url}.\n"
            "Check the URL, your internet connection, and that the server is running."
        )
    except requests.exceptions.ChunkedEncodingError:
        err("\nError: the connection was interrupted mid-stream.")
    except requests.exceptions.RequestException as exc:
        err(f"Error: request failed: {exc}")
    finally:
        if response is not None:
            response.close()

    return 1


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def read_stdin_if_piped() -> str:
    """Return piped stdin content, or an empty string when stdin is a terminal."""
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    try:
        return sys.stdin.read().strip()
    except (OSError, UnicodeDecodeError) as exc:
        err(f"Warning: could not read piped input ({exc}).")
        return ""


def run() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config()

    # 1. Persist any --set-* flags.
    updated = False
    if args.set_url is not None:
        config["base_url"] = args.set_url.strip()
        updated = True
    if args.set_key is not None:
        config["api_key"] = args.set_key.strip()
        updated = True
    if args.set_model is not None:
        config["model"] = args.set_model.strip()
        updated = True
    if updated:
        save_config(config)
        print(f"Settings saved to {CONFIG_FILE}")

    # 2. Show configuration if requested.
    if args.config:
        show_config(config)
        return 0

    # 3. Build the prompt from CLI words and/or piped stdin.
    #    `cat file.py | opencli "refactor this"` -> instruction first, then content.
    cli_prompt = " ".join(args.prompt).strip()
    piped = read_stdin_if_piped()
    if cli_prompt and piped:
        prompt = f"{cli_prompt}\n\n{piped}"
    else:
        prompt = cli_prompt or piped

    if not prompt:
        if updated:
            return 0  # user only wanted to save settings
        parser.print_help()
        return 0

    # 4. Apply one-time overrides (not saved) and resolve the API key.
    base_url = (args.url or config["base_url"]).strip()
    model = (args.model or config["model"]).strip()
    if not base_url:
        err("Error: no base URL configured. Use --set-url <url>.")
        return 1
    if not model:
        err("Error: no model configured. Use --set-model <model>.")
        return 1

    api_key, _source = resolve_api_key(base_url, config["api_key"], args.key)

    # The default Gemini endpoint always requires a key; fail early with help
    # instead of sending a doomed request.
    if not api_key and is_google_host(base_url):
        err(
            "Error: no API key found for the Gemini endpoint.\n"
            f"  1. Get a key at {GEMINI_KEY_PAGE}\n"
            "  2. Then run one of:\n"
            "       export GEMINI_API_KEY=your_key\n"
            "       opencli --set-key your_key\n"
            "Using a local server (e.g. Ollama)? Point to it with --set-url."
        )
        return 1

    # 5. Send the request and stream the response.
    return stream_chat(base_url, api_key, model, prompt)


def main() -> None:
    """Entry point with clean exit handling."""
    setup_stdio()
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        err("\nInterrupted.")
        sys.exit(130)
    except BrokenPipeError:
        # Happens when output is piped to something like `head`.
        try:
            sys.stdout.close()
        except Exception:
            pass
        sys.exit(0)


if __name__ == "__main__":
    main()
