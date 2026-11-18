"""Future integration boundaries. No placeholder inference is presented as a result."""
from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class Detection:
    label: str
    # Continuous original pixel-edge coordinates; no rounding for CAD.
    box: tuple[float, float, float, float]
    confidence: float | None = None


class Detector(Protocol):
    def detect(self, rgb_tile, descriptions: Sequence[str]) -> Sequence[Detection]: ...


class BoxRefiner(Protocol):
    def propose(self, rgb_roi, detection: Detection) -> dict: ...


class CadExporter(Protocol):
    def export(self, approved_detections: Sequence[Detection], spatial_context: dict, destination: str) -> str: ...


class Advisor(Protocol):
    def propose(self, user_request: str, project_context: dict) -> dict: ...
