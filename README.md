# sub2api-cli

A small terminal UI for managing the sub2api group used by your local Codex token.

It reads the Codex API key from `~/.codex/auth.json`, finds the matching sub2api API key, shows its current group, lets you switch that group, toggles account scheduling inside a group, and can print recent usage logs.

The CLI never prints the full Codex token. It only shows a masked token and a short SHA-256 fingerprint.

## Features

- Detect the current Codex token from `~/.codex/auth.json`
- Locate which sub2api group that token currently uses
- Switch the current Codex token to another group
- List accounts in a group
- Toggle account scheduling on or off
- View latest usage logs, defaulting to the latest 20 records
- Use a keyboard-driven terminal UI
- Store the sub2api Admin API Key locally with `0600` permissions
- Use `http://127.0.0.1:7890` as the default proxy for sub2api requests

## Requirements

- Python 3.10+
- A terminal with `curses` support
- A sub2api Admin API Key
- A Codex auth file at `~/.codex/auth.json`

No third-party Python packages are required.

## Install

Clone the repository:

```bash
git clone https://github.com/tensor-x/sub2api-cli.git
cd sub2api-cli
chmod +x sub2api_cli.py
```

Optional: install it as `sub2api-cli`:

```bash
ln -sf "$PWD/sub2api_cli.py" /usr/local/bin/sub2api-cli
```

## Configure

Configure the sub2api Admin API Key.

This is **not** your Codex token. It is the Admin API Key used to call sub2api management APIs.

```bash
sub2api-cli config --admin-token '<your-sub2api-admin-api-key>'
```

The config file is written to:

```text
~/.config/sub2api-cli/config.json
```

The file mode is set to `0600`.

The default base URL is:

```text
https://sub2api.seei.app
```

Change it if needed:

```bash
sub2api-cli config --base-url https://sub2api.seei.app
```

The default proxy is:

```text
http://127.0.0.1:7890
```

Change the proxy:

```bash
sub2api-cli config --proxy-url http://127.0.0.1:7890
```

Disable the proxy:

```bash
sub2api-cli config --proxy-url ''
```

## Usage

Open the interactive UI:

```bash
sub2api-cli
```

or:

```bash
sub2api-cli ui
```

Print current status:

```bash
sub2api-cli status
```

Show the latest 20 usage logs:

```bash
sub2api-cli logs
```

Show a custom number of usage logs:

```bash
sub2api-cli logs -n 50
```

## Keyboard Shortcuts

| Key | Action |
| --- | --- |
| `↑` / `↓` | Move selection |
| `←` / `→` | Switch between group panel and account panel |
| `Enter` on group | Switch current Codex token to the selected group |
| `Enter` on account | Toggle account scheduling |
| `Space` on account | Toggle account scheduling |
| `o` on account | Enable account scheduling |
| `x` on account | Disable account scheduling |
| `r` | Refresh |
| `q` / `Esc` | Quit |

## How It Works

The CLI uses these sub2api Admin API endpoints:

- `GET /api/v1/admin/groups/all`
- `GET /api/v1/admin/groups/:id/api-keys`
- `GET /api/v1/admin/accounts?group=:id`
- `PUT /api/v1/admin/api-keys/:id`
- `POST /api/v1/admin/accounts/:id/schedulable`
- `GET /api/v1/admin/usage`

The CLI sends the Admin API Key with:

```text
x-api-key: <your-admin-api-key>
```

It also sends a browser-like `User-Agent` to avoid being blocked by overly strict edge rules.

## Security Notes

- Do not publish your `~/.config/sub2api-cli/config.json`.
- Do not publish your `~/.codex/auth.json`.
- The CLI masks token output and does not print full tokens.
- The Admin API Key is stored locally because the tool needs it to call sub2api management APIs.

## License

MIT
