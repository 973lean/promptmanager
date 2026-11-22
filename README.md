# Prompt Manager for espanso

A tiny, instant editor for your espanso prompts. Type, and the prompt is live in espanso about a second later. There's nothing to copy and paste into `base.yml`.

- **Tabs:** group prompts (Coding, Writing, Sales…). Each tab is its own `.yml` file in espanso's `match` folder, which is how espanso organises files anyway. **General** is `base.yml`.
- **Instant:** one Python file plus one HTML page, standard library only, no framework. Also available as a single `.exe`.
- **Import from Google Sheets:** copy your rows (with the header row) and paste them. CSV files work too. Columns: `trigger`, `prompt`, `label`, `group` (each group becomes a tab).
- **Auto-update:** it checks this repo when it starts and installs new versions in the background. You can also check by hand from the version button (top right). Updates never touch your prompts.
- **Safe:** saves are atomic and each file gets a `.bak` backup on the first save. Matches with variables, regex or forms are kept untouched. A YAML error pauses editing instead of overwriting.
- **Your library:** **Quick add → Import many → Load my library** pulls the prompt library in [`library/`](library) into tabs (General, Copywriting, Creative Strategy, Formatting, Metaprompts, Study) on any computer. Prompts you already have are matched up and moved, not duplicated.
- **Switch view:** the small button next to **Quick add** moves you between the app window and a normal Chrome tab, and remembers your choice.
- **Find anything:** search across all tabs (Ctrl/Cmd+K), a sidebar per tab, and espanso's own search (Alt+Space) in any app.
- **Refine:** one click copies a prompt-improver for Claude. With an API key, it rewrites the prompt in place, with Undo.

## Install

**Windows, no Python needed:** download **PromptManager.exe** from [Releases](https://github.com/973lean/promptmanager/releases/latest), put it anywhere (e.g. Documents), and double-click it. Windows may warn about an unknown app the first time: click **More info → Run anyway**. It updates itself from Releases.

**With Python (any OS):** download **Code → Download ZIP** and *extract it first* (don't run it from inside the zip, or updates get lost). Then:

| OS | Do |
|---|---|
| Windows | double-click `PromptManager.pyw` (no console window) |
| macOS | double-click `start.command` (first time: right-click → Open) |
| Any | `python3 pm.py` |

It opens in its own Chrome/Edge app window (falls back to your normal browser), with no console window. Double-clicking again just brings it back. Use **Settings** (top right) to quit, start it with Windows, switch between an app window and a normal tab, or turn auto-update off. In Chrome or Edge you can also use **Install app** from the address bar.

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

Bump `VERSION` in `pm.py` and `"version"` in `manifest.json` (keep them the same), list any new files in `manifest.json`, and push to `main`. Script installs pick it up on their next start. The **Build Windows app** workflow builds `PromptManager.exe` and publishes a release, which `.exe` installs pick up.
