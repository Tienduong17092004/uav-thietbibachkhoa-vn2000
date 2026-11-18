import { createViewport } from './viewport.js?v=20261030_1';
import { createAdvanced } from './advanced.js?v=20261030_1';

const $ = id => document.getElementById(id);

function formatTileId(id) {
  return String(id || '').replace(/^tile_/i, 'Ảnh ');
}

function applyTheme(theme) {
  const mode = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = mode;
  try { localStorage.setItem('uav_theme', mode); } catch {}
  document.querySelectorAll('[data-theme-choice]').forEach(btn => {
    const active = btn.dataset.themeChoice === mode;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', String(active));
  });
}

(function initTheme() {
  let saved = 'light';
  try {
    const stored = localStorage.getItem('uav_theme');
    if (stored === 'dark' || stored === 'light') saved = stored;
  } catch {}
  applyTheme(saved);
  document.querySelectorAll('[data-theme-choice]').forEach(btn => {
    btn.addEventListener('click', () => applyTheme(btn.dataset.themeChoice));
  });
})();
const fields = {
  base_x: $('base-x'), base_y: $('base-y'),
  tile_width: $('tile-width'), tile_height: $('tile-height'),
  overlap_x: $('overlap-x'), overlap_y: $('overlap-y'),
  max_object_diameter_cm: $('object-diameter'),
};
const model = { token: '', ready: false, busy: false, step: 1, metadata: null,
  plan: null, planKey: '', job: null, proposals: [], pollTimer: null };
const headings = [
  ['Ảnh & Tọa độ Base', ''],
  ['Chia lưới ảnh', ''],
  ['Nhận diện & Tạo mẫu', ''],
  ['Xuất DXF & Lưu Mẫu', ''],
  ['Huấn luyện & Quét YOLO', ''],
];
let viewport = null;
let detailRequest = 0;
let advanced = null;

function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text !== undefined && text !== null) result.textContent = text;
  if (className) result.className = className;
  return result;
}
function showError(message = '') {
  $('app-error').textContent = message;
  $('app-error').hidden = !message;
}
function running() { return ['queued', 'running', 'cancelling'].includes(model.job?.status); }
function fieldValue(key) {
  const value = fields[key].value.trim();
  return value === '' ? null : Number(value);
}
function hasBase() {
  return ['base_x', 'base_y'].every(key => fieldValue(key) !== null && Number.isFinite(fieldValue(key)));
}
function sourceReady() { return Boolean(model.metadata?.eligible && hasBase()); }
function config() {
  const result = {};
  for (const key of Object.keys(fields)) result[key] = fieldValue(key);
  for (const key of ['base_x', 'base_y']) {
    if (result[key] === null || !Number.isFinite(result[key])) throw new Error('Nhập đầy đủ tọa độ Base X và Base Y bằng số hữu hạn.');
  }
  for (const key of ['tile_width', 'tile_height']) {
    if (!Number.isSafeInteger(result[key]) || result[key] <= 0) throw new Error('Chiều rộng và chiều cao ảnh phải là số nguyên dương.');
  }
  for (const key of ['overlap_x', 'overlap_y']) {
    if (!Number.isFinite(result[key]) || result[key] < 10 || result[key] > 50) throw new Error('Overlap ngang và dọc đều phải nằm trong khoảng 10% đến 50%.');
    result[key] /= 100;
  }
  const diameter = result.max_object_diameter_cm;
  if (diameter !== null && (!Number.isFinite(diameter) || diameter <= 0)) throw new Error('Đường kính đối tượng phải lớn hơn 0, hoặc để trống nếu chưa xác định.');
  return result;
}
function inputKey() {
  try { return JSON.stringify({ path: $('source-path').value.trim(), config: config() }); }
  catch { return ''; }
}
function planReady() { return Boolean(model.plan && model.planKey && model.planKey === inputKey() && sourceReady()); }
function hasDetectionSession() {
  return Boolean(advanced?.hasResults?.() || model.job?.kind === 'detection' || model.hasSavedDetectionJob);
}
function fillDefaults(defaults = {}) {
  $('source-path').value = defaults.input_path || '';
  for (const [key, field] of Object.entries(fields)) {
    const value = defaults[key];
    if (value === undefined) continue;
    field.value = value === null ? '' : key.startsWith('overlap_') ? value * 100 : value;
  }
}
function updateControls() {
  const locked = !model.ready || model.busy || running();
  const canEnterDetectionOrExport = planReady() || hasDetectionSession();
  const canEnterYolo = canEnterDetectionOrExport || Boolean(advanced?.hasTurboReady?.());
  document.querySelectorAll('[data-mutable]').forEach(control => { control.disabled = locked; });
  $('inspect').disabled = locked || !$('source-path').value.trim();
  $('calculate').disabled = locked || !sourceReady();
  $('export').disabled = locked || !planReady();
  $('back').disabled = locked || model.step === 1;
  $('next').hidden = model.step === 5;
  $('next').disabled = locked || (
    model.step === 1
      ? (!sourceReady() && !hasDetectionSession())
      : (model.step === 4 ? !canEnterYolo : !canEnterDetectionOrExport)
  );
  document.querySelectorAll('[data-step]').forEach(button => {
    const target = Number(button.dataset.step);
    button.disabled = locked || (
      target === 2 ? !sourceReady()
      : target === 5 ? !canEnterYolo
      : target > 2 ? !canEnterDetectionOrExport
      : false
    );
    if (target === model.step) button.setAttribute('aria-current', 'step');
    else button.removeAttribute('aria-current');
  });
  const isDetectRunning = running() && model.job?.kind === 'detection';
  const isDetectResumable = !running() && model.job?.kind === 'detection'
    && ['paused', 'cancelled', 'interrupted'].includes(model.job?.status)
    && (model.job?.done ?? 0) < (model.job?.total ?? 0);
  if ($('pause-job')) {
    $('pause-job').hidden = !isDetectRunning;
    $('pause-job').disabled = model.busy || model.job?.status === 'cancelling';
  }
  if ($('resume-job')) {
    $('resume-job').hidden = !isDetectResumable;
    $('resume-job').disabled = model.busy || !model.ready;
    if (isDetectResumable) {
      $('resume-job').textContent = `▶ Tiếp tục quét (${model.job.done ?? 0}/${model.job.total ?? 0})`;
    }
  }
  $('cancel').hidden = !running();
  $('cancel').disabled = model.busy || model.job?.status === 'cancelling';
  $('open-output').hidden = !model.job?.output_dir || running();
  $('open-output').disabled = model.busy || !model.ready;
  $('tile-select').disabled = !model.plan?.tiles.length;
  if ($('main-job-panel')) {
    const jobKind = model.job?.kind || (model.job ? 'export' : '');
    const isTurboDetection = jobKind === 'detection'
      && ['turbo_zone', 'turbo_clump'].includes(model.job?.request?.settings?.engine);
    const showForStep =
      (jobKind === 'detection' && !isTurboDetection && model.step === 3) ||
      (jobKind === 'warp' && model.step === 1) ||
      (jobKind === 'export' && model.step === 4) ||
      ((jobKind === 'turbo_train' || isTurboDetection) && model.step === 5);
    $('main-job-panel').hidden = !(Boolean(model.job) && (running() || showForStep));
  }
  const tileInspector = document.querySelector('.tile-inspector');
  if (tileInspector) {
    tileInspector.hidden = model.step === 4 || model.step === 5;
  }
  $('navigation-hint').textContent = running() ? 'Đang xử lý…' : [
    sourceReady() ? 'Ảnh & Base sẵn sàng.' : 'Cần ảnh và Base.',
    planReady() ? 'Lưới sẵn sàng.' : 'Cần tính lưới.',
    'Sẵn sàng nhận diện & duyệt mẫu.',
    'Sẵn sàng lưu mẫu & xuất CAD.',
    'Sẵn sàng huấn luyện & quét YOLO.',
  ][model.step - 1];
  advanced?.controls(locked);
}
function goToStep(step, focus = true) {
  if (step < 1 || step > 5) return;
  model.step = step;
  for (let n = 1; n <= 5; n++) $('step-' + n).hidden = n !== step;
  $('step-title').textContent = headings[step - 1][0];
  $('step-description').textContent = headings[step - 1][1];
  $('step-description').hidden = true;
  $('step-kicker').textContent = `Bước 0${step} / 05`;
  if (step === 4) {
    renderReview();
    window.scrollTo({ top: 0, behavior: 'instant' });
  } else if (step === 5) {
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  updateControls();
  if (focus) $('step-title').focus({ preventScroll: true });
}
async function api(path, body) {
  const options = body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Session-Token': model.token },
    body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  let result;
  try { result = await response.json(); }
  catch { throw new Error('Máy chủ trả về dữ liệu không hợp lệ. Hãy kiểm tra cửa sổ ứng dụng.'); }
  if (!response.ok) throw new Error(localized(result.error || 'Không thể hoàn thành yêu cầu.'));
  return result;
}
async function action(callback) {
  if (model.busy || !model.ready) return;
  model.busy = true;
  showError();
  updateControls();
  try { await callback(); }
  catch (error) { showError(error.message || 'Không thể hoàn thành thao tác.'); }
  finally { model.busy = false; updateControls(); }
}
function addRows(parent, rows) {
  const list = node('dl');
  for (const [label, value] of rows) list.append(node('dt', label), node('dd', value));
  parent.append(list);
}
function fixed(value, digits = 3) { return Number.isFinite(value) ? value.toFixed(digits) : '—'; }
function localized(message) {
  const coverage = /^Actual overlap on ([XY]) is (.+) cm; at least 2\.5 times diameter \((.+) cm\) is required$/.exec(message);
  if (coverage) return `Overlap thực tế theo chiều ${coverage[1]} là ${coverage[2]} cm; cần ít nhất ${coverage[3]} cm (2,5 lần đường kính). Tăng overlap/kích thước ảnh hoặc kiểm tra lại đường kính.`;
  const translations = new Map([
    ['GSD is projected-grid distance; it does not certify survey accuracy.', 'GSD là khoảng cách trên lưới chiếu, không chứng nhận độ chính xác khảo sát.'],
    ['GSD describes projected-grid distance, not survey accuracy.', 'GSD là khoảng cách trên lưới chiếu, không chứng nhận độ chính xác khảo sát.'],
    ['Preview uses display scaling; exported GeoTIFF values are preserved.', 'Màu xem trước có thể được co giãn; GeoTIFF xuất giữ giá trị pixel gốc.'],
    ['CRS was read from a sibling .prj sidecar; keep it beside the source image.', 'CRS được đọc từ file .prj đi kèm; hãy giữ .prj cạnh ảnh nguồn.'],
    ['Source storage blocks are large; GDAL may read a whole block for a small window.', 'Khối lưu trữ của ảnh nguồn lớn; đọc một cửa sổ nhỏ vẫn có thể cần đọc cả khối.'],
    ['Source edges and nodata can cut objects; overlap cannot recover missing data.', 'Biên ảnh và NoData có thể cắt đối tượng; overlap không khôi phục dữ liệu bị thiếu.'],
    ['Object diameter is unspecified: the object-coverage condition has not been checked.', 'Chưa nhập đường kính: chưa kiểm tra điều kiện overlap ≥ 2,5 lần đường kính.'],
    ['Missing CRS: a projected coordinate reference system is required for slicing.', 'Ảnh thiếu CRS. Cần hệ tọa độ chiếu để chia ảnh.'],
    ['A projected CRS is required; geographic/angular or other CRS cannot be sliced in this phase.', 'Ảnh cần dùng hệ tọa độ chiếu. CRS địa lý theo độ chưa được hỗ trợ ở giai đoạn này.'],
    ['Raster rotation or shear requires an explicit warp step, which is a later milestone.', 'Ảnh có phép xoay hoặc xiên; cần bước chuẩn hóa ảnh trước khi chia ảnh.'],
    ['A north-up affine with positive X scale and negative Y scale is required.', 'Cần ảnh north-up với tỷ lệ X dương và tỷ lệ Y âm.'],
    ['Cannot convert the projected CRS linear unit to metres.', 'Không xác định được hệ số đổi đơn vị của CRS sang mét.'],
  ]);
  return translations.get(message) || message;
}
function renderMetadata() {
  const target = $('metadata');
  target.replaceChildren();
  const meta = model.metadata;
  if (!meta) { target.append(node('p', 'Chưa có thông tin ảnh.', 'empty-note')); return; }
  target.append(node('span', meta.eligible ? 'Đủ điều kiện chia ảnh' : 'Chưa đủ điều kiện', `status-tag ${meta.eligible ? 'success' : 'invalid'}`));
  const rows = [
    ['Kích thước', `${meta.width.toLocaleString('vi-VN')} × ${meta.height.toLocaleString('vi-VN')} px`],
    ['Hệ tọa độ', meta.crs || 'Thiếu CRS'],
    ['GSD X / Y', `${fixed(meta.gsd_x_cm)} / ${fixed(meta.gsd_y_cm)} cm/px`],
    ['Đơn vị tọa độ', meta.linear_unit || 'Chưa xác định'],
    ['Dữ liệu', `${meta.count} kênh · ${meta.dtype}`],
    ['Hướng ảnh', meta.north_up ? 'North-up' : 'Cần kiểm tra'],
  ];
  if (meta.multispectral?.available) {
    rows.push(['Kênh Đa phổ đi kèm', `${meta.multispectral.band_names.map(b => b.toUpperCase()).join(' + ')} (${meta.multispectral.indices_supported.join(', ')})`]);
  }
  addRows(target, rows);
  if (!meta.eligible) {
    const warning = node('div', null, 'notice error');
    warning.append(node('strong', 'P01 · Hãy dùng phần chuẩn hóa ảnh bên dưới'));
    const list = node('ul');
    for (const error of meta.errors || []) list.append(node('li', localized(error)));
    warning.append(list);
    target.append(warning);
  }
}
function clearDetails() {
  detailRequest++;
  $('tile-select').replaceChildren();
  $('tile-image').hidden = true;
  $('tile-image').removeAttribute('src');
  $('tile-image-note').hidden = false;
  $('tile-image-note').textContent = 'Chưa chọn ảnh.';
  $('tile-details').replaceChildren(node('p', 'Chưa có tọa độ chi tiết.', 'empty-note'));
  $('preview-limit').hidden = true;
}
function invalidatePlan() {
  advanced?.invalidateDetection();
  model.plan = null;
  model.planKey = '';
  viewport?.setPlan(null);
  clearDetails();
  $('plan-stats').replaceChildren(node('p', 'Chưa tính lưới.', 'empty-note'));
  $('plan-warnings').replaceChildren();
  renderReview();
  updateControls();
}
function invalidateSource() {
  advanced?.invalidateWarp();
  model.metadata = null;
  viewport?.clearSource();
  $('viewport-placeholder').hidden = false;
  $('viewport-status').textContent = 'Chưa có ảnh tổng quan.';
  $('map-crs').textContent = 'Chưa có ảnh';
  renderMetadata();
  invalidatePlan();
}
function previewUrl(tile = null) {
  const query = new URLSearchParams({ path: model.metadata.path });
  if (tile) for (const key of ['col', 'row', 'width', 'height']) query.set(key, tile[key]);
  return '/api/preview?' + query.toString();
}
async function inspectSource() {
  invalidateSource();
  $('inspect').textContent = 'Đang đọc thông tin…';
  try {
    model.metadata = await api('/api/inspect', { path: $('source-path').value.trim() });
    $('source-path').value = model.metadata.path;
    renderMetadata();
    $('map-crs').textContent = model.metadata.crs || 'Thiếu CRS';
    if (model.metadata.eligible && viewport) {
      $('viewport-status').textContent = 'Đang đọc ảnh tổng quan…';
      try {
        await viewport.loadSource(model.metadata, previewUrl());
        $('viewport-placeholder').hidden = true;
      } catch (error) {
        $('viewport-status').textContent = 'Không tải được tổng quan.';
        showError(`Đã đọc metadata nhưng không tải được ảnh xem trước: ${error.message}`);
      }
    } else if (!model.metadata.eligible) {
      $('viewport-status').textContent = 'Cần chuẩn hóa ảnh.';
    }
  } finally { $('inspect').textContent = 'Đọc thông tin ảnh'; }
}
function renderPlan() {
  const plan = model.plan;
  const target = $('plan-stats');
  target.replaceChildren();
  const count = node('div', plan.tile_count.toLocaleString('vi-VN'), 'plan-count');
  count.append(node('span', 'ảnh dự kiến'));
  const stats = node('div', null, 'stat-grid');
  const metric = (label, value) => { const item = node('div'); item.append(node('span', label), node('strong', value)); stats.append(item); };
  metric('Lưới', `${plan.columns} cột × ${plan.rows} hàng`);
  metric('Bước dịch X / Y', `${plan.stride_x} / ${plan.stride_y} px`);
  metric('Overlap thực tế X', `${plan.actual_overlap_x_px} px · ${fixed(plan.actual_overlap_x_px * plan.metadata.gsd_x_cm, 1)} cm`);
  metric('Overlap thực tế Y', `${plan.actual_overlap_y_px} px · ${fixed(plan.actual_overlap_y_px * plan.metadata.gsd_y_cm, 1)} cm`);
  target.append(count, stats);
  $('plan-warnings').replaceChildren();
  if (plan.coverage_guarantee_checked) $('plan-warnings').append(node('p', 'Đã kiểm tra overlap ≥ 2,5 lần đường kính ở cả hai chiều.'));
  else $('plan-warnings').append(node('p', 'Chưa nhập đường kính: chưa kiểm tra điều kiện overlap ≥ 2,5 lần đường kính.'));
  for (const warning of plan.warnings || []) {
    if (warning.includes('storage blocks')) $('plan-warnings').append(node('p', localized(warning)));
  }
  $('preview-limit').hidden = !plan.preview_truncated;
  $('preview-limit').textContent = `Lưới xem trước chỉ hiển thị ${plan.tiles.length.toLocaleString('vi-VN')} / ${plan.tile_count.toLocaleString('vi-VN')} ảnh đầu tiên. Xuất sẽ xử lý toàn bộ ${plan.tile_count.toLocaleString('vi-VN')} ảnh.`;
  $('tile-select').replaceChildren(...plan.tiles.map(tile => {
    const option = node('option', formatTileId(tile.id)); option.value = tile.id; return option;
  }));
  viewport?.setPlan(plan);
  if (plan.tiles.length) selectTile(plan.tiles[0], { fly: false });
  renderReview();
}
function selectTile(tile, { fly = true } = {}) {
  if (!tile || !model.plan) return;
  advanced?.invalidateDetection();
  $('tile-select').value = tile.id;
  viewport?.selectTile(tile, { fly });
  const target = $('tile-details');
  target.replaceChildren();
  target.append(node('strong', formatTileId(tile.id)));
  target.append(node('p', `Cửa sổ nguồn: col ${tile.col}, row ${tile.row} · ${tile.width} × ${tile.height} px`));
  const table = node('table');
  const caption = node('caption', `Tọa độ tương đối · ${model.metadata.linear_unit || 'đơn vị CRS'}`);
  caption.style.cssText = 'text-align:left;font-size:10px;color:#67726b;margin-bottom:5px';
  const head = node('thead'); const heading = node('tr');
  ['Góc', 'X − Base X', 'Y − Base Y'].forEach(label => { const th = node('th', label); th.scope = 'col'; heading.append(th); });
  head.append(heading);
  const body = node('tbody');
  const labels = ['Trái trên', 'Phải trên', 'Phải dưới', 'Trái dưới'];
  tile.corners_relative.forEach((point, index) => {
    const row = node('tr'); row.append(node('td', labels[index]), node('td', fixed(point[0])), node('td', fixed(point[1]))); body.append(row);
  });
  table.append(caption, head, body); target.append(table);
  const request = ++detailRequest;
  const image = $('tile-image');
  image.hidden = true;
  $('tile-image-note').hidden = false;
  $('tile-image-note').textContent = 'Đang đọc cửa sổ nguồn…';
  image.onload = () => {
    if (request !== detailRequest) return;
    image.hidden = false;
    $('tile-image-note').hidden = true;
  };
  image.onerror = () => {
    if (request !== detailRequest) return;
    image.hidden = true;
    $('tile-image-note').hidden = false;
    $('tile-image-note').textContent = 'Không tải được ảnh chi tiết.';
  };
  image.alt = `Cửa sổ ảnh nguồn ${formatTileId(tile.id)}, cột ${tile.col}, hàng ${tile.row}, ${tile.width} × ${tile.height} pixel`;
  image.style.aspectRatio = `${tile.width} / ${tile.height}`;
  image.src = previewUrl(tile);
}
function renderReview() {
  const target = $('review-summary');
  target.replaceChildren();
  const plan = model.plan;
  const cfg = plan?.config || (running() && !model.job.kind ? model.job.config : null);
  if (!cfg) { target.append(node('p', 'Chưa có lưới để xuất.', 'empty-note')); return; }
  addRows(target, [
    ['Số ảnh', (plan?.tile_count ?? model.job.total).toLocaleString('vi-VN')],
    ['Kích thước yêu cầu', `${cfg.tile_width} × ${cfg.tile_height} px`],
    ['Overlap X / Y', `${fixed(cfg.overlap_x * 100, 2)}% / ${fixed(cfg.overlap_y * 100, 2)}%`],
    ['Base X', fixed(cfg.base_x)], ['Base Y', fixed(cfg.base_y)],
    ['Nhận diện', 'Duyệt khung trước khi xuất'],
  ]);
  target.append(node('p', model.metadata?.path || $('source-path').value || 'Ảnh nguồn của tác vụ đã lưu.', 'review-source'));
}
function renderJob() {
  const job = model.job;
  if (!job) return;
  const labels = {
    running: 'Đang xuất ảnh',
    queued: 'Đang chuẩn bị xuất',
    cancelling: 'Đang dừng sau ảnh hiện tại',
    paused: 'Đã tạm dừng (Đã nhả GPU)',
    completed: 'Đã xuất xong',
    cancelled: 'Đã hủy tác vụ',
    failed: 'Xuất không thành công',
    interrupted: 'Lần xuất trước bị gián đoạn',
  };
  const total = Math.max(job.total || 1, 1);
  const done = Math.min(total, Math.max(0, job.done || 0));
  const pct = Math.round((done / total) * 100);
  const unitLabel = job.kind === 'turbo_train' ? '%' : ' ảnh';
  $('job-status').textContent = job.kind === 'turbo_train'
    ? `Huấn luyện Turbo YOLO11 · ${pct}%`
    : `${labels[job.status] || job.status} · ${done} / ${job.total ?? 0}${unitLabel}`;
  $('job-status').dataset.status = job.status;
  $('job-progress').max = total;
  $('job-progress').value = done;
  if ($('job-progress-ring')) {
    const circ = 301.59;
    $('job-progress-ring').style.strokeDashoffset = String((circ * (1 - done / total)).toFixed(2));
  }
  if ($('job-progress-pct')) $('job-progress-pct').textContent = `${pct}%`;
  if ($('job-progress-count')) $('job-progress-count').textContent = job.kind === 'turbo_train' ? 'YOLO11 FP16' : `${done} / ${job.total ?? 0}`;
  if ($('circular-progress-card')) $('circular-progress-card').dataset.status = job.status || '';
  $('job-message').textContent = job.message || '';
  $('output-path').textContent = job.output_dir || '';
  viewport?.setJobProgressOverlay(job);
  updateControls();
  advanced?.renderJob(job);
}
function pollJob(delay = 600) {
  clearTimeout(model.pollTimer);
  if (!running()) return;
  model.pollTimer = setTimeout(async () => {
    try {
      model.job = await api('/api/job');
      renderJob();
      $('connection-status').textContent = 'Đã kết nối · Dữ liệu xử lý cục bộ';
      pollJob();
    } catch (error) {
      $('connection-status').textContent = 'Mất kết nối tiến độ · Đang thử lại';
      showError(`Chưa đọc được tiến độ: ${error.message} Cấu hình tiếp tục được khóa để bảo vệ tác vụ.`);
      pollJob(2000);
    }
  }, delay);
}
function renderProposals() {
  if (advanced) { advanced.renderProposals(); return; }
  $('proposals').replaceChildren();
  for (const proposal of model.proposals) {
    const card = node('div', null, 'proposal-card');
    card.append(node('p', `${proposal.id} · ${proposal.title || 'Đề xuất thiết kế'}`));
    const buttons = node('div', null, 'proposal-actions');
    for (const [decision, label] of [['approve', 'Duyệt thiết kế'], ['reject', 'Từ chối']]) {
      const button = node('button', label, 'secondary'); button.type = 'button'; button.dataset.mutable = '';
      button.addEventListener('click', () => action(async () => {
        const state = await api('/api/proposal', { id: proposal.id, decision });
        model.proposals = state.pending_proposals || [];
        renderProposals();
      }));
      buttons.append(button);
    }
    card.append(buttons); $('proposals').append(card);
  }
}

$('source-path').addEventListener('input', () => { showError(); invalidateSource(); });
Object.values(fields).forEach(field => field.addEventListener('input', () => { showError(); invalidatePlan(); }));
$('inspect').addEventListener('click', () => action(inspectSource));
$('browse').addEventListener('click', () => action(async () => {
  const result = await api('/api/browse', {});
  if (result.path) { $('source-path').value = result.path; invalidateSource(); await inspectSource(); }
}));
$('calculate').addEventListener('click', () => action(async () => {
  const cfg = config();
  if (!sourceReady()) throw new Error('Ảnh chưa hợp lệ hoặc chưa nhập đủ Base.');
  const key = inputKey();
  invalidatePlan();
  $('calculate').textContent = 'Đang tính lưới…';
  try {
    model.plan = await api('/api/plan', { path: model.metadata.path, config: cfg });
    model.planKey = key;
    renderPlan();
  } finally { $('calculate').textContent = 'Tính và xem lưới'; }
}));
$('next').addEventListener('click', () => {
  if (running() || model.busy) return;
  if (model.step === 1) {
    if (sourceReady()) goToStep(2);
    else if (hasDetectionSession()) goToStep(3);
    return;
  }
  if (planReady() || hasDetectionSession() || (model.step === 4 && advanced?.hasTurboReady?.())) {
    goToStep(model.step + 1);
  }
});
$('back').addEventListener('click', () => { if (!running() && !model.busy) goToStep(model.step - 1); });
document.querySelectorAll('[data-step]').forEach(button => button.addEventListener('click', () => { if (!button.disabled) goToStep(Number(button.dataset.step)); }));
$('tile-select').addEventListener('change', () => selectTile(model.plan?.tiles.find(tile => tile.id === $('tile-select').value)));
$('fit-view').addEventListener('click', () => viewport?.fit());
$('zoom-in').addEventListener('click', () => viewport?.zoom(1.3));
$('zoom-out').addEventListener('click', () => viewport?.zoom(1 / 1.3));
$('export').addEventListener('click', () => action(async () => {
  if (!planReady()) throw new Error('Cấu hình đã thay đổi. Hãy tính lại lưới trước khi xuất.');
  // The request contains a detached copy of the reviewed plan, never live input fields.
  const snapshot = structuredClone({ path: model.metadata.path, config: model.plan.config });
  model.job = await api('/api/export', snapshot);
  renderJob();
  pollJob();
}));
$('cancel').addEventListener('click', () => action(async () => {
  model.job = await api('/api/cancel', {});
  renderJob(); pollJob(150);
}));
if ($('pause-job')) {
  $('pause-job').addEventListener('click', () => action(async () => {
    model.job = await api('/api/pause', {});
    renderJob();
    pollJob(150);
  }));
}
if ($('resume-job')) {
  $('resume-job').addEventListener('click', () => {
    if (advanced?.resumeDetection) advanced.resumeDetection();
    else action(async () => {
      model.job = await api('/api/detect/resume', { job_id: model.job?.id });
      renderJob();
      pollJob(200);
    });
  });
}
$('open-output').addEventListener('click', () => action(() => api('/api/open-output', {})));
window.addEventListener('beforeunload', () => { clearTimeout(model.pollTimer); viewport?.dispose(); });

async function initialize() {
  updateControls();
  try {
    advanced = await createAdvanced({api, action, model, config, planReady, goToStep, inspectSource,
      invalidateSource, updateControls, showError, renderMainJob:renderJob, pollJob, selectTile, getViewport: () => viewport});
  } catch(error) { showError(error.message); return; }
  try {
    viewport = createViewport($('viewport'), {
      onSelect: tile => selectTile(tile), onStatus: status => { $('viewport-status').textContent = status; },
    });
    advanced.bindViewport?.(viewport);
    $('viewport-status').textContent = 'Đọc thông tin ảnh để nạp tổng quan.';
  } catch {
    $('viewport-status').textContent = 'Khung nhìn WebGL không khả dụng. Bạn vẫn có thể xem chi tiết ảnh và xuất GeoTIFF.';
  }
  try {
    const result = await api('/api/state');
    model.token = result.token;
    model.ready = true;
    model.job = result.state?.last_job || null;
    model.hasSavedDetectionJob = Boolean(result.state?.last_detection_job || result.state?.last_job?.kind === 'detection');
    model.proposals = result.proposals || [];
    fillDefaults(result.defaults);
    updateControls();
    if ($('source-path').value.trim()) {
      try {
        await inspectSource();
        if (sourceReady()) {
          const cfg = config();
          const key = inputKey();
          model.plan = await api('/api/plan', { path: model.metadata.path, config: cfg });
          model.planKey = key;
          renderPlan();
        }
      } catch {}
    }
    try {
      await advanced?.initialize(result);
    } catch (advError) {
      console.warn('Khởi tạo phần nâng cao có cảnh báo:', advError);
    }
    renderProposals();
    renderJob();
    if (running()) {
      const isYoloJob = model.job?.kind === 'turbo_train'
        || (model.job?.kind === 'detection' && ['turbo_zone', 'turbo_clump'].includes(model.job?.request?.settings?.engine));
      goToStep(isYoloJob ? 5 : (model.job?.kind === 'detection' ? 3 : 4), false);
      pollJob(100);
    } else if (hasDetectionSession() && model.step === 1) {
      goToStep(3, false);
    }
    $('connection-status').textContent = 'Đã kết nối · Dữ liệu xử lý cục bộ';
    updateControls();
  } catch (error) {
    showError(`Không thể kết nối ứng dụng: ${error.message}`);
    $('connection-status').textContent = 'Chưa kết nối · Hãy tải lại trang';
  }
}
initialize();
