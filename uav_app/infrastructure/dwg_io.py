"""Native AutoCAD .DWG <-> .DXF conversion and Polyline (PL) I/O using headless AutoCAD Core Console or COM."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

import ezdxf


def find_accoreconsole() -> Path | None:
    """Locate AutoCAD's headless `accoreconsole.exe` on Windows."""
    env_path = (os.environ.get("UAV_ACCORECONSOLE") or "").strip()
    if env_path and Path(env_path).is_file():
        return Path(env_path)

    autodesk_root = Path(r"C:\Program Files\Autodesk")
    if autodesk_root.is_dir():
        candidates = sorted(
            autodesk_root.glob("AutoCAD */accoreconsole.exe"),
            key=lambda p: p.parent.name,
            reverse=True,
        )
        # Prefer stable 2025/2026/2024 first if available, else newest
        for pref in ("2025", "2026", "2024", "2023", "2027"):
            for cand in candidates:
                if pref in cand.parent.name and cand.is_file():
                    return cand
        for cand in candidates:
            if cand.is_file():
                return cand
    return None


def convert_dwg_to_dxf(dwg_path: str | Path, output_dxf_path: str | Path | None = None, use_cache: bool = True) -> Path:
    """Convert a native AutoCAD `.dwg` file to `.dxf` headlessly via `accoreconsole.exe` or AutoCAD COM."""
    src = Path(str(dwg_path).strip().strip('"')).expanduser().resolve()
    if not src.is_file():
        raise ValueError(f"Không tìm thấy tệp bản vẽ: {src}")
    if src.suffix.lower() == ".dxf":
        return src
    if src.suffix.lower() != ".dwg":
        raise ValueError(f"Định dạng bản vẽ không hỗ trợ ({src.suffix}). Hãy chọn tệp .DWG hoặc .DXF.")

    cache_dir = Path(tempfile.gettempdir()) / "uav_dwg_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    stat = src.stat()
    sig = hashlib.sha256(f"{src}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")).hexdigest()[:16]

    if output_dxf_path is not None:
        dst = Path(output_dxf_path).expanduser().resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
    else:
        dst = cache_dir / f"{src.stem}_{sig}.dxf"

    if use_cache and dst.is_file() and dst.stat().st_size > 128:
        return dst

    # Work in a clean ASCII-safe temporary filenames path for accoreconsole stability
    work_in = cache_dir / f"in_{sig}.dwg"
    work_out = cache_dir / f"out_{sig}.dxf"
    scr_path = cache_dir / f"to_dxf_{sig}.scr"

    try:
        shutil.copy2(src, work_in)
        if work_out.is_file():
            work_out.unlink()

        accore = find_accoreconsole()
        if accore is not None:
            scr_path.write_text(f'_DXFOUT\n"{work_out}"\n16\n_QUIT\n_Y\n', encoding="utf-8")
            subprocess.run(
                [str(accore), "/i", str(work_in), "/s", str(scr_path)],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if work_out.is_file() and work_out.stat().st_size > 128:
                if dst != work_out:
                    shutil.move(str(work_out), str(dst))
                return dst

        # Fallback: ODA File Converter via ezdxf if installed
        try:
            from ezdxf.addons import odafc

            if odafc.is_installed():
                odafc.convert(str(work_in), str(work_out), version="R2013")
                if work_out.is_file() and work_out.stat().st_size > 128:
                    if dst != work_out:
                        shutil.move(str(work_out), str(dst))
                    return dst
        except Exception:
            pass

        # Fallback: AutoCAD COM Automation
        try:
            from uav_app.infrastructure.autocad_com import _connect_autocad

            app = _connect_autocad(create_if_not_exists=True)
            doc = app.Documents.Open(str(work_in), True)
            try:
                # 61 = ac2013_dxf, 49 = ac2010_dxf
                doc.SaveAs(str(work_out), 61)
            finally:
                doc.Close(False)
            if work_out.is_file() and work_out.stat().st_size > 128:
                if dst != work_out:
                    shutil.move(str(work_out), str(dst))
                return dst
        except Exception:
            pass
    finally:
        for tmp_f in (work_in, scr_path):
            try:
                if tmp_f.is_file():
                    tmp_f.unlink()
            except OSError:
                pass

    raise ValueError(f"Không thể chuyển đổi tệp .DWG ({src.name}) sang .DXF tự động.")


def convert_dxf_to_dwg(
    dxf_path: str | Path,
    output_dwg_path: str | Path | None = None,
    dwg_version: str = "2018",
) -> Path | None:
    """Convert an exported `.dxf` file directly into a native AutoCAD `.dwg` file."""
    src = Path(str(dxf_path).strip().strip('"')).expanduser().resolve()
    if not src.is_file():
        return None

    dst = (
        Path(output_dwg_path).expanduser().resolve()
        if output_dwg_path is not None
        else src.with_suffix(".dwg")
    )
    dst.parent.mkdir(parents=True, exist_ok=True)

    cache_dir = Path(tempfile.gettempdir()) / "uav_dwg_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    sig = hashlib.sha256(f"{src}|{src.stat().st_mtime_ns}".encode("utf-8")).hexdigest()[:16]
    work_in = cache_dir / f"dxf_in_{sig}.dxf"
    work_out = cache_dir / f"dwg_out_{sig}.dwg"
    scr_path = cache_dir / f"to_dwg_{sig}.scr"

    try:
        shutil.copy2(src, work_in)
        if work_out.is_file():
            work_out.unlink()

        accore = find_accoreconsole()
        if accore is not None:
            scr_path.write_text(
                f'_DXFIN\n"{work_in}"\n_SAVEAS\n{dwg_version}\n"{work_out}"\n_QUIT\n_Y\n',
                encoding="utf-8",
            )
            subprocess.run(
                [str(accore), "/s", str(scr_path)],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if work_out.is_file() and work_out.stat().st_size > 128:
                shutil.move(str(work_out), str(dst))
                return dst

        # Fallback: ODA File Converter
        try:
            from ezdxf.addons import odafc

            if odafc.is_installed():
                odafc.convert(str(work_in), str(work_out), version="R2018")
                if work_out.is_file() and work_out.stat().st_size > 128:
                    shutil.move(str(work_out), str(dst))
                    return dst
        except Exception:
            pass
    finally:
        for tmp_f in (work_in, work_out, scr_path):
            try:
                if tmp_f.is_file():
                    tmp_f.unlink()
            except OSError:
                pass

    return dst if dst.is_file() and dst.stat().st_size > 128 else None


def inspect_dwg_polylines_summary(dwg_or_dxf_path: str | Path) -> dict[str, Any]:
    """Read a `.dwg` or `.dxf` file and summarize all layers and `PL` (`LWPOLYLINE`/`POLYLINE`) entities."""
    dxf_p = convert_dwg_to_dxf(dwg_or_dxf_path)
    doc = ezdxf.readfile(str(dxf_p))
    msp = doc.modelspace()
    layers: dict[str, dict[str, Any]] = {}
    total_pl = 0
    for ent in msp:
        lyr = str(ent.dxf.layer or "0")
        et = ent.dxftype()
        if lyr not in layers:
            l_obj = doc.layers.get(lyr) if lyr in doc.layers else None
            layers[lyr] = {
                "layer": lyr,
                "color": int(l_obj.color) if l_obj else 7,
                "linetype": str(l_obj.dxf.linetype) if l_obj else "Continuous",
                "counts": {},
                "pl_count": 0,
            }
        layers[lyr]["counts"][et] = layers[lyr]["counts"].get(et, 0) + 1
        if et in {"LWPOLYLINE", "POLYLINE", "LINE"}:
            layers[lyr]["pl_count"] += 1
            total_pl += 1
    return {
        "source_file": Path(dwg_or_dxf_path).name,
        "resolved_dxf": str(dxf_p),
        "total_layers": len(layers),
        "total_polylines": total_pl,
        "layers": sorted(layers.values(), key=lambda x: (-x["pl_count"], x["layer"])),
    }
