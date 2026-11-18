import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export const CAD_PALETTE = [
  { color: '#00d992', fill: 'rgba(0, 217, 146, 0.16)', hatch: 'diag45', name: 'Emerald Signal' },
  { color: '#ffba00', fill: 'rgba(255, 186, 0, 0.16)', hatch: 'diag135', name: 'Amber CAD' },
  { color: '#4cb3d4', fill: 'rgba(76, 179, 212, 0.16)', hatch: 'cross', name: 'Teal CAD' },
  { color: '#fb565b', fill: 'rgba(251, 86, 91, 0.16)', hatch: 'horiz_diag', name: 'Coral CAD' },
  { color: '#818cf8', fill: 'rgba(129, 140, 248, 0.16)', hatch: 'vert_diag', name: 'Indigo CAD' },
  { color: '#2fd6a1', fill: 'rgba(47, 214, 161, 0.16)', hatch: 'grid', name: 'Mint CAD' },
];

function pointInPoly2D(px, py, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0], yi = poly[i][1];
    const xj = poly[j][0], yj = poly[j][1];
    if (((yi > py) !== (yj > py)) && (px < (xj - xi) * (py - yi) / ((yj - yi) || 1e-9) + xi)) {
      inside = !inside;
    }
  }
  return inside;
}

function polyIntersectsTile(poly, tile) {
  const left = tile.col, top = tile.row, right = tile.col + tile.width, bottom = tile.row + tile.height;
  for (const [vx, vy] of poly) {
    if (vx >= left && vx <= right && vy >= top && vy <= bottom) return true;
  }
  const corners = [[left, top], [right, top], [right, bottom], [left, bottom], [(left + right) / 2, (top + bottom) / 2]];
  for (const [cx, cy] of corners) {
    if (pointInPoly2D(cx, cy, poly)) return true;
  }
  return false;
}

function formatTileId(id) {
  return String(id || '').replace(/\btile_/gi, 'Ảnh ');
}

/** A north-up, orthographic overview with an interactive CAD Polyline/Polygon & Live Progress Hatch overlay. */
export function createViewport(container, { onSelect = () => {}, onStatus = () => {} } = {}) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#080a09');
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 1000);
  camera.position.set(0, 0, 100);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const canvas = renderer.domElement;
  canvas.tabIndex = 0;
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', 'Ảnh tổng quan và lưới ảnh. Kéo để di chuyển, cuộn để thu phóng; phím mũi tên để di chuyển, cộng và trừ để thu phóng, phím 0 để vừa khung.');
  canvas.style.display = 'block';
  canvas.style.width = '100%';
  canvas.style.height = '100%';
  canvas.style.touchAction = 'none';
  container.appendChild(canvas);

  // 2D CAD overlay canvas for Polyline drawing, Hatching, Vertex Grips, Region Badges, and Live Progress
  const overlayCanvas = document.createElement('canvas');
  overlayCanvas.className = 'cad-overlay-canvas';
  overlayCanvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:2;';
  container.appendChild(overlayCanvas);
  const ctx2d = overlayCanvas.getContext('2d');

  const controls = new OrbitControls(camera, canvas);
  controls.enableRotate = false;
  controls.enableDamping = false;
  controls.screenSpacePanning = true;
  controls.minZoom = 0.2;
  controls.maxZoom = 80;
  controls.zoomSpeed = 0.85;
  controls.mouseButtons.LEFT = THREE.MOUSE.PAN;
  controls.mouseButtons.MIDDLE = THREE.MOUSE.PAN;
  controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
  controls.touches.ONE = THREE.TOUCH.PAN;
  controls.touches.TWO = THREE.TOUCH.DOLLY_PAN;

  const rasterGroup = new THREE.Group();
  const gridGroup = new THREE.Group();
  const selectedGroup = new THREE.Group();
  scene.add(rasterGroup, gridGroup, selectedGroup);
  let metadata = null;
  let sourceMesh = null;
  let plan = null;
  let scaleX = 1;
  let scaleY = 1;
  let worldWidth = 1000;
  let worldHeight = 700;
  let frustumHeight = 800;
  let disposed = false;
  let loadVersion = 0;
  let pointerDown = null;

  // CAD Multi-Region & Live Progress / Review Spotlight state
  let cadRegions = [];
  let selectedRegionIndex = -1;
  let cadMode = 'none'; // 'none' | 'draw_pline' | 'draw_rect' | 'edit'
  let draftPoints = [];
  let hoverImagePt = null;
  let hoveredGrip = null; // { type: 'vertex' | 'midpoint', regionIndex, vertexIndex }
  let draggingGrip = null; // { regionIndex, vertexIndex }
  let activeTileObj = null;
  let tilePulseStart = 0;
  let activeDetectionRecord = null;
  let allDetectionRecords = [];
  let selectedDetectionId = null;
  let boxesVisible = true;
  let terrainVectors = [];
  let mapScale = 500;
  let jobProgressState = null;
  let lastFollowedKey = '';
  let cadCallbacks = {
    onRegionsChange: () => {},
    onFinishDraft: () => {},
    onModeChange: () => {},
  };

  function x(col) { return (col - metadata.width / 2) * scaleX; }
  function y(row) { return (metadata.height / 2 - row) * scaleY; }

  function imageToScreen(col, row) {
    if (!metadata) return [0, 0];
    const { width, height } = dimensions();
    const v = new THREE.Vector3(x(col), y(row), 0).project(camera);
    return [(v.x * 0.5 + 0.5) * width, (-v.y * 0.5 + 0.5) * height];
  }

  function screenToImage(clientX, clientY) {
    if (!metadata) return null;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const ndcX = ((clientX - rect.left) / rect.width) * 2 - 1;
    const ndcY = -((clientY - rect.top) / rect.height) * 2 + 1;
    const v = new THREE.Vector3(ndcX, ndcY, 0).unproject(camera);
    const col = Math.max(0, Math.min(metadata.width, v.x / scaleX + metadata.width / 2));
    const row = Math.max(0, Math.min(metadata.height, metadata.height / 2 - v.y / scaleY));
    return [Math.round(col * 10) / 10, Math.round(row * 10) / 10];
  }

  function countIntersectingTiles(poly) {
    if (!plan?.tiles?.length || !poly || poly.length < 3) return 0;
    let count = 0;
    for (const tile of plan.tiles) {
      if (polyIntersectsTile(poly, tile)) count++;
    }
    return count;
  }

  function drawHatchFill(screenPts, style, isSelected) {
    if (screenPts.length < 3) return;
    ctx2d.save();
    ctx2d.beginPath();
    screenPts.forEach(([sx, sy], i) => {
      if (i === 0) ctx2d.moveTo(sx, sy);
      else ctx2d.lineTo(sx, sy);
    });
    ctx2d.closePath();
    ctx2d.fillStyle = style.fill;
    ctx2d.fill();
    if (isSelected) {
      ctx2d.fillStyle = 'rgba(0, 217, 146, 0.08)';
      ctx2d.fill();
    }
    ctx2d.clip();

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const [sx, sy] of screenPts) {
      if (sx < minX) minX = sx;
      if (sy < minY) minY = sy;
      if (sx > maxX) maxX = sx;
      if (sy > maxY) maxY = sy;
    }
    const span = Math.max(maxX - minX, maxY - minY) + 32;
    const step = 10;
    ctx2d.strokeStyle = style.color;
    ctx2d.globalAlpha = isSelected ? 0.72 : 0.48;
    ctx2d.lineWidth = isSelected ? 1.4 : 1.0;
    ctx2d.beginPath();

    const mode = style.hatch || 'diag45';
    if (mode === 'diag45' || mode === 'cross' || mode === 'horiz_diag') {
      for (let d = -span; d <= span * 2; d += step) {
        ctx2d.moveTo(minX + d, minY - 8);
        ctx2d.lineTo(minX + d - span, minY + span + 8);
      }
    }
    if (mode === 'diag135' || mode === 'cross' || mode === 'vert_diag') {
      for (let d = -span; d <= span * 2; d += step) {
        ctx2d.moveTo(minX + d, minY - 8);
        ctx2d.lineTo(minX + d + span, minY + span + 8);
      }
    }
    if (mode === 'horiz_diag' || mode === 'grid') {
      for (let yPos = minY; yPos <= maxY; yPos += step * 1.3) {
        ctx2d.moveTo(minX - 8, yPos);
        ctx2d.lineTo(maxX + 8, yPos);
      }
    }
    if (mode === 'vert_diag' || mode === 'grid') {
      for (let xPos = minX; xPos <= maxX; xPos += step * 1.3) {
        ctx2d.moveTo(xPos, minY - 8);
        ctx2d.lineTo(xPos, maxY + 8);
      }
    }
    ctx2d.stroke();
    ctx2d.restore();
  }

  function renderCadOverlay() {
    if (!ctx2d || disposed) return;
    const { width, height } = dimensions();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (overlayCanvas.width !== Math.round(width * dpr) || overlayCanvas.height !== Math.round(height * dpr)) {
      overlayCanvas.width = Math.round(width * dpr);
      overlayCanvas.height = Math.round(height * dpr);
    }
    ctx2d.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx2d.clearRect(0, 0, width, height);
    if (!metadata) return;

    // 1. Render existing closed CAD regions
    cadRegions.forEach((region, rIdx) => {
      const poly = region.polygon;
      if (!poly || poly.length < 3) return;
      const palette = CAD_PALETTE[rIdx % CAD_PALETTE.length];
      const style = {
        color: region.color || palette.color,
        fill: palette.fill,
        hatch: region.hatch || palette.hatch,
      };
      const isSelected = rIdx === selectedRegionIndex;
      const screenPts = poly.map(([c, r]) => imageToScreen(c, r));

      drawHatchFill(screenPts, style, isSelected);

      // Outline
      ctx2d.save();
      ctx2d.beginPath();
      screenPts.forEach(([sx, sy], i) => {
        if (i === 0) ctx2d.moveTo(sx, sy);
        else ctx2d.lineTo(sx, sy);
      });
      ctx2d.closePath();
      if (isSelected) {
        ctx2d.strokeStyle = '#ffffff';
        ctx2d.lineWidth = 4.2;
        ctx2d.stroke();
      }
      ctx2d.strokeStyle = style.color;
      ctx2d.lineWidth = isSelected ? 2.6 : 2.0;
      ctx2d.stroke();
      ctx2d.restore();

      // Midpoint Grips (+) for inserting a new vertex
      for (let i = 0; i < screenPts.length; i++) {
        const p1 = screenPts[i];
        const p2 = screenPts[(i + 1) % screenPts.length];
        const mx = (p1[0] + p2[0]) * 0.5;
        const my = (p1[1] + p2[1]) * 0.5;
        const isMidHover = hoveredGrip?.type === 'midpoint' && hoveredGrip.regionIndex === rIdx && hoveredGrip.vertexIndex === i;
        ctx2d.save();
        ctx2d.fillStyle = isMidHover ? '#ffba00' : '#00d992';
        ctx2d.strokeStyle = '#050507';
        ctx2d.lineWidth = 1.2;
        const sz = isMidHover ? 4.5 : 3.2;
        ctx2d.fillRect(mx - sz, my - sz, sz * 2, sz * 2);
        ctx2d.strokeRect(mx - sz, my - sz, sz * 2, sz * 2);
        ctx2d.restore();
      }

      // Vertex Grips (□) for dragging vertices
      screenPts.forEach(([sx, sy], vIdx) => {
        const isHot = (hoveredGrip?.type === 'vertex' && hoveredGrip.regionIndex === rIdx && hoveredGrip.vertexIndex === vIdx)
          || (draggingGrip && draggingGrip.regionIndex === rIdx && draggingGrip.vertexIndex === vIdx);
        const sz = isHot ? 5.5 : (isSelected ? 4.5 : 3.8);
        ctx2d.save();
        ctx2d.fillStyle = isHot ? '#fb565b' : (isSelected ? '#ffba00' : '#f2f2f2');
        ctx2d.strokeStyle = isHot ? '#ffffff' : style.color;
        ctx2d.lineWidth = 2;
        ctx2d.fillRect(sx - sz, sy - sz, sz * 2, sz * 2);
        ctx2d.strokeRect(sx - sz, sy - sz, sz * 2, sz * 2);
        ctx2d.restore();
      });

      // Region Numbered Badge & Categories at centroid
      let cx = 0, cy = 0;
      for (const [sx, sy] of screenPts) { cx += sx; cy += sy; }
      cx /= screenPts.length;
      cy /= screenPts.length;
      const tileCount = region.tile_count || countIntersectingTiles(poly);
      const titleText = `${region.name || ('VÙNG ' + (rIdx + 1))}${tileCount ? ` · ${tileCount} ảnh` : ''}`;
      const catText = (region.categories || []).slice(0, 3).join(', ') + ((region.categories?.length > 3) ? '…' : '');

      ctx2d.save();
      ctx2d.font = 'bold 11.5px SFMono-Regular, Consolas, monospace';
      const w1 = ctx2d.measureText(titleText).width;
      ctx2d.font = '10.5px Inter, sans-serif';
      const w2 = catText ? ctx2d.measureText(catText).width : 0;
      const boxW = Math.max(w1, w2) + 18;
      const boxH = catText ? 34 : 22;

      ctx2d.fillStyle = 'rgba(5, 5, 7, 0.90)';
      ctx2d.strokeStyle = style.color;
      ctx2d.lineWidth = isSelected ? 2 : 1.4;
      ctx2d.beginPath();
      ctx2d.roundRect(cx - boxW / 2, cy - boxH / 2, boxW, boxH, 5);
      ctx2d.fill();
      ctx2d.stroke();

      ctx2d.fillStyle = style.color;
      ctx2d.font = 'bold 11.5px SFMono-Regular, Consolas, monospace';
      ctx2d.textAlign = 'center';
      ctx2d.textBaseline = 'middle';
      ctx2d.fillText(titleText, cx, catText ? cy - 6 : cy);
      if (catText) {
        ctx2d.fillStyle = '#f2f2f2';
        ctx2d.font = '10.5px Inter, sans-serif';
        ctx2d.fillText(catText, cx, cy + 8);
      }
      ctx2d.restore();
    });

    // 2. Render active CAD Polyline / Rectangle draft
    if (draftPoints.length > 0) {
      const nextPalette = CAD_PALETTE[cadRegions.length % CAD_PALETTE.length];
      let previewPts = [...draftPoints];
      if (cadMode === 'draw_rect' && draftPoints.length === 1 && hoverImagePt) {
        const [c1, r1] = draftPoints[0];
        const [c2, r2] = hoverImagePt;
        previewPts = [[c1, r1], [c2, r1], [c2, r2], [c1, r2]];
      } else if (hoverImagePt) {
        previewPts = [...draftPoints, hoverImagePt];
      }
      const screenDraft = previewPts.map(([c, r]) => imageToScreen(c, r));
      if (screenDraft.length >= 3) {
        drawHatchFill(screenDraft, nextPalette, true);
      }
      ctx2d.save();
      ctx2d.beginPath();
      screenDraft.forEach(([sx, sy], i) => {
        if (i === 0) ctx2d.moveTo(sx, sy);
        else ctx2d.lineTo(sx, sy);
      });
      if (cadMode === 'draw_rect' && screenDraft.length === 4) ctx2d.closePath();
      ctx2d.strokeStyle = nextPalette.color;
      ctx2d.lineWidth = 2.2;
      ctx2d.stroke();

      // Dashed closing line back to vertex 0 for Polyline
      if (cadMode === 'draw_pline' && screenDraft.length >= 3) {
        ctx2d.beginPath();
        ctx2d.setLineDash([5, 5]);
        const lastPt = screenDraft[screenDraft.length - 1];
        const firstPt = screenDraft[0];
        ctx2d.moveTo(lastPt[0], lastPt[1]);
        ctx2d.lineTo(firstPt[0], firstPt[1]);
        ctx2d.strokeStyle = '#ffba00';
        ctx2d.lineWidth = 1.5;
        ctx2d.stroke();
      }
      ctx2d.restore();

      // Draw placed vertices of draft
      draftPoints.forEach(([c, r], idx) => {
        const [sx, sy] = imageToScreen(c, r);
        ctx2d.save();
        ctx2d.fillStyle = idx === 0 ? '#ffba00' : '#f2f2f2';
        ctx2d.strokeStyle = nextPalette.color;
        ctx2d.lineWidth = 2;
        const sz = idx === 0 ? 5.5 : 4;
        ctx2d.fillRect(sx - sz, sy - sz, sz * 2, sz * 2);
        ctx2d.strokeRect(sx - sz, sy - sz, sz * 2, sz * 2);
        ctx2d.restore();
      });
    }

    // 3. Render Live Job Progress Hatch (Export Tiles & Detection Windows/Regions)
    if (jobProgressState && metadata) {
      const jp = jobProgressState;
      // 3a. Tile Export progress hatching
      if (!jp.kind && plan?.tiles?.length && jp.done > 0) {
        const doneCount = Math.min(jp.done, plan.tiles.length, 2000);
        for (let i = 0; i < doneCount; i++) {
          const t = plan.tiles[i];
          const pts = [
            imageToScreen(t.col, t.row),
            imageToScreen(t.col + t.width, t.row),
            imageToScreen(t.col + t.width, t.row + t.height),
            imageToScreen(t.col, t.row + t.height),
          ];
          drawHatchFill(pts, { color: '#00d992', fill: 'rgba(0, 217, 146, 0.14)', hatch: 'diag45' }, false);
        }
        if (jp.status === 'running' && jp.done < plan.tiles.length) {
          const act = plan.tiles[jp.done];
          if (act) {
            const pts = [
              imageToScreen(act.col, act.row),
              imageToScreen(act.col + act.width, act.row),
              imageToScreen(act.col + act.width, act.row + act.height),
              imageToScreen(act.col, act.row + act.height),
            ];
            drawHatchFill(pts, { color: '#ffba00', fill: 'rgba(255, 186, 0, 0.22)', hatch: 'cross' }, true);
            ctx2d.save();
            ctx2d.strokeStyle = '#ffba00';
            ctx2d.lineWidth = 2.4;
            ctx2d.strokeRect(pts[0][0], pts[0][1], pts[2][0] - pts[0][0], pts[2][1] - pts[0][1]);
            ctx2d.restore();
          }
        }
      }

      // 3b. Detection regions & micro-windows live hatching
      if (jp.kind === 'detection') {
        const completedSet = new Set(jp.completed_regions || []);
        const jobRegions = jp.regions || jp.request?.regions || [];
        const isJobCompleted = jp.status === 'completed' || ((jp.total || 0) > 0 && (jp.done || 0) >= (jp.total || 0));
        jobRegions.forEach((reg, idx) => {
          const rIdx = reg.region_index || (idx + 1);
          const poly = reg.polygon;
          if (!poly || poly.length < 3) return;
          const isDone = completedSet.has(rIdx) || isJobCompleted;
          const isRunning = jp.status === 'running' && jp.active_region_index === rIdx;
          if (!isDone && !isRunning) return;
          const screenPts = poly.map(([c, r]) => imageToScreen(c, r));
          const style = isDone
            ? { color: '#00d992', fill: 'rgba(0, 217, 146, 0.16)', hatch: 'diag45' }
            : { color: '#ffba00', fill: 'rgba(255, 186, 0, 0.16)', hatch: 'cross' };
          drawHatchFill(screenPts, style, isRunning);
          ctx2d.save();
          ctx2d.beginPath();
          screenPts.forEach(([sx, sy], i) => { if (i === 0) ctx2d.moveTo(sx, sy); else ctx2d.lineTo(sx, sy); });
          ctx2d.closePath();
          ctx2d.strokeStyle = style.color;
          ctx2d.lineWidth = isRunning ? 2.6 : 2.2;
          ctx2d.stroke();
          ctx2d.restore();
        });

        // If whole-image / single-region detection completed without polygon regions, hatch its bounding region uniformly
        if (isJobCompleted && jobRegions.length === 0 && jp.region && jp.region.width > 0 && jp.region.height > 0) {
          const rg = jp.region;
          const rPts = [
            imageToScreen(rg.col, rg.row),
            imageToScreen(rg.col + rg.width, rg.row),
            imageToScreen(rg.col + rg.width, rg.row + rg.height),
            imageToScreen(rg.col, rg.row + rg.height),
          ];
          drawHatchFill(rPts, { color: '#00d992', fill: 'rgba(0, 217, 146, 0.14)', hatch: 'diag45' }, false);
        }

        // Only draw individual live scanned micro-windows while job/region is still in progress (never draw a truncated tail over a 100% completed region)
        if (!isJobCompleted) {
          const scanned = jp.scanned_windows || [];
          for (const w of scanned) {
            const [wc, wr, ww, wh, wRegIdx] = w;
            if (wRegIdx && completedSet.has(wRegIdx)) continue;
            const pts = [
              imageToScreen(wc, wr),
              imageToScreen(wc + ww, wr),
              imageToScreen(wc + ww, wr + wh),
              imageToScreen(wc, wr + wh),
            ];
            drawHatchFill(pts, { color: '#00d992', fill: 'rgba(0, 217, 146, 0.16)', hatch: 'diag45' }, false);
            ctx2d.save();
            ctx2d.strokeStyle = 'rgba(0, 217, 146, 0.55)';
            ctx2d.lineWidth = 1;
            ctx2d.strokeRect(pts[0][0], pts[0][1], pts[2][0] - pts[0][0], pts[2][1] - pts[0][1]);
            ctx2d.restore();
          }
        }

        if (jp.status === 'running' && jp.active_window) {
          const aw = jp.active_window;
          const pts = [
            imageToScreen(aw.col, aw.row),
            imageToScreen(aw.col + aw.width, aw.row),
            imageToScreen(aw.col + aw.width, aw.row + aw.height),
            imageToScreen(aw.col, aw.row + aw.height),
          ];
          drawHatchFill(pts, { color: '#ffba00', fill: 'rgba(255, 186, 0, 0.24)', hatch: 'cross' }, true);
          ctx2d.save();
          ctx2d.strokeStyle = '#00d992';
          ctx2d.lineWidth = 2.5;
          const rx = pts[0][0], ry = pts[0][1], rw = pts[2][0] - pts[0][0], rh = pts[2][1] - pts[0][1];
          ctx2d.strokeRect(rx, ry, rw, rh);
          const label = `⚡ ${formatTileId(aw.region_name || 'Đang quét')} · ${formatTileId(aw.tile_id || '')}`;
          ctx2d.font = 'bold 11px SFMono-Regular, Consolas, monospace';
          const tw = ctx2d.measureText(label).width + 14;
          ctx2d.fillStyle = 'rgba(5, 5, 7, 0.92)';
          ctx2d.strokeStyle = '#00d992';
          ctx2d.lineWidth = 1.4;
          ctx2d.beginPath();
          ctx2d.roundRect(rx + rw / 2 - tw / 2, Math.max(8, ry - 24), tw, 20, 4);
          ctx2d.fill();
          ctx2d.stroke();
          ctx2d.fillStyle = '#00d992';
          ctx2d.textAlign = 'center';
          ctx2d.textBaseline = 'middle';
          ctx2d.fillText(label, rx + rw / 2, Math.max(18, ry - 14));
          ctx2d.restore();
        }
      }
    }

    // 4. Render Selected Tile Spotlight & Pulse Ring
    if (activeTileObj && metadata) {
      const t = activeTileObj;
      const pTL = imageToScreen(t.col, t.row);
      const pBR = imageToScreen(t.col + t.width, t.row + t.height);
      const rx = pTL[0], ry = pTL[1], rw = pBR[0] - pTL[0], rh = pBR[1] - pTL[1];
      const pts = [pTL, [pBR[0], pTL[1]], pBR, [pTL[0], pBR[1]]];
      drawHatchFill(pts, { color: '#00d992', fill: 'rgba(0, 217, 146, 0.12)', hatch: 'diag135' }, true);

      ctx2d.save();
      ctx2d.strokeStyle = '#00d992';
      ctx2d.lineWidth = 2.2;
      ctx2d.strokeRect(rx, ry, rw, rh);

      // Corner target brackets
      const brk = Math.max(6, Math.min(16, Math.min(Math.abs(rw), Math.abs(rh)) * 0.25));
      ctx2d.strokeStyle = '#2fd6a1';
      ctx2d.lineWidth = 3;
      ctx2d.beginPath();
      ctx2d.moveTo(rx, ry + brk); ctx2d.lineTo(rx, ry); ctx2d.lineTo(rx + brk, ry);
      ctx2d.moveTo(rx + rw - brk, ry); ctx2d.lineTo(rx + rw, ry); ctx2d.lineTo(rx + rw, ry + brk);
      ctx2d.moveTo(rx + rw, ry + rh - brk); ctx2d.lineTo(rx + rw, ry + rh); ctx2d.lineTo(rx + rw - brk, ry + rh);
      ctx2d.moveTo(rx + brk, ry + rh); ctx2d.lineTo(rx, ry + rh); ctx2d.lineTo(rx, ry + rh - brk);
      ctx2d.stroke();

      // Expanding pulse ring when freshly selected
      const elapsed = performance.now() - tilePulseStart;
      if (elapsed < 700) {
        const p = elapsed / 700;
        const pad = p * 22;
        ctx2d.strokeStyle = `rgba(0, 217, 146, ${(1 - p) * 0.85})`;
        ctx2d.lineWidth = 2.5 * (1 - p);
        ctx2d.strokeRect(rx - pad, ry - pad, rw + pad * 2, rh + pad * 2);
        requestAnimationFrame(() => { if (!disposed) renderCadOverlay(); });
      }

      // Tile ID pill badge
      const badge = `🎯 ${formatTileId(t.id)}`;
      ctx2d.font = 'bold 11px SFMono-Regular, Consolas, monospace';
      const bw = ctx2d.measureText(badge).width + 12;
      const bx = rx + rw / 2 - bw / 2;
      const by = Math.max(6, ry - 22);
      ctx2d.fillStyle = 'rgba(5, 5, 7, 0.92)';
      ctx2d.strokeStyle = '#00d992';
      ctx2d.lineWidth = 1.3;
      ctx2d.beginPath();
      ctx2d.roundRect(bx, by, bw, 18, 4);
      ctx2d.fill();
      ctx2d.stroke();
      ctx2d.fillStyle = '#2fd6a1';
      ctx2d.textAlign = 'center';
      ctx2d.textBaseline = 'middle';
      ctx2d.fillText(badge, rx + rw / 2, by + 9);
      ctx2d.restore();
    }

    // 5. Render All Detection Boxes Across Entire Region (Batched Path2D for 60 FPS with 1,300+ objects)
    if (boxesVisible && metadata && allDetectionRecords.length > 0) {
      const selId = activeDetectionRecord?.id || selectedDetectionId;
      const acceptedPath = new Path2D();
      const unreviewedPath = new Path2D();
      const rejectedPath = new Path2D();
      let hasAccepted = false, hasUnreviewed = false, hasRejected = false;
      const viewW = overlayCanvas.clientWidth || 1200;
      const viewH = overlayCanvas.clientHeight || 800;

      for (const rec of allDetectionRecords) {
        if (!rec || !Array.isArray(rec.box) || rec.box.length !== 4) continue;
        if (rec.id && rec.id === selId) continue;
        const box = (rec.review_status === 'accepted_candidate' && Array.isArray(rec.candidate_box) && rec.candidate_box.length === 4)
          ? rec.candidate_box
          : rec.box;
        const [x1, y1, x2, y2] = box;
        const p1 = imageToScreen(x1, y1);
        const p2 = imageToScreen(x2, y2);
        const bx = p1[0], by = p1[1];
        const bw = Math.max(4, p2[0] - p1[0]), bh = Math.max(4, p2[1] - p1[1]);
        if (bx + bw < -20 || by + bh < -20 || bx > viewW + 20 || by > viewH + 20) continue;

        if (rec.review_status === 'rejected') {
          rejectedPath.rect(bx, by, bw, bh);
          hasRejected = true;
        } else if (rec.review_status === 'accepted_raw' || rec.review_status === 'accepted_candidate') {
          acceptedPath.rect(bx, by, bw, bh);
          hasAccepted = true;
        } else {
          unreviewedPath.rect(bx, by, bw, bh);
          hasUnreviewed = true;
        }
      }

      ctx2d.save();
      if (hasRejected) {
        ctx2d.strokeStyle = 'rgba(251, 86, 91, 0.45)';
        ctx2d.lineWidth = 1.0;
        ctx2d.stroke(rejectedPath);
      }
      if (hasAccepted) {
        ctx2d.fillStyle = 'rgba(0, 217, 146, 0.16)';
        ctx2d.strokeStyle = '#00d992';
        ctx2d.lineWidth = 1.5;
        ctx2d.fill(acceptedPath);
        ctx2d.stroke(acceptedPath);
      }
      if (hasUnreviewed) {
        ctx2d.fillStyle = 'rgba(255, 173, 51, 0.16)';
        ctx2d.strokeStyle = '#ffad33';
        ctx2d.lineWidth = 1.5;
        ctx2d.fill(unreviewedPath);
        ctx2d.stroke(unreviewedPath);
      }
      ctx2d.restore();
    }

    if (boxesVisible && activeDetectionRecord && metadata) {
      const rec = activeDetectionRecord;
      if (rec.window) {
        const w = rec.window;
        const wPts = [
          imageToScreen(w.col, w.row),
          imageToScreen(w.col + w.width, w.row),
          imageToScreen(w.col + w.width, w.row + w.height),
          imageToScreen(w.col, w.row + w.height),
        ];
        drawHatchFill(wPts, { color: '#2fd6a1', fill: 'rgba(47, 214, 161, 0.12)', hatch: 'diag45' }, false);
      }
      const box = (rec.review_status === 'accepted_candidate' && Array.isArray(rec.candidate_box) && rec.candidate_box.length === 4)
        ? rec.candidate_box
        : rec.box;
      if (Array.isArray(box) && box.length === 4) {
        const [x1, y1, x2, y2] = box;
        const p1 = imageToScreen(x1, y1);
        const p2 = imageToScreen(x2, y2);
        const bx = p1[0], by = p1[1], bw = Math.max(8, p2[0] - p1[0]), bh = Math.max(8, p2[1] - p1[1]);
        const cx = bx + bw / 2, cy = by + bh / 2;

        ctx2d.save();
        ctx2d.strokeStyle = '#00d992';
        ctx2d.lineWidth = 2.2;
        ctx2d.beginPath();
        ctx2d.arc(cx, cy, Math.max(14, Math.hypot(bw, bh) * 0.75), 0, Math.PI * 2);
        ctx2d.stroke();

        ctx2d.fillStyle = 'rgba(255, 186, 0, 0.18)';
        ctx2d.fillRect(bx - 2, by - 2, bw + 4, bh + 4);
        ctx2d.strokeStyle = '#ffba00';
        ctx2d.lineWidth = 2.6;
        ctx2d.strokeRect(bx - 2, by - 2, bw + 4, bh + 4);

        const tag = `${rec.id} · ${rec.sub_class || rec.category}`;
        ctx2d.font = 'bold 11.5px SFMono-Regular, Consolas, monospace';
        const tw = ctx2d.measureText(tag).width + 14;
        ctx2d.fillStyle = 'rgba(5, 5, 7, 0.92)';
        ctx2d.strokeStyle = '#00d992';
        ctx2d.lineWidth = 1.4;
        ctx2d.beginPath();
        ctx2d.roundRect(cx - tw / 2, Math.max(6, by - 26), tw, 20, 4);
        ctx2d.fill();
        ctx2d.stroke();
        ctx2d.fillStyle = '#00d992';
        ctx2d.textAlign = 'center';
        ctx2d.textBaseline = 'middle';
        ctx2d.fillText(tag, cx, Math.max(16, by - 16));
        ctx2d.restore();
      }
    }

    // 6. Render 9-Class Terrain & Corridor Survey Vectors (2-Edge Roads, Centerline, Ponds, Masonry Ditches, Buildings, Vegetation Blocks)
    if (metadata && Array.isArray(terrainVectors) && terrainVectors.length > 0) {
      const kScale = Math.max(0.5, (Number(mapScale) || 500) / 500);
      const styleMap = {
        asphalt_road: { color: '#ef4444', dashed: false, center: true },
        concrete_road: { color: '#94a3b8', dashed: false, center: true },
        dirt_road: { color: '#d97706', dashed: true, center: false },
        footpath: { color: '#a855f7', dashed: true, center: false },
        pond: { color: '#0ea5e9', dashed: false, center: false },
        masonry_ditch: { color: '#06b6d4', dashed: false, center: false },
        house_building: { color: '#fb7185', dashed: false, center: false },
        landscape_tree: { color: '#22c55e', dashed: false, center: false },
      };
      const drawScreenChain = (pts, closed = false) => {
        if (!Array.isArray(pts) || pts.length < 2) return;
        ctx2d.beginPath();
        pts.forEach(([c, r], idx) => {
          const [sx, sy] = imageToScreen(c, r);
          if (idx === 0) ctx2d.moveTo(sx, sy);
          else ctx2d.lineTo(sx, sy);
        });
        if (closed) ctx2d.closePath();
        ctx2d.stroke();
      };

      const drawCadVegetationPattern = (feat) => {
        const polyPx = feat.zone_boundary_px || feat.polygon_px;
        if (Array.isArray(polyPx) && polyPx.length >= 3) {
          ctx2d.save();
          ctx2d.strokeStyle = '#22c55e';
          ctx2d.lineWidth = 1.8;
          ctx2d.setLineDash([7 * Math.min(2.2, Math.sqrt(kScale)), 4 * Math.min(2.2, Math.sqrt(kScale))]);
          drawScreenChain(polyPx, true);
          ctx2d.restore();
        }
        const centerPx = feat.center_px || feat.centerPx;
        if (Array.isArray(centerPx) && centerPx.length >= 2) {
          // If part of a uniform grid, filter out rows/cols when kScale > 1 so grid spacing scales by k
          const rc = feat.grid_rc || feat.gridRC;
          const stride = Math.max(1, Math.round(kScale));
          if (Array.isArray(rc) && stride > 1 && (rc[0] % stride !== 0 || rc[1] % stride !== 0)) {
            return;
          }
          const [sx, sy] = imageToScreen(centerPx[0], centerPx[1]);
          const baseRPx = Number(feat.radius_px || feat.radiusPx || 7);
          const [sxR] = imageToScreen(centerPx[0] + baseRPx * kScale, centerPx[1]);
          const symRadius = Math.max(4, Math.min(48, Math.abs(sxR - sx) || 6 * Math.sqrt(kScale)));
          const srcBlk = String(feat.source_block || feat.sourceBlock || feat.block_name || feat.blockName || 'cumcay2').toLowerCase();
          ctx2d.save();
          ctx2d.strokeStyle = '#22c55e';
          ctx2d.lineWidth = 1.65;
          ctx2d.setLineDash([]);
          ctx2d.beginPath();
          if (srcBlk === 'cothap' || srcBlk === 'cocao') {
            const hB = srcBlk === 'cocao' ? symRadius * 0.62 : symRadius * 0.45;
            ctx2d.moveTo(sx - symRadius * 0.34, sy - hB);
            ctx2d.lineTo(sx, sy);
            ctx2d.lineTo(sx + symRadius * 0.34, sy - hB);
            ctx2d.moveTo(sx, sy);
            ctx2d.lineTo(sx, sy - hB * 1.15);
          } else if (srcBlk === 'hoa') {
            const pR = symRadius * 0.42;
            ctx2d.arc(sx, sy, pR * 0.45, 0, Math.PI * 2);
            for (let a = 0; a < 5; a++) {
              const ang = (a * Math.PI * 2) / 5;
              const px = sx + Math.cos(ang) * pR;
              const py = sy + Math.sin(ang) * pR;
              ctx2d.moveTo(px + pR * 0.35, py);
              ctx2d.arc(px, py, pR * 0.35, 0, Math.PI * 2);
            }
          } else {
            ctx2d.arc(sx, sy, symRadius, 0, Math.PI * 2);
            ctx2d.moveTo(sx - symRadius * 0.45, sy);
            ctx2d.lineTo(sx + symRadius * 0.45, sy);
            ctx2d.moveTo(sx, sy - symRadius * 0.45);
            ctx2d.lineTo(sx, sy + symRadius * 0.45);
          }
          ctx2d.stroke();
          ctx2d.restore();
        } else if (Array.isArray(polyPx) && polyPx.length >= 3) {
          // Fill polygon with uniform 2D vegetation block grid (caylato, cumcay2, cothap, cocao, hoa) spaced by stepPx * kScale
          const sPts = polyPx.map(([c, r]) => imageToScreen(c, r));
          let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
          for (const [sx, sy] of sPts) {
            if (sx < minX) minX = sx;
            if (sy < minY) minY = sy;
            if (sx > maxX) maxX = sx;
            if (sy > maxY) maxY = sy;
          }
          const stepPx = Math.max(18, 26 * kScale);
          const symRadius = Math.max(4, 5.5 * Math.min(2.8, Math.sqrt(kScale)));
          ctx2d.save();
          ctx2d.strokeStyle = '#22c55e';
          ctx2d.lineWidth = 1.5;
          ctx2d.setLineDash([]);
          let rIdx = 0;
          for (let gy = minY + stepPx * 0.5; gy <= maxY - 4; gy += stepPx, rIdx++) {
            let cIdx = 0;
            for (let gx = minX + stepPx * 0.5; gx <= maxX - 4; gx += stepPx, cIdx++) {
              if (!pointInPoly2D(gx, gy, sPts)) continue;
              const pat = (rIdx + cIdx) % 4;
              ctx2d.beginPath();
              if (pat === 2) {
                const hB = symRadius * 0.52;
                ctx2d.moveTo(gx - symRadius * 0.34, gy - hB);
                ctx2d.lineTo(gx, gy);
                ctx2d.lineTo(gx + symRadius * 0.34, gy - hB);
              } else if (pat === 3) {
                ctx2d.arc(gx, gy, symRadius * 0.55, 0, Math.PI * 2);
              } else {
                ctx2d.arc(gx, gy, symRadius, 0, Math.PI * 2);
                ctx2d.moveTo(gx - symRadius * 0.4, gy);
                ctx2d.lineTo(gx + symRadius * 0.4, gy);
              }
              ctx2d.stroke();
            }
          }
          ctx2d.restore();
        }
      };

      for (const feat of terrainVectors) {
        const clsKey = feat.class_key || feat.classKey;
        const st = styleMap[clsKey] || { color: '#10b981', dashed: false, center: false };
        ctx2d.save();
        if (feat.geometry === 'BLOCK' || clsKey === 'landscape_tree') {
          drawCadVegetationPattern(feat);
        } else if (feat.geometry === 'POLYGON' && Array.isArray(feat.polygon_px) && feat.polygon_px.length >= 3) {
          const sPts = feat.polygon_px.map(([c, r]) => imageToScreen(c, r));
          ctx2d.beginPath();
          sPts.forEach(([sx, sy], idx) => {
            if (idx === 0) ctx2d.moveTo(sx, sy);
            else ctx2d.lineTo(sx, sy);
          });
          ctx2d.closePath();
          ctx2d.fillStyle = clsKey === 'house_building' ? 'rgba(251, 113, 133, 0.20)' : 'rgba(14, 165, 233, 0.20)';
          ctx2d.fill();
          ctx2d.strokeStyle = st.color;
          ctx2d.lineWidth = 2.2;
          ctx2d.stroke();

          if (clsKey === 'pond' && sPts.length >= 4) {
            let cx = 0, cy = 0;
            for (const [sx, sy] of sPts) { cx += sx; cy += sy; }
            cx /= sPts.length;
            cy /= sPts.length;
            const step = Math.max(1, Math.floor((sPts.length / 12) * Math.sqrt(kScale)));
            const tickLen = 7 * Math.min(2.2, Math.sqrt(kScale));
            ctx2d.beginPath();
            for (let i = 0; i < sPts.length; i += step) {
              const [px, py] = sPts[i];
              const vx = cx - px, vy = cy - py;
              const vl = Math.hypot(vx, vy) || 1;
              ctx2d.moveTo(px, py);
              ctx2d.lineTo(px + (vx / vl) * tickLen, py + (vy / vl) * tickLen);
            }
            ctx2d.stroke();
          }
        } else {
          ctx2d.strokeStyle = st.color;
          ctx2d.lineWidth = 2.1;
          ctx2d.setLineDash(st.dashed ? [7, 5] : []);
          drawScreenChain(feat.left_edge_px, false);
          drawScreenChain(feat.right_edge_px, false);
          if (st.center && Array.isArray(feat.centerline_px)) {
            ctx2d.strokeStyle = '#facc15';
            ctx2d.lineWidth = 1.4;
            ctx2d.setLineDash([10, 4, 2, 4]);
            drawScreenChain(feat.centerline_px, false);
          }
        }
        ctx2d.restore();
      }
    }
  }

  function render() {
    if (!disposed) {
      renderer.render(scene, camera);
      renderCadOverlay();
    }
  }

  function disposeGroup(group) {
    for (const child of [...group.children]) {
      child.geometry?.dispose();
      const materials = Array.isArray(child.material) ? child.material : [child.material];
      for (const material of materials) {
        material?.map?.dispose();
        material?.dispose();
      }
      group.remove(child);
    }
  }

  function dimensions() {
    return {
      width: Math.max(1, container.clientWidth),
      height: Math.max(1, container.clientHeight),
    };
  }

  function resize() {
    if (disposed) return;
    const { width, height } = dimensions();
    const aspect = width / height;
    camera.left = -frustumHeight * aspect / 2;
    camera.right = frustumHeight * aspect / 2;
    camera.top = frustumHeight / 2;
    camera.bottom = -frustumHeight / 2;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
    render();
  }

  function fit() {
    if (disposed) return;
    const { width, height } = dimensions();
    frustumHeight = Math.max(worldHeight, worldWidth / (width / height)) * 1.14;
    camera.zoom = 1;
    camera.position.set(0, 0, 100);
    controls.target.set(0, 0, 0);
    controls.update();
    resize();
  }

  function zoom(factor) {
    if (disposed || !Number.isFinite(factor) || factor <= 0) return;
    camera.zoom = THREE.MathUtils.clamp(camera.zoom * factor, controls.minZoom, controls.maxZoom);
    camera.updateProjectionMatrix();
    controls.update();
    render();
  }

  function addOutline(positions, col, row, width, height, depth) {
    const left = x(col), right = x(col + width), top = y(row), bottom = y(row + height);
    positions.push(left, top, depth, right, top, depth,
      right, top, depth, right, bottom, depth,
      right, bottom, depth, left, bottom, depth,
      left, bottom, depth, left, top, depth);
  }

  function addRect(positions, col, row, width, height, depth) {
    if (width <= 0 || height <= 0) return;
    const left = x(col), right = x(col + width), top = y(row), bottom = y(row + height);
    positions.push(left, top, depth, left, bottom, depth, right, top, depth,
      right, top, depth, left, bottom, depth, right, bottom, depth);
  }

  function geometry(positions) {
    const result = new THREE.BufferGeometry();
    result.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    return result;
  }

  function intersection(a, b, positions) {
    if (!b) return;
    const left = Math.max(a.col, b.col), top = Math.max(a.row, b.row);
    const right = Math.min(a.col + a.width, b.col + b.width);
    const bottom = Math.min(a.row + a.height, b.row + b.height);
    addRect(positions, left, top, right - left, bottom - top, 0.1);
  }

  function setPlan(nextPlan) {
    plan = nextPlan;
    disposeGroup(gridGroup);
    disposeGroup(selectedGroup);
    if (!metadata || !plan) { render(); return; }
    const tiles = plan.tiles.slice(0, 2000);
    const positions = [];
    const overlaps = [];
    const tileAt = new Map(tiles.map(tile => [`${tile.col},${tile.row}`, tile]));
    for (const tile of tiles) {
      addOutline(positions, tile.col, tile.row, tile.width, tile.height, 0.2);
      intersection(tile, tileAt.get(`${tile.col - plan.stride_x},${tile.row}`), overlaps);
      intersection(tile, tileAt.get(`${tile.col},${tile.row - plan.stride_y}`), overlaps);
    }
    if (overlaps.length) {
      const overlap = new THREE.Mesh(geometry(overlaps), new THREE.MeshBasicMaterial({
        color: '#2fd6a1', transparent: true, opacity: 0.14, depthWrite: false,
      }));
      overlap.renderOrder = 1;
      gridGroup.add(overlap);
    }
    if (positions.length) {
      const lines = new THREE.LineSegments(geometry(positions), new THREE.LineBasicMaterial({
        color: '#8b949e', transparent: true, opacity: 0.55,
      }));
      lines.renderOrder = 2;
      gridGroup.add(lines);
    }
    render();
  }

  function flyToRect(col, row, width, height, { paddingFactor = 2.8, duration = 340, minSpan = 90 } = {}) {
    if (disposed || !metadata) return;
    const cx = x(col + width * 0.5);
    const cy = y(row + height * 0.5);
    const spanW = Math.max(minSpan, width * scaleX * paddingFactor);
    const spanH = Math.max(minSpan, height * scaleY * paddingFactor);
    const dims = dimensions();
    const targetZoom = THREE.MathUtils.clamp(
      frustumHeight / Math.max(spanH, spanW / (dims.width / dims.height)),
      Math.max(1, controls.minZoom),
      Math.min(16, controls.maxZoom)
    );

    const startX = camera.position.x;
    const startY = camera.position.y;
    const startZ = camera.zoom;
    const startTime = performance.now();
    function stepFly(now) {
      if (disposed) return;
      const t = Math.min(1, (now - startTime) / duration);
      const ease = 1 - Math.pow(1 - t, 3);
      const nx = startX + (cx - startX) * ease;
      const ny = startY + (cy - startY) * ease;
      const nz = startZ + (targetZoom - startZ) * ease;
      camera.position.set(nx, ny, 100);
      controls.target.set(nx, ny, 0);
      camera.zoom = nz;
      camera.updateProjectionMatrix();
      controls.update();
      render();
      if (t < 1) requestAnimationFrame(stepFly);
    }
    requestAnimationFrame(stepFly);
  }

  function selectTile(tile, { fly = true } = {}) {
    disposeGroup(selectedGroup);
    activeTileObj = tile || null;
    tilePulseStart = performance.now();
    if (!metadata || !tile) { render(); return; }
    const outline = [], fill = [];
    addOutline(outline, tile.col, tile.row, tile.width, tile.height, 0.4);
    addRect(fill, tile.col, tile.row, tile.width, tile.height, 0.3);
    const selectedFill = new THREE.Mesh(geometry(fill), new THREE.MeshBasicMaterial({
      color: '#00d992', transparent: true, opacity: 0.22, depthWrite: false,
    }));
    const selectedLine = new THREE.LineSegments(geometry(outline), new THREE.LineBasicMaterial({ color: '#2fd6a1' }));
    selectedFill.renderOrder = 3;
    selectedLine.renderOrder = 4;
    selectedGroup.add(selectedFill, selectedLine);
    if (fly) {
      flyToRect(tile.col, tile.row, tile.width, tile.height, { paddingFactor: 3.4, duration: 340 });
    } else {
      render();
    }
  }

  function highlightDetectionBox(record, { fly = true } = {}) {
    activeDetectionRecord = record || null;
    selectedDetectionId = record?.id || null;
    tilePulseStart = performance.now();
    if (!record || !metadata) {
      render();
      return;
    }
    if (fly) {
      if (record.window) {
        flyToRect(record.window.col, record.window.row, record.window.width, record.window.height, { paddingFactor: 2.6, duration: 320 });
      } else if (Array.isArray(record.box) && record.box.length === 4) {
        const [x1, y1, x2, y2] = record.box;
        flyToRect(x1, y1, Math.max(64, x2 - x1), Math.max(64, y2 - y1), { paddingFactor: 4.5, duration: 320 });
      } else {
        render();
      }
    } else {
      render();
    }
  }

  function setAllDetections(records, selectedId = null) {
    allDetectionRecords = Array.isArray(records) ? records : [];
    if (selectedId !== null && selectedId !== undefined) {
      selectedDetectionId = selectedId;
    }
    render();
  }

  function setBoxesVisible(visible) {
    boxesVisible = Boolean(visible);
    render();
  }

  function setJobProgressOverlay(jobState) {
    jobProgressState = jobState || null;
    if (jobState && jobState.status === 'running' && metadata) {
      if (jobState.kind === 'detection' && jobState.active_window) {
        const aw = jobState.active_window;
        const key = `${aw.region_index || 0}:${aw.col}:${aw.row}`;
        if (key !== lastFollowedKey) {
          lastFollowedKey = key;
          flyToRect(aw.col, aw.row, aw.width, aw.height, { paddingFactor: 4.2, duration: 280 });
          return;
        }
      } else if (!jobState.kind && plan?.tiles?.length && jobState.done < plan.tiles.length) {
        const act = plan.tiles[jobState.done];
        const key = `export:${act?.id}`;
        if (act && key !== lastFollowedKey) {
          lastFollowedKey = key;
          flyToRect(act.col, act.row, act.width, act.height, { paddingFactor: 4.0, duration: 260 });
          return;
        }
      }
    }
    render();
  }

  async function loadSource(nextMetadata, url) {
    const version = ++loadVersion;
    disposeGroup(rasterGroup);
    disposeGroup(gridGroup);
    disposeGroup(selectedGroup);
    sourceMesh = null;
    plan = null;
    activeTileObj = null;
    activeDetectionRecord = null;
    metadata = nextMetadata;
    if (!metadata) { render(); return; }
    const gx = Math.abs(Number(metadata.gsd_x_cm)) || Math.abs(Number(metadata.transform?.[0])) || 1;
    const gy = Math.abs(Number(metadata.gsd_y_cm)) || Math.abs(Number(metadata.transform?.[4])) || 1;
    const normalization = 1000 / Math.max(metadata.width * gx, metadata.height * gy);
    scaleX = gx * normalization;
    scaleY = gy * normalization;
    worldWidth = metadata.width * scaleX;
    worldHeight = metadata.height * scaleY;
    fit();
    onStatus('Đang tải ảnh tổng quan…');
    const response = await fetch(url);
    if (!response.ok) {
      let message = 'Không tải được ảnh tổng quan.';
      try { message = (await response.json()).error || message; } catch { /* A non-JSON HTTP error. */ }
      throw new Error(message);
    }
    const blob = await response.blob();
    if (disposed || version !== loadVersion) return;
    const objectUrl = URL.createObjectURL(blob);
    const image = new Image();
    try {
      image.src = objectUrl;
      await image.decode();
      if (disposed || version !== loadVersion) return;
      const texture = new THREE.Texture(image);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.minFilter = THREE.LinearFilter;
      texture.magFilter = THREE.LinearFilter;
      texture.generateMipmaps = false;
      texture.needsUpdate = true;
      sourceMesh = new THREE.Mesh(new THREE.PlaneGeometry(worldWidth, worldHeight),
        new THREE.MeshBasicMaterial({ map: texture }));
      rasterGroup.add(sourceMesh);
      const border = [];
      addOutline(border, 0, 0, metadata.width, metadata.height, 0.05);
      rasterGroup.add(new THREE.LineSegments(geometry(border), new THREE.LineBasicMaterial({ color: '#00d992' })));
      render();
      onStatus(`Ảnh tổng quan ${image.naturalWidth} × ${image.naturalHeight} px · kéo để di chuyển, cuộn để thu phóng`);
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  }

  function clearSource() {
    loadVersion += 1;
    metadata = null;
    plan = null;
    sourceMesh = null;
    cadRegions = [];
    draftPoints = [];
    selectedRegionIndex = -1;
    activeTileObj = null;
    activeDetectionRecord = null;
    allDetectionRecords = [];
    selectedDetectionId = null;
    jobProgressState = null;
    disposeGroup(rasterGroup);
    disposeGroup(gridGroup);
    disposeGroup(selectedGroup);
    onStatus('');
    render();
  }

  function findGripAtScreen(sx, sy) {
    if (!metadata) return null;
    const order = [...cadRegions.keys()].sort((a, b) => (b === selectedRegionIndex) - (a === selectedRegionIndex));
    for (const rIdx of order) {
      const poly = cadRegions[rIdx]?.polygon;
      if (!poly) continue;
      for (let vIdx = 0; vIdx < poly.length; vIdx++) {
        const [vx, vy] = imageToScreen(poly[vIdx][0], poly[vIdx][1]);
        if (Math.hypot(sx - vx, sy - vy) <= 9) {
          return { type: 'vertex', regionIndex: rIdx, vertexIndex: vIdx };
        }
      }
      for (let vIdx = 0; vIdx < poly.length; vIdx++) {
        const p1 = imageToScreen(poly[vIdx][0], poly[vIdx][1]);
        const p2 = imageToScreen(poly[(vIdx + 1) % poly.length][0], poly[(vIdx + 1) % poly.length][1]);
        const mx = (p1[0] + p2[0]) * 0.5;
        const my = (p1[1] + p2[1]) * 0.5;
        if (Math.hypot(sx - mx, sy - my) <= 8) {
          return { type: 'midpoint', regionIndex: rIdx, vertexIndex: vIdx };
        }
      }
    }
    return null;
  }

  function completeDraftPolygon(points) {
    if (!points || points.length < 3) return false;
    const cleaned = points.map(([c, r]) => [Math.round(c), Math.round(r)]);
    draftPoints = [];
    hoverImagePt = null;
    cadCallbacks.onFinishDraft(cleaned);
    render();
    return true;
  }

  function onPointerDown(event) {
    canvas.focus({ preventScroll: true });
    const rect = canvas.getBoundingClientRect();
    const sx = event.clientX - rect.left;
    const sy = event.clientY - rect.top;

    if (event.button === 0 && cadMode !== 'draw_pline' && cadMode !== 'draw_rect' && cadRegions.length > 0) {
      const grip = findGripAtScreen(sx, sy);
      if (grip) {
        selectedRegionIndex = grip.regionIndex;
        if (grip.type === 'midpoint') {
          const poly = cadRegions[grip.regionIndex].polygon;
          const p1 = poly[grip.vertexIndex];
          const p2 = poly[(grip.vertexIndex + 1) % poly.length];
          const newPt = [Math.round((p1[0] + p2[0]) / 2), Math.round((p1[1] + p2[1]) / 2)];
          poly.splice(grip.vertexIndex + 1, 0, newPt);
          draggingGrip = { regionIndex: grip.regionIndex, vertexIndex: grip.vertexIndex + 1 };
        } else {
          draggingGrip = { regionIndex: grip.regionIndex, vertexIndex: grip.vertexIndex };
        }
        controls.enabled = false;
        canvas.setPointerCapture?.(event.pointerId);
        render();
        return;
      }
    }
    pointerDown = { x: event.clientX, y: event.clientY, id: event.pointerId, button: event.button };
  }

  function onPointerMove(event) {
    if (!metadata) return;
    const rect = canvas.getBoundingClientRect();
    const sx = event.clientX - rect.left;
    const sy = event.clientY - rect.top;

    if (draggingGrip) {
      const imgPt = screenToImage(event.clientX, event.clientY);
      if (imgPt && cadRegions[draggingGrip.regionIndex]) {
        const reg = cadRegions[draggingGrip.regionIndex];
        reg.polygon[draggingGrip.vertexIndex] = [Math.round(imgPt[0]), Math.round(imgPt[1])];
        reg.tile_count = countIntersectingTiles(reg.polygon);
        render();
      }
      return;
    }

    if (cadMode === 'draw_pline' || cadMode === 'draw_rect') {
      hoverImagePt = screenToImage(event.clientX, event.clientY);
      canvas.style.cursor = 'crosshair';
      render();
      return;
    }

    if (cadRegions.length > 0) {
      const grip = findGripAtScreen(sx, sy);
      if (grip?.type !== hoveredGrip?.type || grip?.regionIndex !== hoveredGrip?.regionIndex || grip?.vertexIndex !== hoveredGrip?.vertexIndex) {
        hoveredGrip = grip;
        canvas.style.cursor = grip ? 'grab' : '';
        render();
      }
    } else if (canvas.style.cursor) {
      canvas.style.cursor = '';
    }
  }

  function onPointerUp(event) {
    if (draggingGrip) {
      draggingGrip = null;
      controls.enabled = true;
      canvas.releasePointerCapture?.(event.pointerId);
      cadCallbacks.onRegionsChange(cadRegions, selectedRegionIndex);
      render();
      return;
    }
    if (!pointerDown || pointerDown.id !== event.pointerId) return;
    const start = pointerDown;
    pointerDown = null;
    const moved = Math.hypot(start.x - event.clientX, start.y - event.clientY);

    if (start.button === 2 && cadMode === 'draw_pline' && draftPoints.length >= 3) {
      completeDraftPolygon(draftPoints);
      return;
    }
    if (start.button === 2 && cadRegions.length > 0 && moved <= 5) {
      const rect = canvas.getBoundingClientRect();
      const grip = findGripAtScreen(event.clientX - rect.left, event.clientY - rect.top);
      if (grip && grip.type === 'vertex') {
        const poly = cadRegions[grip.regionIndex]?.polygon;
        if (poly && poly.length > 3) {
          poly.splice(grip.vertexIndex, 1);
          cadRegions[grip.regionIndex].tile_count = countIntersectingTiles(poly);
          cadCallbacks.onRegionsChange(cadRegions, selectedRegionIndex);
          render();
          return;
        }
      }
    }

    if (start.button !== 0 || moved > 5 || !sourceMesh) return;

    const imgPt = screenToImage(event.clientX, event.clientY);
    if (!imgPt) return;

    if (cadMode === 'draw_pline') {
      if (draftPoints.length >= 3) {
        const [fx, fy] = imageToScreen(draftPoints[0][0], draftPoints[0][1]);
        const rect = canvas.getBoundingClientRect();
        if (Math.hypot((event.clientX - rect.left) - fx, (event.clientY - rect.top) - fy) <= 13) {
          completeDraftPolygon(draftPoints);
          return;
        }
      }
      draftPoints.push([Math.round(imgPt[0]), Math.round(imgPt[1])]);
      onStatus(`Đang vẽ Polyline: đã chấm ${draftPoints.length} đỉnh · Click điểm đầu hoặc bấm "Đóng vùng" / Double-click để khép kín.`);
      render();
      return;
    }

    if (cadMode === 'draw_rect') {
      if (draftPoints.length === 0) {
        draftPoints.push([Math.round(imgPt[0]), Math.round(imgPt[1])]);
        onStatus('Đã chọn góc thứ 1 · Di chuyển chuột và click góc đối diện để tạo vùng chữ nhật.');
        render();
      } else {
        const [c1, r1] = draftPoints[0];
        const [c2, r2] = [Math.round(imgPt[0]), Math.round(imgPt[1])];
        if (Math.abs(c2 - c1) > 4 && Math.abs(r2 - r1) > 4) {
          const left = Math.min(c1, c2), right = Math.max(c1, c2);
          const top = Math.min(r1, r2), bottom = Math.max(r1, r2);
          completeDraftPolygon([[left, top], [right, top], [right, bottom], [left, bottom]]);
        }
      }
      return;
    }

    for (let rIdx = cadRegions.length - 1; rIdx >= 0; rIdx--) {
      const poly = cadRegions[rIdx]?.polygon;
      if (poly && pointInPoly2D(imgPt[0], imgPt[1], poly)) {
        selectedRegionIndex = rIdx;
        cadCallbacks.onRegionsChange(cadRegions, selectedRegionIndex);
        render();
        break;
      }
    }

    if (!plan) return;
    const [col, row] = imgPt;
    const candidates = plan.tiles.slice(0, 2000).filter(tile =>
      col >= tile.col && col < tile.col + tile.width && row >= tile.row && row < tile.row + tile.height);
    candidates.sort((a, b) =>
      Math.hypot((col - a.col) / a.width - 0.5, (row - a.row) / a.height - 0.5)
      - Math.hypot((col - b.col) / b.width - 0.5, (row - b.row) / b.height - 0.5));
    if (candidates.length) onSelect(candidates[0]);
  }

  function onDoubleClick(event) {
    if (cadMode === 'draw_pline' && draftPoints.length >= 3) {
      event.preventDefault();
      completeDraftPolygon(draftPoints);
    }
  }

  function onKeyDown(event) {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const key = event.key;
    if (key === 'Enter' && cadMode === 'draw_pline' && draftPoints.length >= 3) {
      event.preventDefault();
      completeDraftPolygon(draftPoints);
      return;
    }
    if (key === 'Escape' && (cadMode === 'draw_pline' || cadMode === 'draw_rect')) {
      event.preventDefault();
      draftPoints = [];
      hoverImagePt = null;
      setCadMode('none');
      return;
    }
    if ((key === 'Delete' || key === 'Backspace') && selectedRegionIndex >= 0 && selectedRegionIndex < cadRegions.length) {
      event.preventDefault();
      cadRegions.splice(selectedRegionIndex, 1);
      selectedRegionIndex = cadRegions.length ? Math.min(selectedRegionIndex, cadRegions.length - 1) : -1;
      cadCallbacks.onRegionsChange(cadRegions, selectedRegionIndex);
      render();
      return;
    }
    if (key === '+' || key === '=') { event.preventDefault(); zoom(1.25); return; }
    if (key === '-' || key === '_') { event.preventDefault(); zoom(0.8); return; }
    if (key === '0' || key === 'Home') { event.preventDefault(); fit(); return; }
    const steps = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
    if (!steps[key]) return;
    event.preventDefault();
    const distance = frustumHeight / camera.zoom * 0.08;
    const [dx, dy] = steps[key];
    const translation = new THREE.Vector3(dx * distance, dy * distance, 0);
    camera.position.add(translation);
    controls.target.add(translation);
    controls.update();
    render();
  }

  function setCadMode(nextMode) {
    cadMode = nextMode;
    draftPoints = [];
    hoverImagePt = null;
    canvas.style.cursor = (cadMode === 'draw_pline' || cadMode === 'draw_rect') ? 'crosshair' : '';
    cadCallbacks.onModeChange(cadMode);
    render();
  }

  function finishCadDraft() {
    if (draftPoints.length >= 3) {
      return completeDraftPolygon(draftPoints);
    }
    return false;
  }

  function setCadRegions(regions, selectedIdx = selectedRegionIndex) {
    cadRegions = (regions || []).map((r, i) => {
      const palette = CAD_PALETTE[i % CAD_PALETTE.length];
      const poly = r.polygon || [];
      return {
        ...r,
        name: r.name || `Vùng ${i + 1}`,
        color: r.color || palette.color,
        hatch: r.hatch || palette.hatch,
        tile_count: poly.length >= 3 ? countIntersectingTiles(poly) : (r.tile_count || 1),
      };
    });
    selectedRegionIndex = selectedIdx;
    render();
  }

  function focusRegion(index) {
    const reg = cadRegions[index];
    if (!reg?.polygon?.length || !metadata) return;
    selectedRegionIndex = index;
    let minC = Infinity, minR = Infinity, maxC = -Infinity, maxR = -Infinity;
    for (const [c, r] of reg.polygon) {
      if (c < minC) minC = c;
      if (r < minR) minR = r;
      if (c > maxC) maxC = c;
      if (r > maxR) maxR = r;
    }
    flyToRect(minC, minR, Math.max(10, maxC - minC), Math.max(10, maxR - minR), { paddingFactor: 1.8, duration: 320 });
  }

  function setCadCallbacks(cbs) {
    cadCallbacks = { ...cadCallbacks, ...cbs };
  }

  function onContextLost(event) {
    event.preventDefault();
    onStatus('Bộ hiển thị ảnh bị gián đoạn. Tải lại trang để khôi phục; tiến trình xuất được lưu riêng.');
  }

  controls.addEventListener('change', render);
  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('pointerup', onPointerUp);
  canvas.addEventListener('dblclick', onDoubleClick);
  canvas.addEventListener('contextmenu', e => { if (cadMode !== 'none' || cadRegions.length > 0) e.preventDefault(); });
  canvas.addEventListener('keydown', onKeyDown);
  canvas.addEventListener('webglcontextlost', onContextLost);
  const observer = new ResizeObserver(resize);
  observer.observe(container);
  fit();

  function dispose() {
    if (disposed) return;
    disposed = true;
    loadVersion += 1;
    observer.disconnect();
    controls.removeEventListener('change', render);
    controls.dispose();
    canvas.removeEventListener('pointerdown', onPointerDown);
    canvas.removeEventListener('pointermove', onPointerMove);
    canvas.removeEventListener('pointerup', onPointerUp);
    canvas.removeEventListener('dblclick', onDoubleClick);
    canvas.removeEventListener('keydown', onKeyDown);
    canvas.removeEventListener('webglcontextlost', onContextLost);
    disposeGroup(rasterGroup);
    disposeGroup(gridGroup);
    disposeGroup(selectedGroup);
    renderer.dispose();
    overlayCanvas.remove();
    canvas.remove();
  }

  return {
    loadSource,
    clearSource,
    setPlan,
    selectTile,
    highlightDetectionBox,
    setAllDetections,
    setBoxesVisible,
    areBoxesVisible: () => boxesVisible,
    setTerrainVectors(features) {
      terrainVectors = Array.isArray(features) ? features : [];
      renderCadOverlay();
    },
    setMapScale(scale) {
      const m = Number(String(scale || 500).replace(/^1\s*[:/]\s*/, '')) || 500;
      mapScale = [500, 1000, 2000, 5000].includes(m) ? m : 500;
      render();
    },
    getMapScale: () => mapScale,
    setJobProgressOverlay,
    flyToRect,
    fit,
    zoom,
    dispose,
    setCadMode,
    finishCadDraft,
    setCadRegions,
    focusRegion,
    setCadCallbacks,
    getSelectedRegionIndex: () => selectedRegionIndex,
    countIntersectingTiles,
  };
}
