"""Lazy, axis-aligned window planning in the raster's projected coordinate system."""
from copy import deepcopy
from dataclasses import dataclass
from itertools import islice
import math
from numbers import Real
from typing import Iterator


MAX_PREVIEW_TILES = 2000


def _finite_number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _positive_integer(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _axis_count(length: int, tile: int, stride: int) -> int:
    # Integer ceiling avoids loss of precision for very large virtual rasters.
    remainder = max(0, length - tile)
    return 1 + (remainder + stride - 1) // stride


@dataclass(frozen=True)
class GridPlan:
    _metadata: dict
    _config: dict
    columns: int
    rows: int
    stride_x: int
    stride_y: int
    actual_overlap_x_px: int
    actual_overlap_y_px: int
    coverage_guarantee_checked: bool
    warnings: tuple[str, ...]

    @property
    def tile_count(self) -> int:
        return self.columns * self.rows

    @property
    def config(self) -> dict:
        return deepcopy(self._config)

    def iter_tiles(self) -> Iterator[dict]:
        """Yield one rectangle at a time; col/row are source pixel offsets."""
        cfg, meta = self._config, self._metadata
        a, b, c, d, e, f = meta["transform"]

        def point(col, row):
            return [a * col + b * row + c, d * col + e * row + f]

        def relative(point):
            return [point[0] - cfg["base_x"], point[1] - cfg["base_y"]]

        for grid_row in range(self.rows):
            row = grid_row * self.stride_y
            height = min(cfg["tile_height"], meta["height"] - row)
            for grid_col in range(self.columns):
                col = grid_col * self.stride_x
                width = min(cfg["tile_width"], meta["width"] - col)
                corners = [point(col, row), point(col + width, row),
                           point(col + width, row + height), point(col, row + height)]
                center = point(col + width / 2, row + height / 2)
                yield {
                    "id": f"tile_{grid_row * self.columns + grid_col + 1:06d}",
                    "col": col, "row": row, "width": width, "height": height,
                    "grid_col": grid_col, "grid_row": grid_row,
                    "corners_map": corners, "corners_relative": [relative(p) for p in corners],
                    "center_map": center, "center_relative": relative(center),
                }

    def as_dict(self, preview_limit: int = MAX_PREVIEW_TILES) -> dict:
        if isinstance(preview_limit, bool) or not isinstance(preview_limit, int) or preview_limit < 0:
            raise ValueError("preview_limit must be a nonnegative integer")
        limit = min(preview_limit, MAX_PREVIEW_TILES)
        return {
            "metadata": deepcopy(self._metadata), "config": self.config,
            "tile_count": self.tile_count, "columns": self.columns, "rows": self.rows,
            "stride_x": self.stride_x, "stride_y": self.stride_y,
            "actual_overlap_x_px": self.actual_overlap_x_px,
            "actual_overlap_y_px": self.actual_overlap_y_px,
            "coverage_guarantee_checked": self.coverage_guarantee_checked,
            "warnings": list(self.warnings),
            "tiles": list(islice(self.iter_tiles(), limit)),
            "preview_truncated": self.tile_count > limit,
        }


def create_plan(metadata: dict, config: dict) -> GridPlan:
    if not metadata.get("eligible"):
        raise ValueError("; ".join(metadata.get("errors", [])) or "Raster is not eligible for slicing")
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    cfg = {name: _finite_number(config.get(name), name) for name in ("base_x", "base_y")}
    for name in ("tile_width", "tile_height"):
        cfg[name] = _positive_integer(config.get(name), name)
    for name in ("overlap_x", "overlap_y"):
        cfg[name] = _finite_number(config.get(name), name)
        if not 0.1 <= cfg[name] <= 0.5:
            raise ValueError(f"{name} must be between 0.1 and 0.5 (10%-50%)")
    diameter = config.get("max_object_diameter_cm")
    if diameter is not None:
        diameter = _finite_number(diameter, "max_object_diameter_cm")
        if diameter <= 0:
            raise ValueError("max_object_diameter_cm must be positive")
    cfg["max_object_diameter_cm"] = diameter
    sx = math.floor(cfg["tile_width"] * (1 - cfg["overlap_x"]))
    sy = math.floor(cfg["tile_height"] * (1 - cfg["overlap_y"]))
    if sx < 1 or sy < 1:
        raise ValueError("The floor stride must be at least one pixel on both axes")
    ox, oy = cfg["tile_width"] - sx, cfg["tile_height"] - sy
    if diameter is not None:
        required = 2.5 * diameter
        for axis, overlap in (("x", ox), ("y", oy)):
            actual = overlap * metadata[f"gsd_{axis}_cm"]
            if actual < required:
                raise ValueError(f"Actual overlap on {axis.upper()} is {actual:g} cm; "
                                 f"at least 2.5 times diameter ({required:g} cm) is required")
    warnings = list(metadata.get("warnings", []))
    warnings.append("Source edges and nodata can cut objects; overlap cannot recover missing data.")
    warnings.append("GSD describes projected-grid distance, not survey accuracy.")
    if diameter is None:
        warnings.append("Object diameter is unspecified: the object-coverage condition has not been checked.")
    return GridPlan(
        deepcopy(metadata), cfg,
        _axis_count(metadata["width"], cfg["tile_width"], sx),
        _axis_count(metadata["height"], cfg["tile_height"], sy),
        sx, sy, ox, oy, diameter is not None, tuple(dict.fromkeys(warnings)),
    )
