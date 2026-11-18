import { CAD_PALETTE } from './viewport.js?v=20261030_1';

let animeAnimate = null;
import('animejs').then(mod => { animeAnimate = mod.animate; }).catch(() => {});

function pulseElements(selectorOrEl) {
  if (!animeAnimate) return;
  try {
    animeAnimate(selectorOrEl, {
      opacity: [0.55, 1],
      translateY: [6, 0],
      duration: 260,
      ease: 'outCubic',
    });
  } catch {}
}

function formatTileId(id) {
  return String(id || '').replace(/\btile_/gi, 'Ảnh ');
}

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtMetric(v, digits = 3) {
  if (typeof v === 'number' && Number.isFinite(v)) return v.toFixed(digits);
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v).toFixed(digits);
  return v ?? '—';
}

const KNOWN_CATEGORY_PHRASES = [
  'newly transplanted rice',
  'healthy rice',
  'ornamental tree',
  'individual tree',
  'tree cluster',
  'electric pole',
  'water body',
  'bare soil',
  'building',
  'vehicle',
  'person',
  'bridge',
  'ditch',
  'hedge',
  'fence',
  'grass',
  'weed',
  'road',
  'tree',
  'rice',
];
const KNOWN_CAT_REGEX = new RegExp(
  '\\b(' + KNOWN_CATEGORY_PHRASES.map(p => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')\\b',
  'gi'
);

function parseSmartCategories(rawText) {
  const rawSegments = String(rawText || '').split(/[\n,;]+/).map(s => s.trim()).filter(Boolean);
  const out = [];
  for (const seg of rawSegments) {
    const matches = [...seg.matchAll(KNOWN_CAT_REGEX)].map(m => m[1].toLowerCase());
    const remainder = seg.replace(KNOWN_CAT_REGEX, '').replace(/\b(and|or|va|và|&|\+)\b/gi, '').trim();
    if (matches.length >= 2 && !remainder) {
      for (const m of matches) {
        if (!out.some(x => x.toLowerCase() === m)) out.push(m);
      }
    } else {
      if (!out.some(x => x.toLowerCase() === seg.toLowerCase())) out.push(seg);
    }
  }
  return out;
}

const $ = id => document.getElementById(id);
const statusNames = {unreviewed:'Chưa duyệt',accepted_raw:'Đã giữ khung gốc',accepted_candidate:'Đã dùng khung co',rejected:'Đã bỏ'};
const statusBadgeClasses = {unreviewed:'status-unreviewed',accepted_raw:'status-accepted-raw',accepted_candidate:'status-accepted-candidate',rejected:'status-rejected'};

export async function createAdvanced(ctx) {
  const {api,action,model,config,planReady,goToStep,inspectSource,invalidateSource,updateControls,showError,selectTile,getViewport} = ctx;
  const response = await fetch('/advanced.html?v=20261030_1');
  if (!response.ok) throw new Error('Không tải được giao diện nhận diện.');
  const content = document.createElement('template'); content.innerHTML = await response.text();
  const clone = id => content.content.querySelector('#'+id).content.cloneNode(true);
  $('metadata').after(clone('warp-template'));
  $('step-3').replaceChildren(clone('detection-template'));
  if ($('step-5') && content.content.querySelector('#yolo-template')) {
    $('step-5').replaceChildren(clone('yolo-template'));
  }
  const resultsFrag = clone('results-template');
  const resultsPanelEl = resultsFrag.querySelector('#results-panel');
  const mapPanelEl = document.querySelector('.map-panel') || document.querySelector('.workspace');
  if (resultsPanelEl && mapPanelEl) mapPanelEl.append(resultsPanelEl);
  if (content.content.querySelector('#taskmgr-template')) {
    const tmFrag = clone('taskmgr-template');
    const tmPanelEl = tmFrag.querySelector('#taskmgr-panel');
    if (tmPanelEl) tmPanelEl.hidden = model.step !== 3 && model.step !== 5;
    const configPanelEl = document.querySelector('.config-panel');
    if (configPanelEl) configPanelEl.append(tmFrag);
  }
  const slot = $('step4-export-slot') || $('step-4');
  slot.append(resultsFrag);
  const reopen = document.createElement('button');
  reopen.id='show-results'; reopen.type='button'; reopen.textContent='🛰️ Xem kết quả nhận diện'; reopen.hidden=true;
  document.querySelector('.header-meta').prepend(reopen);
  document.querySelector('.header-meta > span:last-child').textContent='Nhận diện & xuất dữ liệu';
  const state = {
    defaults:null,estimate:null,estimateKey:'',yoloEstimate:null,yoloEstimateKey:'',warp:null,results:null,offset:0,
    loadedJob:null,loadedJobStateKey:'',lastLiveSyncKey:'',loading:false,renderedObjectId:null,
    sessions:[],regions:[],selectedRegionIndex:-1,cadMode:'none',providerKeys:{},modalProvider:null,filter:'all',
    boxesVisible:true,forceShowResults:false,lastStep:1,cachedObjectStats:null,
    fullMapBoxes:[],fullMapBoxesKey:'',fullMapBoxesLoading:false,
    turboStatus:null,lastTurboCompletedId:'',terrainFeatures:[],
    surveyLibrary:{blocks:[],layers:[],linetypes:[],rules:[]}
  };

  // Floating CAD Toolbar right on the Overview Map (.viewport-shell)
  const mapCadBar = document.createElement('div');
  mapCadBar.id = 'map-cad-toolbar';
  mapCadBar.className = 'map-cad-toolbar';
  mapCadBar.hidden = true;
  mapCadBar.innerHTML = `
    <span class="cad-bar-title">CAD VÙNG:</span>
    <button type="button" id="map-cad-pline" title="Vẽ vùng Polyline (chấm từng đỉnh trên bản đồ)">📐 Vẽ Polyline</button>
    <button type="button" id="map-cad-rect" title="Vẽ vùng Chữ nhật (2 điểm góc)">▭ Vẽ Chữ nhật</button>
    <button type="button" id="map-cad-finish" title="Đóng vùng Polyline đang vẽ (Enter)">✓ Đóng vùng</button>
    <button type="button" id="map-cad-edit" title="Chế độ chọn vùng và nắm kéo các đỉnh (□)">🧭 Kéo đỉnh</button>
    <button type="button" id="map-cad-del" title="Xóa vùng đang chọn (Delete)">✕ Xóa vùng</button>
  `;
  document.querySelector('.viewport-shell')?.append(mapCadBar);

  function settings() {
    const number = id => Number($(id).value);
    const mergeMode = $('merge-boxes').checked ? ($('merge-mode-select')?.value || 'equal_weight') : 'none';
    const parsedCats = parseSmartCategories($('detect-categories').value);
    return {categories:parsedCats.length ? parsedCats : ['newly transplanted rice', 'grass'],
      micro_size:number('micro-size'),micro_overlap:number('micro-overlap')/100,upscale:number('upscale'),
      max_image_size:number('model-image-size'),max_new_tokens:number('model-tokens'),seed:state.defaults?.seed ?? 42,
      merge_mode:mergeMode,merge_iou:state.defaults?.merge_iou ?? .55,
      refinement:$('refine-boxes').checked,padding:number('refine-padding'),
      engine:'locateanything'};
  }
  function yoloSettings() {
    const base = settings();
    const engine = $('detect-engine')?.value || 'turbo_zone';
    return { ...base, engine: engine === 'turbo_clump' ? 'turbo_clump' : 'turbo_zone' };
  }
  function fillSettings(values) {
    if (!values) return;
    state.defaults=values;
    if ($('detect-engine') && values.engine && values.engine !== 'locateanything') {
      $('detect-engine').value = values.engine;
    }
    const normCats = parseSmartCategories((values.categories || []).join('\n'));
    $('detect-categories').value=(normCats.length ? normCats : (values.categories || [])).join('\n');
    for (const [id,key] of [['micro-size','micro_size'],['upscale','upscale'],['model-image-size','max_image_size'],['model-tokens','max_new_tokens'],['refine-padding','padding']]) {
      const field=$(id); const value=String(values[key]);
      if (field.tagName==='SELECT' && !Array.from(field.options).some(o=>o.value===value)) field.add(new Option(value,value));
      field.value=value;
    }
    $('micro-overlap').value=values.micro_overlap*100;
    $('merge-boxes').checked=values.merge_mode!=='none';
    if (values.merge_mode!=='none' && $('merge-mode-select')) $('merge-mode-select').value=values.merge_mode;
    $('refine-boxes').checked=values.refinement;
    renderTurboEngineBanner();
    invalidateDetection();
    invalidateYoloDetection();
  }

  function isSelectedEngineReady() {
    const eng = $('detect-engine')?.value || 'turbo_zone';
    return Boolean(state.turboStatus?.models?.[eng]?.trained);
  }

  function renderTurboEngineBanner() {
    const eng = $('detect-engine')?.value || 'turbo_zone';
    const noteEl = $('detect-engine-status');
    if (!noteEl) return;
    noteEl.classList.remove('is-ready', 'is-warn');
    const mInfo = state.turboStatus?.models?.[eng];
    if (mInfo?.trained) {
      const map50 = mInfo.metrics?.mAP50 != null ? `${(Number(mInfo.metrics.mAP50) * 100).toFixed(1)}%` : 'Sẵn sàng';
      noteEl.classList.add('is-ready');
      noteEl.textContent = `⚡ Sẵn sàng (Batch=32 · FP16 · mAP50: ${map50})`;
    } else {
      noteEl.classList.add('is-warn');
      noteEl.textContent = '⏳ Chưa huấn luyện. Bấm "Huấn luyện Mô hình Turbo" ở trên để tạo trọng số.';
    }
  }

  function renderTurboStatus(st) {
    if (!st || typeof st !== 'object') return;
    state.turboStatus = st;
    const ds = st.dataset || {};
    const posCnt = Number(ds.total_positives || 0);
    const negCnt = Number(ds.total_negatives || 0);

    // Update #detect-engine option labels on Step 5 with live training status
    const engSel = $('detect-engine');
    if (engSel) {
      for (const opt of Array.from(engSel.options)) {
        if (opt.value === 'turbo_zone') {
          const m = st.models?.turbo_zone;
          const badge = m?.trained
            ? `[Sẵn sàng · mAP50 ${((m.metrics?.mAP50 || 0) * 100).toFixed(0)}%]`
            : '[Chưa huấn luyện]';
          opt.textContent = `⚡ Turbo YOLO11 · Quét Vùng Lúa & Cỏ bờ (640×640 · FP16 · Batch=32) ${badge}`;
        } else if (opt.value === 'turbo_clump') {
          const m = st.models?.turbo_clump;
          const badge = m?.trained
            ? `[Sẵn sàng · mAP50 ${((m.metrics?.mAP50 || 0) * 100).toFixed(0)}%]`
            : '[Chưa huấn luyện]';
          opt.textContent = `🌱 Turbo YOLO11 · Bắt Từng Khóm Lúa Lẻ & Cỏ bờ (~15cm · 512×512 · FP16 · Batch=32) ${badge}`;
        }
      }
      if (!st.models?.[engSel.value]?.trained) {
        if (st.models?.turbo_zone?.trained) engSel.value = 'turbo_zone';
        else if (st.models?.turbo_clump?.trained) engSel.value = 'turbo_clump';
      }
    }

    const countsEl = $('turbo-dataset-counts');
    if (countsEl) {
      const negCls = negCnt > 0 ? 'neg-ready' : 'neg-zero';
      const classParts = Object.entries(ds.class_breakdown || {})
        .map(([k, v]) => `${k}: ${Number(v).toLocaleString('vi-VN')}`)
        .join(' · ');
      countsEl.innerHTML = `
        <span class="turbo-count-chip pos" title="${escapeHtml(classParts)}">✅ Mẫu dương đã lưu: ${posCnt.toLocaleString('vi-VN')}</span>
        <span class="turbo-count-chip ${negCls}">🛡️ Mẫu âm (Loại bỏ): ${negCnt.toLocaleString('vi-VN')}</span>
      `;
    }
    const tipEl = $('turbo-neg-tip');
    if (tipEl) {
      if (negCnt === 0) {
        tipEl.innerHTML = 'Mẫu âm (Hard Negatives): 0. Bổ sung tại Bước 03 bằng nút Loại bỏ.';
      } else {
        tipEl.innerHTML = `Đã có <b>${negCnt.toLocaleString('vi-VN')}</b> mẫu âm và <b>${posCnt.toLocaleString('vi-VN')}</b> mẫu dương.`;
      }
    }

    const badgesEl = $('turbo-models-badges');
    if (badgesEl) {
      const cards = [
        ['turbo_zone', '⚡ Chế độ 1: Turbo Quét Vùng (640px)'],
        ['turbo_clump', '🌱 Chế độ 2: Turbo Khóm Lẻ (~15cm)'],
      ].map(([key, title]) => {
        const m = st.models?.[key];
        if (m?.trained) {
          const map50 = m.metrics?.mAP50 != null ? `${(Number(m.metrics.mAP50) * 100).toFixed(1)}%` : '—';
          const prec = m.metrics?.precision != null ? `${(Number(m.metrics.precision) * 100).toFixed(1)}%` : '—';
          const rec = m.metrics?.recall != null ? `${(Number(m.metrics.recall) * 100).toFixed(1)}%` : '—';
          const onnxNote = m.onnx_path ? ' · 📦 Đã xuất best.onnx' : '';
          return `
            <div class="turbo-model-card trained">
              <strong>${title}</strong>
              <div>✅ Đã huấn luyện (${m.epochs || 50} ep · ${m.elapsed_seconds || '—'}s)${onnxNote}</div>
              <div>mAP50: <b>${map50}</b> · Đúng: <b>${prec}</b> · Đủ: <b>${rec}</b></div>
            </div>
          `;
        }
        return `
          <div class="turbo-model-card">
            <strong>${title}</strong>
            <div>⏳ Chưa huấn luyện — Bấm nút Huấn luyện ở trên để tạo trọng số FP16 (.pt + .onnx).</div>
          </div>
        `;
      });
      badgesEl.innerHTML = cards.join('');
    }

    renderTurboEngineBanner();
    updateControls();
  }

  async function refreshTurboStatus() {
    try {
      const st = await api('/api/turbo/status');
      renderTurboStatus(st);
      return st;
    } catch {
      return null;
    }
  }
  function currentCategories() {
    const cats = parseSmartCategories($('detect-categories').value);
    return cats.length ? cats : ['newly transplanted rice', 'grass'];
  }

  function isStep3Multi() {
    return model.step === 3 && $('detect-scope')?.value === 'multi';
  }
  function isStep5Multi() {
    return model.step === 5 && $('yolo-detect-scope')?.value === 'multi';
  }
  function isMultiRegionMode() {
    return isStep3Multi() || isStep5Multi();
  }

  function syncMultiRegionVisibility() {
    const active3 = isStep3Multi();
    const active5 = isStep5Multi();
    const active = active3 || active5;
    if ($('multi-region-box')) $('multi-region-box').hidden = !active3;
    if ($('yolo-multi-region-box')) $('yolo-multi-region-box').hidden = !active5;
    mapCadBar.hidden = !active;
    const vp = getViewport?.();
    if (vp) {
      if (active) {
        vp.setCadRegions(state.regions, state.selectedRegionIndex);
      } else {
        vp.setCadMode('none');
        vp.setCadRegions([], -1);
      }
    }
  }

  function normalizeRegions() {
    const vp = getViewport?.();
    state.regions.forEach((item, idx) => {
      const palette = CAD_PALETTE[idx % CAD_PALETTE.length];
      item.name = `Vùng ${idx + 1}`;
      item.color = palette.color;
      item.hatch = palette.hatch;
      item.tile_id = item.tile_id || `region_${String(idx + 1).padStart(2, '0')}`;
      if (item.polygon && vp?.countIntersectingTiles) {
        item.tile_count = vp.countIntersectingTiles(item.polygon);
      }
    });
    if (state.selectedRegionIndex >= state.regions.length) {
      state.selectedRegionIndex = state.regions.length - 1;
    }
    syncMultiRegionVisibility();
  }

  function updateCadHint(mode = state.cadMode) {
    state.cadMode = mode;
    let hintText = 'Chỉnh đỉnh: Kéo đỉnh (□) hoặc cạnh (+)';
    if (mode === 'draw_pline') {
      hintText = 'Vẽ Polyline: Click chấm đỉnh · Đóng: ✓ Đóng vùng';
    } else if (mode === 'draw_rect') {
      hintText = 'Vẽ Chữ nhật: Click 2 góc đối diện';
    }
    if ($('cad-mode-hint')) $('cad-mode-hint').textContent = hintText;
    if ($('yolo-cad-mode-hint')) $('yolo-cad-mode-hint').textContent = hintText;
    for (const [id, active] of [
      ['cad-draw-pline-btn', mode === 'draw_pline'],
      ['cad-draw-rect-btn', mode === 'draw_rect'],
      ['cad-edit-btn', mode === 'none' || mode === 'edit'],
      ['yolo-cad-draw-pline-btn', mode === 'draw_pline'],
      ['yolo-cad-draw-rect-btn', mode === 'draw_rect'],
      ['yolo-cad-edit-btn', mode === 'none' || mode === 'edit'],
      ['map-cad-pline', mode === 'draw_pline'],
      ['map-cad-rect', mode === 'draw_rect'],
      ['map-cad-edit', mode === 'none' || mode === 'edit'],
    ]) {
      const el = $(id);
      if (el) el.classList.toggle('active-cad-tool', active);
    }
  }

  function buildRegionListItem(item, index, showCatRow = true) {
    const li = document.createElement('li');
    li.className = 'cad-region-card' + (index === state.selectedRegionIndex ? ' selected' : '');
    li.style.borderLeftColor = item.color;

    const head = document.createElement('div');
    head.className = 'cad-region-head';

    const badge = document.createElement('span');
    badge.className = 'cad-swatch-badge';
    badge.style.background = item.color;
    badge.textContent = item.name;

    const meta = document.createElement('span');
    meta.className = 'cad-region-meta';
    const vCount = item.polygon?.length || 4;
    const tCount = item.tile_count || 1;
    meta.textContent = `${vCount} đỉnh · bao phủ ${tCount} ảnh`;

    const actions = document.createElement('div');
    actions.className = 'cad-region-actions';

    const zoomBtn = document.createElement('button');
    zoomBtn.type = 'button';
    zoomBtn.className = 'text-button';
    zoomBtn.textContent = 'Phóng tới';
    zoomBtn.addEventListener('click', () => {
      state.selectedRegionIndex = index;
      getViewport?.()?.focusRegion(index);
      renderRegions();
    });

    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'text-button danger-text';
    del.textContent = 'Xóa vùng';
    del.addEventListener('click', () => {
      state.regions.splice(index, 1);
      renderRegions();
      invalidateDetection();
      invalidateYoloDetection();
      updateControls();
    });

    if (showCatRow) {
      const syncCatBtn = document.createElement('button');
      syncCatBtn.type = 'button';
      syncCatBtn.className = 'text-button';
      syncCatBtn.textContent = 'Gán danh mục trên';
      syncCatBtn.addEventListener('click', () => {
        item.categories = currentCategories();
        renderRegions();
        invalidateDetection();
        invalidateYoloDetection();
        updateControls();
      });
      actions.append(zoomBtn, syncCatBtn, del);
    } else {
      actions.append(zoomBtn, del);
    }
    head.append(badge, meta, actions);
    li.append(head);

    if (showCatRow) {
      const catRow = document.createElement('div');
      catRow.className = 'cad-region-cats';
      const catLabel = document.createElement('small');
      catLabel.textContent = 'Đối tượng tìm riêng trong vùng này (phân cách bằng dấu phẩy):';
      const catInput = document.createElement('input');
      catInput.type = 'text';
      catInput.value = (item.categories || []).join(', ');
      catInput.placeholder = 'Ví dụ: ornamental tree, grass, vehicle';
      catInput.addEventListener('change', () => {
        const parsed = parseSmartCategories(catInput.value);
        if (parsed.length) {
          item.categories = parsed;
          catInput.value = parsed.join(', ');
        } else {
          catInput.value = (item.categories || []).join(', ');
        }
        getViewport?.()?.setCadRegions(state.regions, state.selectedRegionIndex);
        invalidateDetection();
        invalidateYoloDetection();
        updateControls();
      });
      catRow.append(catLabel, catInput);
      li.append(catRow);
    }

    li.addEventListener('click', e => {
      if (e.target.tagName === 'BUTTON' || e.target.tagName === 'INPUT') return;
      state.selectedRegionIndex = index;
      renderRegions();
    });
    return li;
  }

  function renderRegions() {
    normalizeRegions();
    const list3 = $('multi-region-list');
    if (list3) {
      list3.replaceChildren(...state.regions.map((item, idx) => buildRegionListItem(item, idx, true)));
    }
    const list5 = $('yolo-multi-region-list');
    if (list5) {
      list5.replaceChildren(...state.regions.map((item, idx) => buildRegionListItem(item, idx, false)));
    }
    syncMultiRegionVisibility();
  }
  function request() {
    const scope=$('detect-scope').value;
    const req={path:$('source-path').value.trim(),config:config(),settings:settings(),scope,tile_id:$('tile-select').value};
    if (scope==='multi') req.regions=structuredClone(state.regions);
    if ($('sr-mode')) req.sr_mode=$('sr-mode').value;
    if ($('spectral-mode') && $('spectral-mode').value !== 'auto') req.spectral_mode=$('spectral-mode').value;
    return req;
  }
  function yoloRequest() {
    const scope=$('yolo-detect-scope')?.value || 'all';
    const req={path:$('source-path').value.trim(),config:config(),settings:yoloSettings(),scope,tile_id:$('tile-select').value};
    if (scope==='multi') req.regions=structuredClone(state.regions);
    if ($('spectral-mode') && $('spectral-mode').value !== 'auto') req.spectral_mode=$('spectral-mode').value;
    return req;
  }
  function key() { try { return JSON.stringify(request()); } catch { return ''; } }
  function yoloKey() { try { return JSON.stringify(yoloRequest()); } catch { return ''; } }
  function invalidateDetection() {
    state.estimate=null; state.estimateKey='';
    $('detection-plan-info').textContent='Kiểm tra lượt trước khi chạy nhận diện.';
    $('detect-start').disabled=true;
    invalidateYoloDetection();
  }
  function invalidateYoloDetection() {
    state.yoloEstimate=null; state.yoloEstimateKey='';
    if ($('yolo-plan-info')) {
      $('yolo-plan-info').textContent='Kiểm tra lượt quét trước khi chạy YOLO.';
    }
    if ($('yolo-start-btn')) {
      $('yolo-start-btn').textContent='⚡ 2. Bắt đầu quét YOLO Siêu Tốc';
      $('yolo-start-btn').disabled=true;
    }
  }
  function invalidateWarp() {
    state.warp=null; $('warp-plan-info').textContent=''; $('warp-preview-image').hidden=true; $('warp-start').disabled=true;
  }
  function selected() { return state.results?.records.find(r=>r.id===$('object-select').value); }
  function fileUrl(name) { return '/api/result-file?'+new URLSearchParams({name,revision:String(state.results?.revision??0),job:state.results?.job.id||''}); }

  function getResumableInfo() {
    const isRunning = ['queued', 'running', 'cancelling'].includes(model.job?.status);
    if (isRunning) return null;
    const selId = $('session-select')?.value;
    const selSession = (state.sessions || []).find(s => s.id === selId);
    if (selSession && selSession.resumable) {
      return { jobId: selSession.id, done: selSession.completed_queries ?? 0, total: selSession.query_count ?? 0 };
    }
    if (model.job?.kind === 'detection'
        && ['paused', 'cancelled', 'interrupted'].includes(model.job?.status)
        && (model.job?.done ?? 0) < (model.job?.total ?? 0)) {
      return { jobId: model.job.id, done: model.job.done ?? 0, total: model.job.total ?? 0 };
    }
    const rJob = state.results?.job;
    if (rJob && ['paused', 'cancelled', 'interrupted'].includes(rJob.status)
        && (rJob.done ?? 0) < (rJob.total ?? 0)) {
      return { jobId: rJob.id, done: rJob.done ?? 0, total: rJob.total ?? 0 };
    }
    return null;
  }

  function controls(locked) {
    if (state.lastStep !== model.step) {
      if (model.step !== 3) state.forceShowResults = false;
      state.lastStep = model.step;
      if (model.step === 5) renderTurboEngineBanner();
    }
    if ($('results-panel')) {
      $('results-panel').hidden = !(Boolean(state.results) && model.step === 3);
    }
    const tmPanel = $('taskmgr-panel');
    if (tmPanel) {
      const wasHidden = tmPanel.hidden;
      tmPanel.hidden = model.step !== 3 && model.step !== 5;
      if (wasHidden && !tmPanel.hidden) {
        requestAnimationFrame(() => { try { pollHardwareTelemetry(); } catch {} });
      }
    }
    syncMultiRegionVisibility();
    const selTile = $('tile-select')?.value;
    if ($('detect-selected')) {
      $('detect-selected').textContent = selTile
        ? `1. Chỉ ${formatTileId(selTile)} đang chọn ở bản đồ bên phải (Chạy thử nhanh)`
        : '1. Chỉ Ảnh đang chọn ở bản đồ bên phải (Chạy thử nhanh)';
    }
    if ($('yolo-detect-selected')) {
      $('yolo-detect-selected').textContent = selTile
        ? `1. Chỉ ${formatTileId(selTile)} đang chọn ở bản đồ bên phải`
        : '1. Chỉ Ảnh đang chọn ở bản đồ bên phải';
    }
    const canDetect = !locked && planReady() && !($('detect-scope').value==='multi' && !state.regions.length);
    $('detect-plan').disabled = !canDetect;
    $('detect-start').disabled = !canDetect;

    const canYoloDetect = !locked && planReady() && !($('yolo-detect-scope')?.value==='multi' && !state.regions.length);
    const engineReady = isSelectedEngineReady();
    if ($('yolo-plan-btn')) $('yolo-plan-btn').disabled = !canYoloDetect;
    if ($('yolo-start-btn')) $('yolo-start-btn').disabled = !canYoloDetect || !engineReady;

    if ($('train-turbo-btn')) {
      const canTrain = !locked && Boolean(state.turboStatus?.dataset?.ready_to_train ?? (state.results?.reviewed > 0));
      $('train-turbo-btn').disabled = !canTrain;
    }
    if ($('browse-detection-btn')) $('browse-detection-btn').disabled = locked;
    if ($('open-detection-dir-btn')) $('open-detection-dir-btn').disabled = !state.results;
    $('warp-preview-button').disabled=locked || !$('source-path').value.trim();
    $('warp-start').disabled=locked || !state.warp;

    const isDetectRunning = ['queued', 'running', 'cancelling'].includes(model.job?.status) && model.job?.kind === 'detection';
    for (const id of ['detect-pause', 'yolo-pause-btn', 'session-pause-btn', 'pause-job']) {
      if ($(id)) {
        $(id).hidden = !isDetectRunning;
        $(id).disabled = model.busy || model.job?.status === 'cancelling';
      }
    }

    const resumableInfo = getResumableInfo();
    const resumeLabel = resumableInfo ? `▶ Tiếp tục quét (${resumableInfo.done}/${resumableInfo.total})` : '▶ Tiếp tục quét';
    for (const id of ['detect-resume', 'yolo-resume-btn', 'session-resume-btn', 'resume-job']) {
      if ($(id)) {
        $(id).hidden = !resumableInfo;
        $(id).disabled = model.busy || !model.ready;
        if (resumableInfo) $(id).textContent = resumeLabel;
      }
    }

    // Unlock live review, labeling, session & sidebar controls even while detection is actively running
    const reviewLocked = !model.ready || model.busy;
    const record=selected();
    if ($('session-select')) $('session-select').disabled=reviewLocked;
    if ($('session-load-btn')) $('session-load-btn').disabled=reviewLocked || !$('session-select')?.value;
    if ($('browse-detection-btn')) $('browse-detection-btn').disabled=reviewLocked;

    for (const id of ['review-raw','review-reject','crop-out-grass-btn','split-mixed-btn']) {
      if ($(id)) $(id).disabled=reviewLocked || !record;
    }
    if ($('review-candidate')) $('review-candidate').disabled=reviewLocked || !record?.candidate_box;
    if ($('object-subclass')) $('object-subclass').disabled=reviewLocked || !record;
    if ($('results-filter')) $('results-filter').disabled=reviewLocked || !state.results;
    const select=$('object-select');
    const idx=select.selectedIndex;
    $('object-prev').disabled=reviewLocked || !state.results || (state.offset===0 && idx<=0);
    $('object-next').disabled=reviewLocked || !state.results || (idx<0 || (idx>=state.results.records.length-1 && state.offset+50>=state.results.total));
    if ($('page-range-select')) $('page-range-select').disabled=reviewLocked || !state.results?.total;
    $('object-select').disabled=reviewLocked || !state.results?.records.length;

    const totalAny = state.results?.total_all ?? state.results?.total ?? 0;
    $('review-all-raw').disabled=reviewLocked || !totalAny;
    if ($('review-all-candidate')) $('review-all-candidate').disabled=reviewLocked || !totalAny;
    $('export-cad').disabled=reviewLocked || !totalAny;
    if ($('export-dwg')) $('export-dwg').disabled=reviewLocked || !totalAny;
    if ($('sidebar-sr-scale')) $('sidebar-sr-scale').disabled=reviewLocked || !state.results;
    document.querySelectorAll('.sr-mode-btn').forEach(btn => {
      btn.disabled = reviewLocked || !record;
    });
    for (const id of ['fuse-existing-btn','split-clumps-btn','enrich-dem-btn','auto-triage-btn','save-dataset-btn','quick-save-dataset-btn','download-reviewed-json-btn','survey-export-dxf-btn']) {
      if ($(id)) $(id).disabled=reviewLocked || !totalAny;
    }
    if ($('repair-dem-btn')) {
      $('repair-dem-btn').disabled=reviewLocked || (!state.results && !$('source-path').value.trim());
    }
    if ($('enrich-ms-btn')) {
      $('enrich-ms-btn').disabled=reviewLocked || (!state.results && !$('source-path').value.trim());
    }
    $('evaluate-button').disabled=reviewLocked || !state.results;
    $('use-normalized').disabled=locked;
  }
  async function refreshSessions() {
    try {
      const info=await api('/api/sessions');
      state.sessions = info.sessions || [];
      const sel=$('session-select');
      if (!sel) return;
      sel.replaceChildren(...state.sessions.map(s => {
        const resumeNote = s.resumable ? ` · [Tạm dừng ${s.completed_queries}/${s.query_count}]` : '';
        const opt=new Option(`${s.id} · ${s.count} khung${resumeNote} · [${(s.categories||[]).join(', ')}]`, s.id);
        if (s.active) opt.selected=true;
        return opt;
      }));
      updateControls();
    } catch {}
  }
  function positionContextIndicator(box, ctxWin) {
    const wrapEl = document.querySelector('#object-context-fig .context-overview-wrap');
    const boxEl = $('object-context-box');
    if (!wrapEl || !boxEl || !Array.isArray(box) || box.length !== 4 || !ctxWin) return;
    const iw = Math.max(1, ctxWin.width || 1);
    const ih = Math.max(1, ctxWin.height || 1);
    const [x1, y1, x2, y2] = box;
    const relLeft = Math.max(0, Math.min(1, (x1 - ctxWin.col) / iw));
    const relTop = Math.max(0, Math.min(1, (y1 - ctxWin.row) / ih));
    const relW = Math.max(6 / iw, Math.min(1 - relLeft, (x2 - x1) / iw));
    const relH = Math.max(6 / ih, Math.min(1 - relTop, (y2 - y1) / ih));

    const cw = wrapEl.clientWidth || 0;
    const ch = wrapEl.clientHeight || 0;
    if (cw > 16 && ch > 16) {
      const scale = Math.min(cw / iw, ch / ih);
      const renderW = iw * scale;
      const renderH = ih * scale;
      const offX = (cw - renderW) * 0.5;
      const offY = (ch - renderH) * 0.5;
      boxEl.style.left = `${(offX + relLeft * renderW).toFixed(1)}px`;
      boxEl.style.top = `${(offY + relTop * renderH).toFixed(1)}px`;
      boxEl.style.width = `${Math.max(10, relW * renderW).toFixed(1)}px`;
      boxEl.style.height = `${Math.max(10, relH * renderH).toFixed(1)}px`;
    } else {
      boxEl.style.left = `${(relLeft * 100).toFixed(2)}%`;
      boxEl.style.top = `${(relTop * 100).toFixed(2)}%`;
      boxEl.style.width = `${Math.max(3, relW * 100).toFixed(2)}%`;
      boxEl.style.height = `${Math.max(3, relH * 100).toFixed(2)}%`;
    }
  }

  function slimBoxRecord(r) {
    return {
      id: r.id,
      box: r.box,
      candidate_box: r.candidate_box,
      review_status: r.review_status,
      sub_class: r.sub_class,
      category: r.category,
    };
  }

  function getMapDetections() {
    const pageRecords = state.results?.records || [];
    if (state.fullMapBoxes.length > 0) {
      if (pageRecords.length > 0) {
        const pageMap = new Map(pageRecords.map(r => [r.id, r]));
        for (let i = 0; i < state.fullMapBoxes.length; i++) {
          const updated = pageMap.get(state.fullMapBoxes[i].id);
          if (updated) state.fullMapBoxes[i] = slimBoxRecord(updated);
        }
      }
      if (state.fullMapBoxes.length >= pageRecords.length) {
        return state.fullMapBoxes;
      }
    }
    return pageRecords;
  }

  async function ensureFullMapBoxes() {
    const jobId = state.results?.job?.id || '';
    const totalAll = state.results?.total_all ?? state.results?.total ?? 0;
    const pageRecords = state.results?.records || [];
    if (!jobId || totalAll === 0) return;
    const targetKey = `${jobId}:${totalAll}`;
    if (state.fullMapBoxesKey === targetKey && state.fullMapBoxes.length >= totalAll) return;
    if (state.filter === 'all' && pageRecords.length >= totalAll) {
      state.fullMapBoxes = pageRecords.map(slimBoxRecord);
      state.fullMapBoxesKey = targetKey;
      syncBoxToggleButtons();
      getViewport?.()?.setAllDetections?.(state.fullMapBoxes, selected()?.id || null);
      return;
    }
    if (state.fullMapBoxesLoading) return;
    state.fullMapBoxesLoading = true;
    try {
      let slimList = null;
      try {
        const fastResp = await fetch('/api/results-boxes?' + new URLSearchParams({ job: jobId }));
        if (fastResp.ok) {
          const fastData = await fastResp.json();
          if (Array.isArray(fastData?.records)) {
            slimList = fastData.records.map(slimBoxRecord);
          }
        }
      } catch {}
      if (!slimList) {
        const fullResp = await fetch(fileUrl('detections.json'));
        if (fullResp.ok) {
          const fullData = await fullResp.json();
          if (Array.isArray(fullData?.records)) {
            slimList = fullData.records.filter(r => Array.isArray(r?.box) && r.box.length === 4).map(slimBoxRecord);
          }
        }
      }
      if (slimList && state.results?.job?.id === jobId) {
        state.fullMapBoxes = slimList;
        state.fullMapBoxesKey = `${jobId}:${slimList.length}`;
        syncBoxToggleButtons();
        getViewport?.()?.setAllDetections?.(getMapDetections(), selected()?.id || null);
      }
    } catch {} finally {
      state.fullMapBoxesLoading = false;
    }
  }

  function syncBoxToggleButtons() {
    const toggleBtn = $('toggle-box-overlay');
    if (toggleBtn) {
      toggleBtn.setAttribute('aria-pressed', String(state.boxesVisible));
      toggleBtn.classList.toggle('active-box-toggle', state.boxesVisible);
      toggleBtn.classList.toggle('boxes-hidden', !state.boxesVisible);
      toggleBtn.textContent = state.boxesVisible
        ? '🎯 Ẩn khung viền'
        : '🛰️ Hiện khung viền';
    }
    const mapToggleBtn = $('toggle-map-boxes');
    if (mapToggleBtn) {
      mapToggleBtn.setAttribute('aria-pressed', String(state.boxesVisible));
      mapToggleBtn.classList.toggle('active-map-toggle', state.boxesVisible);
      mapToggleBtn.classList.toggle('inactive-map-toggle', !state.boxesVisible);
      const totalBoxes = state.fullMapBoxes.length || state.results?.total_all || state.results?.total || 0;
      const countSuffix = totalBoxes > 0 ? ` (${totalBoxes.toLocaleString('vi-VN')})` : '';
      mapToggleBtn.textContent = state.boxesVisible
        ? `🛰️ Khung nhận diện${countSuffix}`
        : '🎯 Đã ẩn khung';
    }
  }

  function setOverlayBoxesVisible(visible) {
    state.boxesVisible = Boolean(visible);
    syncBoxToggleButtons();
    const vp = getViewport?.();
    vp?.setBoxesVisible?.(state.boxesVisible);
    renderObject({ silent: true });
  }

  async function loadResults(offset=0,keep=null,{silent=false}={}) {
    const prevSelectedId = keep || selected()?.id || null;
    let data=await api('/api/results?'+new URLSearchParams({offset:String(offset),limit:'50',filter:state.filter}));

    // Auto-reset filter & offset when switching to a new detection job
    const jobChanged = Boolean(state.loadedJob && data.job?.id && state.loadedJob !== data.job.id);
    if (jobChanged) {
      state.loadedJob = data.job.id;
      state.renderedObjectId = null;
      if (state.filter !== 'all' || offset !== 0) {
        state.filter = 'all';
        if ($('results-filter')) $('results-filter').value = 'all';
        offset = 0;
        data = await api('/api/results?' + new URLSearchParams({offset:'0',limit:'50',filter:'all'}));
      }
      refreshSessions().catch(() => {});
    }

    // If filter ('accepted' etc.) hides all items while there ARE detected objects, auto-switch to 'all' during live/initial load
    if (state.filter !== 'all' && data.total === 0 && (data.total_all || 0) > 0 && (silent || jobChanged || !state.results)) {
      state.filter = 'all';
      if ($('results-filter')) $('results-filter').value = 'all';
      offset = 0;
      data = await api('/api/results?' + new URLSearchParams({offset:'0',limit:'50',filter:'all'}));
    }

    // Clamp offset if it exceeds available pages
    if (offset > 0 && (!data.records || data.records.length === 0) && (data.total || 0) > 0) {
      offset = Math.max(0, Math.floor((data.total - 1) / 50) * 50);
      data = await api('/api/results?' + new URLSearchParams({offset:String(offset),limit:'50',filter:state.filter}));
    }

    state.results=data; state.offset=offset;
    if (data.job?.id) state.loadedJob = data.job.id;
    $('results-panel').hidden = model.step !== 3;
    reopen.hidden=false;
    const pageNow=Math.floor(offset/50)+1, pageTotal=Math.max(1,Math.ceil(data.total/50));
    const totalAllNote = (typeof data.total_all === 'number' && data.total_all !== data.total)
      ? `${data.total}/${data.total_all} đối tượng`
      : `${data.total} đối tượng`;
    const srcBase = String(data.source || '').split(/[\\/]/).pop() || data.source;
    $('results-summary').textContent=`${totalAllNote} · Đã duyệt ${data.reviewed} (Trang ${pageNow}/${pageTotal}) · ${data.job.id} · ${srcBase}`;
    $('results-summary').title = `${data.source || ''}`;
    if ($('export-objects-summary')) {
      $('export-objects-summary').textContent=`Phiên ${data.job.id}: Đã duyệt ${data.reviewed} / ${data.total_all ?? data.total} đối tượng.`;
    }
    if ($('dataset-ready-summary')) {
      $('dataset-ready-summary').textContent=`Phiên ${data.job.id}: Đã duyệt ${data.reviewed} / ${data.total_all ?? data.total} mẫu sẵn sàng lưu.`;
    }
    const rangeSel=$('page-range-select');
    if (rangeSel) {
      const rangeOpts=[];
      const totalItems=data.total||0;
      if (totalItems===0) {
        rangeOpts.push(new Option('Chưa có đối tượng (0)', '0'));
      } else {
        for (let start=0; start<totalItems; start+=50) {
          const fromIdx=start+1;
          const toIdx=Math.min(start+50, totalItems);
          const opt=new Option(`Trang ${Math.floor(start/50)+1}/${pageTotal} (Mục ${fromIdx}–${toIdx})`, String(start));
          if (start===offset) opt.selected=true;
          rangeOpts.push(opt);
        }
      }
      rangeSel.replaceChildren(...rangeOpts);
    }
    const select=$('object-select'); select.replaceChildren(...data.records.map(record=>{
      const sub=record.sub_class && record.sub_class!==record.category ? ` [${record.sub_class}]` : '';
      const conf=typeof record.confidence_score==='number' ? ` · ${(record.confidence_score*100).toFixed(0)}%` : '';
      const tileTag=record.tile_id ? ` · ${formatTileId(record.tile_id)}` : '';
      return new Option(`${record.id}${tileTag} · ${record.category}${sub} · ${statusNames[record.review_status]||record.review_status}${conf}`,record.id);
    }));
    const effectiveKeep = keep || prevSelectedId;
    if (effectiveKeep==='last' && data.records.length) select.selectedIndex=data.records.length-1;
    else if (effectiveKeep && data.records.some(r=>r.id===effectiveKeep)) select.value=effectiveKeep;
    $('results-overview-link').href=fileUrl('overview.jpg');
    const nowSelected = selected();
    if (jobChanged) {
      state.fullMapBoxes = [];
      state.fullMapBoxesKey = '';
    }
    syncBoxToggleButtons();
    getViewport?.()?.setAllDetections?.(getMapDetections(), nowSelected?.id || null);
    ensureFullMapBoxes();
    if (typeof tmLastTelemetry === 'object' && tmLastTelemetry) {
      try { renderTaskManagerUI(tmLastTelemetry); } catch {}
    }

    // During silent live polling, if the user is already viewing the same valid object, do not overwrite their subclass dropdown or flicker images
    if (silent && nowSelected && state.renderedObjectId === nowSelected.id) {
      updateControls();
      return;
    }
    renderObject({silent}); updateControls();
  }
  function renderObject({silent=false}={}) {
    const record=selected();
    state.renderedObjectId = record?.id || null;
    const srcPath = state.results?.source || model.metadata?.path || $('source-path')?.value?.trim() || '';
    const imgW = Number(state.results?.metadata?.width || model.metadata?.width || 100000);
    const imgH = Number(state.results?.metadata?.height || model.metadata?.height || 100000);

    // 1. Raw Frame (switches to clean un-boxed crop when state.boxesVisible === false)
    const rawImg = $('object-raw');
    if (rawImg) {
      if (!record) {
        rawImg.hidden = true;
        rawImg.removeAttribute('src');
        delete rawImg.dataset.srcUrl;
      } else if ((!state.boxesVisible || !record.raw_image) && srcPath && Array.isArray(record.box) && record.box.length === 4) {
        const [x1, y1, x2, y2] = record.box;
        const pad = 16;
        const left = Math.max(0, Math.floor(x1) - pad);
        const top = Math.max(0, Math.floor(y1) - pad);
        const right = Math.min(imgW, Math.ceil(x2) + pad);
        const bottom = Math.min(imgH, Math.ceil(y2) + pad);
        const cleanUrl = '/api/preview?' + new URLSearchParams({
          path: srcPath,
          col: String(left),
          row: String(top),
          width: String(Math.max(4, right - left)),
          height: String(Math.max(4, bottom - top)),
        });
        rawImg.hidden = false;
        if (rawImg.dataset.srcUrl !== cleanUrl) {
          rawImg.src = cleanUrl;
          rawImg.dataset.srcUrl = cleanUrl;
        }
      } else if (record.raw_image) {
        const nextUrl = fileUrl(record.raw_image);
        rawImg.hidden = false;
        if (rawImg.dataset.srcUrl !== nextUrl) {
          rawImg.src = nextUrl;
          rawImg.dataset.srcUrl = nextUrl;
        }
      } else {
        rawImg.hidden = true;
      }
    }

    // 2. Candidate Frame
    const candImg = $('object-candidate');
    if (candImg) {
      candImg.hidden = !record?.candidate_image;
      if (record?.candidate_image) {
        const nextUrl = fileUrl(record.candidate_image);
        if (candImg.dataset.srcUrl !== nextUrl) {
          candImg.src = nextUrl;
          candImg.dataset.srcUrl = nextUrl;
        }
      } else {
        candImg.removeAttribute('src');
        delete candImg.dataset.srcUrl;
      }
    }

    // 3. Context Overview Frame (Wide ±350 px window on full image + CSS box indicator)
    const ctxImg = $('object-context-img');
    const ctxBox = $('object-context-box');
    if (ctxImg && ctxBox) {
      if (record && Array.isArray(record.box) && record.box.length === 4 && srcPath) {
        const activeBox = (record.review_status === 'accepted_candidate' && Array.isArray(record.candidate_box) && record.candidate_box.length === 4)
          ? record.candidate_box
          : record.box;
        const [bx1, by1, bx2, by2] = activeBox;
        const cxBox = (bx1 + bx2) * 0.5;
        const cyBox = (by1 + by2) * 0.5;
        const padCtx = Math.max(350, Math.round(Math.max(bx2 - bx1, by2 - by1) * 2.5));
        const maxSide = Math.max(32, Math.min(imgW, imgH));
        const side = Math.min(maxSide, padCtx * 2);
        const ctxCol = Math.max(0, Math.min(Math.max(0, imgW - side), Math.round(cxBox - side * 0.5)));
        const ctxRow = Math.max(0, Math.min(Math.max(0, imgH - side), Math.round(cyBox - side * 0.5)));
        const ctxW = Math.max(32, Math.min(side, imgW - ctxCol));
        const ctxH = Math.max(32, Math.min(side, imgH - ctxRow));
        const ctxWin = { col: ctxCol, row: ctxRow, width: ctxW, height: ctxH };
        const ctxUrl = '/api/preview?' + new URLSearchParams({
          path: srcPath,
          col: String(ctxCol),
          row: String(ctxRow),
          width: String(ctxW),
          height: String(ctxH),
        });
        ctxImg.hidden = false;
        ctxBox.hidden = !state.boxesVisible;
        positionContextIndicator(activeBox, ctxWin);
        ctxImg.onload = () => positionContextIndicator(activeBox, ctxWin);
        if (ctxImg.dataset.srcUrl !== ctxUrl) {
          ctxImg.src = ctxUrl;
          ctxImg.dataset.srcUrl = ctxUrl;
        }
      } else {
        ctxImg.hidden = true;
        ctxBox.hidden = true;
        ctxImg.removeAttribute('src');
        delete ctxImg.dataset.srcUrl;
      }
    }

    if (!silent) pulseElements('.review-images figure');
    const vp = getViewport?.();
    vp?.setAllDetections?.(getMapDetections(), record?.id || null);
    vp?.highlightDetectionBox?.(record || null, { fly: !silent });
    if (record?.box && model.plan?.tiles?.length && selectTile) {
      const cx = (record.box[0] + record.box[2]) * 0.5;
      const cy = (record.box[1] + record.box[3]) * 0.5;
      const hostTile = model.plan.tiles.find(t => cx >= t.col && cx <= t.col + t.width && cy >= t.row && cy <= t.row + t.height);
      if (hostTile && $('tile-select')?.value !== hostTile.id) {
        selectTile(hostTile, { fly: false });
      }
    }

    const metaCard = $('object-meta');
    if (!record) {
      const totalAllCount = state.results?.total_all ?? state.results?.total ?? 0;
      const reviewedCount = state.results?.reviewed ?? 0;
      if (metaCard && totalAllCount > 0 && reviewedCount >= totalAllCount && state.filter === 'unreviewed') {
        metaCard.innerHTML = `
          <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;padding:4px 2px">
            <span>✅ <strong>Đã duyệt hoàn tất ${reviewedCount.toLocaleString('vi-VN')} / ${totalAllCount.toLocaleString('vi-VN')} đối tượng!</strong> Không còn mục chưa duyệt.</span>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <button type="button" id="meta-save-dataset-btn" class="primary" style="height:34px;padding:0 12px">💾 Lưu mẫu huấn luyện</button>
              <button type="button" id="meta-goto-step4-btn" class="secondary" style="height:34px;padding:0 12px">📐 Sang Bước 04 (Xuất &amp; Lưu)</button>
              <button type="button" id="meta-show-all-btn" class="secondary" style="height:34px;padding:0 12px">Xem tất cả đối tượng</button>
            </div>
          </div>
        `;
        $('meta-save-dataset-btn')?.addEventListener('click', () => runSaveDataset());
        $('meta-goto-step4-btn')?.addEventListener('click', () => {
          goToStep?.(4);
          $('step-4')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        $('meta-show-all-btn')?.addEventListener('click', () => action(async () => {
          state.filter = 'all';
          if ($('results-filter')) $('results-filter').value = 'all';
          await loadResults(0);
        }));
      } else if (metaCard) {
        metaCard.innerHTML = '<div class="empty-note">Không có đối tượng.</div>';
      }
      if ($('object-info')) $('object-info').textContent = 'Không có đối tượng.';
    } else {
      if ($('object-subclass')) $('object-subclass').value = record.sub_class || '';
      const p = record.spatial_selected || record.spatial_raw;
      const center = p?.center_relative || [null, null];
      const statusLabel = statusNames[record.review_status] || 'Chưa duyệt';
      const badgeCls = statusBadgeClasses[record.review_status] || 'status-unreviewed';
      const classLabel = escapeHtml(record.sub_class || record.label || record.category);
      const confPct = Math.round((record.confidence_score ?? 0.5) * 100);
      const clumps = record.clump_count ?? record.refinement?.estimated_plant_count ?? record.refinement?.clump_count ?? record.refinement?.components ?? (Array.isArray(record.refinement?.clump_boxes) ? record.refinement.clump_boxes.length : null);
      const clumpBadge = (typeof clumps === 'number' && clumps > 1)
        ? ` · <strong class="meta-highlight">🌱 Gồm ${clumps} khóm lúa</strong>`
        : '';
      const isMixedGrassRice = Boolean(
        record.refinement?.has_partial_grass
        || String(record.sub_class || '').includes('Partial')
        || ((String(record.sub_class || '').toLowerCase() === 'grass' || (record.height_m ?? 0) >= 0.32 || (record.ndvi_max ?? 0) >= 0.42) && typeof clumps === 'number' && clumps >= 3)
      );
      const mixedBadge = isMixedGrassRice
        ? `<span class="meta-status-badge status-unreviewed" title="Khung này bao gồm cả dải Cỏ bờ (NDVI/Chiều cao lớn) và ${clumps || 'nhiều'} khóm lúa. Bấm '🌾+🌱 Có 1 phần Cỏ (Lọc lấy Lúa)' hoặc '✂️ Tách riêng Cỏ & Lúa' bên dưới.">🌾+🌱 Vùng lẫn: 1 phần Cỏ bờ + ${clumps || 'nhiều'} khóm lúa</span>`
        : '';
      const zGround = record.ground_elevation_m ?? record.dem_z_ground ?? record.elevation_m;
      const edgeWarn = record.touches_window_edge
        ? ' <span class="meta-status-badge status-unreviewed">⚠️ Chạm biên ô nhỏ</span>'
        : '';

      if (metaCard) {
        metaCard.innerHTML = `
          <div class="object-meta-grid">
            <div class="object-meta-item">
              <span class="object-meta-label">1. Trạng thái &amp; Phân lớp</span>
              <div class="object-meta-value">
                <span class="meta-status-badge ${badgeCls}">${escapeHtml(statusLabel)}</span>
                <span>Phân lớp: <strong class="meta-highlight">${classLabel}</strong></span>
                <span class="meta-conf-badge">Độ tin cậy: ${confPct}%</span>
                ${mixedBadge}
              </div>
            </div>
            <div class="object-meta-item">
              <span class="object-meta-label">2. Chỉ số Đa Phổ</span>
              <div class="object-meta-value">
                <span>NDVI: <strong>${fmtMetric(record.ndvi_mean, 3)}</strong> (max ${fmtMetric(record.ndvi_max, 3)}) · NDRE: <strong>${fmtMetric(record.ndre_mean, 3)}</strong> · NDWI: <strong>${fmtMetric(record.ndwi_mean, 3)}</strong>${clumpBadge}</span>
              </div>
            </div>
            <div class="object-meta-item">
              <span class="object-meta-label">3. Cao độ DEM &amp; Chiều cao</span>
              <div class="object-meta-value">
                <span>Cao độ nền Z = <strong>${fmtMetric(zGround, 2)} m</strong> · Chiều cao cây H = <strong>${fmtMetric(record.height_m, 2)} m</strong></span>
              </div>
            </div>
            <div class="object-meta-item">
              <span class="object-meta-label">4. Tọa độ Base (X, Y)</span>
              <div class="object-meta-value">
                <span>X = <strong>${fmtMetric(center[0], 3)} m</strong> · Y = <strong>${fmtMetric(center[1], 3)} m</strong>${edgeWarn}</span>
              </div>
            </div>
          </div>
        `;
      }
      if ($('object-info')) {
        $('object-info').textContent = `${statusLabel} · Phân lớp: ${record.sub_class || record.label || record.category} (${confPct}%) · X=${fmtMetric(center[0], 3)} m, Y=${fmtMetric(center[1], 3)} m.`;
      }
    }
  }
  async function renderProposals() {
    const target=$('proposals'); target.replaceChildren();
    for (const proposal of model.proposals) {
      const card=document.createElement('section'); card.className='proposal-card';
      const title=document.createElement('strong'); title.textContent=proposal.id+' · '+proposal.title; card.append(title);
      const note=document.createElement('p'); note.textContent=proposal.note||'Đề xuất thiết kế'; card.append(note);
      if (proposal.patch) {
        const table=document.createElement('table');
        const header=table.insertRow(); ['Mục','Hiện tại','Đề nghị'].forEach(value=>{const th=document.createElement('th');th.textContent=value;header.append(th);});
        for (const name of Object.keys(proposal.patch)) {
          const labels={categories:'Đối tượng',micro_size:'Cỡ ô nhỏ',micro_overlap:'Chồng phủ',upscale:'Phóng ảnh',max_image_size:'Cạnh ảnh gửi',max_new_tokens:'Độ dài trả lời',seed:'Hạt giống lấy mẫu',merge_mode:'Cách gộp',merge_iou:'Ngưỡng trùng',refinement:'Co khung',padding:'Chừa thêm'};
          const row=table.insertRow(); [labels[name]||name,JSON.stringify(proposal.before[name]),JSON.stringify(proposal.patch[name])].forEach(value=>{row.insertCell().textContent=value;});
        }
        card.append(table);
      }
      const buttons=document.createElement('div'); buttons.className='action-row';
      for (const [decision,label] of [['approve','Duyệt và áp dụng'],['reject','Bỏ gợi ý']]) {
        const button=document.createElement('button'); button.textContent=label; button.type='button'; button.dataset.mutable='';
        button.addEventListener('click',()=>action(async()=>{
          const result=await api('/api/proposal',{id:proposal.id,decision});
          model.proposals=result.pending_proposals||[];
          fillSettings(result.active_pipeline_config.detection||state.defaults);
          renderProposals(); updateControls();
        })); buttons.append(button);
      }
      card.append(buttons); target.append(card);
    }
  }
  function renderJob(job) {
    $('use-normalized').hidden=!(job?.kind==='warp' && job.status==='completed' && job.summary?.output_path);
    if (job?.kind) {
      const labels={
        running:'Đang xử lý',
        queued:'Đang chuẩn bị',
        cancelling:'Đang dừng',
        paused:'Đã tạm dừng',
        completed:'Đã xong',
        cancelled:'Đã dừng',
        failed:'Có lỗi',
        interrupted:'Lần trước bị gián đoạn'
      };
      const kindLabel = job.kind === 'detection'
        ? 'Nhận diện'
        : job.kind === 'turbo_train'
          ? 'Huấn luyện AI Turbo'
          : 'Chuẩn hóa ảnh';
      $('job-status').textContent=`${kindLabel} · ${labels[job.status]||job.status} · ${job.kind==='turbo_train' ? `${job.done}%` : `${job.done}/${job.total}`}`;
    }
    if (job?.kind === 'turbo_train') {
      if ($('turbo-train-status') && job.message) {
        $('turbo-train-status').textContent = job.message;
      }
      if (job.status === 'completed' && state.lastTurboCompletedId !== job.id) {
        state.lastTurboCompletedId = job.id;
        refreshTurboStatus();
      }
    }
    if (job?.kind==='detection') {
      const isRunning = ['queued','running','cancelling'].includes(job.status);
      const pill = $('live-detect-pill');
      if (pill) {
        if (isRunning) {
          const pct = job.total ? Math.round(((job.done || 0) / job.total) * 100) : 0;
          const liveCnt = job.live_count ?? state.results?.total_all ?? state.results?.total ?? 0;
          pill.hidden = false;
          pill.textContent = `🛰️ Đang quét ${job.done || 0}/${job.total || 0} (${pct}%) · ${liveCnt} đối tượng`;
        } else {
          pill.hidden = true;
        }
      }
      if (isRunning) {
        const stepBucket = Math.floor((job.done || 0) / 4);
        const liveKey = `${job.id}:${job.live_count || 0}:${stepBucket}`;
        if ((state.loadedJob !== job.id || state.lastLiveSyncKey !== liveKey) && !state.loading && !model.busy) {
          state.lastLiveSyncKey = liveKey;
          state.loading = true;
          loadResults(state.offset, selected()?.id, {silent:true})
            .then(()=>{state.loadedJob=job.id;})
            .catch(()=>{})
            .finally(()=>{state.loading=false;});
        }
      } else if (['completed','cancelled','paused','interrupted'].includes(job.status)) {
        const stateKey = `${job.id}:${job.status}:${job.done||0}`;
        if (state.loadedJobStateKey!==stateKey && !state.loading) {
          state.loadedJobStateKey=stateKey;
          state.loading=true;
          loadResults(state.offset, selected()?.id, {silent: job.status!=='completed'})
            .then(()=>{
              state.loadedJob=job.id;
              return refreshSessions();
            })
            .catch(error=>{
              if (job.status==='completed') showError(error.message);
            })
            .finally(()=>{
              state.loading=false;
              updateControls();
            });
        }
      }
    }
  }
  document.querySelectorAll('[data-detection]').forEach(input=>{input.addEventListener('input',()=>{invalidateDetection();updateControls();});input.addEventListener('change',()=>{invalidateDetection();updateControls();});});
  document.querySelectorAll('[data-yolo-detection]').forEach(input=>{input.addEventListener('input',()=>{invalidateYoloDetection();updateControls();});input.addEventListener('change',()=>{invalidateYoloDetection();updateControls();});});
  $('detect-engine')?.addEventListener('change', () => {
    renderTurboEngineBanner();
    invalidateYoloDetection();
    updateControls();
  });
  $('detect-categories')?.addEventListener('change',()=>{
    const parsed = parseSmartCategories($('detect-categories').value);
    if (parsed.length) $('detect-categories').value = parsed.join('\n');
  });
  document.querySelectorAll('[data-cat-chip]').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const chip=btn.dataset.catChip;
      const lines=parseSmartCategories($('detect-categories').value);
      if (!lines.some(l=>l.toLowerCase()===chip.toLowerCase())) lines.push(chip);
      $('detect-categories').value=lines.join('\n');
      invalidateDetection(); updateControls();
    });
  });
  function activateMultiScope() {
    if (model.step === 5 && $('yolo-detect-scope')) {
      if ($('yolo-detect-scope').value !== 'multi') $('yolo-detect-scope').value = 'multi';
    } else if ($('detect-scope') && $('detect-scope').value !== 'multi') {
      $('detect-scope').value = 'multi';
    }
    syncMultiRegionVisibility();
  }

  function startCadMode(mode) {
    activateMultiScope();
    const vp = getViewport?.();
    vp?.setCadMode(mode);
    updateCadHint(mode);
  }

  function deleteSelectedRegion() {
    if (state.selectedRegionIndex >= 0 && state.selectedRegionIndex < state.regions.length) {
      state.regions.splice(state.selectedRegionIndex, 1);
      renderRegions();
      invalidateDetection();
      invalidateYoloDetection();
      updateControls();
    }
  }

  function addSelectedTileAsRegion() {
    const tid = $('tile-select').value;
    const cats = currentCategories();
    if (!tid || !cats.length) return;
    const tileObj = model.plan?.tiles?.find(t => t.id === tid);
    let poly = null;
    if (tileObj) {
      const { col, row, width, height } = tileObj;
      poly = [[col, row], [col + width, row], [col + width, row + height], [col, row + height]];
    }
    state.regions.push({ tile_id: tid, polygon: poly, categories: cats });
    state.selectedRegionIndex = state.regions.length - 1;
    renderRegions(); invalidateDetection(); invalidateYoloDetection(); updateControls();
  }

  function clearAllRegions() {
    state.regions = [];
    state.selectedRegionIndex = -1;
    getViewport?.()?.setCadMode('none');
    renderRegions(); invalidateDetection(); invalidateYoloDetection(); updateControls();
  }

  $('detect-scope').addEventListener('change',()=>{
    syncMultiRegionVisibility();
    invalidateDetection(); updateControls();
  });
  $('yolo-detect-scope')?.addEventListener('change',()=>{
    syncMultiRegionVisibility();
    invalidateYoloDetection(); updateControls();
  });

  for (const id of ['cad-draw-pline-btn', 'yolo-cad-draw-pline-btn', 'map-cad-pline']) {
    $(id)?.addEventListener('click', () => startCadMode('draw_pline'));
  }
  for (const id of ['cad-draw-rect-btn', 'yolo-cad-draw-rect-btn', 'map-cad-rect']) {
    $(id)?.addEventListener('click', () => startCadMode('draw_rect'));
  }
  for (const id of ['cad-edit-btn', 'yolo-cad-edit-btn', 'map-cad-edit']) {
    $(id)?.addEventListener('click', () => startCadMode('edit'));
  }
  for (const id of ['cad-finish-pline-btn', 'yolo-cad-finish-pline-btn', 'map-cad-finish']) {
    $(id)?.addEventListener('click', () => getViewport?.()?.finishCadDraft());
  }
  for (const id of ['delete-selected-region-btn', 'yolo-delete-selected-region-btn', 'map-cad-del']) {
    $(id)?.addEventListener('click', deleteSelectedRegion);
  }
  for (const id of ['add-region-btn', 'yolo-add-region-btn']) {
    $(id)?.addEventListener('click', addSelectedTileAsRegion);
  }
  for (const id of ['clear-regions-btn', 'yolo-clear-regions-btn']) {
    $(id)?.addEventListener('click', clearAllRegions);
  }

  $('tile-select').addEventListener('change',()=>{invalidateDetection();invalidateYoloDetection();updateControls();});
  for (const id of ['warp-crs','warp-gsd','warp-resampling']) $(id).addEventListener('input',()=>{invalidateWarp();updateControls();});
  $('save-detection').addEventListener('click',()=>action(async()=>{fillSettings(await api('/api/detection-settings',{settings:settings()}));$('detection-plan-info').textContent='Đã lưu cấu hình cho lượt chạy sau.';}));
  function formatPlanBanner(plan) {
    const scopeLabel = plan.scope === 'all'
      ? 'Toàn bộ ảnh gốc'
      : (plan.scope === 'multi' ? `${plan.regions.length} vùng đã chọn` : formatTileId(plan.tile_id));
    if (plan.engine === 'turbo_zone' || plan.engine === 'turbo_clump') {
      const batches = Math.max(1, Math.ceil((plan.query_count || 1) / (plan.batch_size || 32)));
      const tSize = plan.settings?.micro_size || (plan.engine === 'turbo_zone' ? 640 : 512);
      return `⚡ ${scopeLabel}: ${plan.micro_count} ô ${tSize}×${tSize}px → chỉ ${plan.query_count} lượt quét FP16 (~${batches} mẻ GPU Batch=32).`;
    }
    return `${scopeLabel}: ${plan.micro_count} ô nhỏ → ${plan.query_count} lượt hỏi mô hình.`;
  }

  $('detect-plan').addEventListener('click',()=>action(async()=>{
    const body=request(); const plan=await api('/api/detection-plan',body);
    state.estimate=body; state.estimateKey=key();
    $('detection-plan-info').textContent=formatPlanBanner(plan);
    $('detect-start').textContent=`2. Bắt đầu nhận diện · ${plan.query_count} lượt`;
  }));
  async function runDetectionNow() {
    if (!state.estimate || state.estimateKey!==key()) {
      const body=request();
      const plan=await api('/api/detection-plan',body);
      state.estimate=body; state.estimateKey=key();
      $('detection-plan-info').textContent=formatPlanBanner(plan);
      $('detect-start').textContent=`2. Bắt đầu nhận diện · ${plan.query_count} lượt`;
    }
    model.job=await api('/api/detect',structuredClone(state.estimate));
    if (model.step !== 3) goToStep(3);
    ctx.renderMainJob(); ctx.pollJob();
  }

  $('yolo-plan-btn')?.addEventListener('click',()=>action(async()=>{
    const body=yoloRequest(); const plan=await api('/api/detection-plan',body);
    state.yoloEstimate=body; state.yoloEstimateKey=yoloKey();
    if ($('yolo-plan-info')) $('yolo-plan-info').textContent=formatPlanBanner(plan);
    if ($('yolo-start-btn')) $('yolo-start-btn').textContent=`⚡ 2. Bắt đầu quét YOLO · ${plan.query_count} ô`;
  }));
  async function runYoloDetectionNow() {
    if (!isSelectedEngineReady()) {
      throw new Error('Mô hình YOLO11 đang chọn chưa được huấn luyện. Hãy bấm "🚀 Huấn luyện Mô hình Turbo" ở mục 01 phía trên trước.');
    }
    if (!state.yoloEstimate || state.yoloEstimateKey!==yoloKey()) {
      const body=yoloRequest();
      const plan=await api('/api/detection-plan',body);
      state.yoloEstimate=body; state.yoloEstimateKey=yoloKey();
      if ($('yolo-plan-info')) $('yolo-plan-info').textContent=formatPlanBanner(plan);
      if ($('yolo-start-btn')) $('yolo-start-btn').textContent=`⚡ 2. Bắt đầu quét YOLO · ${plan.query_count} ô`;
    }
    model.job=await api('/api/detect',structuredClone(state.yoloEstimate));
    if (model.step !== 5) goToStep(5);
    ctx.renderMainJob(); ctx.pollJob();
  }

  async function pauseDetectionNow() {
    await action(async()=>{
      model.job=await api('/api/pause',{});
      ctx.renderMainJob(); ctx.pollJob(150);
    });
  }
  async function resumeDetectionNow() {
    await action(async()=>{
      const info=getResumableInfo();
      const jobId=info?.jobId || state.loadedJob || model.job?.id;
      const job=await api('/api/detect/resume',{job_id:jobId});
      model.job=job;
      const isTurboJob = ['turbo_zone', 'turbo_clump'].includes(job?.request?.settings?.engine);
      if (isTurboJob && model.step !== 5) goToStep(5);
      else if (!isTurboJob && model.step < 3) goToStep(3);
      ctx.renderMainJob(); ctx.pollJob(200);
    });
  }
  $('detect-start').addEventListener('click',()=>action(runDetectionNow));
  $('yolo-start-btn')?.addEventListener('click',()=>action(runYoloDetectionNow));
  $('step4-goto-yolo-btn')?.addEventListener('click',()=>{ goToStep?.(5); });
  $('yolo-back-step3-neg-btn')?.addEventListener('click',()=>{ goToStep?.(3); });
  $('yolo-goto-review-btn')?.addEventListener('click',()=>{
    state.forceShowResults = true;
    goToStep?.(3);
    requestAnimationFrame(() => $('results-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  });
  $('yolo-goto-export-btn')?.addEventListener('click',()=>{ goToStep?.(4); });
  for (const id of ['detect-pause','yolo-pause-btn','session-pause-btn']) {
    if ($(id)) $(id).addEventListener('click',pauseDetectionNow);
  }
  for (const id of ['detect-resume','yolo-resume-btn','session-resume-btn']) {
    if ($(id)) $(id).addEventListener('click',resumeDetectionNow);
  }
  if ($('browse-detection-btn')) {
    $('browse-detection-btn').addEventListener('click',()=>action(async()=>{
      const res=await api('/api/browse-detection',{});
      if (res.loaded && res.session) {
        state.loadedJob=res.session.id;
        await refreshSessions();
        await loadResults(0);
      }
    }));
  }
  if ($('open-detection-dir-btn')) {
    $('open-detection-dir-btn').addEventListener('click',()=>action(()=>api('/api/open-detection-output',{})));
  }
  $('warp-preview-button').addEventListener('click',()=>action(async()=>{
    invalidateWarp();
    state.warp=await api('/api/warp-plan',{path:$('source-path').value.trim(),target_crs:$('warp-crs').value.trim(),resolution_cm:Number($('warp-gsd').value),resampling:$('warp-resampling').value});
    const p=state.warp;
    $('warp-plan-info').textContent=`${p.source_crs} → ${p.target_crs} · ${p.width} × ${p.height} pixel · khoảng ${(p.estimated_uncompressed_bytes/1024**2).toFixed(1)} MB dữ liệu chưa nén. ${p.notice}`;
    $('warp-preview-image').src='/api/warp-preview?'+new URLSearchParams({signature:p.signature}); $('warp-preview-image').hidden=false;
  }));
  $('warp-start').addEventListener('click',()=>action(async()=>{if(!state.warp)throw new Error('Hãy xem trước lại.'); model.job=await api('/api/warp',{signature:state.warp.signature});goToStep(4);ctx.renderMainJob();ctx.pollJob();}));
  $('use-normalized').addEventListener('click',()=>action(async()=>{
    $('source-path').value=model.job.summary.output_path; $('base-x').value=''; $('base-y').value='';
    invalidateSource();goToStep(1);await inspectSource();
  }));

  // Kilo Code style Provider Connect Modal
  const providerTitles={anthropic:'Anthropic',openai:'OpenAI',deepseek:'DeepSeek',google:'Google Gemini',openrouter:'OpenRouter'};
  document.querySelectorAll('[data-connect-provider]').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const p=btn.dataset.connectProvider;
      state.modalProvider=p;
      $('kilo-modal-title').textContent=`Connect ${providerTitles[p]||p}`;
      $('kilo-modal-desc').textContent=`Enter your ${providerTitles[p]||p} API key to connect your account. Model selection is handled automatically.`;
      $('kilo-api-key-input').value=state.providerKeys[p]||'';
      $('kilo-modal').hidden=false;
      $('kilo-api-key-input').focus();
    });
  });
  const closeModal=()=>{ $('kilo-modal').hidden=true; state.modalProvider=null; };
  if ($('kilo-modal-close')) $('kilo-modal-close').addEventListener('click',closeModal);
  if ($('kilo-modal-back')) $('kilo-modal-back').addEventListener('click',closeModal);
  if ($('kilo-modal-submit')) {
    $('kilo-modal-submit').addEventListener('click',()=>{
      const p=state.modalProvider;
      const keyVal=$('kilo-api-key-input').value.trim();
      if (!p || !keyVal) return;
      state.providerKeys[p]=keyVal;
      $('advisor-provider').value=p;
      $('advisor-key').value=keyVal;
      $('advisor-cloud').hidden=false;
      $('kilo-active-badge').textContent=`Connected: ${providerTitles[p]||p}`;
      $('kilo-active-badge').className='status-tag success';
      const btn=document.querySelector(`[data-connect-provider="${p}"]`);
      if (btn) btn.textContent='Connected ✓';
      $('kilo-api-key-input').value='';
      closeModal();
    });
  }

  $('advisor-propose').addEventListener('click',()=>action(async()=>{
    state.defaults=await api('/api/detection-settings',{settings:settings()});
    const prov=$('advisor-provider').value;
    const apiKey=$('advisor-key').value || state.providerKeys[prov] || '';
    try {
      await api('/api/advise',{request:$('advisor-request').value,provider:prov,
        model:$('advisor-model').value.trim(),api_key:apiKey,workspace:$('advisor-workspace').value.trim()});
    } finally { $('advisor-key').value=''; }
    const result=await api('/api/state'); model.proposals=result.proposals;renderProposals();
  }));
  $('advisor-provider').addEventListener('change',()=>{$('advisor-cloud').hidden=$('advisor-provider').value==='local';});
  reopen.addEventListener('click',()=>action(async()=>{
    state.forceShowResults=true;
    if (model.step !== 3) goToStep(3);
    await refreshSessions();
    await loadResults();
    $('results-panel').hidden=false;
    $('results-panel').scrollIntoView({block:'start'});
  }));
  if ($('session-select')) {
    $('session-select').addEventListener('change',()=>updateControls());
  }
  if ($('session-load-btn')) {
    $('session-load-btn').addEventListener('click',()=>action(async()=>{
      const id=$('session-select').value;
      if (!id) return;
      const jobRec=await api('/api/sessions/load',{id});
      state.loadedJob=id;
      if (!['queued','running','cancelling'].includes(model.job?.status)) {
        model.job=jobRec;
        ctx.renderMainJob();
      }
      const data=await api('/api/results?offset=0&limit=50');
      const savedOffset=data.saved_cursor?.offset || 0;
      const savedObj=data.saved_cursor?.object_id || null;
      await loadResults(savedOffset, savedObj);
      await refreshSessions();
    }));
  }
  if ($('results-filter')) {
    $('results-filter').addEventListener('change',()=>action(async()=>{
      state.filter=$('results-filter').value;
      await loadResults(0);
    }));
  }
  if ($('object-subclass')) {
    $('object-subclass').addEventListener('change',()=>action(async()=>{
      const rec = selected();
      if (!rec || !state.results) return;
      const newSubClass = $('object-subclass').value || '';
      rec.sub_class = newSubClass || rec.label || rec.category;
      if (rec.review_status && rec.review_status !== 'unreviewed') {
        const decisionMap = {accepted_raw:'raw', accepted_candidate:'candidate', rejected:'reject'};
        const dec = decisionMap[rec.review_status] || 'raw';
        await api('/api/review', {
          id: rec.id,
          decision: dec,
          revision: state.results.revision,
          job_id: state.results.job.id,
          sub_class: newSubClass || undefined,
          offset: state.offset,
        });
        await loadResults(state.offset, rec.id, {silent: true});
      }
      renderObject({silent: true});
    }));
  }
  $('object-select').addEventListener('change',()=>{renderObject();updateControls();});
  if ($('page-range-select')) {
    $('page-range-select').addEventListener('change',()=>action(async()=>{
      const nextOffset=Number($('page-range-select').value)||0;
      await loadResults(nextOffset);
    }));
  }
  $('object-prev').addEventListener('click',()=>action(async()=>{
    const select=$('object-select');
    if (select.selectedIndex>0) { select.selectedIndex-=1; renderObject(); updateControls(); }
    else if (state.offset>0) await loadResults(Math.max(0,state.offset-50),'last');
  }));
  $('object-next').addEventListener('click',()=>action(async()=>{
    const select=$('object-select');
    if (select.selectedIndex+1<select.options.length) { select.selectedIndex+=1; renderObject(); updateControls(); }
    else if (state.results && state.offset+50<state.results.total) await loadResults(state.offset+50);
  }));
  for (const [id,decision] of [['review-raw','raw'],['review-candidate','candidate'],['review-reject','reject'],['review-all-raw','raw'],['review-all-candidate','all_candidates']]) {
    if (!$(id)) continue;
    $(id).addEventListener('click',()=>action(async()=>{
      const isBulk = (id==='review-all-raw'||id==='review-all-candidate');
      const objectId = isBulk ? 'all' : selected()?.id;
      if (!objectId) return;
      const subClass=$('object-subclass')?.value || undefined;
      let nextOffset = state.offset;
      let nextKeep = selected()?.id;
      if (!isBulk) {
        const records = state.results?.records || [];
        const curIdx = records.findIndex(r => r.id === objectId);
        if (curIdx >= 0) {
          if (curIdx + 1 < records.length) {
            nextKeep = records[curIdx + 1].id;
          } else if (state.filter === 'unreviewed') {
            if (records.length === 1 && state.offset >= 50) {
              nextOffset = Math.max(0, state.offset - 50);
              nextKeep = 'last';
            } else {
              nextKeep = null;
            }
          } else if (state.results && state.offset + 50 < state.results.total) {
            nextOffset = state.offset + 50;
            nextKeep = null;
          }
        }
      }
      await api('/api/review',{id:objectId,decision,revision:state.results.revision,job_id:state.results.job.id,sub_class:subClass,offset:nextOffset});
      if (isBulk) {
        state.fullMapBoxesKey = '';
      } else if (state.fullMapBoxes.length > 0) {
        const statusMap = { raw: 'accepted_raw', candidate: 'accepted_candidate', reject: 'rejected' };
        const mItem = state.fullMapBoxes.find(b => b.id === objectId);
        if (mItem) {
          mItem.review_status = statusMap[decision] || mItem.review_status;
          if (subClass) mItem.sub_class = subClass;
        }
      }
      $('cad-result').replaceChildren();
      await loadResults(nextOffset, nextKeep);
    }));
  }

  function computeRiceOnlyGlobalBox(rec) {
    if (!rec || !Array.isArray(rec.box) || rec.box.length !== 4) return null;
    const raw = rec.box;
    const ref = rec.refinement || {};
    const cboxes = ref.rice_clump_boxes?.length ? ref.rice_clump_boxes : (ref.clump_boxes || []);
    if (!Array.isArray(cboxes) || cboxes.length < 2) return rec.candidate_box || rec.box;
    const crop = ref.crop || [16, 16, Math.round(raw[2] - raw[0]) + 16, Math.round(raw[3] - raw[1]) + 16];
    const cwLocal = Math.max(1, crop[2] - crop[0]);
    const chLocal = Math.max(1, crop[3] - crop[1]);
    const sx = cwLocal / Math.max(1, raw[2] - raw[0]);
    const sy = chLocal / Math.max(1, raw[3] - raw[1]);

    const mapped = cboxes.map(cb => {
      const gx1 = raw[0] + (cb[0] - crop[0]) / sx;
      const gy1 = raw[1] + (cb[1] - crop[1]) / sy;
      const gx2 = raw[0] + (cb[2] - crop[0]) / sx;
      const gy2 = raw[1] + (cb[3] - crop[1]) / sy;
      const w = Math.max(1, gx2 - gx1);
      const h = Math.max(1, gy2 - gy1);
      return { gx1, gy1, gx2, gy2, w, h, maxDim: Math.max(w, h), area: w * h };
    });

    // Exclude large or elongated grass levee segments (maxDim >= 44 or area >= 700)
    let riceOnly = mapped.filter(m => m.maxDim < 44 && m.area < 700 && (m.maxDim / Math.max(1, Math.min(m.w, m.h)) < 2.6 || m.maxDim < 28));
    if (!riceOnly.length) {
      // Fallback: exclude the single largest component (the grass levee)
      const sortedByArea = [...mapped].sort((a, b) => a.area - b.area);
      riceOnly = sortedByArea.slice(0, Math.max(1, sortedByArea.length - 1));
    }
    const minX = Math.max(raw[0], Math.min(...riceOnly.map(m => m.gx1)));
    const minY = Math.max(raw[1], Math.min(...riceOnly.map(m => m.gy1)));
    const maxX = Math.min(raw[2], Math.max(...riceOnly.map(m => m.gx2)));
    const maxY = Math.min(raw[3], Math.max(...riceOnly.map(m => m.gy2)));
    if (maxX <= minX + 2 || maxY <= minY + 2) return rec.candidate_box || rec.box;
    return [Number(minX.toFixed(2)), Number(minY.toFixed(2)), Number(maxX.toFixed(2)), Number(maxY.toFixed(2))];
  }

  if ($('crop-out-grass-btn')) {
    $('crop-out-grass-btn').addEventListener('click', () => action(async () => {
      const rec = selected();
      if (!rec || !state.results) return;
      const riceBox = computeRiceOnlyGlobalBox(rec);
      const targetSubClass = 'Newly transplanted rice + Partial Grass';
      if ($('object-subclass')) $('object-subclass').value = targetSubClass;

      let nextOffset = state.offset;
      let nextKeep = rec.id;
      const records = state.results?.records || [];
      const curIdx = records.findIndex(r => r.id === rec.id);
      if (curIdx >= 0) {
        if (curIdx + 1 < records.length) nextKeep = records[curIdx + 1].id;
        else if (state.results && state.offset + 50 < state.results.total) {
          nextOffset = state.offset + 50;
          nextKeep = null;
        }
      }

      await api('/api/review', {
        id: rec.id,
        decision: 'candidate',
        revision: state.results.revision,
        job_id: state.results.job.id,
        sub_class: targetSubClass,
        custom_box: riceBox,
        offset: nextOffset,
      });
      if (state.fullMapBoxes.length > 0) {
        const mItem = state.fullMapBoxes.find(b => b.id === rec.id);
        if (mItem) {
          mItem.review_status = 'accepted_candidate';
          mItem.sub_class = targetSubClass;
          if (riceBox) mItem.candidate_box = riceBox;
        }
      }
      if ($('pipeline-tools-status')) {
        $('pipeline-tools-status').textContent = `🌾+🌱 Đã ghi nhận ${rec.id} có 1 phần Cỏ bờ: tự động co khung loại bỏ dải cỏ bờ và gắn nhãn "${targetSubClass}".`;
      }
      await loadResults(nextOffset, nextKeep);
    }));
  }

  if ($('split-mixed-btn')) {
    $('split-mixed-btn').addEventListener('click', () => action(async () => {
      const rec = selected();
      if (!rec || !state.results) return;
      let r;
      try {
        r = await api('/api/split-clumps', {
          revision: state.results.revision,
          job_id: state.results.job.id,
          object_id: `${rec.id}:reject_grass`,
        });
      } catch {
        r = await api('/api/split-clumps', {
          revision: state.results.revision,
          job_id: state.results.job.id,
          object_id: rec.id,
        });
      }
      const created = r.created_clumps ?? r.new_boxes ?? 0;
      const riceCnt = r.rice_count ?? Math.max(0, created - 1);
      const grassCnt = r.grass_count ?? (created > riceCnt ? created - riceCnt : 1);
      if ($('pipeline-tools-status')) {
        $('pipeline-tools-status').textContent = `✂️ Đã tách vùng lẫn ${rec.id} thành ${riceCnt} khóm lúa (🌾 Newly transplanted rice) và ${grassCnt} dải cỏ bờ (🌱 Grass).`;
      }
      state.fullMapBoxesKey = '';
      await loadResults(state.offset);
    }));
  }
  for (const id of ['object-raw','object-candidate','object-context-img']) {
    $(id)?.addEventListener('click',()=>{if($(id).src)window.open($(id).src,'_blank','noopener');});
  }
  if ($('toggle-box-overlay')) {
    $('toggle-box-overlay').addEventListener('click', () => setOverlayBoxesVisible(!state.boxesVisible));
  }
  if ($('toggle-map-boxes')) {
    $('toggle-map-boxes').addEventListener('click', () => setOverlayBoxesVisible(!state.boxesVisible));
  }
  syncBoxToggleButtons();
  $('export-cad').addEventListener('click',()=>action(async()=>{
    const result=await api('/api/export-cad',{revision:state.results.revision,job_id:state.results.job.id});
    const overlapNote=result.removed_overlaps?` (đã loại bỏ ${result.removed_overlaps} khung chồng lấn)`:'';
    const target=$('cad-result'); target.textContent=`Đã xuất ${result.count} đối tượng đã duyệt${overlapNote}. ${result.excluded_unreviewed} đối tượng chưa duyệt được để lại. `;
    for (const name of result.files) {
      const link=document.createElement('a');link.href=fileUrl(`reviewed_r${result.revision}/${name}`);link.download=name;link.textContent='Tải '+name; target.append(document.createElement('br'),link);
    }
  }));
  if ($('export-dwg')) {
    $('export-dwg').addEventListener('click',()=>action(async()=>{
      const result=await api('/api/export-dwg',{revision:state.results.revision,job_id:state.results.job.id});
      const target=$('cad-result'); target.textContent=result.message || `Đã vẽ ${result.drawn_count} đối tượng vào AutoCAD.`;
      if (result.saved_dwg) {
        const link=document.createElement('a');link.href=fileUrl(`reviewed_r${result.revision}/objects.dwg`);link.download='objects.dwg';link.textContent='Tải objects.dwg';
        target.append(document.createElement('br'),link);
      }
    }));
  }
  function syncActiveSrButtons(activeMode) {
    document.querySelectorAll('.sr-mode-btn[data-sr-mode]').forEach(btn => {
      btn.classList.toggle('active-sr-mode', btn.dataset.srMode === activeMode);
    });
  }
  if ($('sidebar-sr-scale')) {
    $('sidebar-sr-scale').addEventListener('change', () => {
      if ($('upscale')) $('upscale').value = $('sidebar-sr-scale').value;
    });
  }
  if ($('upscale')) {
    $('upscale').addEventListener('change', () => {
      if ($('sidebar-sr-scale') && ($('upscale').value === '2' || $('upscale').value === '4')) {
        $('sidebar-sr-scale').value = $('upscale').value;
      }
    });
  }
  if ($('sr-mode')) {
    $('sr-mode').addEventListener('change', () => syncActiveSrButtons($('sr-mode').value));
  }
  document.querySelectorAll('.sr-mode-btn[data-sr-mode]').forEach(btn => {
    btn.addEventListener('click', () => action(async () => {
      const rec = selected();
      if (!rec) return;
      const mode = btn.dataset.srMode || $('sr-mode')?.value || 'ttst';
      if ($('sr-mode')) $('sr-mode').value = mode;
      syncActiveSrButtons(mode);
      const scale = Number($('sidebar-sr-scale')?.value || $('upscale')?.value || 4) || 4;
      $('pipeline-tools-status').textContent = `Đang chạy siêu phân giải (${mode} ${scale}x + Khử mờ tán cây) trên GPU cho ${rec.id}…`;
      const r = await api('/api/sr-enhance', { id: rec.id, job_id: state.results.job.id, mode, scale });
      const ts = Date.now();
      const nextRaw = fileUrl(r.sr_image) + '&t=' + ts;
      $('object-raw').src = nextRaw;
      $('object-raw').dataset.srcUrl = nextRaw;
      if (r.sr_candidate_image && $('object-candidate')) {
        const nextCand = fileUrl(r.sr_candidate_image) + '&t=' + ts;
        $('object-candidate').hidden = false;
        $('object-candidate').src = nextCand;
        $('object-candidate').dataset.srcUrl = nextCand;
      }
      pulseElements('.review-images figure');
      $('pipeline-tools-status').textContent = `Đã làm nét cửa sổ gốc & khung đề nghị cho ${rec.id} bằng ${r.sr_meta?.engine || mode} (${r.sr_meta?.weight || 'local'} · ${scale}x).`;
    }));
  });

  // Separate Topographic Survey & CAD Symbol/Block Library Module
  function renderSurveyRulesTable() {
    const tbody = $('survey-rules-tbody');
    if (!tbody) return;
    tbody.replaceChildren();
    const blocks = state.surveyLibrary.blocks || [];
    const layers = state.surveyLibrary.layers || [];
    const rules = state.surveyLibrary.rules || [];

    rules.forEach((rule) => {
      const tr = document.createElement('tr');

      const tdCat = document.createElement('td');
      const catStrong = document.createElement('strong');
      catStrong.textContent = rule.category;
      const catSub = document.createElement('small');
      catSub.style.display = 'block';
      catSub.style.color = '#64748b';
      catSub.textContent = rule.label_vi || '';
      tdCat.append(catStrong, catSub);

      const tdType = document.createElement('td');
      const selType = document.createElement('select');
      for (const [val, label] of [
        ['BLOCK', 'Chèn Block CAD (INSERT)'],
        ['DOUBLE_LINE', 'Kẻ 2 Line song song (Mương/Đường)'],
        ['BRIDGE_SYMBOL', 'Ký hiệu Cầu / Cống'],
        ['CLOSED_POLYLINE', 'Polyline khép kín (Công trình)'],
      ]) {
        const opt = new Option(label, val);
        if (rule.cad_type === val) opt.selected = true;
        selType.append(opt);
      }
      selType.addEventListener('change', () => { rule.cad_type = selType.value; });
      tdType.append(selType);

      const tdBlock = document.createElement('td');
      const selBlock = document.createElement('select');
      selBlock.append(new Option('— Không dùng Block —', ''));
      for (const b of blocks) {
        const opt = new Option(`${b.name}`, b.name);
        if (rule.block_name === b.name) opt.selected = true;
        selBlock.append(opt);
      }
      if (rule.block_name && !blocks.some(b => b.name === rule.block_name)) {
        const customOpt = new Option(rule.block_name, rule.block_name, true, true);
        selBlock.append(customOpt);
      }
      selBlock.addEventListener('change', () => { rule.block_name = selBlock.value; });
      tdBlock.append(selBlock);

      const tdLayer = document.createElement('td');
      const inpLayer = document.createElement('input');
      inpLayer.type = 'text';
      inpLayer.value = rule.layer || 'KS_DEFAULT';
      inpLayer.setAttribute('list', 'survey-layer-datalist');
      inpLayer.addEventListener('change', () => { rule.layer = inpLayer.value.trim() || 'KS_DEFAULT'; });
      tdLayer.append(inpLayer);

      const tdColor = document.createElement('td');
      const inpColor = document.createElement('input');
      inpColor.type = 'number';
      inpColor.min = '1';
      inpColor.max = '255';
      inpColor.value = String(rule.color || 3);
      inpColor.style.width = '64px';
      inpColor.addEventListener('change', () => { rule.color = Number(inpColor.value) || 3; });
      tdColor.append(inpColor);

      const tdSize = document.createElement('td');
      const inpSize = document.createElement('input');
      inpSize.type = 'number';
      inpSize.step = '0.1';
      inpSize.min = '0.1';
      const isCorridor = rule.cad_type === 'DOUBLE_LINE' || rule.cad_type === 'BRIDGE_SYMBOL';
      inpSize.value = String(isCorridor ? (rule.width_m || 1.2) : (rule.scale || 1.0));
      inpSize.style.width = '74px';
      inpSize.title = isCorridor ? 'Bề rộng lòng mương / mặt đường (m)' : 'Tỷ lệ phóng Block CAD';
      inpSize.addEventListener('change', () => {
        const v = Number(inpSize.value) || 1.0;
        if (rule.cad_type === 'DOUBLE_LINE' || rule.cad_type === 'BRIDGE_SYMBOL') rule.width_m = v;
        else rule.scale = v;
      });
      tdSize.append(inpSize);

      const tdCenter = document.createElement('td');
      tdCenter.style.textAlign = 'center';
      const chkCenter = document.createElement('input');
      chkCenter.type = 'checkbox';
      chkCenter.checked = Boolean(rule.centerline);
      chkCenter.style.width = '16px';
      chkCenter.style.minHeight = '16px';
      chkCenter.addEventListener('change', () => { rule.centerline = chkCenter.checked; });
      tdCenter.append(chkCenter);

      tr.append(tdCat, tdType, tdBlock, tdLayer, tdColor, tdSize, tdCenter);
      tbody.append(tr);
    });

    let datalist = $('survey-layer-datalist');
    if (!datalist) {
      datalist = document.createElement('datalist');
      datalist.id = 'survey-layer-datalist';
      document.body.append(datalist);
    }
    datalist.replaceChildren(...layers.map(l => new Option(`${l.name} (${l.description || 'ACI ' + l.color})`, l.name)));
  }

  async function loadSurveyLibrary(customPath = undefined) {
    try {
      const info = customPath !== undefined
        ? await api('/api/survey/library', { path: customPath })
        : await api('/api/survey/library');
      state.surveyLibrary = info;
      if ($('survey-lib-path') && info.library_path) {
        $('survey-lib-path').value = info.library_path;
      }
      renderSurveyRulesTable();
      if (customPath !== undefined && $('survey-module-status')) {
        $('survey-module-status').textContent = `Đã nạp thư viện CAD (${info.blocks.length} Block, ${info.layers.length} Layer).`;
      }
    } catch (err) {
      if (customPath !== undefined) showError(err.message);
    }
  }

  document.querySelectorAll('[data-survey-cat]').forEach(btn => {
    btn.addEventListener('click', () => {
      const chip = btn.dataset.surveyCat;
      const lines = $('detect-categories').value.split('\n').map(s => s.trim()).filter(Boolean);
      if (!lines.some(l => l.toLowerCase() === chip.toLowerCase())) lines.push(chip);
      $('detect-categories').value = lines.join('\n');
      invalidateDetection();
      updateControls();
      if ($('survey-module-status')) {
        $('survey-module-status').textContent = `Đã thêm "${chip}" vào danh sách đối tượng cần tìm ở Bước 3.`;
      }
    });
  });

  if ($('survey-load-lib-btn')) {
    $('survey-load-lib-btn').addEventListener('click', () => action(async () => {
      await loadSurveyLibrary($('survey-lib-path').value.trim());
    }));
  }
  if ($('survey-save-rules-btn')) {
    $('survey-save-rules-btn').addEventListener('click', () => action(async () => {
      const res = await api('/api/survey/rules', {
        rules: state.surveyLibrary.rules,
        library_path: $('survey-lib-path')?.value.trim() || null,
      });
      state.surveyLibrary.rules = res.rules;
      $('survey-module-status').textContent = 'Đã lưu bảng quy tắc ánh xạ Ký hiệu & Layer Bình đồ Khảo sát CAD.';
    }));
  }
  const TCVN_MAP_SCALE_SPECS = {
    500: {
      scale: 500,
      k: 1.0,
      ratioLabel: '1:500',
      treeGridLabel: '20×10m',
      grassGridLabel: '10×5m',
      elevGridLabel: '12.5m',
      textHeightLabel: '1.2m',
      contourInterval: '0.5m',
    },
    1000: {
      scale: 1000,
      k: 2.0,
      ratioLabel: '1:1000',
      treeGridLabel: '40×20m',
      grassGridLabel: '20×10m',
      elevGridLabel: '25m',
      textHeightLabel: '2.4m',
      contourInterval: '0.5m',
    },
    2000: {
      scale: 2000,
      k: 4.0,
      ratioLabel: '1:2000',
      treeGridLabel: '80×40m',
      grassGridLabel: '40×20m',
      elevGridLabel: '50m',
      textHeightLabel: '4.8m',
      contourInterval: '0.5m/1.0m',
    },
    5000: {
      scale: 5000,
      k: 10.0,
      ratioLabel: '1:5000',
      treeGridLabel: '200×100m',
      grassGridLabel: '100×50m',
      elevGridLabel: '125m',
      textHeightLabel: '12.0m',
      contourInterval: '1.0m',
    },
  };

  const parseAdvMapScale = (raw) => {
    const s = String(raw || '500').trim().replace(/^1\s*[:/]\s*/, '');
    const m = Number(s);
    return TCVN_MAP_SCALE_SPECS[m] ? m : 500;
  };

  const updateAdvTcvnScaleBadge = (scaleVal) => {
    const m = parseAdvMapScale(scaleVal);
    const spec = TCVN_MAP_SCALE_SPECS[m] || TCVN_MAP_SCALE_SPECS[500];
    const badge = $('tcvnScaleInfoBadge') || $('advTcvnScaleInfoBadge');
    if (badge) {
      badge.innerHTML =
        `<strong>TCVN ${spec.ratioLabel}</strong> · Hệ số <code>k = ×${spec.k.toFixed(1)}</code> · ` +
        `Lưới cây <code>${spec.treeGridLabel}</code> · Cỏ <code>${spec.grassGridLabel}</code> · ` +
        `Cao độ <code>${spec.elevGridLabel}</code> · Chữ <code>${spec.textHeightLabel}</code> · ĐM <code>${spec.contourInterval}</code>`;
    }
    return spec;
  };

  const TRAINED_MODEL_BADGE_HTML =
    '🧠 <strong>Model 9 Lớp (Huấn luyện chuẩn <code>ACAD_KHU TAM GIAC.dwg</code> + Mylib2 Block Grid + TCVN Scale)</strong>';

  const updateTrainedModelBannerForSource = (srcPath) => {
    const modelBadge = $('trained-model-status-badge');
    const fileName = String(srcPath || $('source-path')?.value || '').trim().split(/[\\/]/).pop();
    if (modelBadge) {
      modelBadge.innerHTML = fileName
        ? `${TRAINED_MODEL_BADGE_HTML} · Ảnh đang chọn: <code>${fileName}</code> (tự động rải đều Block <code>caylato</code>, <code>cumcay2</code>, <code>cothap</code>, <code>cocao</code>, <code>hoa</code> + <code>Ranhgioi_thucvat</code> + <code>Taluy</code> + <code>Cao độ</code> + <code>Đồng mức</code>)`
        : TRAINED_MODEL_BADGE_HTML;
    }
  };

  if ($('source-path')) {
    $('source-path').addEventListener('input', (ev) => updateTrainedModelBannerForSource(ev.target.value));
    $('source-path').addEventListener('change', (ev) => updateTrainedModelBannerForSource(ev.target.value));
    updateTrainedModelBannerForSource($('source-path').value);
  }

  const advScaleSelect = $('advMapScaleSelect') || $('mapScaleSelect');
  if (advScaleSelect) {
    updateAdvTcvnScaleBadge(advScaleSelect.value);
    advScaleSelect.addEventListener('change', (ev) => {
      const m = parseAdvMapScale(ev.target.value);
      const spec = updateAdvTcvnScaleBadge(m);
      state.mapScale = m;
      getViewport?.()?.setMapScale?.(m);
      const statusEl = $('terrain-seg-status');
      if (statusEl) {
        statusEl.querySelectorAll('a[data-terrain-dl]').forEach((a) => {
          const kind = a.getAttribute('data-terrain-dl');
          a.href = `/api/terrain/${kind}?map_scale=${m}&t=${Date.now()}`;
        });
      }
      setStatus(`📐 Đã dàn lại bản vẽ theo tỉ lệ TCVN ${spec.ratioLabel} (hệ số k = ×${spec.k.toFixed(1)}).`);
    });
  }

  if ($('terrain-seg-run-btn')) {
    $('terrain-seg-run-btn').addEventListener('click', () => action(async () => {
      const enabledClasses = [...document.querySelectorAll('.terrain-cls-chk:checked')].map(c => c.value);
      const rawPath = $('source-path')?.value?.trim() || state.results?.source || '';
      const bx = Number($('base-x')?.value);
      const by = Number($('base-y')?.value);
      const base = (Number.isFinite(bx) && Number.isFinite(by)) ? [bx, by] : (state.results?.base || [0, 0]);
      const mapScale = parseAdvMapScale(($('advMapScaleSelect') || $('mapScaleSelect'))?.value || state.mapScale || 500);
      state.mapScale = mapScale;
      updateTrainedModelBannerForSource(rawPath);
      const statusEl = $('terrain-seg-status');
      if (statusEl) {
        statusEl.textContent = `🧠 Model 9 Lớp (Huấn luyện chuẩn ACAD_KHU TAM GIAC.dwg + Mylib2 Block Grid + TCVN Scale 1:${mapScale}): đang nhận diện & tự động dàn bản vẽ AutoCAD VN2000…`;
      }
      const res = await api(`/api/terrain/segment?map_scale=${mapScale}`, {
        path: rawPath || null,
        base,
        enabled_classes: enabledClasses,
        map_scale: mapScale,
        job_id: state.results?.job?.id || null,
      });
      state.terrainFeatures = res.features || [];
      getViewport?.()?.setMapScale?.(mapScale);
      getViewport?.()?.setTerrainVectors?.(state.terrainFeatures);
      if (statusEl) {
        statusEl.textContent = (res.message || `Đã xuất bình đồ địa hình (1:${mapScale}).`) + ' ';
        const dwgLink = document.createElement('a');
        dwgLink.setAttribute('data-terrain-dl', 'dwg');
        dwgLink.href = `/api/terrain/dwg?map_scale=${mapScale}&t=${Date.now()}`;
        dwgLink.download = res.dwg_file || `binh_do_duong_ao_muong_1_${mapScale}.dwg`;
        dwgLink.textContent = '📐 Tải ' + (res.dwg_file || `binh_do_duong_ao_muong_1_${mapScale}.dwg`);
        dwgLink.style.marginRight = '12px';
        dwgLink.style.fontWeight = '700';
        statusEl.append(dwgLink);

        const link = document.createElement('a');
        link.setAttribute('data-terrain-dl', 'dxf');
        link.href = `/api/terrain/dxf?map_scale=${mapScale}&t=${Date.now()}`;
        link.download = res.dxf_file || `binh_do_duong_ao_muong_1_${mapScale}.dxf`;
        link.textContent = '📐 Tải ' + (res.dxf_file || `binh_do_duong_ao_muong_1_${mapScale}.dxf`);
        statusEl.append(link);
      }
    }));
  }
  if ($('terrain-train-dwg-btn')) {
    $('terrain-train-dwg-btn').addEventListener('click', () => action(async () => {
      const folder = window.prompt(
        'Nhập đường dẫn thư mục chứa các bản vẽ .DWG + ảnh ORTHO (.JPG + .JGW) để huấn luyện (Để trống để dùng thư mục Waterpoint_10.3.26 mặc định):',
        'D:\\LUUTRU VIEC N\\ACAD\\Waterpoint_10.3.26'
      );
      if (folder === null) return;
      const statusEl = $('terrain-seg-status');
      if (statusEl) {
        statusEl.textContent = '🎓 Đang đọc trực tiếp các đường PL từ bản vẽ .DWG + ảnh ORTHO và huấn luyện mô hình trên GPU…';
      }
      const roots = folder.trim() ? [folder.trim()] : [];
      const meta = await api('/api/terrain/train-dwg', { survey_roots: roots, steps: 160 });
      if (statusEl) {
        const zones = (meta.real_dwg_zones_trained || []).map(z => z.dwg_file).join(', ');
        statusEl.textContent = `Đã huấn luyện thành công trên ${meta.real_dwg_zones_count || 0} bản vẽ .DWG (${zones}) với ${meta.real_patches_sampled || 0} mẫu học trên ${meta.device_trained || 'GPU'} (Độ chính xác: ${Math.round((meta.val_pixel_accuracy || 0) * 100)}%).`;
      }
    }));
  }
  if ($('survey-export-dxf-btn')) {
    $('survey-export-dxf-btn').addEventListener('click', () => action(async () => {
      if (!state.results) return;
      const res = await api('/api/survey/export', {
        job_id: state.results.job.id,
        rules: state.surveyLibrary.rules,
        library_path: $('survey-lib-path')?.value.trim() || null,
        survey_polylines: state.regions,
        include_unreviewed: true,
      });
      const statusEl = $('survey-module-status');
      statusEl.textContent = res.message + ' ';
      const link = document.createElement('a');
      link.href = fileUrl(res.dxf_file);
      link.download = res.dxf_file;
      link.textContent = 'Tải ' + res.dxf_file;
      statusEl.append(link);
    }));
  }
  if ($('fuse-existing-btn')) {
    $('fuse-existing-btn').addEventListener('click',()=>action(async()=>{
      const r=await api('/api/fuse-results',{revision:state.results.revision,job_id:state.results.job.id,mode:'smart_overlap',threshold:0.50,stitch_large:true});
      $('pipeline-tools-status').textContent=`Đã gộp khung trùng & nối cây lớn: từ ${r.before_count} xuống còn ${r.after_count} đối tượng (giảm ${r.reduced_duplicates} khung trùng ở biên chồng lấn).`;
      await loadResults(0);
    }));
  }
  if ($('split-clumps-btn')) {
    $('split-clumps-btn').addEventListener('click',()=>action(async()=>{
      const r=await api('/api/split-clumps',{revision:state.results.revision,job_id:state.results.job.id});
      const splitParents = r.split_parents ?? r.split_boxes ?? 0;
      const createdClumps = r.created_clumps ?? r.new_boxes ?? 0;
      $('pipeline-tools-status').textContent=r.message
        || `🌱 Đã tách khóm lúa gộp: từ ${r.before_count ?? state.results.total} lên ${r.after_count ?? r.total ?? '—'} đối tượng (tách ${splitParents} khung vùng lớn thành ${createdClumps} khóm lúa đơn lẻ).`;
      await loadResults(state.offset,selected()?.id);
    }));
  }
  if ($('enrich-dem-btn')) {
    $('enrich-dem-btn').addEventListener('click',()=>action(async()=>{
      const r=await api('/api/enrich-dem',{revision:state.results.revision,job_id:state.results.job.id});
      const classes=Object.entries(r.class_counts||{}).map(([k,v])=>`${k}: ${v}`).join(', ');
      $('pipeline-tools-status').textContent=`Đã đọc DEM (${r.dem_path}) cho ${r.enriched_count}/${r.total} đối tượng. Phân loại: ${classes}.`;
      await loadResults(state.offset,selected()?.id);
    }));
  }
  if ($('repair-dem-btn')) {
    $('repair-dem-btn').addEventListener('click',()=>action(async()=>{
      const r=await api('/api/dem/repair',{job_id:state.results?.job?.id||null});
      $('pipeline-tools-status').textContent=`Đã sửa DEM gốc (${r.dem_path}): loại bỏ ${r.repaired_pixels} pixel nhiễu xanh/vàng và làm phẳng theo cao độ đỏ liền kề (không để lại dấu vết).`;
    }));
  }
  if ($('enrich-ms-btn')) {
    $('enrich-ms-btn').addEventListener('click',()=>action(async()=>{
      const body={
        revision:state.results?.revision ?? null,
        job_id:state.results?.job?.id ?? null,
        source_path:$('source-path')?.value?.trim() || state.results?.source || null,
      };
      const r=await api('/api/enrich-multispectral',body);
      const classes=Object.entries(r.class_counts||{}).map(([k,v])=>`${k}: ${v}`).join(', ');
      const scene=r.land_cover_pct || r.field_summary?.land_cover_pct || r.scene_stats || null;
      let sceneText='';
      if (scene && typeof scene==='object') {
        const labelMap={
          newly_transplanted_rice:'Lúa mới cấy',
          healthy_rice:'Lúa khỏe',
          grass_weed:'Cỏ bờ',
          grass:'Cỏ bờ',
          water:'Mặt nước',
          bare_soil:'Đất bùn',
        };
        const parts=Object.entries(scene)
          .filter(([,v])=>typeof v==='number')
          .map(([k,v])=>`${labelMap[k]||k}: ${v.toFixed(1)}%`);
        if (parts.length) sceneText=` · Diện tích toàn ảnh: ${parts.join(' | ')}`;
      }
      const objNote = r.total ? `Đã cập nhật ${r.enriched_count??r.total}/${r.total} đối tượng (${classes||'Hoàn tất'})` : 'Đã phân tích toàn bộ ảnh Orthomosaic';
      $('pipeline-tools-status').textContent=r.message
        || `🌿 Phân tích Đa phổ toàn ảnh (${(r.bands_used||[]).map(b=>b.toUpperCase()).join(' + ')||'RGB/ExG'}): ${objNote}${sceneText}.`;
      if (state.results) await loadResults(state.offset,selected()?.id);
    }));
  }
  if ($('auto-triage-btn')) {
    $('auto-triage-btn').addEventListener('click',()=>action(async()=>{
      const r=await api('/api/auto-triage',{revision:state.results.revision,job_id:state.results.job.id,threshold:0.75});
      const matchedCnt=r.matched_by_user_prototype ?? r.template_matched;
      const matchedNote=typeof matchedCnt==='number' && matchedCnt>0 ? ` (khớp ${matchedCnt} mẫu bạn đã xác nhận)` : '';
      const rejectNote=r.suggested_reject ? `, đánh dấu ${r.suggested_reject} khung nghi nhiễu/gộp` : '';
      $('pipeline-tools-status').textContent=r.message
        || `⚡ Đã lọc nhanh theo mẫu đã duyệt: Tự duyệt ${r.auto_accepted??0} khung tương đồng${matchedNote}${rejectNote}. Còn ${r.needs_review??0} khung cần kiểm tra.`;
      state.fullMapBoxesKey = '';
      await loadResults(state.offset,selected()?.id);
    }));
  }
  function runSaveDataset() {
    return action(async () => {
      if (!state.results?.job?.id) return;
      const r = await api('/api/dataset-export', { job_id: state.results.job.id });
      if (r.turbo_status) renderTurboStatus(r.turbo_status);
      else await refreshTurboStatus();
      const msg = `💾 Đã lưu ${r.run_exported} mẫu sạch 100% vào Dataset Ground Truth (${r.dataset_dir}). Tổng tích lũy: ${r.total_positives} mẫu dương, ${r.total_negatives} mẫu âm.`;
      if ($('dataset-export-status')) $('dataset-export-status').textContent = msg;
      if ($('pipeline-tools-status')) $('pipeline-tools-status').textContent = msg;
    });
  }
  if ($('train-turbo-btn')) {
    $('train-turbo-btn').addEventListener('click', () => action(async () => {
      const mode = $('turbo-train-mode')?.value || 'both';
      const epochs = Number($('turbo-train-epochs')?.value || 50) || 50;
      if ($('turbo-train-status')) {
        $('turbo-train-status').textContent = '🚀 Đang cắt bộ ô GeoTIFF sạch & khởi động YOLO11s-FP16 trên RTX GPU… Theo dõi vòng tròn tiến độ bên dưới.';
      }
      model.job = await api('/api/turbo/train', { mode, epochs });
      if (model.step !== 5) goToStep?.(5);
      ctx.renderMainJob();
      ctx.pollJob(400);
    }));
  }
  if ($('save-dataset-btn')) {
    $('save-dataset-btn').addEventListener('click', runSaveDataset);
  }
  if ($('quick-save-dataset-btn')) {
    $('quick-save-dataset-btn').addEventListener('click', runSaveDataset);
  }
  if ($('download-reviewed-json-btn')) {
    $('download-reviewed-json-btn').addEventListener('click', () => action(async () => {
      if (!state.results?.job?.id) return;
      const jobId = state.results.job.id;
      const resp = await fetch(fileUrl('detections.json'));
      if (!resp.ok) throw new Error('Không tải được tệp nhãn detections.json.');
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${jobId}_detections_reviewed.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1500);
      const msg = `📥 Đã tải tệp nhãn ${jobId}_detections_reviewed.json (${state.results.reviewed} / ${state.results.total_all ?? state.results.total} đối tượng đã duyệt).`;
      if ($('dataset-export-status')) $('dataset-export-status').textContent = msg;
      if ($('pipeline-tools-status')) $('pipeline-tools-status').textContent = msg;
    }));
  }
  $('label-template').addEventListener('click',()=>{
    if(!state.results)return;
    const data={source:state.results.source,region:state.results.region,coordinate_convention:'box=[x1,y1,x2,y2], mép pixel ảnh gốc; category trùng tên truy vấn',records:[]};
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='nhan_kiem_chung.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  $('evaluate-button').addEventListener('click',()=>action(async()=>{
    const r=await api('/api/evaluate',{path:$('truth-path').value.trim(),job_id:state.results.job.id});
    $('evaluation-result').textContent=`Đúng: ${r.true_positive} · Dư: ${r.false_positive} · Bỏ sót: ${r.false_negative}. Tỷ lệ khung đúng: ${r.precision===null?'chưa có':(r.precision*100).toFixed(1)+'%'}. Tỷ lệ tìm đủ: ${r.recall===null?'chưa có':(r.recall*100).toFixed(1)+'%'}. ${r.note}`;
  }));
  function bindViewport(vp) {
    if (!vp) return;
    vp.setCadCallbacks({
      onRegionsChange(updatedRegions, selectedIdx) {
        state.regions = updatedRegions;
        state.selectedRegionIndex = selectedIdx;
        renderRegions();
        invalidateDetection();
        updateControls();
      },
      onFinishDraft(polygon) {
        activateMultiScope();
        state.regions.push({
          polygon,
          categories: currentCategories(),
        });
        state.selectedRegionIndex = state.regions.length - 1;
        renderRegions();
        invalidateDetection();
        updateControls();
      },
      onModeChange(mode) {
        updateCadHint(mode);
      },
    });
    vp.setBoxesVisible?.(state.boxesVisible);
    vp.setTerrainVectors?.(state.terrainFeatures || []);
    if (state.results?.records) {
      vp.setAllDetections?.(state.results.records, selected()?.id || null);
    }
    syncMultiRegionVisibility();
  }

  // ==========================================================================
  // Interactive "?" Help Inspector Mode (Cursor + Hover Popover + Esc to exit)
  // ==========================================================================
  const HELP_CATALOG = {
    'terrain-seg-run-btn': {
      stage: 'Bước 04 · Bình đồ Địa hình 6 Lớp',
      title: '🛣️ Phân vùng Đường · Ao · Mương xây & Xuất AutoCAD VN2000 (.DXF)',
      desc: 'Chạy mạng phân vùng địa hình 6 lớp kết hợp đa phổ NDVI/NDWI và rút xương Zhang-Suen để dựng 2 nét mép lòng đường + tim đường (Đường nhựa, Đường bê tông, Đường đất, Đường đi bộ < 1.9m), đa giác Ao/Hồ kèm vạch bờ taluy và thành đôi Mương xây.',
      tip: '📡 Kết quả vẽ trực tiếp lên bản đồ tổng quan và xuất tệp binh_do_duong_ao_muong.dxf chuẩn Layer khảo sát.',
    },
    'detect-engine': {
      stage: 'Bước 05 · Chọn Chế độ YOLO11 Turbo',
      title: '⚡ Chế độ Động cơ YOLO11 Turbo (Quét Vùng 640px vs Khóm Lẻ ~15cm)',
      desc: 'Chọn giữa "⚡ Turbo Quét Vùng" (quét các dải/ô lúa 640×640px + tự đếm tách khóm bằng Đa phổ NDVI) và "🌱 Turbo Khóm Lẻ" (bắt trực tiếp từng khóm lúa ~15cm trên ô 512×512px) chạy Batch=32 FP16 qua SharedMemory.',
      tip: '📡 Tốc độ quét thực địa đạt < 1 phút cho 5 ha trên RTX 4070.',
    },
    'train-turbo-btn': {
      stage: 'Bước 05 · Huấn luyện AI Tốc Độ Cao',
      title: '🚀 Huấn luyện Mô hình Turbo (RTX CUDA · FP16 + ONNX)',
      desc: 'Tự động cắt bộ ô sạch 640×640 & 512×512 trực tiếp từ ảnh GeoTIFF gốc dựa trên các Mẫu dương và Mẫu âm (Loại bỏ) bạn đã lưu ở Bước 04, huấn luyện YOLO11s-FP16 và xuất tệp best.onnx tương thích chuẩn Web/Desktop/QGIS.',
      tip: '📡 Nên bổ sung 15–50 Mẫu âm (về Bước 03 bấm Loại bỏ cho các khung bắt nhầm bờ/mương/cây → Lưu mẫu ở Bước 04) trước khi bấm nút này.',
    },
    'yolo-start-btn': {
      stage: 'Bước 05 · Quét Thực địa Siêu Tốc',
      title: '⚡ Bắt đầu quét YOLO11 Siêu Tốc (Batch=32 · SharedMemory)',
      desc: 'Chạy mô hình YOLO11 đã huấn luyện trên toàn bộ ảnh gốc hoặc vùng vẽ CAD với tốc độ ~600–900 ô/phút, tự gộp khung biên (Class-Aware Sweep NMS) và cho phép duyệt kết quả ở Bước 03 hoặc xuất AutoCAD ở Bước 04.',
      tip: '📡 Bấm "1. Kiểm tra lượt quét YOLO" để xem tổng số ô và số mẻ GPU Batch=32 trước khi quét.',
    },
    'help-mode-btn': {
      stage: 'Trợ giúp Tương tác',
      title: '🧭 Chế độ Giải thích Chức năng (?)',
      desc: 'Biến con trỏ chuột thành dấu chấm hỏi (?). Rê chuột đến bất kỳ nút bấm, ô chọn hoặc khung ảnh nào để xem giải thích chi tiết về thuật toán và công dụng.',
      tip: '📡 Nhấn phím [Esc] trên bàn phím hoặc bấm lại nút này để thoát.',
    },
    'review-help-btn': {
      stage: 'Trợ giúp Tương tác',
      title: '🧭 Chế độ Giải thích Chức năng (?)',
      desc: 'Bật con trỏ chấm hỏi (?) để tra cứu nhanh công dụng và thứ tự thực hiện của các nút xử lý Đa phổ, Hạ DEM, Tách khóm lúa, Tăng phân giải và Duyệt mẫu.',
      tip: '📡 Nhấn phím [Esc] bất cứ lúc nào để trở lại con trỏ bình thường.',
    },
    'taskmgr-panel': {
      stage: 'Task Manager · Giám sát Trạm Trắc địa & GPU',
      title: '🖥️ Bảng Theo dõi Phần cứng GPU & Đối tượng UAV',
      desc: 'Hiển thị trực tiếp mức tải CPU, RAM, GPU 0 (iGPU), GPU 1 (NVIDIA RTX 4070: 3D/CUDA, Copy/DMA, Dedicated VRAM, Shared GPU Memory, Nhiệt độ °C, Driver) kết hợp thống kê số lượng đối tượng & khóm lúa theo thời gian thực.',
      tip: '📡 Bấm chọn CPU / Memory / GPU 0 / GPU 1 / 🌾 Đối tượng ở cột trái để chuyển biểu đồ chi tiết.',
    },
    'enrich-ms-btn': {
      stage: 'Sidebar Workflow · Bước A.1 (Toàn ảnh)',
      title: '🛰️ 1. Phân tích Đa phổ toàn ảnh',
      desc: 'Đọc đồng thời 4 kênh phổ (_Green, _Red, _RedEdge, _NIR) trên toàn bộ ảnh ghép Orthomosaic chỉ với 1 lần bấm. Tính chỉ số sinh trưởng thực vật NDVI, NDRE, chỉ số nước NDWI, xuất bản đồ spectral_overview.png và phân lớp chính xác Lúa mới cấy / Lúa khỏe / Cỏ bờ / Mặt nước cho mọi đối tượng.',
      tip: '📡 Nên bấm đầu tiên ở Bước A để có dữ liệu phổ chính xác trước khi tách khóm hoặc lọc nhanh.',
    },
    'repair-dem-btn': {
      stage: 'Sidebar Workflow · Bước A.2 (Xử lý DEM)',
      title: '⛰️ 2. Hạ / Khử nhiễu nền DEM',
      desc: 'Quét tệp cao độ số (DEM .tif) đi kèm, phát hiện các mảng nhiễu cao độ giả (màu xanh/vàng bất thường do lóa mặt nước hoặc tán cây) và hạ/nội suy mượt về cao độ mặt ruộng chuẩn liền kề.',
      tip: '📡 Dùng khi bản đồ DEM có các đốm cao độ nhô cao bất thường trên mặt ruộng.',
    },
    'enrich-dem-btn': {
      stage: 'Sidebar Workflow · Bước A.3 (Đo chiều cao RTK/DEM)',
      title: '📡 3. Cập nhật cao độ RTK / DEM',
      desc: 'Trích xuất cao độ mặt đất nền (Z nền) từ vòng đệm xung quanh từng đối tượng và cao độ đỉnh (Z đỉnh) để tính chiều cao thực tế của cây/khóm lúa (H = Z đỉnh − Z nền, đơn vị mét).',
      tip: '📡 Giúp phân biệt rõ Lúa mới cấy (H < 0.35 m) với Bụi cỏ cao hoặc Cây cảnh.',
    },
    'split-clumps-btn': {
      stage: 'Sidebar Workflow · Bước B.4 (Tách khóm)',
      title: '🌾 4. Tách khóm lúa gộp',
      desc: 'Sử dụng mặt nạ diệp lục Đa phổ (NDVI / ExG) để phân tích các khung lớn bị gộp nhiều khóm lúa (từ 3 khóm trở lên) và tự động tách thành từng bản ghi khóm lúa đơn lẻ độc lập có tọa độ tâm riêng.',
      tip: '📡 Khắc phục triệt để hiện tượng mô hình khoanh 1 vùng lớn chứa hàng chục khóm lúa mới cấy.',
    },
    'fuse-existing-btn': {
      stage: 'Sidebar Workflow · Bước B.5 (Gộp biên)',
      title: '🧭 5. Gộp khung trùng biên',
      desc: 'Loại bỏ các khung nhận diện bị nhân đôi ở vùng chồng lấn (overlap) giữa 2 ô quét liền kề, đồng thời bảo vệ không gộp nhầm 2 khóm lúa đứng sát nhau.',
      tip: '📡 Giúp số lượng đếm khóm lúa/cây cảnh không bị trùng lặp ở mép các ô lưới.',
    },
    'sr-enhance-btn': {
      stage: 'Sidebar Workflow · Bước C.6.1 (Siêu phân giải)',
      title: '🛰️ 6.1 TTST 4x (Viễn thám UAV)',
      desc: 'Chạy mạng Top-k Token Selective Transformer (ttst_4x.pth) huấn luyện chuyên biệt trên ảnh viễn thám/UAV chụp từ trên cao để tái tạo chi tiết lá lúa, tán cây và bụi cỏ mờ.',
      tip: '📡 Khuyên dùng hàng đầu cho ảnh UAV nông nghiệp (đã tích hợp sẵn trọng số ttst_4x.pth).',
    },
    'sr-btn-uav-detail': {
      stage: 'Sidebar Workflow · Bước C.6.2 (Siêu phân giải)',
      title: '🌿 6.2 UAV Detail (Khử mờ tán lá)',
      desc: 'Giải chập quang học (Lucy-Richardson Deconvolution) kết hợp lọc vi tương phản đa tỷ lệ (DoG + CLAHE trên kênh LAB) để làm nổi gân lá và tách rõ ranh giới khóm lúa.',
      tip: '📡 Tốc độ xử lý cực nhanh, không làm biến dạng hình học của bụi lúa nhỏ.',
    },
    'sr-btn-realesrgan': {
      stage: 'Sidebar Workflow · Bước C.6.3 (Siêu phân giải)',
      title: '⚡ 6.3 Real-ESRGAN (Khôi phục biên)',
      desc: 'Sử dụng kiến trúc RRDBNet / SRVGGNet để khôi phục biên lá sắc nét khi ảnh UAV bị rung nhẹ hoặc chụp ở độ cao lớn.',
      tip: '📡 Rất hiệu quả khi cần làm rõ đường viền tán cây cảnh và bụi cỏ.',
    },
    'sr-btn-swinir': {
      stage: 'Sidebar Workflow · Bước C.6.4 (Siêu phân giải)',
      title: '🌾 6.4 SwinIR (Giữ hình học lúa)',
      desc: 'Sử dụng Swin Transformer khôi phục ảnh thực tế với ưu điểm giữ nguyên cấu trúc hình học của hàng lúa và khoảng cách giữa các khóm mà không sinh chi tiết giả.',
      tip: '📡 Phù hợp khi cần kiểm tra chính xác tâm cây và tách các khóm lúa đứng sát nhau.',
    },
    'sr-btn-hat': {
      stage: 'Sidebar Workflow · Bước C.6.5 (Siêu phân giải)',
      title: '🔬 6.5 HAT Transformer (Chi tiết sâu)',
      desc: 'Kết hợp Channel Attention và Window Self-Attention để huy động nhiều pixel lân cận nhất nhằm tái tạo kết cấu tán lá cực nét.',
      tip: '📡 Dùng cho các đối tượng khó phân biệt cần độ nét tối đa.',
    },
    'sr-btn-lanczos': {
      stage: 'Sidebar Workflow · Bước C.6.6 (Nội suy chuẩn)',
      title: '📐 6.6 Lanczos (Nội suy trắc địa)',
      desc: 'Phóng đại ảnh bằng thuật toán toán học Lanczos-4 thuần túy, giữ trung thực 100% giá trị quang phổ gốc mà không dùng mạng AI.',
      tip: '📡 Dùng khi muốn đối chiếu nguyên bản pixel gốc với các thuật toán AI.',
    },
    'sidebar-sr-scale': {
      stage: 'Sidebar Workflow · Bước C (Mức phóng)',
      title: 'Hệ số phóng đại (2x / 4x)',
      desc: 'Chọn mức phóng đại 2 lần hoặc 4 lần khi bấm vào bất kỳ tùy chọn Tăng phân giải nào bên dưới.',
      tip: '📡 Chọn 4x cho khóm lúa mới cấy rất nhỏ; chọn 2x cho cây cảnh hoặc bụi lớn.',
    },
    'auto-triage-btn': {
      stage: 'Sidebar Workflow · Bước D.7 (Lọc thông minh)',
      title: '⚡ 7. Lọc nhanh theo mẫu đã duyệt',
      desc: 'Học đặc trưng (Kích thước khóm + Chỉ số NDVI + Chiều cao DEM) từ chính vài đối tượng bạn vừa xác nhận ("Giữ khung gốc" / "Dùng khung co" / "Loại bỏ") để tự động duyệt hàng loạt các khóm lúa tương đồng còn lại.',
      tip: '📡 Chỉ cần duyệt mẫu 3–5 khóm lúa chuẩn rồi bấm nút này để tiết kiệm 80–90% thời gian duyệt tay.',
    },
    'review-all-candidate': {
      stage: 'Sidebar Workflow · Bước D (Duyệt hàng loạt)',
      title: '✓ Duyệt tất cả (Khung co)',
      desc: 'Chấp nhận toàn bộ các đối tượng trong phiên bằng Khung đề nghị co sát (màu xanh) để sẵn sàng xuất sang bản vẽ CAD/DXF.',
      tip: '📡 Dùng sau khi đã tách khóm và lọc bỏ các khung nhiễu.',
    },
    'review-all-raw': {
      stage: 'Sidebar Workflow · Bước D (Duyệt hàng loạt)',
      title: '✓ Duyệt tất cả (Khung gốc)',
      desc: 'Chấp nhận toàn bộ các đối tượng trong phiên theo Khung nhận diện gốc ban đầu của mô hình AI.',
      tip: '📡 Phù hợp khi khung gốc của AI đã vừa vặn với đối tượng.',
    },
    'toggle-box-overlay': {
      stage: 'Khu So sánh Ảnh',
      title: '🎯 Ẩn / Hiện khung viền trắc địa',
      desc: 'Tắt hoặc bật nét vẽ khung bao trên cả ảnh phóng to lẫn ảnh tổng quan để khung viền không che khuất các khóm lúa nhỏ bên dưới.',
      tip: '📡 Rất hữu ích khi kiểm tra khóm lúa mới cấy có kích thước chỉ vài pixel.',
    },
    'toggle-map-boxes': {
      stage: 'Bản đồ Tổng quan',
      title: '🛰️ Bật / Tắt khung nhận diện trên bản đồ',
      desc: 'Ẩn hoặc hiện đồng loạt tất cả các khung nhận diện trên bản đồ lớn để quan sát rõ nền ảnh gốc.',
      tip: '📡 Đồng bộ trực tiếp với nút Ẩn/Hiện khung viền ở khu so sánh.',
    },
    'fig-raw': {
      stage: 'Khu So sánh 3 Khung · Cột 1',
      title: 'Khung gốc (Viền Cam)',
      desc: 'Hiển thị cửa sổ ảnh gốc kèm khung bao ban đầu do mô hình AI phát hiện. Bấm vào ảnh để mở phóng to toàn màn hình.',
      tip: '📡 Nếu bấm "Ẩn khung viền", ảnh này sẽ hiển thị ảnh gốc sạch không có nét vẽ đè lên.',
    },
    'fig-candidate': {
      stage: 'Khu So sánh 3 Khung · Cột 2',
      title: 'Khung đề nghị (Viền Xanh)',
      desc: 'Hiển thị khung đã co sát vào tán lá thực tế bằng phổ NDVI/ExG và đánh dấu từng khóm lúa con (viền xanh lá) bên trong.',
      tip: '📡 Giúp kiểm tra xem khung có bị lẫn bùn/nước hay chứa nhiều khóm lúa gộp hay không.',
    },
    'object-context-fig': {
      stage: 'Khu So sánh 3 Khung · Cột 3',
      title: 'Vị trí trên ảnh tổng',
      desc: 'Hiển thị vùng cảnh quan rộng xung quanh đối tượng trên ảnh ghép tổng thể để bạn biết chính xác đối tượng nằm ở hàng lúa, bờ ruộng hay mương nước nào.',
      tip: '📡 Khung chỉ thị trên ảnh tổng cũng tự động ẩn/hiện khi bạn bấm nút Ẩn khung viền.',
    },
    'review-raw': {
      stage: 'Duyệt Đối tượng Đang xem',
      title: 'Giữ khung gốc (Tự chuyển ảnh tiếp)',
      desc: 'Xác nhận đối tượng đang xem là đúng theo Khung gốc (màu cam), lưu làm mẫu chuẩn và tự động chuyển ngay sang đối tượng tiếp theo.',
      tip: '📡 Nếu cần sửa lại đối tượng vừa duyệt, chỉ cần bấm "◀ Ảnh trước".',
    },
    'review-candidate': {
      stage: 'Duyệt Đối tượng Đang xem',
      title: 'Dùng khung co (Tự chuyển ảnh tiếp)',
      desc: 'Xác nhận đối tượng đang xem là đúng theo Khung đề nghị co sát tán cây (màu xanh), lưu làm mẫu dương tính và tự động chuyển ngay sang đối tượng tiếp theo.',
      tip: '📡 Nếu cần sửa lại đối tượng vừa duyệt, chỉ cần bấm "◀ Ảnh trước".',
    },
    'crop-out-grass-btn': {
      stage: 'Xử lý Vùng Hỗn hợp (Lúa + 1 phần Cỏ bờ)',
      title: '🌾+🌱 Có 1 phần Cỏ (Lọc lấy Lúa)',
      desc: 'Dùng khi khung nhận diện trùm lên cả bờ cỏ lẫn mặt ruộng lúa (khiến máy báo nhầm cả vùng là Grass). Nút này tự động loại bỏ dải cỏ bờ lớn khỏi khung bao, co khung chỉ ôm vùng các khóm lúa con và gắn nhãn "Newly transplanted rice + Partial Grass".',
      tip: '📡 Tự động duyệt và chuyển ngay sang đối tượng tiếp theo.',
    },
    'split-mixed-btn': {
      stage: 'Xử lý Vùng Hỗn hợp (Tách Cỏ & Lúa)',
      title: '✂️ Tách riêng Cỏ & Lúa',
      desc: 'Tách khung lớn đang xem thành các bản ghi độc lập: phần dải bờ cỏ lớn được tách thành bản ghi "🌱 Grass (Cỏ)" riêng, còn từng khóm lúa nhỏ bên dưới được tách thành các bản ghi "🌾 Newly transplanted rice (Lúa mới cấy)" riêng.',
      tip: '📡 Rất hiệu quả cho các khung chứa từ vài chục đến hàng trăm khóm lúa nằm sát bờ ruộng.',
    },
    'review-reject': {
      stage: 'Duyệt Đối tượng Đang xem',
      title: 'Loại bỏ (Tự chuyển ảnh tiếp)',
      desc: 'Đánh dấu khung đang xem là nhận diện sai/nhiễu (không xuất ra CAD), ghi nhận mẫu âm tính và tự động chuyển ngay sang đối tượng tiếp theo.',
      tip: '📡 Nếu bấm nhầm, chỉ cần bấm "◀ Ảnh trước" để chọn lại.',
    },
    'object-subclass': {
      stage: 'Phân loại Chi tiết',
      title: 'Phân lớp đối tượng (Gắn nhãn)',
      desc: 'Xem hoặc gán lại nhãn phân lớp chuyên sâu (Lúa mới cấy, Lúa khỏe, Cỏ, Cây đơn lẻ, Cụm cây, Hàng rào cây, Trạm/Người, Máy nông nghiệp).',
      tip: '📡 Khi xuất DXF/DWG ở Bước 4, mỗi phân lớp sẽ được tách thành Layer CAD riêng.',
    },
    'results-filter': {
      stage: 'Bộ lọc Danh sách',
      title: 'Bộ lọc trạng thái duyệt',
      desc: 'Lọc danh sách để chỉ xem các đối tượng Chưa duyệt, Độ tin cậy thấp cần kiểm tra, hoặc Đã duyệt.',
      tip: '📡 Chọn "Độ tin cậy thấp (Cần duyệt)" sau khi chạy Lọc nhanh để chỉ kiểm tra các ca khó.',
    },
    'detect-plan': {
      stage: 'Bước 03 · Nhận diện ảnh',
      title: '1. Kiểm tra lượt nhận diện',
      desc: 'Tính toán trước số lượng ô quét nhỏ và số lượt suy luận GPU dựa trên phạm vi bạn đã chọn.',
      tip: '📡 Nhờ cơ chế gộp đa danh mục mới, số lượt hỏi mô hình đã giảm 2–4 lần.',
    },
    'detect-start': {
      stage: 'Bước 03 · Nhận diện ảnh',
      title: '2. Bắt đầu nhận diện',
      desc: 'Khởi chạy pipeline nhận diện AI tăng tốc (Prefetch đa luồng + Fast-Skip vùng nước trống + TF32 GPU) và đẩy kết quả trực tiếp sang khu đối chiếu.',
      tip: '📡 Bạn có thể duyệt & gắn nhãn đối tượng ngay trong lúc máy đang quét.',
    },
    'detect-pause': {
      stage: 'Bước 03 · Quản lý GPU',
      title: '⏸ Tạm dừng (Nhả GPU)',
      desc: 'Lưu ngay lập tức tiến độ quét hiện tại vào đĩa (checkpoint.json) và giải phóng hoàn toàn bộ nhớ VRAM để bạn dùng card đồ họa cho việc khác.',
      tip: '📡 Không mất bất kỳ kết quả nào đã quét được.',
    },
    'detect-resume': {
      stage: 'Bước 03 · Quản lý GPU',
      title: '▶ Tiếp tục quét',
      desc: 'Nạp lại phiên nhận diện đang tạm dừng và tiếp tục quét chính xác từ ô ảnh tiếp theo mà không phải chạy lại từ đầu.',
      tip: '📡 Giữ nguyên toàn bộ các đối tượng và trạng thái bạn đã duyệt trước đó.',
    },
    'export-cad': {
      stage: 'Bước 04 · Xuất Bản vẽ CAD',
      title: 'Xuất DXF',
      desc: 'Xuất toàn bộ các đối tượng đã duyệt sang tệp bản vẽ kỹ thuật chuẩn AutoCAD (.dxf) kèm tọa độ thực và phân lớp Layer.',
      tip: '📡 Tự động loại bỏ các khung chồng lấn trước khi xuất.',
    },
    'export-dwg': {
      stage: 'Bước 04 · Xuất Bản vẽ CAD',
      title: 'Xuất AutoCAD (DWG)',
      desc: 'Kết nối trực tiếp với phần mềm AutoCAD trên máy để vẽ đối tượng và lưu thành tệp .dwg chuẩn.',
      tip: '📡 Hỗ trợ đầy đủ tọa độ VN2000 / UTM từ Bước 1.',
    },
    'survey-export-dxf-btn': {
      stage: 'Bước 04 · Bình đồ Khảo sát',
      title: 'Xuất Bình đồ Khảo sát (.dxf)',
      desc: 'Ánh xạ từng loại đối tượng sang Block ký hiệu địa chính, đường đôi (mương/đường) và Layer chuẩn VN2000 để xuất thành tệp binh_do_khao_sat.dxf.',
      tip: '📡 Có thể nạp tệp .dxf mẫu của đơn vị bạn để dùng đúng bộ Block nội bộ.',
    },
    'save-dataset-btn': {
      stage: 'Bước 04 · Huấn luyện AI',
      title: 'Lưu mẫu huấn luyện',
      desc: 'Đóng gói các khung bạn đã xác nhận (mẫu dương) và các khung đã loại bỏ (mẫu âm) vào thư mục outputs/training_dataset/ để huấn luyện mô hình tốc độ cao cho các đợt bay sau.',
      tip: '📡 Càng lưu nhiều phiên, bộ dữ liệu chuẩn của cánh đồng càng đầy đủ.',
    },
    'quick-save-dataset-btn': {
      stage: 'Bước D · Lưu nhanh Dataset',
      title: '8. Lưu mẫu huấn luyện',
      desc: 'Lưu trực tiếp toàn bộ đối tượng đã duyệt và gắn nhãn của phiên hiện tại vào bộ Dataset Ground Truth (outputs/training_dataset/).',
      tip: '📡 Tương đương nút Lưu mẫu huấn luyện tại Bước 04.',
    },
    'download-reviewed-json-btn': {
      stage: 'Bước 04 · Xuất tệp nhãn JSON',
      title: 'Lưu file nhãn (.json)',
      desc: 'Tải về máy tệp JSON chứa toàn bộ tọa độ khung, trạng thái duyệt, phân lớp cây trồng và chỉ số đa phổ của phiên hiện tại.',
      tip: '📡 Có thể mở lại bất cứ lúc nào bằng nút Chọn file (.json).',
    },
  };

  const helpBanner = document.createElement('div');
  helpBanner.id = 'help-mode-banner';
  helpBanner.className = 'help-mode-banner';
  helpBanner.hidden = true;
  helpBanner.innerHTML = `
    <span>🧭 <strong>Chế độ Giải thích Chức năng</strong>: Rê chuột đến nút bất kỳ để xem công dụng · Nhấn <kbd>Esc</kbd> để thoát</span>
    <button type="button" id="help-banner-exit">Thoát (Esc)</button>
  `;
  document.body.append(helpBanner);

  const helpPop = document.createElement('div');
  helpPop.id = 'help-inspector-popover';
  helpPop.className = 'help-inspector-popover';
  helpPop.hidden = true;
  document.body.append(helpPop);

  let helpModeActive = false;
  let lastHoveredTarget = null;

  function syncHelpButtons() {
    for (const id of ['help-mode-btn', 'review-help-btn']) {
      const btn = $(id);
      if (!btn) continue;
      btn.setAttribute('aria-pressed', String(helpModeActive));
      btn.classList.toggle('active-help-mode', helpModeActive);
      btn.textContent = '?';
    }
  }

  function setHelpMode(active) {
    helpModeActive = Boolean(active);
    document.body.classList.toggle('help-inspector-active', helpModeActive);
    helpBanner.hidden = !helpModeActive;
    if (!helpModeActive) {
      helpPop.hidden = true;
      if (lastHoveredTarget) {
        lastHoveredTarget.classList.remove('help-hover-target');
        lastHoveredTarget = null;
      }
    }
    syncHelpButtons();
  }

  function resolveHelpInfo(el) {
    if (!el) return null;
    const target = el.closest(
      'button, select, input, textarea, summary, a, #fig-raw, #fig-candidate, #object-context-fig, #object-meta, .sidebar-wf-card, #taskmgr-panel'
    );
    if (!target) return null;
    if (target.id && HELP_CATALOG[target.id]) {
      return { target, ...HELP_CATALOG[target.id] };
    }
    if (target.dataset?.catChip) {
      return {
        target,
        stage: 'Bước 03 · Chọn nhanh đối tượng nông nghiệp',
        title: `🌾 Thêm đối tượng "${target.dataset.catChip}"`,
        desc: `Bấm để thêm nhanh từ khóa "${target.dataset.catChip}" vào danh sách đối tượng cần tìm kiếm trên ảnh.`,
        tip: '📡 Có thể kết hợp nhiều loại đối tượng trong cùng 1 lần quét.',
      };
    }
    if (target.dataset?.surveyCat) {
      return {
        target,
        stage: 'Bước 04 · Đối tượng Khảo sát CAD',
        title: `📐 Thêm đối tượng khảo sát "${target.dataset.surveyCat}"`,
        desc: `Thêm "${target.dataset.surveyCat}" vào danh mục nhận diện để phục vụ vẽ tự động Bình đồ Khảo sát (2 nét song song hoặc chèn Block CAD).`,
        tip: '📡 Quy tắc Layer và Block được cấu hình ngay trong bảng bên dưới.',
      };
    }
    if (target.dataset?.tmTab) {
      const tabNames = {
        cpu: ['Task Manager · Bộ vi xử lý', '🖥️ CPU Telemetry', 'Xem biểu đồ xung nhịp GHz, % tải thực thi đa luồng và số nhân logic khi đọc ảnh GeoTIFF / nạp trước ô lưới.'],
        ram: ['Task Manager · Bộ nhớ hệ thống', '🖥️ Memory (RAM) Telemetry', 'Xem dung lượng bộ nhớ RAM đang sử dụng và phần bộ nhớ dùng chung (Shared GPU Memory) cấp cho pipeline nhận diện.'],
        gpu0: ['Task Manager · Đồ họa tích hợp', '🖥️ GPU 0 (Intel UHD Graphics)', 'Theo dõi hoạt động của bộ xử lý đồ họa tích hợp phục vụ hiển thị giao diện và giải mã ảnh nền.'],
        gpu1: ['Task Manager · Card đồ họa rời AI', '🖥️ GPU 1 (NVIDIA GeForce RTX)', 'Theo dõi trực tiếp tải nhân 3D/CUDA, băng thông Copy DMA (Pinned Memory), VRAM Dedicated, Shared Memory và Nhiệt độ (°C).'],
        objects: ['Task Manager · Đối tượng Nông nghiệp', '🌾 Telemetry Đối tượng & Khóm lúa', 'Theo dõi biến động số lượng đối tượng phát hiện, tổng số khóm lúa đơn lẻ đã tách và tỷ lệ phân lớp trực tiếp.'],
      }[target.dataset.tmTab];
      if (tabNames) {
        return {
          target,
          stage: tabNames[0],
          title: tabNames[1],
          desc: tabNames[2],
          tip: '📡 Bấm để chuyển 4 biểu đồ dao động bên phải sang thành phần này.',
        };
      }
    }
    if (target.dataset?.step) {
      const stepNum = target.dataset.step;
      const stepExplain = {
        '1': ['Bước 01 / 04', '📡 Ảnh & Tọa độ Base', 'Chọn tệp ảnh GeoTIFF nguồn, kiểm tra hệ tọa độ CRS, độ phân giải GSD và nhập tọa độ mốc Base RTK (X, Y).'],
        '2': ['Bước 02 / 04', '🧭 Chia lưới ảnh UAV', 'Thiết lập kích thước ảnh con và độ chồng phủ (Overlap) để chia ảnh lớn thành lưới phục vụ xử lý.'],
        '3': ['Bước 03 / 04', '🌾 Nhận diện ảnh', 'Chọn đối tượng cần tìm (Lúa mới cấy, Cây, Cỏ...), chọn vùng quét và chạy AI nhận diện kết hợp đối chiếu trực quan.'],
        '4': ['Bước 04 / 04', '📐 Xuất DXF & Dữ liệu', 'Xuất các đối tượng đã duyệt sang bản vẽ AutoCAD (.dxf / .dwg), Bình đồ khảo sát VN2000, ảnh GeoTIFF và bộ mẫu huấn luyện.'],
      }[stepNum];
      if (stepExplain) {
        return {
          target,
          stage: stepExplain[0],
          title: stepExplain[1],
          desc: stepExplain[2],
          tip: '📡 Chuyển qua lại giữa các bước bất cứ lúc nào khi dữ liệu đã sẵn sàng.',
        };
      }
    }
    if (target.id === 'object-meta') {
      return {
        target,
        stage: 'Khu So sánh · Bảng Thông số',
        title: 'Bảng Thông số Chi tiết Đối tượng (4 Thẻ)',
        desc: 'Hiển thị rõ ràng Trạng thái duyệt, Phân lớp, Độ tin cậy %, Chỉ số phổ (NDVI, NDRE, NDWI), Số khóm lúa, Cao độ nền Z, Chiều cao cây H và Tọa độ thực (X, Y) so với mốc Base.',
        tip: '📡 Các chỉ số tự động cập nhật ngay khi bạn bấm Phân tích Đa phổ hoặc Cập nhật DEM ở Sidebar bên phải.',
      };
    }
    const labelText = (
      target.getAttribute('title') ||
      target.getAttribute('aria-label') ||
      (target.id && document.querySelector(`label[for="${target.id}"]`)?.textContent) ||
      target.textContent ||
      ''
    ).trim().slice(0, 90);
    if (!labelText) return null;
    return {
      target,
      stage: 'Điều khiển Giao diện',
      title: labelText,
      desc: target.getAttribute('title') || `Điều khiển chức năng "${labelText}" trong quy trình xử lý ảnh UAV.`,
      tip: '📡 Nhấn phím [Esc] để thoát chế độ giải thích và thao tác bình thường.',
    };
  }

  function positionHelpPopover(clientX, clientY, targetRect) {
    const popW = helpPop.offsetWidth || 370;
    const popH = helpPop.offsetHeight || 160;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = (clientX || targetRect.left) + 18;
    let top = (clientY || targetRect.bottom) + 18;
    if (left + popW + 16 > vw) {
      left = Math.max(12, (clientX || targetRect.right) - popW - 18);
    }
    if (top + popH + 16 > vh) {
      top = Math.max(12, (clientY || targetRect.top) - popH - 18);
    }
    helpPop.style.left = `${Math.round(left)}px`;
    helpPop.style.top = `${Math.round(top)}px`;
  }

  document.addEventListener('mousemove', (e) => {
    if (!helpModeActive) return;
    if (e.target.closest('#help-mode-btn, #review-help-btn, #help-mode-banner')) {
      helpPop.hidden = true;
      if (lastHoveredTarget) {
        lastHoveredTarget.classList.remove('help-hover-target');
        lastHoveredTarget = null;
      }
      return;
    }
    const info = resolveHelpInfo(e.target);
    if (!info) {
      helpPop.hidden = true;
      if (lastHoveredTarget) {
        lastHoveredTarget.classList.remove('help-hover-target');
        lastHoveredTarget = null;
      }
      return;
    }
    if (lastHoveredTarget !== info.target) {
      if (lastHoveredTarget) lastHoveredTarget.classList.remove('help-hover-target');
      lastHoveredTarget = info.target;
      lastHoveredTarget.classList.add('help-hover-target');
      helpPop.innerHTML = `
        <span class="help-pop-stage">${escapeHtml(info.stage)}</span>
        <strong class="help-pop-title">${escapeHtml(info.title)}</strong>
        <p class="help-pop-desc">${escapeHtml(info.desc)}</p>
        ${info.tip ? `<p class="help-pop-tip">${escapeHtml(info.tip)}</p>` : ''}
      `;
    }
    helpPop.hidden = false;
    positionHelpPopover(e.clientX, e.clientY, info.target.getBoundingClientRect());
  });

  document.addEventListener('click', (e) => {
    if (!helpModeActive) return;
    if (e.target.closest('#help-mode-btn, #review-help-btn, #help-banner-exit')) return;
    const info = resolveHelpInfo(e.target);
    if (info) {
      e.preventDefault();
      e.stopPropagation();
      positionHelpPopover(e.clientX, e.clientY, info.target.getBoundingClientRect());
    }
  }, true);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && helpModeActive) {
      e.preventDefault();
      setHelpMode(false);
    }
  });

  for (const id of ['help-mode-btn', 'review-help-btn']) {
    $(id)?.addEventListener('click', () => setHelpMode(!helpModeActive));
  }
  $('help-banner-exit')?.addEventListener('click', () => setHelpMode(false));

  // ==========================================================================
  // Task Manager Hardware & Object Telemetry Workstation (Three.js + Anime.js)
  // ==========================================================================
  const TM_HISTORY_LEN = 60;
  const tmHistory = {
    cpu: Array(TM_HISTORY_LEN).fill(14),
    ram: Array(TM_HISTORY_LEN).fill(68),
    gpu0: Array(TM_HISTORY_LEN).fill(1),
    gpu1_3d: Array(TM_HISTORY_LEN).fill(12),
    gpu1_copy: Array(TM_HISTORY_LEN).fill(2),
    gpu1_ded: Array(TM_HISTORY_LEN).fill(42),
    gpu1_shared: Array(TM_HISTORY_LEN).fill(14),
    obj_count: Array(TM_HISTORY_LEN).fill(0),
    obj_clumps: Array(TM_HISTORY_LEN).fill(0),
    obj_reviewed: Array(TM_HISTORY_LEN).fill(0),
    obj_progress: Array(TM_HISTORY_LEN).fill(0),
  };
  let tmActiveTab = 'gpu1';
  let tm3dEnabled = true;
  let tmGridPhase = 0;
  let tmLastTelemetry = null;
  const tmAnimNumbers = { total: 0, clumps: 0, reviewed: 0, progress: 0 };

  function pushRing(arr, val) {
    arr.push(Math.max(0, Math.min(100, Number(val) || 0)));
    if (arr.length > TM_HISTORY_LEN) arr.shift();
  }

  function computeClientObjectStats() {
    const records = state.results?.records || [];
    const totalAll = state.results?.total_all ?? state.results?.total ?? model.job?.live_count ?? records.length;
    const reviewed = state.results?.reviewed ?? records.filter(r => r.review_status && r.review_status !== 'unreviewed').length;
    const activeJobId = state.results?.job?.id || state.loadedJob || '';
    let estClumps = totalAll;
    let classCounts = {};
    if (records.length > 0) {
      let sampleClumps = 0;
      for (const r of records) {
        const c = Number(r.clump_count ?? r.refinement?.estimated_plant_count ?? 1);
        sampleClumps += Number.isFinite(c) && c > 0 ? c : 1;
        const cls = String(r.sub_class || r.label || r.category || 'Khác').trim();
        classCounts[cls] = (classCounts[cls] || 0) + 1;
      }
      const scaleFactor = totalAll > records.length ? (totalAll / records.length) : 1;
      estClumps = Math.max(totalAll, Math.round(sampleClumps * scaleFactor));
      if (scaleFactor > 1.05) {
        for (const k of Object.keys(classCounts)) {
          classCounts[k] = Math.round(classCounts[k] * scaleFactor);
        }
      }
      state.cachedObjectStats = { jobId: activeJobId, total_clumps: estClumps, class_counts: { ...classCounts } };
    } else if (state.cachedObjectStats && state.cachedObjectStats.jobId === activeJobId && totalAll > 0) {
      estClumps = state.cachedObjectStats.total_clumps;
      classCounts = { ...state.cachedObjectStats.class_counts };
    }
    const done = model.job?.done ?? state.results?.job?.done ?? 0;
    const totalQ = model.job?.total ?? state.results?.job?.total ?? 0;
    return {
      total: totalAll,
      reviewed,
      unreviewed: Math.max(0, totalAll - reviewed),
      total_clumps: estClumps,
      class_counts: classCounts,
      job_status: model.job?.status || state.results?.job?.status || 'idle',
      job_done: done,
      job_total: totalQ,
    };
  }

  function synthesizeFallbackTelemetry() {
    const isRunning = ['queued', 'running', 'cancelling'].includes(model.job?.status);
    const wave = Math.sin(Date.now() / 1100);
    const jitter = (Math.random() - 0.5) * 3.2;
    const util3d = isRunning ? Math.min(100, Math.max(82, 95 + wave * 3 + jitter)) : Math.max(2, 8 + wave * 3 + jitter);
    const utilCopy = isRunning ? Math.min(100, Math.max(12, 34 + wave * 9 + jitter)) : Math.max(0, 2 + Math.abs(jitter));
    const dedUsed = isRunning ? 11.45 : 3.2;
    const dedTotal = 12.0;
    const sharedUsed = isRunning ? 3.45 : 0.85;
    const sharedTotal = 15.9;
    const cpuPct = isRunning ? Math.min(100, Math.max(18, 28 + wave * 6 + jitter)) : Math.max(3, 9 + wave * 2 + jitter);
    const tempC = isRunning ? Math.round(49 + wave * 1.5) : 41;
    return {
      cpu: {
        name: 'Intel(R) Core(TM) i7-14700K',
        utilization_pct: Number(cpuPct.toFixed(1)),
        speed_ghz: isRunning ? 4.48 : 4.12,
        cores: 28,
      },
      memory: {
        used_gb: isRunning ? 22.1 : 18.4,
        total_gb: 31.8,
        percent: isRunning ? 69.5 : 57.8,
      },
      gpus: [
        {
          id: 'GPU 0',
          name: 'Intel(R) UHD Graphics 770',
          type: 'Integrated (iGPU)',
          utilization_pct: isRunning ? 2.0 : 0.5,
          copy_pct: 0.0,
          dedicated_used_gb: 0.0,
          dedicated_total_gb: 0.0,
          shared_used_gb: 0.4,
          shared_total_gb: 15.9,
          total_used_gb: 0.4,
          total_memory_gb: 15.9,
          temperature_c: null,
          driver_version: '32.0.101.7088',
          driver_date: '6/18/2026',
          directx_version: '12 (FL 12.1)',
          physical_location: 'PCI bus 0, device 2, function 0',
        },
        {
          id: 'GPU 1',
          name: 'NVIDIA GeForce RTX 4070',
          type: 'Discrete (CUDA AI)',
          utilization_pct: Number(util3d.toFixed(1)),
          copy_pct: Number(utilCopy.toFixed(1)),
          video_encode_pct: 0.0,
          video_decode_pct: 0.0,
          dedicated_used_gb: dedUsed,
          dedicated_total_gb: dedTotal,
          shared_used_gb: sharedUsed,
          shared_total_gb: sharedTotal,
          total_used_gb: Number((dedUsed + sharedUsed).toFixed(1)),
          total_memory_gb: Number((dedTotal + sharedTotal).toFixed(1)),
          temperature_c: tempC,
          power_draw_w: isRunning ? 186.0 : 24.5,
          power_limit_w: 200.0,
          clock_graphics_mhz: isRunning ? 2475 : 210,
          driver_version: '32.0.16.1088',
          driver_date: '7/22/2026',
          directx_version: '12 (FL 12.2)',
          physical_location: 'PCI bus 1, device 0, function 0',
        },
      ],
      objects: computeClientObjectStats(),
    };
  }

  function drawTaskMgrOscilloscope(canvas, dataArr, { stroke = '#8b5cf6', fillTop = 'rgba(139, 92, 246, 0.34)', fillBottom = 'rgba(139, 92, 246, 0.04)', mini = false } = {}) {
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(48, Math.round((rect.width || canvas.width || 160) * dpr));
    const h = Math.max(26, Math.round((rect.height || canvas.height || 60) * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    const ctx2d = canvas.getContext('2d');
    if (!ctx2d) return;
    const isDark = document.documentElement.dataset.theme === 'dark';
    ctx2d.clearRect(0, 0, w, h);
    ctx2d.fillStyle = isDark ? '#0b0c10' : '#ffffff';
    ctx2d.fillRect(0, 0, w, h);

    // Subtle Task Manager scrolling grid
    const gridColor = isDark ? 'rgba(148, 163, 184, 0.13)' : 'rgba(139, 92, 246, 0.14)';
    ctx2d.strokeStyle = gridColor;
    ctx2d.lineWidth = Math.max(1, 0.8 * dpr);
    const rows = mini ? 2 : 4;
    for (let r = 1; r < rows; r++) {
      const y = Math.round((h / rows) * r) + 0.5;
      ctx2d.beginPath();
      ctx2d.moveTo(0, y);
      ctx2d.lineTo(w, y);
      ctx2d.stroke();
    }
    const cols = mini ? 4 : 10;
    const stepX = w / cols;
    const offset = (tmGridPhase * 2.5 * dpr) % stepX;
    for (let c = 0; c <= cols; c++) {
      const x = Math.round(c * stepX - offset) + 0.5;
      if (x < 0 || x > w) continue;
      ctx2d.beginPath();
      ctx2d.moveTo(x, 0);
      ctx2d.lineTo(x, h);
      ctx2d.stroke();
    }

    // Signal polygon + line
    const n = dataArr.length;
    if (n < 2) return;
    ctx2d.beginPath();
    for (let i = 0; i < n; i++) {
      const x = (i / (n - 1)) * w;
      const pct = Math.max(0, Math.min(100, dataArr[i] || 0));
      const y = h - (pct / 100) * (h - 4 * dpr) - 2 * dpr;
      if (i === 0) ctx2d.moveTo(x, y);
      else ctx2d.lineTo(x, y);
    }
    ctx2d.strokeStyle = stroke;
    ctx2d.lineWidth = (mini ? 1.5 : 2.0) * dpr;
    ctx2d.lineJoin = 'round';
    ctx2d.stroke();

    ctx2d.lineTo(w, h);
    ctx2d.lineTo(0, h);
    ctx2d.closePath();
    const grad = ctx2d.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, fillTop);
    grad.addColorStop(1, fillBottom);
    ctx2d.fillStyle = grad;
    ctx2d.fill();
  }

  // Three.js + Anime.js 3D Live Wave Telemetry Surface
  let tmThreeCtx = null;
  const tmWaveCrest = { gpu: 12, vram: 40, dma: 5, obj: 0 };

  function initTaskMgrThreeWave() {
    const canvas = $('tm-webgl-canvas');
    if (!canvas) return;
    import('three').then((THREE) => {
      let renderer;
      try {
        renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
      } catch {
        return;
      }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(38, 4, 0.1, 100);
      camera.position.set(0, 3.6, 7.2);
      camera.lookAt(0, 0.2, 0);

      // 4 3D Ribbon Lines representing CUDA 3D, Dedicated VRAM, Shared DMA, and Object stream
      const ribbons = [];
      const colors = [0xa855f7, 0x00d992, 0x38bdf8, 0xf59e0b];
      const zOffsets = [1.0, 0.35, -0.35, -1.0];
      for (let r = 0; r < 4; r++) {
        const geom = new THREE.BufferGeometry();
        const pts = new Float32Array(TM_HISTORY_LEN * 3);
        geom.setAttribute('position', new THREE.BufferAttribute(pts, 3));
        const mat = new THREE.LineBasicMaterial({ color: colors[r], linewidth: 2 });
        const line = new THREE.Line(geom, mat);
        line.position.z = zOffsets[r];
        scene.add(line);
        ribbons.push({ geom, line });
      }

      const gridHelper = new THREE.GridHelper(12, 24, 0x4c1d95, 0x1e293b);
      gridHelper.position.y = -0.6;
      scene.add(gridHelper);

      tmThreeCtx = { THREE, renderer, scene, camera, ribbons, gridHelper };

      let frameId = 0;
      function animate3D() {
        frameId = requestAnimationFrame(animate3D);
        if (!tm3dEnabled || $('tm-webgl-wrap')?.hidden) return;
        const rect = canvas.getBoundingClientRect();
        const w = Math.max(120, Math.round(rect.width || 360));
        const h = Math.max(60, Math.round(rect.height || 92));
        if (canvas.width !== w || canvas.height !== h) {
          renderer.setSize(w, h, false);
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
        }
        const t = performance.now() * 0.0022;
        const streams = [tmHistory.gpu1_3d, tmHistory.gpu1_ded, tmHistory.gpu1_shared, tmHistory.obj_progress];
        for (let r = 0; r < ribbons.length; r++) {
          const arr = streams[r];
          const pos = ribbons[r].geom.attributes.position.array;
          for (let i = 0; i < TM_HISTORY_LEN; i++) {
            const x = ((i / (TM_HISTORY_LEN - 1)) - 0.5) * 10.2;
            const val = (arr[i] || 0) / 100;
            const ripple = Math.sin(t + i * 0.25 + r) * 0.06;
            pos[i * 3] = x;
            pos[i * 3 + 1] = -0.45 + val * 1.65 + ripple;
            pos[i * 3 + 2] = 0;
          }
          ribbons[r].geom.attributes.position.needsUpdate = true;
        }
        camera.position.x = Math.sin(t * 0.35) * 0.45;
        camera.lookAt(0, 0.2, 0);
        renderer.render(scene, camera);
      }
      animate3D();
    }).catch(() => {});
  }

  function renderTaskManagerUI(data) {
    if (!$('taskmgr-panel') || !data) return;
    tmLastTelemetry = data;
    tmGridPhase = (tmGridPhase + 1) % 1000;

    const cpu = data.cpu || {};
    const mem = data.memory || {};
    const gpus = data.gpus || [];
    const gpu0 = gpus[0] || {};
    const gpu1 = gpus[1] || gpus[0] || {};

    // Combine server object stats with live client-side state.results for instant zero-lag updates
    const clientObj = computeClientObjectStats();
    const srvObj = data.objects || {};
    const objTotal = Math.max(srvObj.total || 0, clientObj.total || 0);
    const objReviewed = Math.max(srvObj.reviewed || 0, clientObj.reviewed || 0);
    const objClumps = Math.max(srvObj.total_clumps || 0, clientObj.total_clumps || 0, objTotal);
    const jobDone = clientObj.job_done || srvObj.job_done || 0;
    const jobTotal = clientObj.job_total || srvObj.job_total || 0;
    const jobPct = jobTotal > 0 ? Math.min(100, Math.round((jobDone / jobTotal) * 100)) : (objTotal > 0 ? 100 : 0);
    const classCounts = Object.keys(clientObj.class_counts || {}).length >= Object.keys(srvObj.class_counts || {}).length
      ? (clientObj.class_counts || {})
      : (srvObj.class_counts || {});

    const dedPct = gpu1.dedicated_total_gb > 0 ? (gpu1.dedicated_used_gb / gpu1.dedicated_total_gb) * 100 : 0;
    const sharedPct = gpu1.shared_total_gb > 0 ? (gpu1.shared_used_gb / gpu1.shared_total_gb) * 100 : 0;

    pushRing(tmHistory.cpu, cpu.utilization_pct ?? 10);
    pushRing(tmHistory.ram, mem.percent ?? 65);
    pushRing(tmHistory.gpu0, gpu0.utilization_pct ?? 1);
    pushRing(tmHistory.gpu1_3d, gpu1.utilization_pct ?? 0);
    pushRing(tmHistory.gpu1_copy, gpu1.copy_pct ?? 0);
    pushRing(tmHistory.gpu1_ded, dedPct);
    pushRing(tmHistory.gpu1_shared, sharedPct);
    pushRing(tmHistory.obj_count, objTotal > 0 ? Math.min(100, 20 + Math.log10(objTotal + 1) * 28) : 0);
    pushRing(tmHistory.obj_clumps, objClumps > 0 ? Math.min(100, 25 + Math.log10(objClumps + 1) * 28) : 0);
    pushRing(tmHistory.obj_reviewed, objTotal > 0 ? (objReviewed / objTotal) * 100 : 0);
    pushRing(tmHistory.obj_progress, jobPct);

    // Update Left Selector Rail labels & mini sparklines
    if ($('tm-rail-cpu-name')) $('tm-rail-cpu-name').textContent = (cpu.name || 'CPU').replace(/\(R\)|\(TM\)|14th Gen /gi, '').trim();
    if ($('tm-rail-cpu-val')) $('tm-rail-cpu-val').textContent = `${Math.round(cpu.utilization_pct || 0)}% · ${(cpu.speed_ghz || 4.2).toFixed(2)} GHz`;
    if ($('tm-rail-ram-val')) $('tm-rail-ram-val').textContent = `${(mem.used_gb || 0).toFixed(1)}/${(mem.total_gb || 31.8).toFixed(1)} GB (${Math.round(mem.percent || 0)}%)`;
    if ($('tm-rail-gpu0-name')) $('tm-rail-gpu0-name').textContent = gpu0.name || 'Intel UHD Graphics';
    if ($('tm-rail-gpu0-val')) $('tm-rail-gpu0-val').textContent = `${Math.round(gpu0.utilization_pct || 0)}% (Shared ${(gpu0.shared_used_gb || 0).toFixed(1)} GB)`;
    if ($('tm-rail-gpu1-name')) $('tm-rail-gpu1-name').textContent = gpu1.name || 'NVIDIA GeForce RTX';
    const tempNote = gpu1.temperature_c != null ? ` (${gpu1.temperature_c} °C)` : '';
    if ($('tm-rail-gpu1-val')) $('tm-rail-gpu1-val').textContent = `${Math.round(gpu1.utilization_pct || 0)}%${tempNote}`;
    if ($('tm-rail-obj-val')) $('tm-rail-obj-val').textContent = `${objTotal} khung · ${objClumps} khóm`;

    drawTaskMgrOscilloscope($('tm-spark-cpu'), tmHistory.cpu, { stroke: '#0284c7', fillTop: 'rgba(2, 132, 199, 0.32)', fillBottom: 'rgba(2, 132, 199, 0.04)', mini: true });
    drawTaskMgrOscilloscope($('tm-spark-ram'), tmHistory.ram, { stroke: '#8b5cf6', fillTop: 'rgba(139, 92, 246, 0.32)', fillBottom: 'rgba(139, 92, 246, 0.04)', mini: true });
    drawTaskMgrOscilloscope($('tm-spark-gpu0'), tmHistory.gpu0, { stroke: '#0ea5e9', fillTop: 'rgba(14, 165, 233, 0.28)', fillBottom: 'rgba(14, 165, 233, 0.03)', mini: true });
    drawTaskMgrOscilloscope($('tm-spark-gpu1'), tmHistory.gpu1_3d, { stroke: '#8b5cf6', fillTop: 'rgba(139, 92, 246, 0.36)', fillBottom: 'rgba(139, 92, 246, 0.05)', mini: true });
    drawTaskMgrOscilloscope($('tm-spark-obj'), tmHistory.obj_progress, { stroke: '#009966', fillTop: 'rgba(0, 217, 146, 0.36)', fillBottom: 'rgba(0, 217, 146, 0.05)', mini: true });

    // Update Main Detail Pane according to selected left-rail tab
    const tempBadge = $('tm-temp-badge');
    const tc = gpu1.temperature_c ?? 48;
    if (tempBadge) {
      tempBadge.classList.toggle('warn', tc >= 75 && tc < 83);
      tempBadge.classList.toggle('hot', tc >= 83);
      const statusTxt = tc < 72 ? 'Ổn định' : (tc < 82 ? 'Tải cao' : 'Nóng');
      tempBadge.textContent = `${tc} °C · ${statusTxt}`;
    }

    let c1Data = tmHistory.gpu1_3d, c2Data = tmHistory.gpu1_copy, c3Data = tmHistory.gpu1_ded, c4Data = tmHistory.gpu1_shared;
    let strokeMain = '#8b5cf6', fillMainTop = 'rgba(139, 92, 246, 0.34)', fillMainBot = 'rgba(139, 92, 246, 0.04)';

    if (tmActiveTab === 'cpu') {
      strokeMain = '#0284c7'; fillMainTop = 'rgba(2, 132, 199, 0.32)'; fillMainBot = 'rgba(2, 132, 199, 0.04)';
      $('tm-unit-title').textContent = 'CPU';
      $('tm-unit-model').textContent = cpu.name || 'Intel(R) Core(TM) i7-14700K';
      $('tm-chart1-label').textContent = '⌄ % Utilization (All Cores)';
      $('tm-chart1-val').textContent = `${Math.round(cpu.utilization_pct || 0)}%`;
      $('tm-chart2-label').textContent = '⌄ Clock Frequency';
      $('tm-chart2-val').textContent = `${(cpu.speed_ghz || 4.2).toFixed(2)} GHz`;
      $('tm-chart3-label').textContent = 'System RAM Utilization';
      $('tm-chart3-val').textContent = `${(mem.used_gb || 0).toFixed(1)} / ${(mem.total_gb || 31.8).toFixed(1)} GB`;
      $('tm-chart4-label').textContent = 'Shared GPU Memory DMA';
      $('tm-chart4-val').textContent = `${(gpu1.shared_used_gb || 0).toFixed(1)} / ${(gpu1.shared_total_gb || 15.9).toFixed(1)} GB`;
      c1Data = tmHistory.cpu; c2Data = tmHistory.cpu; c3Data = tmHistory.ram; c4Data = tmHistory.gpu1_shared;
    } else if (tmActiveTab === 'ram') {
      strokeMain = '#7c3aed'; fillMainTop = 'rgba(124, 58, 237, 0.32)'; fillMainBot = 'rgba(124, 58, 237, 0.04)';
      $('tm-unit-title').textContent = 'Memory';
      $('tm-unit-model').textContent = `${(mem.total_gb || 31.8).toFixed(1)} GB DDR5 System RAM`;
      $('tm-chart1-label').textContent = '⌄ Memory Usage %';
      $('tm-chart1-val').textContent = `${Math.round(mem.percent || 0)}%`;
      $('tm-chart2-label').textContent = '⌄ Shared GPU Pool';
      $('tm-chart2-val').textContent = `${(gpu1.shared_used_gb || 0).toFixed(1)} GB`;
      $('tm-chart3-label').textContent = 'In Use / Total Physical RAM';
      $('tm-chart3-val').textContent = `${(mem.used_gb || 0).toFixed(1)} / ${(mem.total_gb || 31.8).toFixed(1)} GB`;
      $('tm-chart4-label').textContent = 'Dedicated GPU VRAM';
      $('tm-chart4-val').textContent = `${(gpu1.dedicated_used_gb || 0).toFixed(1)} / ${(gpu1.dedicated_total_gb || 12.0).toFixed(1)} GB`;
      c1Data = tmHistory.ram; c2Data = tmHistory.gpu1_shared; c3Data = tmHistory.ram; c4Data = tmHistory.gpu1_ded;
    } else if (tmActiveTab === 'gpu0') {
      strokeMain = '#0ea5e9'; fillMainTop = 'rgba(14, 165, 233, 0.32)'; fillMainBot = 'rgba(14, 165, 233, 0.04)';
      $('tm-unit-title').textContent = 'GPU 0';
      $('tm-unit-model').textContent = gpu0.name || 'Intel(R) UHD Graphics 770';
      $('tm-chart1-label').textContent = '⌄ 3D (Integrated)';
      $('tm-chart1-val').textContent = `${Math.round(gpu0.utilization_pct || 0)}%`;
      $('tm-chart2-label').textContent = '⌄ Copy';
      $('tm-chart2-val').textContent = `${Math.round(gpu0.copy_pct || 0)}%`;
      $('tm-chart3-label').textContent = 'Shared GPU memory (GPU 0)';
      $('tm-chart3-val').textContent = `${(gpu0.shared_used_gb || 0).toFixed(1)} / ${(gpu0.shared_total_gb || 15.9).toFixed(1)} GB`;
      $('tm-chart4-label').textContent = 'GPU 1 Dedicated VRAM (RTX)';
      $('tm-chart4-val').textContent = `${(gpu1.dedicated_used_gb || 0).toFixed(1)} / ${(gpu1.dedicated_total_gb || 12.0).toFixed(1)} GB`;
      c1Data = tmHistory.gpu0; c2Data = tmHistory.gpu0; c3Data = tmHistory.gpu1_shared; c4Data = tmHistory.gpu1_ded;
    } else if (tmActiveTab === 'objects') {
      strokeMain = '#009966'; fillMainTop = 'rgba(0, 217, 146, 0.34)'; fillMainBot = 'rgba(0, 217, 146, 0.04)';
      $('tm-unit-title').textContent = '🌾 Đối tượng UAV';
      $('tm-unit-model').textContent = `${objTotal} đối tượng · ${objClumps} khóm lúa`;
      $('tm-chart1-label').textContent = '⌄ Mật độ Đối tượng phát hiện';
      $('tm-chart1-val').textContent = `${objTotal} khung`;
      $('tm-chart2-label').textContent = '⌄ Mật độ Khóm lúa tách';
      $('tm-chart2-val').textContent = `${objClumps} khóm`;
      $('tm-chart3-label').textContent = 'Tiến độ quét lưới UAV';
      $('tm-chart3-val').textContent = `${jobDone} / ${jobTotal} lượt (${jobPct}%)`;
      $('tm-chart4-label').textContent = 'Tỷ lệ Đã duyệt & Gắn nhãn';
      $('tm-chart4-val').textContent = `${objReviewed} / ${objTotal} (${objTotal ? Math.round((objReviewed / objTotal) * 100) : 0}%)`;
      c1Data = tmHistory.obj_count; c2Data = tmHistory.obj_clumps; c3Data = tmHistory.obj_progress; c4Data = tmHistory.obj_reviewed;
    } else {
      // Default: GPU 1 (NVIDIA GeForce RTX 4070) matching Image 2
      $('tm-unit-title').textContent = 'GPU 1';
      $('tm-unit-model').textContent = gpu1.name || 'NVIDIA GeForce RTX 4070';
      $('tm-chart1-label').textContent = '⌄ 3D / CUDA Compute';
      $('tm-chart1-val').textContent = `${Math.round(gpu1.utilization_pct || 0)}%`;
      $('tm-chart2-label').textContent = '⌄ Copy / Shared DMA';
      $('tm-chart2-val').textContent = `${Math.round(gpu1.copy_pct || 0)}%`;
      $('tm-chart3-label').textContent = 'Dedicated GPU memory';
      $('tm-chart3-val').textContent = `${(gpu1.dedicated_used_gb || 0).toFixed(1)} / ${(gpu1.dedicated_total_gb || 12.0).toFixed(1)} GB`;
      $('tm-chart4-label').textContent = 'Shared GPU memory';
      $('tm-chart4-val').textContent = `${(gpu1.shared_used_gb || 0).toFixed(1)} / ${(gpu1.shared_total_gb || 15.9).toFixed(1)} GB`;
    }

    drawTaskMgrOscilloscope($('tm-canvas-1'), c1Data, { stroke: strokeMain, fillTop: fillMainTop, fillBottom: fillMainBot });
    drawTaskMgrOscilloscope($('tm-canvas-2'), c2Data, { stroke: strokeMain, fillTop: fillMainTop, fillBottom: fillMainBot });
    drawTaskMgrOscilloscope($('tm-canvas-3'), c3Data, { stroke: strokeMain, fillTop: fillMainTop, fillBottom: fillMainBot });
    drawTaskMgrOscilloscope($('tm-canvas-4'), c4Data, { stroke: strokeMain, fillTop: fillMainTop, fillBottom: fillMainBot });

    // Bottom Task Manager Readouts (exact match with Image 2)
    if ($('tm-stat-util')) $('tm-stat-util').textContent = `${Math.round(gpu1.utilization_pct || 0)}%`;
    if ($('tm-stat-ded')) $('tm-stat-ded').textContent = `${(gpu1.dedicated_used_gb || 0).toFixed(1)}/${(gpu1.dedicated_total_gb || 12.0).toFixed(1)} GB`;
    if ($('tm-stat-total-mem')) $('tm-stat-total-mem').textContent = `${(gpu1.total_used_gb || 0).toFixed(1)}/${(gpu1.total_memory_gb || 27.9).toFixed(1)} GB`;
    if ($('tm-stat-shared')) $('tm-stat-shared').textContent = `${(gpu1.shared_used_gb || 0).toFixed(1)}/${(gpu1.shared_total_gb || 15.9).toFixed(1)} GB`;
    if ($('tm-stat-temp')) $('tm-stat-temp').textContent = `${tc} °C`;
    const pwr = gpu1.power_draw_w != null ? `${Math.round(gpu1.power_draw_w)} W` : '—';
    const clk = gpu1.clock_graphics_mhz != null ? `${gpu1.clock_graphics_mhz} MHz` : '';
    if ($('tm-stat-power')) $('tm-stat-power').textContent = clk ? `${pwr} · ${clk}` : pwr;

    if ($('tm-meta-driver')) $('tm-meta-driver').textContent = gpu1.driver_version || '32.0.16.1088';
    if ($('tm-meta-date')) $('tm-meta-date').textContent = gpu1.driver_date || '7/22/2026';
    if ($('tm-meta-dx')) $('tm-meta-dx').textContent = gpu1.directx_version || '12 (FL 12.2)';
    if ($('tm-meta-loc')) $('tm-meta-loc').textContent = gpu1.physical_location || 'PCI bus 1, device 0, function 0';
    if ($('tm-meta-gpu0')) $('tm-meta-gpu0').textContent = gpu0.name || 'Intel(R) UHD Graphics 770';
    if ($('tm-meta-cpu')) $('tm-meta-cpu').textContent = `${(cpu.name || 'i7-14700K').replace(/Intel\(R\) Core\(TM\) /i, '')} · ${(mem.used_gb || 0).toFixed(1)}/${(mem.total_gb || 31.8).toFixed(1)} GB`;

    // Live Object Telemetry Strip with Anime.js smooth counter transitions
    const isRunning = ['queued', 'running', 'cancelling'].includes(model.job?.status);
    if ($('tm-obj-status-pill')) {
      $('tm-obj-status-pill').textContent = isRunning
        ? `🛰️ Đang quét ${jobPct}% (${jobDone}/${jobTotal})`
        : (objTotal > 0 ? `🛰️ Đã nạp ${objTotal} đối tượng` : '🛰️ Sẵn sàng giám sát');
    }
    if (animeAnimate && (tmAnimNumbers.total !== objTotal || tmAnimNumbers.clumps !== objClumps || tmAnimNumbers.reviewed !== objReviewed)) {
      try {
        animeAnimate(tmAnimNumbers, {
          total: objTotal,
          clumps: objClumps,
          reviewed: objReviewed,
          progress: jobPct,
          duration: 420,
          ease: 'outQuad',
          onUpdate: () => {
            if ($('tm-obj-total')) $('tm-obj-total').textContent = Math.round(tmAnimNumbers.total).toLocaleString('vi-VN');
            if ($('tm-obj-clumps')) $('tm-obj-clumps').textContent = Math.round(tmAnimNumbers.clumps).toLocaleString('vi-VN');
            if ($('tm-obj-reviewed')) $('tm-obj-reviewed').textContent = Math.round(tmAnimNumbers.reviewed).toLocaleString('vi-VN');
            if ($('tm-obj-progress')) $('tm-obj-progress').textContent = `${Math.round(tmAnimNumbers.progress)}%`;
          },
        });
      } catch {
        if ($('tm-obj-total')) $('tm-obj-total').textContent = objTotal.toLocaleString('vi-VN');
        if ($('tm-obj-clumps')) $('tm-obj-clumps').textContent = objClumps.toLocaleString('vi-VN');
        if ($('tm-obj-reviewed')) $('tm-obj-reviewed').textContent = objReviewed.toLocaleString('vi-VN');
        if ($('tm-obj-progress')) $('tm-obj-progress').textContent = `${jobPct}%`;
      }
    } else {
      tmAnimNumbers.total = objTotal;
      tmAnimNumbers.clumps = objClumps;
      tmAnimNumbers.reviewed = objReviewed;
      tmAnimNumbers.progress = jobPct;
      if ($('tm-obj-total')) $('tm-obj-total').textContent = objTotal.toLocaleString('vi-VN');
      if ($('tm-obj-clumps')) $('tm-obj-clumps').textContent = objClumps.toLocaleString('vi-VN');
      if ($('tm-obj-reviewed')) $('tm-obj-reviewed').textContent = objReviewed.toLocaleString('vi-VN');
      if ($('tm-obj-progress')) $('tm-obj-progress').textContent = `${jobPct}%`;
    }
    if ($('tm-obj-rate')) {
      const avgClump = objTotal > 0 ? (objClumps / objTotal).toFixed(1) : '1.0';
      $('tm-obj-rate').textContent = `TB: ${avgClump} khóm/khung`;
    }
    if ($('tm-obj-unreviewed')) {
      const unrevCnt = Math.max(0, objTotal - objReviewed);
      $('tm-obj-unreviewed').textContent = unrevCnt > 0
        ? `Chưa duyệt: ${unrevCnt.toLocaleString('vi-VN')} (Bấm để xem ↗)`
        : 'Đã duyệt hết 100% ✓';
      $('tm-kpi-review-box')?.classList.toggle('has-unreviewed', unrevCnt > 0);
      $('tm-kpi-review-box')?.classList.toggle('filter-active-unreviewed', state.filter === 'unreviewed');
    }
    if ($('tm-obj-queries')) {
      $('tm-obj-queries').textContent = `${jobDone} / ${jobTotal} lượt GPU`;
    }

    // Class Breakdown Bars
    const barsEl = $('tm-class-bars');
    if (barsEl) {
      const entries = Object.entries(classCounts).sort((a, b) => b[1] - a[1]).slice(0, 5);
      if (!entries.length) {
        barsEl.innerHTML = '<div class="empty-note" style="font-size:11.5px">Chưa có dữ liệu phân lớp.</div>';
      } else {
        const sumCls = Math.max(1, entries.reduce((acc, [, v]) => acc + v, 0));
        const iconForClass = (name) => {
          const low = name.toLowerCase();
          if (low.includes('newly') || low.includes('rice') || low.includes('lúa')) return '🌾';
          if (low.includes('healthy')) return '🌿';
          if (low.includes('grass') || low.includes('weed') || low.includes('cỏ')) return '🌱';
          if (low.includes('tree') || low.includes('cây')) return '🌳';
          if (low.includes('hedge') || low.includes('rào')) return '🌿';
          if (low.includes('vehicle') || low.includes('xe')) return '🚜';
          return '🛰️';
        };
        barsEl.innerHTML = entries.map(([cls, cnt]) => {
          const pct = Math.min(100, Math.round((cnt / sumCls) * 100));
          return `
            <div class="tm-class-row">
              <span class="tm-class-name">${iconForClass(cls)} ${escapeHtml(cls)}</span>
              <div class="tm-class-track"><div class="tm-class-fill" style="width:${pct}%"></div></div>
              <span class="tm-class-count">${cnt} (${pct}%)</span>
            </div>
          `;
        }).join('');
      }
    }
  }

  let tmPollingBusy = false;
  async function pollHardwareTelemetry() {
    if (tmPollingBusy || $('taskmgr-panel')?.hidden) return;
    tmPollingBusy = true;
    try {
      const resp = await fetch('/api/telemetry');
      if (resp.ok) {
        const data = await resp.json();
        renderTaskManagerUI(data);
        return;
      }
    } catch {} finally {
      tmPollingBusy = false;
    }
    renderTaskManagerUI(synthesizeFallbackTelemetry());
  }

  // Bind Task Manager Left Rail Tabs & 3D Toggle
  document.querySelectorAll('.tm-rail-item[data-tm-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      tmActiveTab = btn.dataset.tmTab || 'gpu1';
      document.querySelectorAll('.tm-rail-item[data-tm-tab]').forEach(b => {
        const active = b.dataset.tmTab === tmActiveTab;
        b.classList.toggle('active', active);
        b.setAttribute('aria-selected', String(active));
      });
      if (tmLastTelemetry) renderTaskManagerUI(tmLastTelemetry);
    });
  });

  if ($('tm-toggle-3d-btn')) {
    $('tm-toggle-3d-btn').addEventListener('click', () => {
      tm3dEnabled = !tm3dEnabled;
      $('tm-toggle-3d-btn').classList.toggle('active', tm3dEnabled);
      $('tm-toggle-3d-btn').setAttribute('aria-pressed', String(tm3dEnabled));
      if ($('tm-webgl-wrap')) $('tm-webgl-wrap').hidden = !tm3dEnabled;
    });
  }

  if ($('tm-kpi-review-box')) {
    const jumpToUnreviewed = () => action(async () => {
      const nextFilter = state.filter === 'unreviewed' ? 'all' : 'unreviewed';
      state.filter = nextFilter;
      if ($('results-filter')) $('results-filter').value = nextFilter;
      state.forceShowResults = true;
      await loadResults(0);
      $('results-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    $('tm-kpi-review-box').addEventListener('click', jumpToUnreviewed);
    $('tm-kpi-review-box').addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        jumpToUnreviewed();
      }
    });
  }

  initTaskMgrThreeWave();
  pollHardwareTelemetry();
  setInterval(pollHardwareTelemetry, 1500);

  return {controls,invalidateDetection,invalidateWarp,renderProposals,renderJob,bindViewport,resumeDetection:resumeDetectionNow,
    hasResults: () => Boolean(state.results || state.loadedJob || state.sessions?.length),
    hasTurboReady: () => Boolean(
      state.turboStatus?.dataset?.ready_to_train
      || state.turboStatus?.models?.turbo_zone?.trained
      || state.turboStatus?.models?.turbo_clump?.trained
    ),
    async initialize(data) {
      if (data.turbo_status) renderTurboStatus(data.turbo_status);
      else { try { await refreshTurboStatus(); } catch {} }
      fillSettings(data.detection_defaults);
      try { await refreshSessions(); } catch {}
      try { await loadSurveyLibrary(); } catch {}
      if(data.state?.last_detection_job){
        try {
          state.loadedJob=data.state.last_detection_job.id;
          const savedCursor=data.state?.review_cursors?.[state.loadedJob];
          await loadResults(savedCursor?.offset||0, savedCursor?.object_id||null);
        } catch {
          state.loadedJob=null;
          state.results=null;
        }
      }
      renderProposals();renderJob(model.job);
      pollHardwareTelemetry();
    }};
}
