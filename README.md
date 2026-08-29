# Magnet Link Downloader

![Python](https://img.shields.io/badge/python-3.6%2B-blue?style=flat-square)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey?style=flat-square)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)

A minimal command-line tool to download any magnet link with a **live, in-place progress bar**. <br>
Paste a **MAGNET link**, watch it as it downloads and get your files.<br> <br>
Built as a thin wrapper around `aria2c` so no third-party Python packages needed.

---

## What it looks like ?

**Phase 1: finding peers (normal for the first minute or two)**
```
  /  Finding peers...  connected: 3
```

**Phase 2: downloading**
```
  ████████████░░░░░░░░░░░░░░░░░░░░░░░   35.2%  4.2 GB / 12.0 GB  ↓ 8.5 MB/s  ETA 15m 32s  peers 12  │ Sofia.The.First.S03
```

**Done:**
```
✅  Done!  Files saved to: /root/downloads
```

The progress line rewrites itself in place — no scrolling wall of text.

---


## Features

- Live progress bar with percentage, speed, ETA, and peer count
- Spinner during the peer-discovery phase so you know it's alive
- Preserves full folder structure for multi-file torrents
- Resumes interrupted downloads automatically (aria2c resume files)
- Zero Python dependencies; standard library only
- Works over SSH, including inside tmux

---

## Prerequisites

You need **Python 3.6+** (already on most systems) and **aria2c**:

```bash
# Check if you have both
python3 --version
aria2c --version
```

If `aria2c` is missing:

```bash
sudo apt install aria2        # Ubuntu / Debian
sudo yum install aria2        # CentOS / RHEL / Fedora
brew install aria2            # macOS
```

---

## Installation

No installation step, just grab the file:

```bash
curl -O https://raw.githubusercontent.com/justwillzy/magnet-link-downloader-script/main/dl.py
```

Or clone the repo **(recommended)**:

```bash
git clone https://github.com/justwillzy/magnet-link-downloader-script.git
cd magnet-link-downloader-script
```

Optionally make it executable so you don't need to type `python3` every time:

```bash
chmod +x dl.py
```

---

## Usage

### Interactive: paste the link when prompted

```bash
python3 dl.py
```

```
Paste magnet link and press Enter:
▌
```

Paste your magnet link, hit Enter. Done.

---

### Direct: pass the link as an argument

```bash
python3 dl.py "magnet:?xt=urn:btih:..."
```

> **Always wrap the link in quotes.** Magnet links contain `&` characters that the shell will misread without them.

---

### Running on a remote server (VPS / SSH) ?

Use **tmux** so the download keeps going after you close your terminal:

```bash
# Start a named session
tmux new -s dl

# Run the downloader inside it
python3 dl.py

# Detach — leave download running, close your terminal safely
Ctrl+B  then  D

# Come back later and reattach
tmux attach -t dl

# Kill the session when you're done
tmux kill-session -t dl
```

---

## Configuration

Open `dl.py` and edit the two lines at the top:

```python
DOWNLOAD_DIR = os.path.expanduser("~/downloads")  # where files land
RPC_PORT     = 16800                              # internal port (not exposed publicly)
```

Change `~/downloads` to any path you want, e.g. `/mnt/external/media`.

---

## How it works

`dl.py` launches `aria2c` as a background process with its JSON-RPC interface enabled, then polls that interface every 1.5 seconds to pull live stats (speed, progress, peer count, torrent name) and redraws a single terminal line. This keeps aria2c's own output completely hidden while giving you clean, readable progress.

```
dl.py  ──launch──►  aria2c (background)
                        │  JSON-RPC  (localhost:16800)
dl.py  ◄──poll every 1.5s──┘
dl.py  ──redraw──►  terminal progress line
```

When the download completes, aria2c exits cleanly and `dl.py` prints the final path.

---

## Troubleshooting

**Speed is 0 for the first few minutes**
This is normal. aria2c is discovering peers via DHT and the tracker list in the magnet link. Give it 2–3 minutes. If it never moves after 10 min, the torrent has very few active seeders.

**Download was interrupted — will it restart from scratch?**
No. aria2c writes `.aria2` resume files next to each partial file. Run the same command again and it picks up exactly where it stopped.

**`aria2c` exits immediately with a non-zero code**
Run aria2c directly to see its own error output:
```bash
aria2c --dir ~/downloads --seed-time=0 "magnet:?xt=..."
```

**Permission denied on the download directory**
```bash
chmod 755 ~/downloads
```

**Port 16800 already in use**
Change `RPC_PORT` in `dl.py` to any unused port, e.g. `16801`.

---

## License

MIT — do whatever you want with it.
