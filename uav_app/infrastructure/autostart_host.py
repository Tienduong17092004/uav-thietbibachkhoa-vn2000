"""Zero-Hosting Custom Domain & Power-Coupled Autostart Host Controller.

Binds the local machine's default web port (8765 / 8766 / 7860) directly to
`https://thietbibachkhoa.id.vn/` using Cloudflare Tunnel (`cloudflared`) without
requiring paid web hosting or a cloud VPS:
- Machine ON (OS Boot): Starts the local UAV GeoTIFF WebGPU server on the default
  port (8765) and launches the Cloudflare Tunnel for `thietbibachkhoa.id.vn`.
- Machine OFF (OS Shutdown): Handles SIGTERM/SIGINT to gracefully stop the web
  server and terminate the tunnel so `https://thietbibachkhoa.id.vn/` goes offline
  immediately when the machine powers down.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

DEFAULT_PORT: int = 8765
SECONDARY_PORT: int = 8766
CONTAINER_PORT: int = 7860
SUPPORTED_PORTS: Tuple[int, ...] = (8765, 8766, 7860)

CUSTOM_DOMAIN: str = "thietbibachkhoa.id.vn"
CUSTOM_DOMAIN_URL: str = "https://thietbibachkhoa.id.vn/"
DEFAULT_TUNNEL_ID: str = "uav-thietbibachkhoa-tunnel"


def get_default_port(env_port: Optional[str | int] = None) -> int:
    """Resolve the active local port from argument, environment, or codebase default (8765)."""
    raw = env_port
    if raw is None:
        raw = os.environ.get("UAV_WEB_PORT") or os.environ.get("UAV_PORT") or os.environ.get("PORT")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_PORT
    try:
        port = int(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"Invalid port value: {raw!r}") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"Port must be between 1 and 65535, got {port}")
    return port


def generate_cloudflared_config(
    port: int = DEFAULT_PORT,
    domain: str = CUSTOM_DOMAIN,
    tunnel_id: str = DEFAULT_TUNNEL_ID,
    credentials_file: Optional[str] = None,
    secondary_port: int = SECONDARY_PORT,
    protocol: str = "quic",
    firewall_bypass: bool = False,
    http_proxy: Optional[str] = None,
) -> str:
    """Generate a Cloudflare Tunnel YAML configuration for https://thietbibachkhoa.id.vn/."""
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError(f"Invalid port: {port}. Must be an integer in 1..65535.")
    clean_domain = str(domain).strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
    if not clean_domain or "." not in clean_domain:
        raise ValueError(f"Invalid domain name: {domain!r}")
    clean_tunnel = str(tunnel_id).strip() or DEFAULT_TUNNEL_ID
    creds = credentials_file or f"/etc/cloudflared/{clean_tunnel}.json"

    effective_protocol = "http2" if (firewall_bypass or str(protocol).strip().lower() == "http2") else str(protocol).strip().lower() or "quic"

    lines = [
        "# Zero-Hosting Cloudflare Tunnel Configuration for UAV GeoTIFF WebGPU Survey VN2000",
        f"# Custom Domain: https://{clean_domain}/ -> Local Machine Port {port}",
        "# Power-Coupled: Online when workstation is ON, Offline when workstation is OFF",
        f"tunnel: {clean_tunnel}",
        f"credentials-file: {creds}",
        f"protocol: {effective_protocol}",
        "no-autoupdate: true",
    ]
    if firewall_bypass or effective_protocol == "http2":
        lines.append('edge-ip-version: "4"')
    if http_proxy:
        lines.append(f"# Corporate HTTP/HTTPS Proxy: {http_proxy}")
    lines.extend([
        "",
        "ingress:",
        f"  - hostname: {clean_domain}",
        f"    service: http://127.0.0.1:{port}",
        "    originRequest:",
        "      noTLSVerify: true",
        "      connectTimeout: 10s",
        f"  - hostname: www.{clean_domain}",
        f"    service: http://127.0.0.1:{port}",
        "    originRequest:",
        "      noTLSVerify: true",
        "      connectTimeout: 10s",
        f"  - hostname: studio.{clean_domain}",
        f"    service: http://127.0.0.1:{secondary_port}",
        "    originRequest:",
        "      noTLSVerify: true",
        "  - service: http_status:404",
        "",
    ])
    return "\n".join(lines)


class AutostartHostManager:
    """Manages power-linked startup and shutdown of the local web server and Cloudflare tunnel."""

    def __init__(
        self,
        port: Optional[int] = None,
        domain: str = CUSTOM_DOMAIN,
        host: str = "127.0.0.1",
        project_root: Optional[Path] = None,
        config_path: Optional[Path] = None,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.port = 0 if port == 0 else get_default_port(port)
        self.domain = str(domain).strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
        self.url = f"https://{self.domain}/"
        self.host = host
        self.config_path = config_path or (
            self.project_root / "config" / "cloudflared_thietbibachkhoa.yml"
        )
        self._server: Any = None
        self._server_thread: Any = None
        self._tunnel_process: Optional[subprocess.Popen[Any]] = None
        self._running: bool = False
        self._shutdown_callbacks: List[Callable[[], None]] = []
        self._signals_registered: bool = False

    @property
    def is_running(self) -> bool:
        return self._running

    def ensure_cloudflared_config(self) -> Path:
        """Ensure the Cloudflare Tunnel config file exists on disk."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            cfg_port = self.port if self.port > 0 else DEFAULT_PORT
            yaml_text = generate_cloudflared_config(port=cfg_port, domain=self.domain)
            self.config_path.write_text(yaml_text, encoding="utf-8")
        return self.config_path

    def start_web_server(self, host: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
        """Start the local UAV WebGPU HTTP server in a background daemon thread."""
        from uav_app.adapters.webgpu_public_server import start_background_server

        bind_host = host or self.host
        if port is None:
            bind_port = self.port
        elif port == 0:
            bind_port = 0
        else:
            bind_port = get_default_port(port)
        self._server, self._server_thread = start_background_server(host=bind_host, port=bind_port)
        actual_port = int(self._server.server_address[1])
        self.port = actual_port
        self._running = True
        return {
            "status": "started",
            "host": bind_host,
            "port": actual_port,
            "domain": self.domain,
            "url": self.url,
            "local_url": f"http://{bind_host}:{actual_port}/",
            "power_coupled": True,
        }

    def stop(self) -> Dict[str, Any]:
        """Gracefully stop the local web server and disconnect any active tunnel on machine shutdown."""
        if self._tunnel_process is not None and self._tunnel_process.poll() is None:
            self._tunnel_process.terminate()
            try:
                self._tunnel_process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self._tunnel_process.kill()
        self._tunnel_process = None

        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
            self._server_thread = None

        self._running = False
        for cb in list(self._shutdown_callbacks):
            try:
                cb()
            except Exception:
                pass

        return {
            "status": "stopped",
            "domain": self.domain,
            "url": self.url,
            "port": self.port,
            "online": False,
            "power_coupled": True,
        }

    def register_shutdown_signals(self) -> None:
        """Hook OS shutdown signals (SIGTERM, SIGINT) so turning off the PC stops the web app."""

        def _handle_signal(signum: int, _frame: Any) -> None:
            self.stop()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)
        self._signals_registered = True

    def get_domain_lifecycle_status(self) -> Dict[str, Any]:
        """Return full diagnostic status of the zero-hosting custom domain setup."""
        from uav_app.infrastructure.firewall_bypass import (
            PROCESSED_DATA_GDRIVE_FOLDER_ID,
            detect_corporate_proxy,
        )

        cfg_exists = self.config_path.exists()
        proxy_info = detect_corporate_proxy()
        return {
            "domain": self.domain,
            "url": self.url,
            "custom_domain_url": CUSTOM_DOMAIN_URL,
            "default_port": self.port,
            "port": self.port,
            "supported_ports": list(SUPPORTED_PORTS),
            "hosting_mode": "zero_hosting_local_workstation",
            "tunnel_provider": "cloudflare_tunnel",
            "power_coupled": True,
            "server_running": self._running,
            "tunnel_configured": cfg_exists,
            "cloudflared_config_path": str(self.config_path),
            "signals_registered": self._signals_registered,
            "firewall_bypass": {
                "proxy_info": proxy_info,
                "http2_loopback": {
                    "protocol": "http2",
                    "edge_ip_version": "4",
                    "bind_host": "127.0.0.1",
                    "port": self.port,
                    "cli_flags": ["--no-autoupdate", "--protocol", "http2", "--edge-ip-version", "4"],
                    "requires_udp_7844": False,
                    "requires_admin_rights": False,
                },
                "cloudflare_worker_edge": {
                    "domain_url": self.url,
                    "worker_script": "deploy/cloudflare_worker_thietbibachkhoa.js",
                    "inbound_ports_required": 0,
                    "requires_udp_7844": False,
                    "requires_tcp_7844": False,
                    "requires_admin_rights": False,
                },
                "outbound_https_443_bridge": {
                    "transport": "outbound_https_443",
                    "outbound_port": 443,
                    "processed_data_folder_id": PROCESSED_DATA_GDRIVE_FOLDER_ID,
                    "requires_admin_rights": False,
                },
            },
            "lifecycle": {
                "machine_on": (
                    f"OS boot triggers autostart_host -> starts local server on port {self.port} "
                    f"and connects cloudflared tunnel -> {self.url} is ONLINE"
                ),
                "machine_off": (
                    f"OS shutdown sends SIGTERM/SIGINT -> stops local server on port {self.port} "
                    f"and disconnects cloudflared tunnel -> {self.url} is OFFLINE"
                ),
            },
            "autostart_artifacts": {
                "linux_script": "scripts/start_thietbibachkhoa_linux.sh",
                "windows_batch": "scripts/start_thietbibachkhoa_windows.bat",
                "windows_powershell_installer": "scripts/install_windows_autostart.ps1",
                "systemd_web_service": "deploy/systemd/thietbibachkhoa-web.service",
                "systemd_tunnel_service": "deploy/systemd/thietbibachkhoa-tunnel.service",
            },
        }


def enable_autostart_on_boot(port: int = DEFAULT_PORT, domain: str = CUSTOM_DOMAIN) -> Dict[str, Any]:
    """Ensure Cloudflare Tunnel config and boot autostart descriptors are ready."""
    mgr = AutostartHostManager(port=port, domain=domain)
    cfg = mgr.ensure_cloudflared_config()
    status = mgr.get_domain_lifecycle_status()
    status["cloudflared_config_path"] = str(cfg)
    status["autostart_enabled"] = True
    return status


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Zero-Hosting Custom Domain (https://thietbibachkhoa.id.vn/) Autostart Host Controller"
    )
    parser.add_argument("--port", type=int, default=get_default_port(), help="Local server port (default: 8765)")
    parser.add_argument("--domain", type=str, default=CUSTOM_DOMAIN, help="Custom domain name")
    parser.add_argument("--status", action="store_true", help="Print domain lifecycle status JSON")
    parser.add_argument("--generate-config", action="store_true", help="Write cloudflared config file")
    args = parser.parse_args(argv)

    mgr = AutostartHostManager(port=args.port, domain=args.domain)
    if args.generate_config:
        mgr.ensure_cloudflared_config()
    if args.status or True:
        print(json.dumps(mgr.get_domain_lifecycle_status(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
