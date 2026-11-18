@echo off
REM ============================================================================
REM Zero-Hosting Power-Coupled Boot Script (Windows Company Workstation - Firewall Bypass Edition)
REM Domain : https://thietbibachkhoa.id.vn/
REM Port   : 8765 (bound to 127.0.0.1 loopback to avoid Windows Defender Firewall block)
REM ============================================================================

setlocal EnableExtensions
cd /d "%~dp0.."

REM Load optional company workstation environment overrides (.env.windows)
if exist "%cd%\config\.env.windows" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%cd%\config\.env.windows") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
    )
)

if "%UAV_WEB_PORT%"=="" set UAV_WEB_PORT=8765
if "%UAV_TPU_PROVIDER%"=="" set UAV_TPU_PROVIDER=kaggle_free_tpu
set UAV_CUSTOM_DOMAIN=thietbibachkhoa.id.vn
set TUNNEL_CONFIG=%cd%\config\cloudflared_thietbibachkhoa.yml
if exist "%cd%\config\cloudflared_thietbibachkhoa_windows.yml" (
    set TUNNEL_CONFIG=%cd%\config\cloudflared_thietbibachkhoa_windows.yml
)

echo [thietbibachkhoa.id.vn] Starting local UAV GeoTIFF WebGPU Server on 127.0.0.1:%UAV_WEB_PORT% (Loopback - No Windows Firewall Popup)...
if exist ".venv\Scripts\python.exe" (
    start "UAV_WebGPU_8765" /min ".venv\Scripts\python.exe" -m uav_app.adapters.webgpu_public_server --host 127.0.0.1 --port %UAV_WEB_PORT%
    ".venv\Scripts\python.exe" -m uav_app.infrastructure.firewall_bypass --heartbeat
) else (
    start "UAV_WebGPU_8765" /min python -m uav_app.adapters.webgpu_public_server --host 127.0.0.1 --port %UAV_WEB_PORT%
    python -m uav_app.infrastructure.firewall_bypass --heartbeat
)

timeout /t 2 /nobreak >nul

where cloudflared >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    if not "%CLOUDFLARE_TUNNEL_TOKEN%"=="" (
        echo [thietbibachkhoa.id.vn] Connecting Cloudflare Tunnel via HTTP/2 TCP IPv4 (Firewall Bypass) -> http://127.0.0.1:%UAV_WEB_PORT%...
        start "UAV_Cloudflare_Tunnel" /min cloudflared tunnel --no-autoupdate --protocol http2 --edge-ip-version 4 run --token "%CLOUDFLARE_TUNNEL_TOKEN%"
    ) else (
        echo [thietbibachkhoa.id.vn] Connecting Cloudflare Tunnel via Config "%TUNNEL_CONFIG%" (HTTP/2 TCP IPv4) -> http://127.0.0.1:%UAV_WEB_PORT%...
        start "UAV_Cloudflare_Tunnel" /min cloudflared tunnel --no-autoupdate --protocol http2 --edge-ip-version 4 --config "%TUNNEL_CONFIG%" run
    )
) else (
    echo [thietbibachkhoa.id.vn] cloudflared.exe not found; Outbound HTTPS 443 Cloud Bridge active.
)

endlocal
