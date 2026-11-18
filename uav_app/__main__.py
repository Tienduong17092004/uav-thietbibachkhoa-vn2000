import argparse
import os
from pathlib import Path
import subprocess
import threading
import time
import webbrowser

from uav_app.adapters.server import make_server


def _free_port_if_stale(port: int) -> None:
    if os.name != "nt" or port <= 0:
        return
    try:
        my_pid = os.getpid()
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
                pid = int(parts[4])
                if pid != my_pid and pid > 0:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                    )
                    time.sleep(0.25)
    except Exception:
        pass


def main():
    app_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="UAV GeoTIFF Studio — local phase 1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--project-root", type=Path, default=app_root.parent)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    _free_port_if_stale(args.port)
    server = None
    last_error = None
    candidate_ports = [args.port] + ([p for p in range(args.port + 1, args.port + 15)] + [0] if args.port > 0 else [])
    for candidate_port in candidate_ports:
        try:
            server = make_server(args.project_root, app_root, candidate_port)
            break
        except OSError as exc:
            last_error = exc
            continue
    if server is None:
        raise last_error
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"UAV GeoTIFF Studio: {url}", flush=True)
    print("Press Ctrl+C to stop the local application.", flush=True)
    if not args.no_browser:
        opener = threading.Timer(.5, webbrowser.open, args=(url,))
        opener.daemon = True
        opener.start()
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.service.close()
        server.server_close()


if __name__ == "__main__":
    main()
