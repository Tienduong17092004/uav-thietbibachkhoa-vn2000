"""One CUDA model subprocess per job, with bounded cancellation, async pipelining,
and Shared GPU Memory (pin_memory=True) DMA staging."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time


class DetectionCancelled(Exception):
    pass


class ModelClient:
    supports_multi_category = True
    supports_async_pipeline = True

    def __init__(self, project, output_dir, cancelled=lambda: False):
        self.supports_multi_category = True
        self.supports_async_pipeline = True
        self.cancelled = cancelled
        self.queue = queue.Queue(maxsize=64)
        self._write_lock = threading.Lock()
        self.log = (Path(output_dir) / "model.log").open("w", encoding="utf-8")
        project = Path(project)
        python = project / ".venv" / "Scripts" / "python.exe"
        if not python.is_file():
            self.log.close()
            raise ValueError("Không tìm thấy Python của mô hình trong .venv ở thư mục dự án.")
        worker = Path(__file__).resolve().parents[1] / "adapters" / "model_worker.py"
        environment = dict(
            os.environ,
            PYTHONIOENCODING="utf-8",
            PYTHONUNBUFFERED="1",
            HF_HUB_OFFLINE="1",
            UAV_SHARED_GPU_MEM_GIB=os.environ.get("UAV_SHARED_GPU_MEM_GIB", "2.0"),
            PYTORCH_CUDA_ALLOC_CONF=os.environ.get("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True"),
        )
        self.process = subprocess.Popen(
            [str(python), "-u", str(worker), str(project)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=project,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        def read():
            try:
                for line in self.process.stdout:
                    if line.startswith("@UAV@"):
                        try:
                            self.queue.put_nowait(json.loads(line[5:]))
                        except (json.JSONDecodeError, queue.Full):
                            pass
                    else:
                        self.log.write(line)
                        self.log.flush()
            finally:
                try:
                    self.queue.put_nowait({"status": "exited"})
                except queue.Full:
                    pass

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            self.info = self._receive(300)
        except Exception:
            self.close()
            raise

    def _receive(self, timeout=600):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.cancelled():
                raise DetectionCancelled("Đã dừng nhận diện.")
            try:
                result = self.queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if result["status"] in {"error", "exited"}:
                raise RuntimeError(
                    result.get("message", "Tiến trình mô hình đã đóng. Xem model.log trong thư mục kết quả.")
                )
            return result
        raise RuntimeError("Mô hình quá thời gian chờ. Hãy giảm số token hoặc kích thước ảnh.")

    def submit(self, image, category, options, pre_resized=False, req_id=None):
        """Non-blocking submission into model_worker's Shared GPU Memory preprocessor queue."""
        cats = list(category) if isinstance(category, (list, tuple)) else [str(category)]
        payload = dict(
            image=str(image),
            category=category,
            categories=cats,
            options=options,
            pre_resized=bool(pre_resized),
            req_id=req_id,
        )
        with self._write_lock:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()

    def receive(self, timeout=600):
        """Receive the next completed prediction from the pipelined GPU worker."""
        return self._receive(timeout=timeout)

    def predict(self, image, category, options, pre_resized=False):
        self.submit(image, category, options, pre_resized=pre_resized)
        return self.receive()

    def close(self):
        if getattr(self, "process", None):
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.reader.join(3)
            self.process.stdin.close()
            self.process.stdout.close()
        self.log.close()
