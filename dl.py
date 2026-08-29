#!/usr/bin/env python3
"""
Magnet link downloader with live progress bar.
Uses aria2c's JSON-RPC — no extra dependencies beyond Python 3.

Usage:
    python3 dl.py
    python3 dl.py "magnet:?xt=..."
"""
import subprocess, sys, os, time, json, urllib.request

# ── Config ──────────────────────────────────────────────
DOWNLOAD_DIR = os.path.expanduser("~/downloads")  # ← change if needed
RPC_PORT     = 16800                              # internal port (not exposed)
# ────────────────────────────────────────────────────────

def show_inscription():
    """Fetch and display the WILLZY inscription from GitHub."""
    url = "https://raw.githubusercontent.com/justwillzy/willzy/main/inscription.txt"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            content = r.read().decode()
        print()
        print(content.replace("\\033", "\033"))
        time.sleep(2)
    except Exception:
        pass  # silently skip if unreachable

def rpc(method, params=None):
    """Hit aria2c's local JSON-RPC endpoint."""
    try:
        payload = json.dumps({
            "jsonrpc": "2.0", "id": "dl",
            "method": method, "params": params or []
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{RPC_PORT}/jsonrpc",
            data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read()).get("result")
    except Exception:
        return None


def fmt_size(b):
    b = float(b or 0)
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024 or u == "TB":
            return f"{b:.1f} {u}"
        b /= 1024


def fmt_eta(sec):
    sec = int(sec or 0)
    if sec <= 0:
        return "--"
    h, rem = divmod(sec, 3600)
    m, s   = divmod(rem, 60)
    if h:   return f"{h}h {m:02}m"
    if m:   return f"{m}m {s:02}s"
    return  f"{s}s"


def draw_bar(pct, width=35):
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def watch(proc):
    """Poll RPC every ~1.5 s and redraw a single progress line."""
    cols = 100
    if sys.stdout.isatty():
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            pass

    prev_len = 0
    spinner_frames = "|/-\\"
    frame = 0

    while True:
        # Exit if aria2c has quit and there's nothing active
        if proc.poll() is not None:
            break

        active = rpc("aria2.tellActive") or []

        if not active:
            # Check for just-completed downloads
            stopped = rpc("aria2.tellStopped", [0, 1]) or []
            if stopped:
                break
            # Still waiting / connecting
            sp = spinner_frames[frame % len(spinner_frames)]
            line = f"\r  {sp}  Waiting for peers / fetching torrent metadata..."
            frame += 1
        else:
            dl    = active[0]
            done  = int(dl.get("completedLength", 0))
            total = int(dl.get("totalLength",     0))
            speed = int(dl.get("downloadSpeed",   0))
            peers = dl.get("numSeeders", "?")
            name  = dl.get("bittorrent", {}).get("info", {}).get("name", "")

            if total == 0:
                # Metadata not yet received
                sp = spinner_frames[frame % len(spinner_frames)]
                line = f"\r  {sp}  Finding peers...  connected: {peers}"
                frame += 1
            else:
                pct = done / total * 100
                eta = (total - done) / speed if speed > 0 else 0

                bar  = draw_bar(pct)
                stat = (
                    f"  {bar}  {pct:5.1f}%"
                    f"  {fmt_size(done)} / {fmt_size(total)}"
                    f"  ↓ {fmt_size(speed)}/s"
                    f"  ETA {fmt_eta(eta)}"
                    f"  peers {peers}"
                )
                if name:
                    stat += f"  │ {name}"
                line = f"\r{stat}"

        # Truncate to terminal width, pad to erase leftover chars
        line = line[:cols]
        padding = " " * max(0, prev_len - len(line))
        print(line + padding, end="", flush=True)
        prev_len = len(line)

        time.sleep(1.5)

    print()  # newline after the progress line is done


def main():
    show_inscription()

    # ── Get magnet link ──
    if len(sys.argv) > 1:
        magnet = sys.argv[1].strip()
    else:
        print("Paste magnet link and press Enter:")
        magnet = input().strip()

    if not magnet.startswith("magnet:"):
        sys.exit("❌  Doesn't look like a magnet link.")

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print(f"\n📂  {DOWNLOAD_DIR}\n")

    # ── Launch aria2c with RPC enabled ──
    cmd = [
        "aria2c",
        "--dir",                         DOWNLOAD_DIR,
        "--seed-time=0",                 # don't seed after finish
        "--max-connection-per-server=4",
        "--split=4",
        "--bt-enable-lpd=true",
        "--enable-dht=true",
        "--enable-rpc=true",
        f"--rpc-listen-port={RPC_PORT}",
        "--quiet=true",                  # suppress aria2c's own output (we draw ours)
        magnet,
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        sys.exit("❌  aria2c not found. Install it: sudo apt install aria2")

    print("⬇️   Downloading...  Ctrl+C to cancel\n")

    try:
        time.sleep(1.5)      # give aria2c a moment to spin up its RPC server
        watch(proc)
        proc.wait()

        if proc.returncode == 0:
            print(f"✅  Done!  Files saved to: {DOWNLOAD_DIR}")
        else:
            print(f"⚠️   aria2c exited with code {proc.returncode}")

    except KeyboardInterrupt:
        print("\n\n⛔  Cancelled.")
        proc.terminate()


if __name__ == "__main__":
    main()
