"""Pixel-edge boxes, conservative score-free fusion, and labelled evaluation."""
import copy
import math
import re

TOKENS = re.compile(r"<ref>\s*(?P<label>.*?)\s*</ref>|<box>\s*"
                    r"<(?P<x1>-?[\d.]+)>\s*<(?P<y1>-?[\d.]+)>\s*"
                    r"<(?P<x2>-?[\d.]+)>\s*<(?P<y2>-?[\d.]+)>\s*</box>", re.I | re.S)


def _match_category(label: str, categories: list[str] | tuple[str, ...]) -> str:
    if not categories:
        return label or "object"
    if len(categories) == 1:
        return categories[0]
    norm = (label or "").strip().casefold()
    if not norm:
        return categories[0]
    for cat in categories:
        if cat.strip().casefold() == norm:
            return cat
    for cat in categories:
        c_low = cat.strip().casefold()
        if c_low in norm or norm in c_low:
            return cat
    label_words = set(re.findall(r"[a-z0-9]+", norm))
    best_cat, best_overlap = categories[0], 0
    for cat in categories:
        cat_words = set(re.findall(r"[a-z0-9]+", cat.casefold()))
        overlap = len(label_words & cat_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best_cat = cat
    return best_cat


def parse_boxes(text, width, height, category):
    is_multi = isinstance(category, (list, tuple))
    cat_list = [str(c) for c in category] if is_multi else [str(category)]
    default_cat = cat_list[0] if cat_list else "object"
    result, label, active_cat = [], default_cat, default_cat
    for match in TOKENS.finditer(text):
        if match.group("label") is not None:
            label = " ".join(match.group("label").split()) or default_cat
            active_cat = _match_category(label, cat_list) if is_multi else default_cat
            continue
        try:
            values = [float(match.group(k)) for k in ("x1", "y1", "x2", "y2")]
        except ValueError:
            continue
        if not all(math.isfinite(v) for v in values):
            continue
        a, b, c, d = [max(0, min(1000, v)) for v in values]
        x1, x2 = sorted((a * width / 1000, c * width / 1000))
        y1, y2 = sorted((b * height / 1000, d * height / 1000))
        if x2 > x1 and y2 > y1:
            result.append(dict(label=label, category=active_cat, box=[x1, y1, x2, y2],
                               box_1000=values, confidence=None))
    return result


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union > 0 else 0


def diou(a, b):
    distance = ((a[0]+a[2]-b[0]-b[2])/2)**2 + ((a[1]+a[3]-b[1]-b[3])/2)**2
    diagonal = (max(a[2],b[2])-min(a[0],b[0]))**2 + (max(a[3],b[3])-min(a[1],b[1]))**2
    return iou(a,b) - distance / diagonal if diagonal else iou(a,b)


def _box_area(a):
    return max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])


def _intersection_area(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _windows_overlap_match(first, item, threshold):
    """Smart overlap test that avoids merging two distinct adjacent rice plants/trees."""
    b1, b2 = first["box"], item["box"]
    a1, a2 = _box_area(b1), _box_area(b2)
    if a1 <= 0 or a2 <= 0:
        return False, 0.0
    inter = _intersection_area(b1, b2)
    if inter <= 0:
        return False, 0.0

    # If window metadata is present, require the intersection center to lie inside the shared window overlap
    w1, w2 = first.get("window"), item.get("window")
    if isinstance(w1, dict) and isinstance(w2, dict):
        ox1 = max(w1["col"], w2["col"])
        oy1 = max(w1["row"], w2["row"])
        ox2 = min(w1["col"] + w1["width"], w2["col"] + w2["width"])
        oy2 = min(w1["row"] + w1["height"], w2["row"] + w2["height"])
        if ox2 <= ox1 or oy2 <= oy1:
            return False, 0.0
        icx = (max(b1[0], b2[0]) + min(b1[2], b2[2])) / 2.0
        icy = (max(b1[1], b2[1]) + min(b1[3], b2[3])) / 2.0
        if not (ox1 - 4 <= icx <= ox2 + 4 and oy1 - 4 <= icy <= oy2 + 4):
            return False, 0.0

    cx1, cy1 = (b1[0] + b1[2]) / 2.0, (b1[1] + b1[3]) / 2.0
    cx2, cy2 = (b2[0] + b2[2]) / 2.0, (b2[1] + b2[3]) / 2.0
    center_dist = math.hypot(cx1 - cx2, cy1 - cy2)
    mean_span = (math.hypot(b1[2] - b1[0], b1[3] - b1[1]) + math.hypot(b2[2] - b2[0], b2[3] - b2[1])) / 2.0
    size_ratio = min(a1, a2) / max(a1, a2)
    score = iou(b1, b2)

    # Case 1: Same plant seen fully in two overlapping windows -> centers must be very close & sizes similar
    if score >= threshold and center_dist <= 0.42 * mean_span and size_ratio >= 0.35:
        return True, score

    # Case 2: One box was clipped by a micro-window edge and is contained inside the unclipped box
    containment = inter / min(a1, a2)
    if (first.get("touches_window_edge") or item.get("touches_window_edge")) and containment >= 0.82 and center_dist <= 0.55 * mean_span:
        return True, max(score, containment * 0.9)

    return False, 0.0


def fuse_boxes(records, mode="none", threshold=.55):
    """Equal geometry weights; confidence stays null, no confidence-weighted WBF.

    Match only different windows of the same query. Keep a fixed representative
    to prevent a chain of touching rice clumps becoming one large detection.
    """
    if mode not in {"none", "equal_weight", "smart_overlap"}:
        raise ValueError("Chế độ gộp không hợp lệ.")
    if not .1 <= threshold <= .95:
        raise ValueError("Ngưỡng gộp phải nằm trong 0,1–0,95.")
    groups, buckets, large = [], {}, set()

    def cells(box):
        x1,y1,x2,y2 = (math.floor(v / 128) for v in box)
        if (x2-x1+1)*(y2-y1+1) > 256:
            return None
        return [(x,y) for x in range(x1,x2+1) for y in range(y1,y2+1)]

    for item in records:
        box, selected = item["box"], None
        keys = cells(box)
        candidates = set(range(len(groups))) if keys is None else set(large)
        if keys:
            for key in keys:
                candidates.update(buckets.get(key, ()))
        best = threshold
        if mode in {"equal_weight", "smart_overlap"}:
            for index in sorted(candidates):
                group = groups[index]
                first = group["members"][0]
                if first["category"] != item["category"] or item["window_id"] in group["windows"]:
                    continue
                if mode == "smart_overlap":
                    matched, score = _windows_overlap_match(first, item, threshold)
                    if matched and score >= best:
                        selected, best = index, score
                else:
                    score = iou(first["box"], box)
                    if score >= best and diou(first["box"], box) >= threshold - .1:
                        selected, best = index, score
        if selected is None:
            selected = len(groups)
            groups.append(dict(members=[], windows=set()))
            if keys is None:
                large.add(selected)
            else:
                for key in keys:
                    buckets.setdefault(key, set()).add(selected)
        groups[selected]["members"].append(item)
        groups[selected]["windows"].add(item["window_id"])
    result = []
    for number, group in enumerate(groups, 1):
        members = group["members"]
        usable = [m for m in members if not m.get("touches_window_edge")] or members
        record = copy.deepcopy(usable[0])
        record.update(id=f"object_{number:06d}", raw_ids=[m["id"] for m in members],
                      box=[sum(m["box"][i] for m in usable)/len(usable) for i in range(4)],
                      confidence=None, fusion_policy="equal_geometry_weights_prefer_unclipped" if len(members)>1 else "unmerged")
        result.append(record)
    return result


def stitch_large_objects(records):
    """Merge boundary-clipped boxes from adjacent windows that belong to objects larger than one micro-window."""
    if len(records) < 2:
        return records
    used = set()
    stitched = []
    for i, rec in enumerate(records):
        if i in used:
            continue
        if not rec.get("touches_window_edge"):
            stitched.append(copy.deepcopy(rec))
            continue
        cur = copy.deepcopy(rec)
        b1 = list(cur["box"])
        raw_ids = list(cur.get("raw_ids") or [cur["id"]])
        merged_any = False
        for j in range(i + 1, len(records)):
            if j in used:
                continue
            other = records[j]
            if other["category"] != cur["category"] or other.get("window_id") == cur.get("window_id"):
                continue
            if not other.get("touches_window_edge"):
                continue
            b2 = other["box"]
            inter = _intersection_area(b1, b2)
            min_a = min(_box_area(b1), _box_area(b2))
            if min_a > 0 and inter / min_a >= 0.25:
                b1 = [min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])]
                raw_ids.extend(other.get("raw_ids") or [other["id"]])
                used.add(j)
                merged_any = True
        if merged_any:
            cur["box"] = b1
            cur["raw_ids"] = list(dict.fromkeys(raw_ids))
            cur["fusion_policy"] = "stitched_large_object"
            cur["touches_window_edge"] = False
        stitched.append(cur)
    for idx, item in enumerate(stitched, 1):
        item["id"] = f"object_{idx:06d}"
    return stitched


def estimate_confidence(record: dict) -> float:
    """Stage 3 heuristic quality score (0..1) for active-learning triage (auto-accept vs human review)."""
    score = 0.45
    raw_ids = record.get("raw_ids") or [record.get("id")]
    if len(raw_ids) >= 2:
        score += 0.20
    if not record.get("touches_window_edge"):
        score += 0.12
    ref = record.get("refinement") or {}
    veg = ref.get("vegetation_fraction")
    if isinstance(veg, (int, float)):
        if 0.12 <= veg <= 0.92:
            score += 0.15
        elif veg > 0.03:
            score += 0.06
    if record.get("candidate_box"):
        score += 0.08
    if isinstance(record.get("height_m"), (int, float)) and record["height_m"] > 0.05:
        score += 0.08
    return round(min(0.99, max(0.05, score)), 3)


def spatial_box(box, affine, base):
    a,b,c,d,e,f = affine
    def point(x,y):
        return [a*x+b*y+c, d*x+e*y+f]
    corners = [point(box[0],box[1]), point(box[2],box[1]), point(box[2],box[3]), point(box[0],box[3])]
    center = point((box[0]+box[2])/2, (box[1]+box[3])/2)
    return dict(corners_map=corners, corners_relative=[[p[0]-base[0],p[1]-base[1]] for p in corners],
                center_map=center, center_relative=[center[0]-base[0],center[1]-base[1]])


def evaluate_boxes(predictions, truth, threshold=.5):
    """One-to-one category/IoU matching; truth is human supplied, not generated."""
    matched, hits = set(), 0
    for item in predictions:
        candidates = [(iou(item["box"], target["box"]), index) for index,target in enumerate(truth)
                      if index not in matched and target["category"] == item["category"]]
        if candidates:
            score,index = max(candidates)
            if score >= threshold:
                matched.add(index)
                hits += 1
    return dict(true_positive=hits, false_positive=len(predictions)-hits, false_negative=len(truth)-hits,
                precision=hits/len(predictions) if predictions else None,
                recall=hits/len(truth) if truth else None, iou_threshold=threshold,
                note="Kết quả chỉ có ý nghĩa trên đúng vùng và danh mục đã được người dùng gán nhãn.")
