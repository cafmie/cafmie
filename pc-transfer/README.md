# PC Transfer

Desktop LAN tool for moving **game installs** and **save data** between a main Windows PC and a handheld Windows sub-PC on the same network.

- Same-LAN peer discovery (UDP broadcast) + manual IP connect
- Bidirectional HTTP transfer
- Manual registration of game folder + save folder(s) (no Steam auto-resolve)
- Games ship as ZIP archives; saves sync afterward with a **freshness check** (newer wins by default)
- In-app verification of registered paths (exists / size / last modified)
- Controller-first UI for handhelds (D-pad focus, A/B confirm/back)

## Requirements

- Python 3.10+
- Windows 10/11 recommended for the handheld + main PC workflow
- Both machines on the same LAN; allow inbound TCP/UDP on the app ports (default **8787** HTTP, **8788** discovery)

> Linux/macOS can run the same source for development and tests. Native folder picker needs a desktop session with tkinter; use typed paths or `PC_TRANSFER_HEADLESS=1` in CI.

## Install (Windows)

```powershell
cd pc-transfer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Run

**Main PC**

```powershell
python -m pc_transfer --role main --name "Main PC"
```

**Handheld**

```powershell
python -m pc_transfer --role handheld --name "Ally"
```

The UI opens at `http://127.0.0.1:8787/`. Other devices on the LAN reach this machine at `http://<lan-ip>:8787/`.

Useful flags:

| Flag | Meaning |
|------|---------|
| `--port 8787` | HTTP listen port |
| `--no-browser` | Do not auto-open a browser |
| `--data-dir PATH` | Override settings/registry location |
| `--headless` | Disable tkinter folder picker |

Data defaults to `%LOCALAPPDATA%\PCTransfer` on Windows, or `~/.local/share/pc-transfer` elsewhere. Override with `PC_TRANSFER_DATA`.

## Typical flow

1. Start the app on both PCs.
2. Open **Pair** — peers should appear within a few seconds (or add a manual IP).
3. On each PC, open **Games** → **Add game** and pick the install folder + save folder.
4. On **Transfer**, choose the game + peer → **Send game ZIP**, then **Sync saves**.
5. Open **Verify** to confirm paths exist and review size / last modified.

Save sync policy:

- **Newer wins** — compare mtime; keep the newer file
- **Always use incoming** — overwrite local saves
- **Prompt** — marks conflicts; non-interactive default keeps local

## Controller map (handheld)

| Input | Action |
|-------|--------|
| D-pad / Left stick | Move focus |
| **A** (South) | Confirm / activate |
| **B** (East) | Back / cancel form |
| **Y** (North) | Refresh peers or run verify |
| **X** (West) | Jump to Transfer |
| **LB / RB** | Previous / next tab |

Keyboard: arrows, Enter, Escape. Mouse still works on the main PC.

Use a browser that exposes the Gamepad API (Edge / Chrome). For a kiosk-like handheld setup, pin the Edge window fullscreen.

## Tests

```powershell
cd pc-transfer
pip install -e ".[dev]"
pytest -q
```

CI-friendly (no GUI picker):

```powershell
$env:PC_TRANSFER_HEADLESS = "1"
pytest -q
```

## Project layout

```
pc-transfer/
  src/pc_transfer/        # discovery, ZIP transfer, save sync, FastAPI app
    web/                  # controller-first UI (HTML/CSS/JS)
  tests/
  README.md
```

## Windows notes / verification checklist

These should be confirmed on real Windows hardware (main + handheld):

- [ ] UDP discovery across the LAN (firewall rules for 8788/udp and 8787/tcp)
- [ ] Large game ZIP transfer durability on Wi-Fi handhelds
- [ ] XInput controller focus in Edge/Chrome Gamepad API
- [ ] tkinter folder picker under Windows
- [ ] Paths with non-ASCII characters under `%USERPROFILE%\Documents\My Games\...`
