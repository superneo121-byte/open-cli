# Open CLI 1.0

A lightweight, universal command-line tool for chatting with **any** AI model that speaks the standard OpenAI chat completions API: OpenAI, Groq, Ollama, DeepSeek, OpenRouter, vLLM, LM Studio, or your own custom base URL.

- Real-time token streaming (Server-Sent Events)
- One tiny dependency (`requests`)
- Settings saved once, overridable per request
- Pipe files straight into the model
- Friendly error messages instead of stack traces

---

## Installation

Requires Python 3.7+.

Install directly from GitHub:

```bash
pip install git+https://github.com/YOUR_USERNAME/open-cli.git
```

Or from a local clone:

```bash
git clone https://github.com/YOUR_USERNAME/open-cli.git
cd open-cli
pip install .
```

This installs a global `opencli` command. Check it works:

```bash
opencli --version
```

To upgrade later, add `--upgrade` (and `--force-reinstall` if pip says it is already up to date):

```bash
pip install --upgrade git+https://github.com/YOUR_USERNAME/open-cli.git
```

---

## Quickstart

**1. Save your provider settings (one time):**

```bash
opencli --set-url https://api.openai.com/v1 --set-key YOUR_API_KEY --set-model gpt-4o-mini
```

**2. Chat:**

```bash
opencli "Explain how a hash map works in simple terms"
```

**3. Check your configuration:**

```bash
opencli --config
```

The API key is masked when displayed.

---

## Usage

```
opencli [prompt ...] [options]
```

| Flag | Description |
| --- | --- |
| `prompt` | The message to send (quote it, or pass several words) |
| `--set-url URL` | Permanently save the API base URL |
| `--set-key KEY` | Permanently save the API key |
| `--set-model MODEL` | Permanently save the model name |
| `--url URL` | Override the base URL for this request only |
| `--key KEY` | Override the API key for this request only |
| `--model MODEL` | Override the model for this request only |
| `--config` | Show the current configuration |
| `--version` | Show the version |
| `-h`, `--help` | Show help |

### One-time overrides

Overrides apply to a single request and are **not** saved:

```bash
opencli --model gpt-4o "Write a haiku about debugging"
opencli --url http://localhost:11434/v1 --model llama3 "Hello!"
```

### Piping input

Pipe any text into `opencli`. If you also pass a prompt, it is used as the instruction and the piped text follows it:

```bash
cat script.py | opencli "refactor this"
git diff | opencli "write a commit message for this diff"
cat error.log | opencli "what is going wrong here?"
echo "What is 2+2?" | opencli
```

---

## Provider examples

Any service exposing `{base_url}/chat/completions` in the OpenAI format works. Common setups:

| Provider | Base URL | Example model | API key |
| --- | --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` | Required |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` | Required |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini` | Required |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` | Required |
| Ollama (local) | `http://localhost:11434/v1` | `llama3` | Not needed |
| vLLM (local) | `http://localhost:8000/v1` | the model you served | Depends on your setup |
| LM Studio (local) | `http://localhost:1234/v1` | the loaded model | Not needed |

Model names change often, so check your provider's docs for current ones.

Example: switching to a local Ollama model

```bash
ollama pull llama3
opencli --set-url http://localhost:11434/v1 --set-model llama3
opencli "Hello from my own machine"
```

For providers that need no key, leave it empty (the default) and no `Authorization` header is sent.

---

## Configuration file

Settings are stored in `~/.config/open-cli/config.json`:

```json
{
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model": "gpt-4o-mini"
}
```

Defaults are used for anything missing. The file is created with owner-only permissions (`600`) where the OS supports it, since it may contain your API key.

**Security note:** keys passed with `--set-key` or `--key` can end up in your shell history. To avoid that, prefix the command with a space (works in bash/zsh when `HISTCONTROL=ignorespace` is set) or edit the config file directly.

---

## Troubleshooting

| Message | Likely cause |
| --- | --- |
| `HTTP 401: Unauthorized` | Missing or invalid API key. Use `--set-key`. |
| `HTTP 404: Not found` | Wrong base URL or model name. Check `--set-url` and `--set-model`. |
| `HTTP 429` | Rate limit or quota exceeded. Wait or check your plan. |
| `could not connect` | Server not running, wrong URL, or no internet connection. |
| `invalid URL` | The base URL is missing `http://` or `https://`. |
| `response could not be parsed` | The endpoint doesn't support OpenAI-style streaming. |

---

## Limitations (v1.0)

- Single-turn: each run sends one message and does not remember earlier ones.
- Streaming only; there is no non-streaming mode.
- No system prompt option yet.

---

## Contributing

Issues and pull requests are welcome. Fork the repo, make your change on a branch, and open a PR.

## License

MIT. Add a `LICENSE` file to your repository before publishing.
