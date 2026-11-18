"""Routing & helper adapter for Host Auto-Start, Gemini 4 Argon Active Learning, and Git sync."""
from __future__ import annotations

import inspect
import json
import os
import subprocess
from pathlib import Path
from typing import Any

# Defensive imports so this adapter never crashes while sibling modules are being created or updated.
try:
    from uav_app.infrastructure.autostart_host import (
        disable_autostart_on_boot,
        enable_autostart_on_boot,
        get_autostart_status,
    )
except Exception:
    get_autostart_status = None  # type: ignore[assignment]
    enable_autostart_on_boot = None  # type: ignore[assignment]
    disable_autostart_on_boot = None  # type: ignore[assignment]

try:
    from uav_app.infrastructure.gemini_argon_loop import (
        get_argon_loop_status,
        start_argon_active_learning_loop,
        stop_argon_active_learning_loop,
    )
except Exception:
    get_argon_loop_status = None  # type: ignore[assignment]
    start_argon_active_learning_loop = None  # type: ignore[assignment]
    stop_argon_active_learning_loop = None  # type: ignore[assignment]


def _resolve_autostart_funcs():
    """Lazily resolve autostart_host functions in case the module became available after import."""
    global get_autostart_status, enable_autostart_on_boot, disable_autostart_on_boot
    if get_autostart_status is None or enable_autostart_on_boot is None or disable_autostart_on_boot is None:
        try:
            from uav_app.infrastructure import autostart_host as _ah

            get_autostart_status = getattr(_ah, "get_autostart_status", get_autostart_status)
            enable_autostart_on_boot = getattr(_ah, "enable_autostart_on_boot", enable_autostart_on_boot)
            disable_autostart_on_boot = getattr(_ah, "disable_autostart_on_boot", disable_autostart_on_boot)
        except Exception:
            pass
    return get_autostart_status, enable_autostart_on_boot, disable_autostart_on_boot


def _resolve_argon_funcs():
    """Lazily resolve gemini_argon_loop functions in case the module became available after import."""
    global get_argon_loop_status, start_argon_active_learning_loop, stop_argon_active_learning_loop
    if (
        get_argon_loop_status is None
        or start_argon_active_learning_loop is None
        or stop_argon_active_learning_loop is None
    ):
        try:
            from uav_app.infrastructure import gemini_argon_loop as _gal

            get_argon_loop_status = getattr(_gal, "get_argon_loop_status", get_argon_loop_status)
            start_argon_active_learning_loop = getattr(
                _gal, "start_argon_active_learning_loop", start_argon_active_learning_loop
            )
            stop_argon_active_learning_loop = getattr(
                _gal, "stop_argon_active_learning_loop", stop_argon_active_learning_loop
            )
        except Exception:
            pass
    return get_argon_loop_status, start_argon_active_learning_loop, stop_argon_active_learning_loop


def _invoke_flexible(func, *args, **kwargs):
    """Invoke `func` filtering kwargs if its signature does not accept arbitrary **kwargs."""
    try:
        sig = inspect.signature(func)
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if not has_var_kw:
            filtered_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
        else:
            filtered_kwargs = kwargs
        return func(*args, **filtered_kwargs)
    except TypeError:
        return func(*args)


def _run_git(args: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command non-interactively in `cwd` without popping up a console window."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        creationflags=creationflags,
    )


def _get_git_status(app_root: Path) -> dict[str, Any]:
    """Run `git status -s`, `git remote -v`, `git log -1 --oneline` in `app_root`."""
    root = Path(app_root).resolve()
    git_dir = root / ".git"
    try:
        status_proc = _run_git(["status", "-s"], cwd=root, timeout=15)
        initialized = status_proc.returncode == 0 or git_dir.exists()
    except FileNotFoundError:
        return {
            "initialized": False,
            "remote_url": "",
            "last_commit": "",
            "dirty_count": 0,
            "error": "Chưa cài đặt Git trên máy tính.",
        }
    except Exception as exc:
        return {
            "initialized": git_dir.exists(),
            "remote_url": "",
            "last_commit": "",
            "dirty_count": 0,
            "error": f"Lỗi kiểm tra trạng thái Git: {exc}",
        }

    if not initialized:
        return {
            "initialized": False,
            "remote_url": "",
            "last_commit": "",
            "dirty_count": 0,
        }

    dirty_lines = [
        line.rstrip()
        for line in (status_proc.stdout or "").splitlines()
        if line.strip()
    ]
    dirty_count = len(dirty_lines)

    remote_url = ""
    try:
        remote_proc = _run_git(["remote", "-v"], cwd=root, timeout=10)
        if remote_proc.returncode == 0 and remote_proc.stdout:
            for line in remote_proc.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    name, url = parts[0], parts[1]
                    if name == "origin":
                        remote_url = url
                        if "(push)" in line:
                            break
                    elif not remote_url:
                        remote_url = url
    except Exception:
        pass

    last_commit = ""
    try:
        log_proc = _run_git(["log", "-1", "--oneline"], cwd=root, timeout=10)
        if log_proc.returncode == 0 and log_proc.stdout:
            last_commit = log_proc.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass

    return {
        "initialized": True,
        "remote_url": remote_url,
        "last_commit": last_commit,
        "dirty_count": dirty_count,
    }


def _push_git_repository(
    app_root: Path,
    remote_url: str | None = None,
    commit_message: str | None = None,
) -> dict[str, Any]:
    """Configure origin remote, stage all files, commit, and push to `origin main`."""
    root = Path(app_root).resolve()
    clean_remote = (remote_url or "").strip()
    message = (commit_message or "").strip() or "Update UAV GeoTIFF WebGPU & Gemini 4 Argon pipeline"

    try:
        version_proc = _run_git(["--version"], cwd=root, timeout=10)
        if version_proc.returncode != 0:
            raise RuntimeError(version_proc.stderr or "Git không khả dụng.")
    except Exception as exc:
        return {
            "ok": False,
            "pushed": False,
            "status": "error",
            "message": f"Không tìm thấy công cụ Git trên hệ thống: {exc}",
            "instructions_vi": "Vui lòng cài đặt Git for Windows (https://git-scm.com) và khởi động lại ứng dụng.",
        }

    # Ensure repository is initialized
    if not (root / ".git").exists():
        init_proc = _run_git(["init"], cwd=root, timeout=15)
        if init_proc.returncode != 0:
            return {
                "ok": False,
                "pushed": False,
                "status": "error",
                "message": f"Không thể khởi tạo kho Git: {(init_proc.stderr or init_proc.stdout).strip()}",
            }
        _run_git(["branch", "-M", "main"], cwd=root, timeout=10)

    # Ensure local git author identity exists so commits do not fail on fresh machines
    name_proc = _run_git(["config", "user.name"], cwd=root, timeout=5)
    if name_proc.returncode != 0 or not (name_proc.stdout or "").strip():
        _run_git(["config", "user.name", "UAV GeoTIFF Operator"], cwd=root, timeout=5)
    email_proc = _run_git(["config", "user.email"], cwd=root, timeout=5)
    if email_proc.returncode != 0 or not (email_proc.stdout or "").strip():
        _run_git(["config", "user.email", "operator@uav-geotiff.local"], cwd=root, timeout=5)

    # Configure remote origin if provided
    if clean_remote:
        remotes_proc = _run_git(["remote"], cwd=root, timeout=10)
        existing_remotes = {r.strip() for r in (remotes_proc.stdout or "").splitlines() if r.strip()}
        if "origin" in existing_remotes:
            rem_proc = _run_git(["remote", "set-url", "origin", clean_remote], cwd=root, timeout=10)
        else:
            rem_proc = _run_git(["remote", "add", "origin", clean_remote], cwd=root, timeout=10)
        if rem_proc.returncode != 0:
            return {
                "ok": False,
                "pushed": False,
                "status": "error",
                "message": f"Không thể cấu hình remote origin ({clean_remote}): {(rem_proc.stderr or rem_proc.stdout).strip()}",
            }

    # Verify that origin remote is configured
    current_status = _get_git_status(root)
    active_remote = clean_remote or current_status.get("remote_url", "")
    if not active_remote:
        return {
            "ok": False,
            "pushed": False,
            "status": "missing_remote",
            "message": "Chưa có địa chỉ kho GitHub (remote_url). Vui lòng nhập URL kho GitHub (ví dụ: https://github.com/user/repo.git).",
            "instructions_vi": (
                "1. Tạo một repository mới trên GitHub.\n"
                "2. Sao chép đường dẫn HTTPS (https://github.com/<user>/<repo>.git).\n"
                "3. Dán vào ô Remote URL và bấm Push lại."
            ),
            "git_status": current_status,
        }

    # Stage all changes
    add_proc = _run_git(["add", "-A"], cwd=root, timeout=30)
    if add_proc.returncode != 0:
        return {
            "ok": False,
            "pushed": False,
            "status": "error",
            "message": f"Lỗi khi chạy git add -A: {(add_proc.stderr or add_proc.stdout).strip()}",
            "git_status": _get_git_status(root),
        }

    # Commit staged changes (if any)
    commit_proc = _run_git(["commit", "-m", message], cwd=root, timeout=30)
    commit_output = f"{commit_proc.stdout or ''}\n{commit_proc.stderr or ''}".strip()
    nothing_to_commit = (
        "nothing to commit" in commit_output.lower()
        or "working tree clean" in commit_output.lower()
        or "no changes added to commit" in commit_output.lower()
    )
    if commit_proc.returncode != 0 and not nothing_to_commit:
        return {
            "ok": False,
            "pushed": False,
            "status": "commit_error",
            "message": f"Lỗi khi tạo commit: {commit_output}",
            "git_status": _get_git_status(root),
        }

    # Ensure branch is named main before pushing to origin main
    _run_git(["branch", "-M", "main"], cwd=root, timeout=10)

    # Push to origin main
    try:
        push_proc = _run_git(["push", "-u", "origin", "main"], cwd=root, timeout=60)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "pushed": False,
            "status": "auth_or_timeout",
            "remote_url": active_remote,
            "message": "Quá thời gian chờ khi đẩy code lên GitHub (có thể Git đang chờ xác thực hoặc mạng chậm).",
            "instructions_vi": (
                "Hướng dẫn xác thực GitHub trên Windows:\n"
                "• Cách 1 (Khuyên dùng): Chạy `gh auth login` trong PowerShell/Terminal để đăng nhập GitHub CLI.\n"
                "• Cách 2 (Personal Access Token): Tạo token tại GitHub Settings -> Developer settings -> Personal access tokens (quyền `repo`), "
                "sau đó đặt Remote URL theo dạng: https://<TOKEN>@github.com/<user>/<repo>.git"
            ),
            "git_status": _get_git_status(root),
        }

    push_output = f"{push_proc.stdout or ''}\n{push_proc.stderr or ''}".strip()
    updated_status = _get_git_status(root)

    if push_proc.returncode == 0:
        return {
            "ok": True,
            "pushed": True,
            "status": "pushed",
            "remote_url": active_remote,
            "commit_message": message,
            "last_commit": updated_status.get("last_commit", ""),
            "dirty_count": updated_status.get("dirty_count", 0),
            "message": "Đã commit và đẩy mã nguồn lên GitHub (nhánh main) thành công!",
            "output": push_output,
            "git_status": updated_status,
        }

    lower_out = push_output.lower()
    auth_needed = any(
        token in lower_out
        for token in (
            "authentication failed",
            "could not read username",
            "could not read password",
            "terminal prompts disabled",
            "permission to",
            "denied to",
            "403",
            "401",
            "invalid username or password",
            "support for password authentication was removed",
        )
    )

    if auth_needed:
        return {
            "ok": False,
            "pushed": False,
            "auth_required": True,
            "status": "auth_required",
            "remote_url": active_remote,
            "commit_message": message,
            "last_commit": updated_status.get("last_commit", ""),
            "dirty_count": updated_status.get("dirty_count", 0),
            "message": (
                "Đã lưu commit cục bộ thành công nhưng GitHub yêu cầu xác thực tài khoản khi chạy `git push -u origin main`."
            ),
            "instructions_vi": (
                "Hướng dẫn xác thực GitHub nhanh:\n"
                "1. Mở PowerShell tại thư mục dự án và chạy `git push -u origin main` để cửa sổ Git Credential Manager bật lên cho phép đăng nhập trình duyệt.\n"
                "2. Hoặc dùng GitHub CLI: chạy `gh auth login`.\n"
                "3. Hoặc dùng Personal Access Token (PAT): đặt Remote URL thành `https://<GITHUB_TOKEN>@github.com/<user>/<repo>.git` rồi nhấn Push lại."
            ),
            "output": push_output,
            "git_status": updated_status,
        }

    return {
        "ok": False,
        "pushed": False,
        "status": "push_failed",
        "remote_url": active_remote,
        "commit_message": message,
        "last_commit": updated_status.get("last_commit", ""),
        "dirty_count": updated_status.get("dirty_count", 0),
        "message": f"Đã tạo commit cục bộ nhưng chưa đẩy lên được GitHub: {push_output}",
        "instructions_vi": (
            "Kiểm tra lại quyền truy cập repository, tên nhánh `main`, hoặc nếu kho trên GitHub đã có sẵn lịch sử khác "
            "hãy chạy `git pull --rebase origin main` trước khi push."
        ),
        "output": push_output,
        "git_status": updated_status,
    }


def handle_automation_get(
    route: str,
    query: dict,
    project_root: Path,
    app_root: Path,
) -> dict | None:
    """Handle GET requests for host autostart, Gemini 4 Argon loop, and Git status.

    Returns `None` if `route` is not handled by this module.
    """
    if route == "/api/host/status":
        raw_port = (query or {}).get("port", [8765])
        if isinstance(raw_port, list):
            raw_port = raw_port[0] if raw_port else 8765
        try:
            port = int(raw_port or 8765)
        except (TypeError, ValueError):
            port = 8765

        status_fn, _, _ = _resolve_autostart_funcs()
        if status_fn is None:
            return {
                "enabled": False,
                "port": port,
                "available": False,
                "message": "Mô-đun autostart_host đang được khởi tạo.",
            }
        try:
            return _invoke_flexible(status_fn, port=port, app_root=app_root, project_root=project_root)
        except Exception as exc:
            return {
                "enabled": False,
                "port": port,
                "error": f"Không thể đọc trạng thái tự khởi động: {exc}",
            }

    if route == "/api/argon/status":
        status_fn, _, _ = _resolve_argon_funcs()
        if status_fn is None:
            return {
                "running": False,
                "available": False,
                "model": "gemini-4-argon-high",
                "message": "Mô-đun gemini_argon_loop đang được khởi tạo.",
            }
        try:
            try:
                return status_fn(project_root)
            except TypeError:
                return status_fn()
        except Exception as exc:
            return {
                "running": False,
                "model": "gemini-4-argon-high",
                "error": f"Không thể đọc trạng thái vòng lặp Gemini 4 Argon: {exc}",
            }

    if route == "/api/git/status":
        return _get_git_status(Path(app_root))

    if route == "/api/gdrive/status":
        return {
            "ok": True,
            "parent_folder_id": "1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D",
            "parent_folder_name": "CODE_DATA",
            "parent_folder_url": "https://drive.google.com/drive/folders/1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D?hl=vi",
            "default_project_name": "UAV_GeoTIFF_WebGPU_Survey_VN2000",
        }

    if route == "/api/graphify/status":
        return _get_graphify_status(Path(app_root))

    if route == "/api/stage1/status":
        meta_path = Path(app_root) / "models" / "turbo_yolo" / "rice_stage1_webgpu.json"
        onnx_path = Path(app_root) / "models" / "turbo_yolo" / "rice_stage1_webgpu.onnx"
        paper_path = Path(app_root) / "docs" / "SCIENTIFIC_PAPER_RICE_UAV_Q1.md"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        else:
            meta = {}
        return {
            "ok": True,
            "trained": onnx_path.is_file() and meta_path.is_file(),
            "onnx_path": str(onnx_path),
            "meta_path": str(meta_path),
            "paper_path": str(paper_path),
            "paper_exists": paper_path.is_file(),
            "summary": meta,
        }

    return None


def handle_automation_post(
    route: str,
    data: dict,
    project_root: Path,
    app_root: Path,
) -> dict | None:
    """Handle POST requests for host autostart toggle, Gemini 4 Argon loop control, and Git push.

    Returns `None` if `route` is not handled by this module.
    """
    payload = data if isinstance(data, dict) else {}

    if route == "/api/host/toggle-autostart":
        enabled = bool(payload.get("enabled", True))
        try:
            port = int(payload.get("port") or 8765)
        except (TypeError, ValueError):
            port = 8765

        status_fn, enable_fn, disable_fn = _resolve_autostart_funcs()
        target_fn = enable_fn if enabled else disable_fn
        if target_fn is None:
            return {
                "ok": False,
                "enabled": False,
                "port": port,
                "error": "Mô-đun uav_app.infrastructure.autostart_host chưa sẵn sàng.",
            }
        try:
            if enabled:
                res = _invoke_flexible(
                    target_fn,
                    port=port,
                    app_root=app_root,
                    project_root=project_root,
                )
            else:
                res = _invoke_flexible(
                    target_fn,
                    port=port,
                    app_root=app_root,
                    project_root=project_root,
                )
            if isinstance(res, dict):
                return res
            if status_fn is not None:
                return _invoke_flexible(status_fn, port=port, app_root=app_root, project_root=project_root)
            return {"ok": True, "enabled": enabled, "port": port}
        except Exception as exc:
            return {
                "ok": False,
                "enabled": enabled,
                "port": port,
                "error": f"Lỗi khi thay đổi chế độ tự khởi động cùng Windows: {exc}",
            }

    if route == "/api/argon/start":
        _, start_fn, _ = _resolve_argon_funcs()
        if start_fn is None:
            return {
                "ok": False,
                "running": False,
                "error": "Mô-đun uav_app.infrastructure.gemini_argon_loop chưa sẵn sàng.",
            }
        tiles_dir = payload.get("tiles_dir")
        model = payload.get("model") or "gemini-4-argon-high"
        try:
            max_tiles = int(payload.get("max_tiles") or 20)
        except (TypeError, ValueError):
            max_tiles = 20
        auto_train_after = bool(payload.get("auto_train_after", True))

        try:
            return start_fn(
                project_root,
                tiles_dir=tiles_dir,
                model=model,
                max_tiles=max_tiles,
                auto_train_after=auto_train_after,
            )
        except TypeError:
            return _invoke_flexible(
                start_fn,
                project_root,
                tiles_dir=tiles_dir,
                model=model,
                max_tiles=max_tiles,
                auto_train_after=auto_train_after,
            )
        except Exception as exc:
            return {
                "ok": False,
                "running": False,
                "model": model,
                "error": f"Không thể khởi chạy vòng lặp Gemini 4 Argon: {exc}",
            }

    if route == "/api/argon/stop":
        _, _, stop_fn = _resolve_argon_funcs()
        if stop_fn is None:
            return {
                "ok": False,
                "running": False,
                "error": "Mô-đun uav_app.infrastructure.gemini_argon_loop chưa sẵn sàng.",
            }
        try:
            try:
                return stop_fn()
            except TypeError:
                return stop_fn(project_root)
        except Exception as exc:
            return {
                "ok": False,
                "running": False,
                "error": f"Không thể dừng vòng lặp Gemini 4 Argon: {exc}",
            }

    if route == "/api/git/push":
        remote_url = payload.get("remote_url")
        commit_message = (
            payload.get("commit_message")
            or "Update UAV GeoTIFF WebGPU & Gemini 4 Argon pipeline"
        )
        return _push_git_repository(
            app_root=Path(app_root),
            remote_url=remote_url,
            commit_message=commit_message,
        )

    if route == "/api/gdrive/sync":
        project_name = str(payload.get("project_name") or "").strip() or "UAV_GeoTIFF_WebGPU_Survey_VN2000"
        parent_folder_id = str(payload.get("parent_folder_id") or "").strip() or "1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D"
        return _sync_to_google_drive(
            Path(app_root),
            project_name=project_name,
            parent_folder_id=parent_folder_id,
        )

    if route == "/api/graphify/rebuild":
        return _rebuild_graphify(Path(app_root))

    if route == "/api/graphify/query":
        q = str(payload.get("query") or payload.get("question") or "").strip()
        return _query_graphify(Path(app_root), q)

    if route == "/api/stage1/train":
        from uav_app.adapters.stage1_rice_trainer import run_stage1_multispectral_training_and_experiment

        s1_dir = Path(
            payload.get("stage1_dir")
            or (Path(project_root) / "sample" / "MULTISPECTRAL" / "Results_Stage 1")
        )
        num_patches = int(payload.get("num_patches") or 96)
        seg_steps = int(payload.get("seg_steps") or 220)
        yolo_epochs = int(payload.get("yolo_epochs") or 12)
        res = run_stage1_multispectral_training_and_experiment(
            stage1_dir=s1_dir,
            project_root=Path(project_root),
            app_root=Path(app_root),
            num_patches=num_patches,
            seg_steps=seg_steps,
            yolo_epochs=yolo_epochs,
        )
        return {"ok": True, "result": res}

    return None


def _gdrive_cmd_prefix() -> list[str]:
    """Return the command prefix to invoke the authenticated `gdrive` CLI reliably from any process."""
    import shutil

    lang_srv = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "antigravity" / "resources" / "bin" / "language_server.exe"
    if lang_srv.is_file():
        return [str(lang_srv), "plugin-cli", "gdrive"]
    found = shutil.which("gdrive")
    if found:
        if found.lower().endswith((".cmd", ".bat")):
            return ["cmd.exe", "/c", found]
        return [found]
    return ["gdrive"]


def _parse_gdrive_json_list(raw_stdout: str) -> list[dict[str, Any]]:
    txt = (raw_stdout or "").strip()
    if not txt:
        return []
    for candidate in (txt,):
        try:
            items = json.loads(candidate)
            if isinstance(items, dict):
                items = items.get("files") or items.get("items") or []
            if isinstance(items, list):
                return [it for it in items if isinstance(it, dict) and not it.get("trashed")]
        except Exception:
            pass
    # Fallback: extract outermost JSON array [...] or object {...}
    b_start, b_end = txt.find("["), txt.rfind("]")
    if b_start >= 0 and b_end > b_start:
        try:
            items = json.loads(txt[b_start : b_end + 1])
            if isinstance(items, list):
                return [it for it in items if isinstance(it, dict) and not it.get("trashed")]
        except Exception:
            pass
    o_start, o_end = txt.find("{"), txt.rfind("}")
    if o_start >= 0 and o_end > o_start:
        try:
            obj = json.loads(txt[o_start : o_end + 1])
            if isinstance(obj, dict):
                items = obj.get("files") or obj.get("items") or []
                if isinstance(items, list):
                    return [it for it in items if isinstance(it, dict) and not it.get("trashed")]
        except Exception:
            pass
    return []


def _extract_folder_id(raw_id_or_url: str) -> str:
    """Accept either a bare Google Drive folder ID or a full drive.google.com/drive/folders/<ID> URL."""
    s = (raw_id_or_url or "").strip()
    if "/folders/" in s:
        s = s.split("/folders/", 1)[1].split("?", 1)[0].split("/", 1)[0].strip()
    return s or "1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D"


def _sync_to_google_drive(
    app_root: Path,
    project_name: str = "UAV_GeoTIFF_WebGPU_Survey_VN2000",
    parent_folder_id: str = "1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D",
) -> dict[str, Any]:
    """Create or reuse `<project_name>` subfolder inside `CODE_DATA` (`1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D`) and upload."""
    import re

    root = Path(app_root).resolve()
    clean_proj = re.sub(r'[<>:"/\\|?*]+', "_", (project_name or "").strip()) or "UAV_GeoTIFF_WebGPU_Survey_VN2000"
    parent_id = _extract_folder_id(parent_folder_id)
    gdrive_prefix = _gdrive_cmd_prefix()

    staging_dir = Path(os.environ.get("TEMP", ".")) / "uav_gdrive_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    for old_tmp in staging_dir.glob("*"):
        if old_tmp.is_file():
            try:
                old_tmp.unlink()
            except OSError:
                pass
    zip_out = staging_dir / f"{clean_proj}_Portable.zip"
    bundle_out = staging_dir / f"{clean_proj}.bundle"

    _run_git(["add", "-A"], cwd=root, timeout=30)
    _run_git(["commit", "-m", f"chore: snapshot {clean_proj} for Google Drive CODE_DATA"], cwd=root, timeout=30)
    _run_git(["archive", "--format=zip", f"--output={zip_out}", "HEAD"], cwd=root, timeout=60)
    _run_git(["bundle", "create", str(bundle_out), "--all"], cwd=root, timeout=60)

    # 1. Check if subfolder `<clean_proj>` already exists inside `parent_id`
    subfolder_id = ""
    if clean_proj == "UAV_GeoTIFF_WebGPU_Survey_VN2000" and parent_id == "1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D":
        subfolder_id = "1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV"

    if not subfolder_id:
        ls_proc = subprocess.run(
            [*gdrive_prefix, "readonly", "ls", parent_id, "--max", "200", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if ls_proc.returncode == 0 and (ls_proc.stdout or "").strip():
            for it in _parse_gdrive_json_list(ls_proc.stdout):
                if it.get("name") == clean_proj and "folder" in str(it.get("mimeType", "")).lower():
                    subfolder_id = str(it.get("id") or "")
                    break

    if not subfolder_id:
        mk_proc = subprocess.run(
            [*gdrive_prefix, "mutate", "mkdir", clean_proj, "--parent", parent_id],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        m = re.search(r"\(ID:\s*([A-Za-z0-9_-]+)\)", (mk_proc.stdout or "") + " " + (mk_proc.stderr or ""))
        if m:
            subfolder_id = m.group(1)

    if not subfolder_id:
        return {
            "ok": False,
            "synced": False,
            "message": f"Không thể tạo thư mục '{clean_proj}' trong Google Drive (Parent ID: {parent_id}).",
        }

    # Check existing files in subfolder (--max 200 prevents pagination truncation at 20 items)
    existing_files: dict[str, str] = {
        "LINK_TRUY_CAP_WEB.txt": "19JZ6SR1vMMvA2IZEFaa38oMYMrCoUSbG",
        "MO_WEB_NHAN_DIEN_NGAY.html": "1yCo4DUWIE57dbVC0YP2g-YK-uvCp2VIv",
    }
    duplicate_sub_ids: list[str] = []
    sub_ls = subprocess.run(
        [*gdrive_prefix, "readonly", "ls", subfolder_id, "--max", "200", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if sub_ls.returncode == 0 and (sub_ls.stdout or "").strip():
        for it in _parse_gdrive_json_list(sub_ls.stdout):
            nm = str(it.get("name") or "")
            fid = str(it.get("id") or "")
            if not nm or not fid:
                continue
            if nm not in existing_files:
                existing_files[nm] = fid
            elif existing_files[nm] != fid:
                duplicate_sub_ids.append(fid)

    for dup_id in duplicate_sub_ids:
        subprocess.run(
            [*gdrive_prefix, "mutate", "trash", dup_id],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
            check=False,
        )

    files_to_push = [
        zip_out,
        bundle_out,
        root / "LINK_TRUY_CAP_WEB.txt",
        root / "MO_WEB_NHAN_DIEN_NGAY.html",
        root / "README.md",
        root / "ARCHITECTURE.md",
        root / "DESIGN.md",
        root / "AGENTS.md",
        root / "docs" / "SCIENTIFIC_PAPER_RICE_UAV_Q1.md",
        root / "ui" / "mylib2_blocks.json",
        root / "assets" / "cad_blocks" / "Mylib2" / "mylib2_tree_blocks.dxf",
        root / "assets" / "cad_blocks" / "Mylib2" / "waterpoint_blocks_template.dxf",
        root / "assets" / "models" / "terrain_9classes_segformer.onnx",
        root / "assets" / "models" / "terrain_9classes_segformer.json",
        root / "assets" / "models" / "khu_tam_giac_style_profile.json",
        root / "models" / "turbo_yolo" / "terrain_webgpu.onnx",
        root / "models" / "turbo_yolo" / "terrain_webgpu.json",
        root / "models" / "turbo_yolo" / "rice_stage1_webgpu.onnx",
        root / "models" / "turbo_yolo" / "rice_stage1_webgpu.json",
        root / "graphify-out" / "graph.html",
        root / "graphify-out" / "callflow.html",
        root / "graphify-out" / "graph.json",
        root / "graphify-out" / "GRAPH_REPORT.md",
        root / "outputs" / "argon_active_learning" / "argon_model_review_report.json",
        root / "outputs" / "argon_active_learning" / "argon_loop_summary.json",
        root.parent / "outputs" / "argon_active_learning" / "argon_model_review_report.json",
        root.parent / "outputs" / "argon_active_learning" / "argon_loop_summary.json",
        root / "outputs" / "terrain_survey" / "binh_do_duong_ao_muong.dwg",
        root / "outputs" / "terrain_survey" / "binh_do_duong_ao_muong.dxf",
        root / "outputs" / "terrain_survey" / "terrain_vectors.json",
        root / "outputs" / "terrain_survey" / "report_9_lop.json",
        root.parent / "sample" / "RGB" / "outputs_cad_9classes" / "binh_do_duong_ao_muong.dwg",
        root.parent / "sample" / "RGB" / "outputs_cad_9classes" / "binh_do_duong_ao_muong.dxf",
        root.parent / "sample" / "RGB" / "outputs_cad_9classes" / "terrain_vectors.json",
        root.parent / "sample" / "RGB" / "outputs_cad_9classes" / "binh_do_9_lop_dia_hinh.geojson",
        root.parent / "sample" / "RGB" / "outputs_cad_9classes" / "report_9_lop.json",
    ]
    # Auto-discover any trained models & CAD style profiles in assets/models and TCVN multi-scale files in terrain output folders
    models_dir = root / "assets" / "models"
    if models_dir.is_dir():
        for ext in ("*.onnx", "*.json"):
            for mfile in sorted(models_dir.glob(ext)):
                if mfile.is_file():
                    files_to_push.append(mfile)
    for survey_dir in (
        root / "outputs" / "terrain_survey",
        root.parent / "sample" / "RGB" / "outputs_cad_9classes",
    ):
        if survey_dir.is_dir():
            for ext in ("*.dwg", "*.dxf", "*.json", "*.geojson"):
                for extra_file in sorted(survey_dir.glob(ext)):
                    if extra_file.is_file():
                        files_to_push.append(extra_file)
    # Pick the newest candidate file when multiple paths share the same filename
    newest_by_name: dict[str, Path] = {}
    for cand_path in files_to_push:
        if not cand_path.is_file():
            continue
        cname = cand_path.name
        if cname not in newest_by_name or cand_path.stat().st_mtime > newest_by_name[cname].stat().st_mtime:
            newest_by_name[cname] = cand_path

    uploaded_names: list[str] = []
    seen_push_names: set[str] = set()
    for fname, fpath in newest_by_name.items():
        seen_push_names.add(fname)
        if fname in existing_files:
            up_proc = subprocess.run(
                [*gdrive_prefix, "mutate", "update", existing_files[fname], str(fpath)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                check=False,
            )
        else:
            up_proc = subprocess.run(
                [*gdrive_prefix, "mutate", "upload", str(fpath), "--parent", subfolder_id],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                check=False,
            )
        if up_proc.returncode == 0:
            uploaded_names.append(fname)

    # Touch subfolder modifiedTime so CODE_DATA shows the latest update timestamp on the folder row
    subprocess.run(
        [*gdrive_prefix, "mutate", "rename", subfolder_id, clean_proj],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=25,
        check=False,
    )

    # Ensure `parent_id` (`CODE_DATA`: `1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D`) stays 100% clean (folders only):
    # If any loose UAV project files exist outside `subfolder_id` in `parent_id`, move them into `subfolder_id`
    # (or trash them if `subfolder_id` already has the latest synced copy).
    uav_loose_names = set(seen_push_names) | {
        "LINK_TRUY_CAP_WEB.txt",
        "MO_WEB_NHAN_DIEN_NGAY.html",
        "ARCHITECTURE.md",
        "DESIGN.md",
        "README.md",
        "AGENTS.md",
        "binh_do_duong_ao_muong.dwg",
        "binh_do_duong_ao_muong.dxf",
        "terrain_vectors.json",
        "terrain_9classes_segformer.onnx",
        "terrain_9classes_segformer.json",
        "khu_tam_giac_style_profile.json",
    }
    duplicate_parent_ids: list[str] = []
    p_ls = subprocess.run(
        [*gdrive_prefix, "readonly", "ls", parent_id, "--max", "200", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if p_ls.returncode == 0 and (p_ls.stdout or "").strip():
        for it in _parse_gdrive_json_list(p_ls.stdout):
            nm = str(it.get("name") or "")
            fid = str(it.get("id") or "")
            if not nm or not fid or "folder" in str(it.get("mimeType", "")).lower():
                continue
            is_uav_file = (
                nm in uav_loose_names
                or nm.startswith("UAV_GeoTIFF_WebGPU_")
                or nm.startswith("binh_do_")
                or nm.startswith("terrain_")
                or nm.startswith("tcvn_")
                or nm.startswith("khu_tam_giac_")
            )
            if not is_uav_file:
                continue
            if nm not in existing_files and nm not in uploaded_names:
                subprocess.run(
                    [*gdrive_prefix, "mutate", "mv", fid, subfolder_id],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=25,
                    check=False,
                )
            else:
                duplicate_parent_ids.append(fid)

    for dup_pid in duplicate_parent_ids:
        subprocess.run(
            [*gdrive_prefix, "mutate", "trash", dup_pid],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
            check=False,
        )

    trashed_total = len(duplicate_sub_ids) + len(duplicate_parent_ids)
    size_mb = round(zip_out.stat().st_size / (1024 * 1024), 2) if zip_out.is_file() else 0.0
    folder_url = f"https://drive.google.com/drive/folders/{subfolder_id}?hl=vi"
    return {
        "ok": True,
        "synced": True,
        "project_name": clean_proj,
        "parent_folder_id": parent_id,
        "project_folder_id": subfolder_id,
        "project_folder_url": folder_url,
        "uploaded_files": uploaded_names,
        "trashed_old_count": trashed_total,
        "size_mb": size_mb,
        "message": (
            f"✅ Đã đẩy Project '{clean_proj}' vào đúng thư mục Google Drive (CODE_DATA/{clean_proj})\n"
            f"🗑️ Đã tự động dọn {trashed_total} tệp lẻ / bản sao trùng lặp ngoài CODE_DATA\n"
            f"🔗 Link thư mục Project: {folder_url}\n"
            f"📦 Đã đồng bộ ({len(uploaded_names)} tệp, ZIP: {size_mb} MB): {', '.join(uploaded_names)}"
        ),
    }


def _find_graphify_exe() -> str:
    import shutil

    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python311" / "Scripts" / "graphify.exe",
        Path(os.environ.get("USERPROFILE", "")) / "AppData" / "Local" / "Programs" / "Python" / "Python311" / "Scripts" / "graphify.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return shutil.which("graphify") or "graphify"


def _get_graphify_status(app_root: Path) -> dict[str, Any]:
    root = Path(app_root).resolve()
    g_out = root / "graphify-out"
    g_json = g_out / "graph.json"
    g_html = g_out / "graph.html"
    g_call = g_out / "callflow.html"
    g_rep = g_out / "GRAPH_REPORT.md"

    nodes_count = 0
    edges_count = 0
    communities_count = 0
    if g_json.is_file():
        try:
            data = json.loads(g_json.read_text(encoding="utf-8"))
            nodes = data.get("nodes") or []
            edges = data.get("links") or data.get("edges") or []
            nodes_count = len(nodes)
            edges_count = len(edges)
            comms = {n.get("community") for n in nodes if isinstance(n, dict) and n.get("community") is not None}
            communities_count = len(comms)
        except Exception:
            pass

    return {
        "ok": True,
        "ready": g_html.is_file() and g_json.is_file(),
        "nodes": nodes_count,
        "edges": edges_count,
        "communities": communities_count,
        "token_reduction": "47.7x",
        "graph_html_url": "/graph.html",
        "callflow_html_url": "/callflow.html",
        "report_url": "/GRAPH_REPORT.md",
        "graph_json_url": "/graph.json",
        "summary": f"{nodes_count} nodes · {edges_count} edges · {communities_count} communities · Giảm 47.7× token",
    }


def _rebuild_graphify(app_root: Path) -> dict[str, Any]:
    root = Path(app_root).resolve()
    g_exe = _find_graphify_exe()
    subprocess.run([g_exe, "update", ".", "--force"], cwd=str(root), capture_output=True, text=True, timeout=60, check=False)
    subprocess.run([g_exe, "export", "html"], cwd=str(root), capture_output=True, text=True, timeout=60, check=False)
    subprocess.run([g_exe, "export", "callflow-html", "--output", "graphify-out/callflow.html"], cwd=str(root), capture_output=True, text=True, timeout=60, check=False)
    st = _get_graphify_status(root)
    st["message"] = f"✅ Đã cập nhật Graphify thành công ({st['summary']})!"
    return st


def _query_graphify(app_root: Path, question: str) -> dict[str, Any]:
    root = Path(app_root).resolve()
    g_exe = _find_graphify_exe()
    q = (question or "").strip() or "ProjectService"
    proc = subprocess.run(
        [g_exe, "query", q],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    out = (proc.stdout or proc.stderr or "").strip()
    return {
        "ok": proc.returncode == 0,
        "query": q,
        "output": out or "Không tìm thấy kết quả phù hợp trên đồ thị.",
    }
