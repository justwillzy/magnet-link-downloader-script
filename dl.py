#!/usr/bin/env python3
"""
Concurrent magnet downloader, one aria2c process, RPC-driven,
multiple torrents in parallel.

usage:
    python3 dl.py
"""
import subprocess, sys, os, time, json, urllib.request, re, select

DOWNLOAD_DIR   = os.path.expanduser("~/downloads")
RPC_PORT       = 16800
MAX_CONCURRENT = 10


def parse_magnet(magnet):
    from urllib.parse import unquote_plus
    m = re.search(r"btih:([A-Za-z0-9]+)", magnet, re.IGNORECASE)
    info_hash = m.group(1).upper() if m else None
    n = re.search(r"[?&]dn=([^&]+)", magnet)
    name = unquote_plus(n.group(1)) if n else None
    return info_hash, name


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
    if re.fullmatch(r"[0-9a-fA-F]{40}", raw):
        return f"magnet:?xt=urn:btih:{raw}", raw.upper()
    if re.fullmatch(r"[A-Z2-7]{32}", raw, re.IGNORECASE):
        return f"magnet:?xt=urn:btih:{raw}", raw.upper()
    return None, None


def extract_magnet(raw):
    raw = raw.strip()
    idx = raw.find("magnet:?xt=")
    if idx != -1:
        return raw[idx:]
    if raw.startswith("?xt=urn:btih:") or raw.lower().startswith("xt=urn:btih:"):
        return "magnet:" + (raw if raw.startswith("?") else "?" + raw)
    return raw


def validate_input(raw):
    raw = extract_magnet(raw)
    if not raw:
        return None

    if not raw.startswith("magnet:"):
        built, info_hash = build_from_hash(raw)
        if not built:
            print("not a valid link or hash, try again")
            return None
        name = lookup_name(info_hash)
        return built, info_hash, name or "(unnamed)"

    info_hash, name = parse_magnet(raw)
    if not info_hash:
        print("bad magnet link, re-copy it")
        return None
    return raw, info_hash, name or "(unnamed)"


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


def add_magnet(magnet):
    return rpc("aria2.addUri", [[magnet], {"dir": DOWNLOAD_DIR}])


def fmt_size(b):
    b = float(b or 0)
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024 or u == "TB":
            return f"{b:.1f}{u}"
        b /= 1024


def fmt_eta(sec):
    sec = int(sec or 0)
    if sec <= 0:
        return "--"
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h: return f"{h}h{m:02}m"
    if m: return f"{m}m{s:02}s"
    return f"{s}s"


def draw_bar(pct, width=24):
    filled = int(width * pct / 100)
    return "#" * filled + "-" * (width - filled)


def short_name(name, n=34):
    return name if len(name) <= n else name[:n-3] + "..."


def render_line(dl, cols):
    done  = int(dl.get("completedLength", 0))
    total = int(dl.get("totalLength", 0))
    speed = int(dl.get("downloadSpeed", 0))
    name  = dl.get("bittorrent", {}).get("info", {}).get("name", "") or dl.get("gid", "")[:8]
    name  = short_name(name)

    if total == 0:
        line = f"[connecting] {name}"
    else:
        pct = done / total * 100
        eta = (total - done) / speed if speed > 0 else 0
        bar = draw_bar(pct)
        line = f"[{bar}] {pct:5.1f}% {fmt_size(done)}/{fmt_size(total)} {fmt_size(speed)}/s eta {fmt_eta(eta)} {name}"
    return line[:cols]


def start_aria2c():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    cmd = [
        "aria2c",
        "--dir", DOWNLOAD_DIR,
        "--continue=true",
        "--seed-time=0",
        "--max-connection-per-server=4",
        "--split=4",
        "--bt-enable-lpd=true",
        "--enable-dht=true",
        "--enable-rpc=true",
        f"--rpc-listen-port={RPC_PORT}",
        f"--max-concurrent-downloads={MAX_CONCURRENT}",
        "--quiet=true",
    ]
    try:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        sys.exit("aria2c not found, install: sudo apt install aria2")


def move_up(n):
    if n > 0:
        sys.stdout.write(f"\033[{n}A")


def clear_down():
    sys.stdout.write("\033[J")


def get_cols():
    if sys.stdout.isatty():
        try:
            return os.get_terminal_size().columns
        except OSError:
            pass
    return 100


def print_added(name):
    print()
    print(f"name: {name}")
    print()
    print(f"dir: {DOWNLOAD_DIR}")
    print()


def main():
    print("paste a magnet link or info hash:")
    raw = input().strip()
    result = validate_input(raw)
    while not result:
        raw = input().strip()
        result = validate_input(raw)

    proc = start_aria2c()
    time.sleep(1.5)

    magnet, info_hash, name = result
    print_added(name)
    add_magnet(magnet)

    added_count = 1
    cols = get_cols()
    prev_line_count = 0
    seen_done = set()

    try:
        while True:
            active  = rpc("aria2.tellActive") or []
            waiting = rpc("aria2.tellWaiting", [0, 50]) or []
            stopped = rpc("aria2.tellStopped", [0, 50]) or []

           
            for dl in stopped:
                gid = dl.get("gid")
                if gid not in seen_done and dl.get("status") == "complete":
                    seen_done.add(gid)
                    nm = dl.get("bittorrent", {}).get("info", {}).get("name", gid)
                    move_up(prev_line_count)
                    clear_down()
                    print(f"done: {short_name(nm)}")
                    print()
                    prev_line_count = 0

      
            lines = []
            if added_count > 1:
                lines.append("DOWNLOADS:")
                lines.append("")
            for dl in active:
                lines.append(render_line(dl, cols))
                lines.append("")
            for dl in waiting:
                nm = dl.get("bittorrent", {}).get("info", {}).get("name", dl.get("gid", "")[:8])
                lines.append(f"[queued] {short_name(nm)}")
                lines.append("")
            if not active and not waiting:
                lines.append("all downloads finished")
                lines.append("")
            lines.append("press enter to start more downloads, ctrl+c to stop")

            move_up(prev_line_count)
            clear_down()
            for l in lines:
                print(l)
            prev_line_count = len(lines)

            ready, _, _ = select.select([sys.stdin], [], [], 1.5)
            if not ready:
                continue

            line = sys.stdin.readline().strip()
            if line != "":
                continue 

            move_up(prev_line_count)
            clear_down()
            print()
            print("something went wrong, ensure you paste the correct/valid magnet link:")

            new_result = None
            while not new_result:
                new_raw = input().strip()
                if new_raw == "":
                    break
                new_result = validate_input(new_raw)

            if new_result:
                magnet, info_hash, name = new_result
                print_added(name)
                add_magnet(magnet)
                added_count += 1

            prev_line_count = 0

    except KeyboardInterrupt:
        print("\nstopped, partial files kept, resume anytime")
    finally:
        rpc("aria2.shutdown")
        time.sleep(0.5)
        proc.terminate()


if __name__ == "__main__":
    main()
