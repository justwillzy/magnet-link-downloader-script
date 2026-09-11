    #!/usr/bin/env python3
"""
Magnet link downloader with live progress bar.
Uses aria2c's JSON-RPC and no extra dependencies beyond Python 3.

how to use:
    python3 dl.py
    python3 dl.py "magnet:?xt=..."
"""
import subprocess, sys, os, time, json, urllib.request, re, select
from urllib.parse import parse_qs, urlparse


DOWNLOAD_DIR = os.path.expanduser("~/downloads")  
RPC_PORT     = 16800                            


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
    try:
        params = parse_qs(urlparse(magnet).query)
        xt = params.get("xt", [""])[0]
        info_hash = xt.split(":")[-1].upper() if "btih:" in xt else None
        name = params.get("dn", [None])[0]
        return info_hash, name
    except Exception:
        return None, None


def bdecode(data):
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
    raw = raw.strip()
    if re.fullmatch(r"[0-9a-fA-F]{40}", raw):        
        return f"magnet:?xt=urn:btih:{raw}", raw.upper()
    if re.fullmatch(r"[A-Z2-7]{32}", raw, re.IGNORECASE): 
        return f"magnet:?xt=urn:btih:{raw}", raw.upper()
    return None, None


def validate_input(raw):
    raw = raw.strip()

    if not raw.startswith("magnet:"):
        built, info_hash = build_from_hash(raw)
        if built:
            print(f"\n🔑  {info_hash}")
            print("🔍  Looking up name...", end="", flush=True)
            name = lookup_name(info_hash)
            if name:
                print(f"\r📄  {name}                    ")
            else:
                print(f"\r📄  (name not found, trackers will fill it in)")
            return built, info_hash, name
        else:
            print("❌  Doesn't look like a magnet link or an info hash, paste it again:\n")
            return None

    info_hash, name = parse_magnet(raw)
    if not info_hash:
        print("❌  Looks like a magnet link but something's off, try re-copying it from the source:\n")
        return None

    print(f"\n🔑  {info_hash}")
    if name:
        print(f"📄  {name}")
    return raw, info_hash, name


def rpc(method, params=None):
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


def watch(proc, on_prompt=False):
    cols = 100
    if sys.stdout.isatty():
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            pass

    prev_len     = 0
    spinner_frames = "|/-\\"
    frame        = 0
    hint_shown   = False 
    queued       = []

    while True:
        # Exit if aria2c has quit
        if proc.poll() is not None:
            break

        active = rpc("aria2.tellActive") or []

        if not active:
            stopped = rpc("aria2.tellStopped", [0, 1]) or []
            if stopped:
                break
            sp   = spinner_frames[frame % len(spinner_frames)]
            line = f"  {sp}  Waiting for peers / fetching torrent metadata..."
            frame += 1

        else:
            dl    = active[0]
            done  = int(dl.get("completedLength", 0))
            total = int(dl.get("totalLength",     0))
            speed = int(dl.get("downloadSpeed",   0))
            peers = dl.get("numSeeders", "?")
            name  = dl.get("bittorrent", {}).get("info", {}).get("name", "")

            if total == 0:
                sp   = spinner_frames[frame % len(spinner_frames)]
                line = f"  {sp}  Finding peers...  connected: {peers}"
                frame += 1

            else:
                pct = done / total * 100

            
                if done >= total:
                    bar       = "█" * 35
                    done_line = f"  {bar}  100.0%  {fmt_size(total)} / {fmt_size(total)}  ✓"
                    print(f"\r{done_line}" + " " * max(0, prev_len - len(done_line)))
                    return queued
            

         
                if on_prompt and not hint_shown:
                    print()   # end the spinner/waiting line cleanly
                    print("💡  Queue another: just type/paste a link + enter")
                    hint_shown = True

                eta  = (total - done) / speed if speed > 0 else 0
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
                line = stat

        line = line[:cols]

   
        pad = " " * max(0, prev_len - len(line))
        sys.stdout.write(f"\r{line + pad}")
        sys.stdout.flush()
        prev_len = len(line)

       
        if on_prompt and hint_shown:
            ready, _, _ = select.select([sys.stdin], [], [], 1.5)
            if ready:
                raw = sys.stdin.readline().strip()
                if raw:
                    result = validate_input(raw)
                    if result:
                        queued.append(result)
                        _, ih, nm = result
                        print(f"\n✓  Queued: {nm or ih}  [{len(queued)} waiting]")
        else:
            time.sleep(1.5)

    print()
    return queued


def main():
    show_inscription()
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    first = True

    while True:

       
        if first and len(sys.argv) > 1:
            raw   = sys.argv[1].strip()
            first = False
        else:
            first = False
            print("\nPaste a magnet link or info hash:")
            raw = input().strip()
            if not raw:
                continue

        result = validate_input(raw)
        if not result:
            continue

        queue = [result]

        while queue:
            magnet, info_hash, name = queue.pop(0)

            print(f"\n📂  {DOWNLOAD_DIR}\n")

           
            cmd = [
                "aria2c",
                "--dir",                         DOWNLOAD_DIR,
                "--continue=true",           
                "--seed-time=0",                
                "--max-connection-per-server=4",
                "--split=4",
                "--bt-enable-lpd=true",
                "--enable-dht=true",
                "--enable-rpc=true",
                f"--rpc-listen-port={RPC_PORT}",
                "--quiet=true",              
                magnet,
            ]

            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                sys.exit("❌  aria2c not found. Install it: sudo apt install aria2")

            print("⬇️   Downloading...  Ctrl+C to cancel\n")

            try:
                time.sleep(1.5)      # give aria2c a moment to spin up its RPC server
                new_items = watch(proc, on_prompt=True)
                proc.wait()

                if proc.returncode == 0:
                    print(f"✅  Done!  Files saved to: {DOWNLOAD_DIR}")
                else:
                    print(f"⚠️   aria2c exited with code {proc.returncode}")

                queue.extend(new_items)

                if queue:
                    next_name = queue[0][2] or queue[0][1]
                    print(f"\n⏭️   Next: {next_name}\n")
                    time.sleep(1)

            except KeyboardInterrupt:
                print("\n\n⛔  Cancelled.")
                proc.terminate()
                queue.clear()
                break

      
        print("\nAll done! Add another download? Press Enter to add  /  any key to exit:")
        if input().strip():
            break


if __name__ == "__main__":
    main()
