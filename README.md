# Prompt Manager for espanso

A tiny, instant editor for your espanso prompts. Type, and the prompt is live in espanso about a second later. There's nothing to copy and paste into `base.yml`.

- **Tabs:** group prompts (Coding, Writing, Sales…). Each tab is its own `.yml` file in espanso's `match` folder, which is how espanso organises files anyway. **General** is `base.yml`.
- **Instant:** one Python file plus one HTML page, standard library only, no build step and no framework. It starts in well under a second.
- **Import from Google Sheets:** copy your rows (with the header row) and paste them. CSV files work too. Columns: `trigger`, `prompt`, `label`, `group` (each group becomes a tab).
- **Auto-update:** it checks this repo when it starts and installs new versions in the background. You can also check by hand from the version button (top right). Updates never touch your prompts.
- **Safe:** saves are atomic and each file gets a `.bak` backup on the first save. Matches with variables, regex or forms are kept untouched. A YAML error pauses editing instead of overwriting.
- **Find anything:** search across all tabs (Ctrl/Cmd+K), a sidebar per tab, and espanso's own search (Alt+Space) in any app.
- **Refine:** one click copies a prompt-improver for Claude. With an API key, it rewrites the prompt in place, with Undo.

## Install

Download **Code → Download ZIP** and unzip it anywhere (Documents, Dropbox, a USB stick). Or clone it:

```bash
git clone https://github.com/973lean/promptmanager
```

Needs Python 3.8+ (built in on macOS and Linux; on Windows, get it from python.org).

## Start

| OS | Do |
|---|---|
| macOS | double-click `start.command` (first time: right-click → Open) |
| Windows | double-click `start.bat` |
| Any | `python3 pm.py` |

Your browser opens `http://127.0.0.1:7878`. Keep the window that started it open while you edit.

## Writing prompts

- **Trigger:** what you type, e.g. `:email`. Use commas for several (`:em, :mail`).
- **Label:** what espanso's search shows.
- **Prompt:** the text. `$|$` marks where the cursor lands.
- **Move to…:** on each prompt, moves it to another tab. Use **⋯** on a tab to rename or delete it (a `.bak` copy is kept).

## Optional: Refine with Claude

```bash
pip install anthropic
```

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Without a key, **Refine** copies a ready-made "improve this prompt" message for you to paste into Claude. Set `PM_MODEL` to use a different model.

## Notes

- Comments inside a `.yml` file aren't kept when it's saved; the `.bak` file has the original.
- The server only listens on `127.0.0.1` and only accepts requests from its own page, so websites can't write to your files.
- Options: `python3 pm.py <match-folder> --port 7900 --no-open`. `ESPANSO_DIR` overrides the detected espanso folder, and `PM_NO_UPDATE=1` skips the startup update check.

## Releasing an update (maintainer)

Bump `VERSION` in `pm.py` and `"version"` in `manifest.json` (keep them the same), list any new files in `manifest.json`, and push to `main`. Every install picks it up on its next start.
