"""Atomic project state; design approval never silently changes active processing."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        with self.path.open(encoding="utf-8-sig") as stream:
            self._state = json.load(stream)
        for key in ("completed_modules", "approved_optimizations",
                    "active_pipeline_config", "next_milestones"):
            if key not in self._state:
                raise ValueError(f"Missing required state field: {key}")
        job = self._state.get("last_job")
        if job and job.get("status") in {"running", "queued", "cancelling"}:
            job.update(status="interrupted", message="Lần chạy trước bị gián đoạn; các tile đã ghi vẫn được giữ.")
            self._save()

    def read(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._state)

    def _save(self) -> None:
        self._state["updated_at"] = utc_now()
        fd, name = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self._state, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def update(self, **changes) -> dict:
        with self._lock:
            before = copy.deepcopy(self._state)
            try:
                self._state.update(copy.deepcopy(changes))
                self._save()
            except Exception:
                self._state = before
                raise
            return self.read()

    def decide(self, proposal_id: str, decision: str) -> dict:
        if decision not in {"approve", "reject"}:
            raise ValueError("Quyết định phải là approve hoặc reject.")
        with self._lock:
            pending = copy.deepcopy(self._state.get("pending_proposals", []))
            proposal = next((p for p in pending if p["id"] == proposal_id), None)
            if proposal is None:
                raise ValueError("Đề xuất không tồn tại hoặc đã được xử lý.")
            pending.remove(proposal)
            approved = copy.deepcopy(self._state["approved_optimizations"])
            if decision == "approve":
                approved.append({**proposal, "approval_scope": "design",
                                 "implementation_status": "planned", "approved_by": "user"})
            return self.update(pending_proposals=pending, approved_optimizations=approved)
