@echo off
REM ============================================================================
REM 1-CLICK CAI DAT VUOT TUONG LUA CONG TY (WINDOWS - KHONG CAN QUYEN ADMIN)
REM - Chay Web Server tren Localhost Loopback (127.0.0.1:8765) -> Khong bi Windows Defender Firewall hoi/chan
REM - Ep Cloudflare Tunnel chay giao thuc HTTP/2 TCP (--protocol http2 --edge-ip-version 4) -> Vuot chan UDP 7844
REM - Tu dong doc Proxy cong ty tu Windows Registry (neu co)
REM - Dong thoi kich hoat Outbound HTTPS 443 Cloud Bridge (firewall_bypass.py) dong bo Google Drive 1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN
REM ============================================================================

cd /d "%~dp0"
echo [1/3] Kiem tra & kich hoat 3 Lop Vuot Tuong Lua cho https://thietbibachkhoa.id.vn/ ...
python -m uav_app.infrastructure.firewall_bypass --probe
python -m uav_app.infrastructure.firewall_bypass --heartbeat

echo [2/3] Dang ky tu khoi dong User-Space (khong can quyen Admin IT cong ty)...
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if exist "%STARTUP_DIR%" (
    echo @echo off > "%STARTUP_DIR%\UAV_ThietBiBachKhoa_Autostart.cmd"
    echo cd /d "%~dp0" >> "%STARTUP_DIR%\UAV_ThietBiBachKhoa_Autostart.cmd"
    echo call "%~dp0scripts\start_thietbibachkhoa_windows.bat" >> "%STARTUP_DIR%\UAV_ThietBiBachKhoa_Autostart.cmd"
    echo [OK] Da luu tu khoi dong tai: "%STARTUP_DIR%\UAV_ThietBiBachKhoa_Autostart.cmd"
)

echo [3/3] Khoi chay Web Server (127.0.0.1:8765) + HTTP/2 Tunnel + Outbound HTTPS 443 Bridge...
call "%~dp0scripts\start_thietbibachkhoa_windows.bat"
echo HOAN TAT! Neu tuong lua cong ty chan hoan toan cloudflared.exe, hay dung file deploy\cloudflare_worker_thietbibachkhoa.js hoac Cloud Server (VPS) theo HUONG_DAN_VUOT_TUONG_LUA_THIETBIBACHKHOA.md.
pause
