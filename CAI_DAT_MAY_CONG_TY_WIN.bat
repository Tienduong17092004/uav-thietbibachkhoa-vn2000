@echo off
REM ============================================================================
REM 1-CLICK CAI DAT TREN MAY CONG TY (WINDOWS)
REM - Tu dong cai dat WebGPU Server cong 8765 + Cloudflare Tunnel thietbibachkhoa.id.vn
REM - Tu dong bat khi mo may tinh cong ty, tu dong tat khi tat may
REM - Ket noi san Kaggle Free TPU (Cach 2 - Mien phi 30h/tuan) & 30TB Google Drive
REM ============================================================================

cd /d "%~dp0"
echo Dang khoi chay trinh cai dat Windows cho https://thietbibachkhoa.id.vn/ ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0scripts\setup_company_windows.ps1\"'"
