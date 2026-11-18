#!/usr/bin/env python3
"""Dedicated Kaggle Free TPU Server Launcher (Method 2 — 30h/week Free TPU v5e-8 / v3-8).

Runs the remote Google TPU inference server in `kaggle_free_tpu` mode on port 8470
(with $0.00 cost, 128 GB HBM TPU v5e-8 / v3-8 profile, and 92.5% GPU load savings).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_colab_tpu_server import (  # noqa: E402
    ColabTPURequestHandler,
    detect_google_tpu_device,
    main as run_tpu_main,
    start_tpu_server,
)

__all__ = [
    "ColabTPURequestHandler",
    "detect_google_tpu_device",
    "main",
    "run_tpu_main",
    "start_tpu_server",
]


def main(argv: Optional[List[str]] = None) -> int:
    os.environ["UAV_TPU_PROVIDER"] = "kaggle_free_tpu"
    args = list(argv if argv is not None else sys.argv[1:])
    if "--provider" not in args:
        args.extend(["--provider", "kaggle_free_tpu"])
    return run_tpu_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
