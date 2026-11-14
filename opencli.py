#!/usr/bin/env python3
"""
Open CLI 1.0
A lightweight, universal command-line interface for chatting with ANY AI model
or provider that supports the standard OpenAI chat completions schema
(OpenAI, Groq, Ollama, DeepSeek, OpenRouter, vLLM, etc.).

Usage examples:
    opencli "Hello world"
    opencli --set-url http://localhost:11434/v1 --set-model llama3
    opencli --model gpt-4o "Explain quantum computing"
    cat script.py | opencli "refactor this"
    opencli --config
"""

import argparse
import json
import os
import stat
import sys
from pathlib import Path

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

__version__ = "1.0.0"
VERSION = "1.0"
CONFIG_DIR = Path.home() / ".config" / "open-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model": "gpt-4o-mini",
}

# (connect timeout, read timeout) in seconds. The read timeout applies to the
# gap between received chunks, so long streams are fine as long as tokens flow.
REQUEST_TIMEOUT = (10, 120)


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
                # Only accept known keys so a hand-edited file can't inject junk.
                for key in DEFAULT_CONFIG:
                    if key in saved and isinstance(saved[key], str):
                        config[key] = saved[key]
        except (json.JSONDecodeError, OSError) as exc:
            sys.stderr.write(
                f"Warning: could not read config file ({exc}). Using defaults.\n"
            )
    return config


def save_config(config: dict) -> None:
    """Persist settings to disk, restricting permissions since it may hold an API key."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        # Owner read/write only (best effort; may be a no-op on some platforms).
        try:
            os.chmod(CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    except OSError as exc:
        sys.stderr.write(f"Error: could not save config file: {exc}\n")
        sys.exit(1)


def mask_key(key: str) -> str:
    """Hide most of an API key when displaying it."""
    if not key:
        return "(not set)"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


def show_config(config: dict) -> None:
    """Print the current configuration."""
    print(f"Open CLI {VERSION} configuration")
    print(f"  Config file : {CONFIG_FILE}")
    print(f"  base_url    : {config['base_url']}")
    print(f"  api_key     : {mask_key(config['api_key'])}")
    print(f"  model       : {config['model']}")


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
    save_group.add_argument("--set-key", metavar="KEY", help="Save the API key.")
    save_group.add_argument("--set-model", metavar="MODEL", help="Save the model name.")

    override_group = parser.add_argument_group("one-time overrides (not saved)")
    override_group.add_argument("--url", metavar="URL", help="Override base URL for this request.")
    override_group.add_argument("--key", metavar="KEY", help="Override API key for this request.")
    override_group.add_argument("--model", metavar="MODEL", help="Override model for this request.")

    parser.add_argument("--config", action="store_true", help="Show current configuration.")
    parser.add_argument("--version", action="version", version=f"Open CLI {VERSION}")
    return parser


# ---------------------------------------------------------------------------
# API communication & streaming
# ---------------------------------------------------------------------------

def explain_http_error(response: requests.Response) -> str:
    """Build a friendly message for a non-2xx HTTP response."""
    status = response.status_code
    hints = {
        400: "Bad request. Check the model name and request format.",
        401: "Unauthorized. Your API key is missing or invalid (use --set-key).",
        403: "Forbidden. Your key doesn't have access to this resource.",
        404: "Not found. Check the base URL (--set-url) and the model name.",
        408: "Request timed out on the server side. Try again.",
        413: "Input too large. Try sending less content.",
        429: "Rate limit or quota exceeded. Wait a moment or check your plan.",
        500: "The server hit an internal error. Try again later.",
        502: "Bad gateway. The provider may be down.",
        503: "Service unavailable. The provider may be overloaded.",
        504: "Gateway timeout. The provider took too long to respond.",
    }
    message = hints.get(status, f"The server returned an error ({response.reason}).")

    # Try to surface the provider's own error message if there is one.
    detail = ""
    try:
        body = response.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            detail = err.get("message", "")
        elif isinstance(err, str):
            detail = err
        elif isinstance(body, dict):
            detail = body.get("message", "")
    except (ValueError, AttributeError):
        text = response.text.strip()
        detail = text[:300] if text else ""

    result = f"HTTP {status}: {message}"
    if detail:
        result += f"\nServer says: {detail}"
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
            sys.stderr.write(f"Error: {explain_http_error(response)}\n")
            return 1

        # Many providers send UTF-8 without declaring a charset; without this,
        # requests may guess Latin-1 and garble non-ASCII text.
        response.encoding = "utf-8"

        received_any = False
        skipped_chunks = 0

        # iter_lines parses the SSE stream line by line as bytes arrive.
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue  # blank line = SSE event separator
            line = raw_line.strip()

            # Ignore SSE comments/keep-alives (": ping") and non-data fields.
            if not line.startswith("data:"):
                continue

            data = line[5:].strip()

            # Clean termination signal.
            if data == "[DONE]":
                break
            if not data:
                continue

            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                skipped_chunks += 1
                continue

            # Some providers send errors mid-stream as a JSON object.
            if isinstance(chunk, dict) and "error" in chunk:
                err = chunk["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                sys.stderr.write(f"\nError from server: {msg}\n")
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
                sys.stdout.flush()  # make tokens appear immediately

        sys.stdout.write("\n")
        sys.stdout.flush()

        if not received_any:
            if skipped_chunks:
                sys.stderr.write(
                    "Error: the server's response could not be parsed. "
                    "Does this endpoint support the OpenAI streaming format?\n"
                )
            else:
                sys.stderr.write("Warning: the model returned an empty response.\n")
            return 1
        return 0

    except requests.exceptions.MissingSchema:
        sys.stderr.write(
            f"Error: invalid URL '{base_url}'. Include the scheme, "
            "e.g. https://api.openai.com/v1\n"
        )
    except requests.exceptions.InvalidSchema:
        sys.stderr.write(
            f"Error: unsupported URL scheme in '{base_url}'. Use http:// or https://\n"
        )
    except requests.exceptions.InvalidURL:
        sys.stderr.write(f"Error: the URL '{base_url}' is not valid.\n")
    except requests.exceptions.ConnectTimeout:
        sys.stderr.write(f"Error: timed out connecting to {base_url}.\n")
    except requests.exceptions.ReadTimeout:
        sys.stderr.write("\nError: the server stopped responding (read timeout).\n")
    except requests.exceptions.SSLError as exc:
        sys.stderr.write(f"Error: SSL/TLS problem while connecting: {exc}\n")
    except requests.exceptions.ConnectionError:
        sys.stderr.write(
            f"Error: could not connect to {base_url}.\n"
            "Check the URL, your internet connection, and that the server is running.\n"
        )
    except requests.exceptions.ChunkedEncodingError:
        sys.stderr.write("\nError: the connection was interrupted mid-stream.\n")
    except requests.exceptions.RequestException as exc:
        sys.stderr.write(f"Error: request failed: {exc}\n")
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
        sys.stderr.write(f"Warning: could not read piped input ({exc}).\n")
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

    # 4. Apply one-time overrides (without saving them).
    base_url = (args.url or config["base_url"]).strip()
    api_key = args.key if args.key is not None else config["api_key"]
    model = (args.model or config["model"]).strip()

    if not base_url:
        sys.stderr.write("Error: no base URL configured. Use --set-url <url>.\n")
        return 1
    if not model:
        sys.stderr.write("Error: no model configured. Use --set-model <model>.\n")
        return 1

    # 5. Send the request and stream the response.
    return stream_chat(base_url, api_key, model, prompt)


def main() -> None:
    """Console-script entry point (wraps run() with clean exit handling)."""
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted.\n")
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
