@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================================
echo   UAV GEOTIFF STUDIO ^& WEBGPU SURVEY PORTAL - DONG BO LEN GITHUB
echo ============================================================================
echo.

where git >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong tim thay Git tren may tinh. Vui long cai dat Git for Windows!
    pause
    exit /b 1
)

if not exist ".git" (
    echo [1/5] Khoi tao kho luu tru Git...
    git init
)

git branch -M main

:: Kiem tra git config user.name va user.email
set "GIT_USER="
for /f "delims=" %%i in ('git config user.name 2^>nul') do set "GIT_USER=%%i"
if "!GIT_USER!"=="" (
    echo [2/5] Thiet lap thong tin tac gia Git mac dinh ^(user.name = "HL Survey Engineer"^)...
    git config user.name "HL Survey Engineer"
) else (
    echo [2/5] Git user.name: !GIT_USER!
)

set "GIT_EMAIL="
for /f "delims=" %%i in ('git config user.email 2^>nul') do set "GIT_EMAIL=%%i"
if "!GIT_EMAIL!"=="" (
    echo       Thiet lap email Git mac dinh ^(user.email = "hl@uav-survey.local"^)...
    git config user.email "hl@uav-survey.local"
) else (
    echo       Git user.email: !GIT_EMAIL!
)

:: Kiem tra remote origin
set "REMOTE_URL="
for /f "delims=" %%i in ('git remote get-url origin 2^>nul') do set "REMOTE_URL=%%i"

if not "%~1"=="" (
    set "INPUT_URL=%~1"
    if "!REMOTE_URL!"=="" (
        git remote add origin "!INPUT_URL!"
    ) else (
        git remote set-url origin "!INPUT_URL!"
    )
    set "REMOTE_URL=!INPUT_URL!"
)

if "!REMOTE_URL!"=="" (
    if not "%GITHUB_REPO_URL%"=="" (
        set "REMOTE_URL=%GITHUB_REPO_URL%"
        git remote add origin "!REMOTE_URL!"
    )
)

if "!REMOTE_URL!"=="" (
    echo.
    echo [3/5] Chua cau hinh duong dan GitHub Remote ^(origin^).
    echo       Vi du: https://github.com/^<username^>/^<repo^>.git
    set /p "USER_REPO_URL=Nhap URL GitHub Repository cua ban: "
    if "!USER_REPO_URL!"=="" (
        echo [LOI] Ban chua nhap URL GitHub Repository. Huy thao tac day code.
        pause
        exit /b 1
    )
    git remote add origin "!USER_REPO_URL!"
    set "REMOTE_URL=!USER_REPO_URL!"
) else (
    echo [3/5] Remote origin hien tai: !REMOTE_URL!
)

:: Stage va Commit cac thay doi moi (neu co)
echo.
echo [4/5] Kiem tra va dong goi cac thay doi moi...
git add -A

git diff --cached --quiet
if errorlevel 1 (
    set "COMMIT_MSG=Update UAV GeoTIFF Studio & WebGPU 6-Class Terrain Survey Portal"
    git commit -m "!COMMIT_MSG!"
) else (
    echo       Khong co thay doi moi can commit ^(cay thu muc da sach^).
)

:: Day len GitHub nhanh main
echo.
echo [5/5] Dang day ma nguon va mo hinh WebGPU ONNX len GitHub ^(origin/main^)...
git push -u origin main
if errorlevel 1 (
    echo.
    echo [CANH BAO] Lenh git push gap loi. Hay kiem tra quyen truy cap GitHub hoac URL: !REMOTE_URL!
    pause
    exit /b 1
)

echo.
echo ============================================================================
echo   HOAN TAT! Du an da duoc day thanh cong len: !REMOTE_URL!
echo ============================================================================
pause
exit /b 0
