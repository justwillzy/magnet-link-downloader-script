#!/usr/bin/env python3
"""
Magnet link downloader with live progress bar.
Uses aria2c's JSON-RPC, no extra dependencies beyond Python 3.

Usage:
    python3 dl.py
    python3 dl.py "magnet:?xt=..."
"""
import subprocess, sys, os, time, json, urllib.request, re
from urllib.parse import parse_qs, urlparse

# ── Config ──────────────────────────────────────────────
DOWNLOAD_DIR = os.path.expanduser("~/downloads")  # ← change if needed
RPC_PORT     = 16800                              # internal port (not exposed)
# ────────────────────────────────────────────────────────

def show_inscription():
    url = "https://raw.githubusercontent.com/justwillzy/willzy/main/inscription.txt"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            content = r.read().decode()
        print()
        print(content.replace("\\033", "\033"))
        time.sleep(2)
    except Exception:
        pass  

def parse_magnet(magnet):
    """Pull the info hash and display name out of a magnet link."""
    try:
        params = parse_qs(urlparse(magnet).query)
        xt = params.get("xt", [""])[0]
        info_hash = xt.split(":")[-1].upper() if "btih:" in xt else None
        name = params.get("dn", [None])[0]
        return info_hash, name
    except Exception:
        return None, None


def bdecode(data):
    """Minimal bencode decoder — just enough to read a .torrent name."""
    def decode(pos):
        c = data[pos:pos+1]
        if c == b'd':
            pos += 1; d = {}
            while data[pos:pos+1] != b'e':
                k, pos = decode(pos)
                v, pos = decode(pos)
                d[k] = v
            return d, pos + 1
        elif c == b'l':
            pos += 1; lst = []
            while data[pos:pos+1] != b'e':
                v, pos = decode(pos); lst.append(v)
            return lst, pos + 1
        elif c == b'i':
            end = data.index(b'e', pos)
            return int(data[pos+1:end]), end + 1
        else:
            sep = data.index(b':', pos)
            n = int(data[pos:sep]); s = sep + 1
            return data[s:s+n], s + n
    return decode(0)[0]


def lookup_name(info_hash):
    """Try to fetch the torrent name from a public lookup service."""
    for url in [
        f"https://itorrents.org/torrent/{info_hash}.torrent",
        f"https://thetorrent.org/{info_hash}.torrent",
    ]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as r:
                torrent = bdecode(r.read())
            name = torrent.get(b"info", {}).get(b"name", None)
            if name:
                return name.decode("utf-8", errors="replace")
        except Exception:
            continue
    return None


def build_from_hash(raw):
    """If the user pasted a bare info hash, construct a minimal magnet link from it."""
    raw = raw.strip()
    if re.fullmatch(r"[0-9a-fA-F]{40}", raw):          # 40-char hex
        return f"magnet:?xt=urn:btih:{raw}", raw.upper()
    if re.fullmatch(r"[A-Z2-7]{32}", raw, re.IGNORECASE):  # 32-char base32
        return f"magnet:?xt=urn:btih:{raw}", raw.upper()
    return None, None


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

    # ── Get magnet link or bare info hash ──
    magnet = sys.argv[1].strip() if len(sys.argv) > 1 else None

    while True:
        if magnet is None:
            print("Paste a magnet link or info hash and press Enter:")
            magnet = input().strip()

        # Bare info hash (40-char hex or 32-char base32)
        if not magnet.startswith("magnet:"):
            built, info_hash = build_from_hash(magnet)
            if built:
                magnet = built
                print(f"\n🔑  {info_hash}")
                print("🔍  Looking up name...", end="", flush=True)
                name = lookup_name(info_hash)
                if name:
                    print(f"\r📄  {name}                    ")
                else:
                    print(f"\r📄  (name not found — trackers will fill it in)")
                break
            else:
                print("❌  Doesn't look like a magnet link or an info hash, please paste it again:\n")
                magnet = None
                continue

        # Full magnet link
        info_hash, name = parse_magnet(magnet)
        if not info_hash:
            print("❌  Looks like a magnet link but something's off, try re-copying it from the source:\n")
            magnet = None
            continue

        print(f"\n🔑  {info_hash}")
        if name:
            print(f"📄  {name}")
        break

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
