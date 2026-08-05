/* 지적도 DXF 추출 서비스 — 프론트엔드
 *
 * 상태바의 좌표 표시는 브라우저 proj4로 즉시 계산하고, 파일에 실제로 쓰이는
 * 확정 좌표는 /api/project로 서버에 물어본다. 구지적(5174)처럼 데이텀 변환
 * 정의가 갈릴 수 있는 좌표계에서 화면과 파일이 어긋나지 않게 하기 위해서다.
 */
'use strict';

const $ = id => document.getElementById(id);

/* ── 좌표계 (화면 표시용 근사) ───────────────────── */
proj4.defs([
  ['EPSG:5185', '+proj=tmerc +lat_0=38 +lon_0=125 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs'],
  ['EPSG:5186', '+proj=tmerc +lat_0=38 +lon_0=127 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs'],
  ['EPSG:5187', '+proj=tmerc +lat_0=38 +lon_0=129 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs'],
  ['EPSG:5188', '+proj=tmerc +lat_0=38 +lon_0=131 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs'],
  ['EPSG:5179', '+proj=tmerc +lat_0=38 +lon_0=127.5 +k=0.9996 +x_0=1000000 +y_0=2000000 +ellps=GRS80 +units=m +no_defs'],
  ['EPSG:5174', '+proj=tmerc +lat_0=38 +lon_0=127.0028902777778 +k=1 +x_0=200000 +y_0=500000 +ellps=bessel +units=m +no_defs +towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43'],
  ['EPSG:32652', '+proj=utm +zone=52 +datum=WGS84 +units=m +no_defs'],
]);
ol.proj.proj4.register(proj4);

let CFG = null;
let crsInfo = {};

/* ── 지도 ─────────────────────────────────────── */
/* 배경지도는 V-World에서 브라우저가 직접 받는다(장당 약 17 ms).
   서버 중계로 돌리려면 .env 에 TILE_DIRECT=0 을 넣는다(약 57 ms).
   어느 쪽이든 지적 데이터는 서버가 대신 조회한다. */
const basemapSource = layer => {
  let url;
  if (CFG && CFG.tile_direct && CFG.tile_url) {
    const ext = (CFG.tile_layers && CFG.tile_layers[layer]) || 'png';
    url = CFG.tile_url
      .replace('{layer}', layer)
      .replace('{ext}', ext);
  } else {
    url = `/api/tiles/${layer}/{z}/{y}/{x}`;
  }
  return new ol.source.XYZ({ url, maxZoom: 19, crossOrigin: 'anonymous' });
};

/* CFG를 받기 전이라 소스는 boot()에서 붙인다. */
let currentBasemap = 'Base';
const baseLayer = new ol.layer.Tile();

const parcelSource = new ol.source.Vector();
const parcelLayer = new ol.layer.Vector({
  source: parcelSource,
  style: f => new ol.style.Style({
    stroke: new ol.style.Stroke({ color: cssVar('--l-parcel'), width: 1.2 }),
    fill: new ol.style.Fill({ color: 'rgba(0,0,0,0)' }),
    text: map.getView().getZoom() >= 18 ? new ol.style.Text({
      text: f.get('jibun') || '',
      font: '10px ui-monospace, Consolas, monospace',
      fill: new ol.style.Fill({ color: cssVar('--l-label') }),
      stroke: new ol.style.Stroke({ color: cssVar('--panel'), width: 2.5 }),
    }) : undefined,
  }),
});

const selSource = new ol.source.Vector();
const selLayer = new ol.layer.Vector({
  source: selSource,
  style: new ol.style.Style({
    stroke: new ol.style.Stroke({ color: cssVar('--accent'), width: 1.8 }),
    fill: new ol.style.Fill({ color: 'rgba(15,95,115,0.10)' }),
  }),
});

/* 즐겨찾기에서 고른 지점을 표시하는 별 표식 */
const favMarkSource = new ol.source.Vector();
const favMarkLayer = new ol.layer.Vector({
  source: favMarkSource,
  zIndex: 10,
  style: f => [
    new ol.style.Style({
      image: new ol.style.Circle({
        radius: 15,
        fill: new ol.style.Fill({ color: 'rgba(15,95,115,0.16)' }),
      }),
    }),
    new ol.style.Style({
      image: new ol.style.RegularShape({
        points: 5, radius: 11, radius2: 4.6, angle: 0,
        fill: new ol.style.Fill({ color: cssVar('--accent') }),
        stroke: new ol.style.Stroke({ color: '#fff', width: 2 }),
      }),
      text: new ol.style.Text({
        text: f.get('name') || '',
        font: '600 12px ' + cssVar('--sans'),
        offsetY: -26,
        padding: [3, 6, 3, 6],
        fill: new ol.style.Fill({ color: '#fff' }),
        backgroundFill: new ol.style.Fill({ color: cssVar('--accent') }),
        overflow: true,
      }),
    }),
  ],
});

const map = new ol.Map({
  target: 'map',
  layers: [baseLayer, parcelLayer, selLayer, favMarkLayer],
  view: new ol.View({
    center: ol.proj.fromLonLat([126.9418, 37.1832]),
    zoom: 16,
    maxZoom: 19,
    minZoom: 7,
  }),
  controls: [],
});

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/* ── 영역 선택 ────────────────────────────────── */
let selection = null;          // {minLon, minLat, maxLon, maxLat}
let tool = 'rect';

const dragBox = new ol.interaction.DragBox({
  className: 'ol-dragbox-sel',
  condition: () => tool === 'rect',
});
map.addInteraction(dragBox);

dragBox.on('boxend', () => {
  const ext = dragBox.getGeometry().getExtent();
  const [minLon, minLat] = ol.proj.toLonLat([ext[0], ext[1]]);
  const [maxLon, maxLat] = ol.proj.toLonLat([ext[2], ext[3]]);
  setSelection({ minLon, minLat, maxLon, maxLat });
});

function setSelection(s) {
  if (!s || Math.abs(s.maxLon - s.minLon) < 1e-7) return;
  selection = s;
  selSource.clear();
  selSource.addFeature(new ol.Feature(
    new ol.geom.Polygon([[
      ol.proj.fromLonLat([s.minLon, s.minLat]),
      ol.proj.fromLonLat([s.maxLon, s.minLat]),
      ol.proj.fromLonLat([s.maxLon, s.maxLat]),
      ol.proj.fromLonLat([s.minLon, s.maxLat]),
      ol.proj.fromLonLat([s.minLon, s.minLat]),
    ]])
  ));
  $('hint').classList.add('hide');
  refreshSummary();
  refreshCornerCoords();
}

function clearSelection() {
  selection = null;
  selSource.clear();
  $('hint').classList.remove('hide');
  refreshSummary();
}

/* ── 면적 계산 ────────────────────────────────── */
const EARTH_R = 6371008.8;
const rad = d => d * Math.PI / 180;

function metrics(s) {
  const midLat = (s.minLat + s.maxLat) / 2;
  const w = rad(s.maxLon - s.minLon) * EARTH_R * Math.cos(rad(midLat));
  const h = rad(s.maxLat - s.minLat) * EARTH_R;
  return { w, h, m2: w * h, km2: w * h / 1e6 };
}

/* ── 패널 갱신 ────────────────────────────────── */
function selectedLayers() {
  return [...document.querySelectorAll('[data-lay]')]
    .filter(c => c.checked && !c.disabled).map(c => c.dataset.lay);
}

function refreshSummary() {
  const code = $('crs').value;
  const info = crsInfo[code] || {};
  const layers = selectedLayers();

  $('layState').textContent = `${layers.length}개 선택`;
  $('s-lay').textContent = `${layers.length} 개`;
  $('s-crs').textContent = `EPSG:${code}`;
  $('sb-crs').textContent = `EPSG:${code} · ${info.wkt_name || ''}`;
  $('m-proj').textContent = info.projection || '—';
  $('m-ell').textContent = info.ellipsoid || '—';
  $('m-orig').textContent = info.origin || '—';
  $('m-unit').textContent = info.unit === 'degree' ? '도 (degree)' : '미터 (m)';
  $('crsNote').classList.toggle('on', !!info.note);
  $('crsNoteTxt').textContent = info.note || '';

  const limit = CFG ? CFG.max_area_km2 : 1;
  $('s-limit').textContent = `${limit.toFixed(2)} km²`;

  if (!selection) {
    $('selchip').classList.remove('on');
    $('areaState').textContent = '미지정';
    $('s-area').textContent = '—';
    $('bigNotice').classList.remove('on');
    setCta(true, '영역을 먼저 지정하세요');
    return;
  }

  const m = metrics(selection);
  $('selchip').classList.add('on');
  $('c-dim').textContent = `${m.w.toFixed(0)} × ${m.h.toFixed(0)} m`;
  $('c-area').textContent = m.km2 >= 0.01
    ? `${m.km2.toFixed(3)} km²`
    : `${Math.round(m.m2).toLocaleString()} m²`;
  $('c-pyeong').textContent = `${Math.round(m.m2 / 3.305785).toLocaleString()} 평`;
  $('areaState').textContent = `${m.km2.toFixed(3)} km²`;
  $('s-area').textContent = `${m.km2.toFixed(3)} km²`;

  const over = m.km2 > limit;
  const none = layers.length === 0;
  // 지적도든 도시계획이든 모두 V-World 에서 받아 온다
  const noKey = CFG && !CFG.has_vworld_key && layers.length > 0;

  $('bigNotice').classList.toggle('on', over || none || noKey);
  $('bigNotice').classList.toggle('err', noKey && !over && !none);
  $('bigNoticeTxt').textContent = none
    ? '추출할 레이어를 하나 이상 선택하세요.'
    : over
      ? `선택 영역 ${m.km2.toFixed(2)} km²가 1회 추출 한도 ${limit.toFixed(2)} km²를 초과했습니다. 영역을 줄이거나 나누어 요청하세요.`
      : 'V-World 인증키가 없어 지적 레이어를 받을 수 없습니다. .env의 VWORLD_KEY를 설정하세요.';

  setCta(over || none || noKey,
    over ? '한도 초과' : none ? '레이어 미선택' : noKey ? '인증키 필요' : 'DXF 생성 및 다운로드');
}

function setCta(disabled, text) {
  $('genBtn').disabled = disabled;
  $('genTxt').textContent = text;
}

let cornerReq = 0;
async function refreshCornerCoords() {
  if (!selection) return;
  const seq = ++cornerReq;
  const code = $('crs').value;
  try {
    const r = await fetch(
      `/api/project?lon=${selection.minLon}&lat=${selection.minLat}&crs=${code}`);
    if (!r.ok || seq !== cornerReq) return;
    const d = await r.json();
    $('c-x').textContent = d.unit === 'degree' ? `${d.x.toFixed(6)}°` : fmtM(d.x);
    $('c-y').textContent = d.unit === 'degree' ? `${d.y.toFixed(6)}°` : fmtM(d.y);
  } catch {
    $('c-x').textContent = '—';
    $('c-y').textContent = '—';
  }
}

const fmtM = n => n.toLocaleString('en-US',
  { minimumFractionDigits: 3, maximumFractionDigits: 3 }).replace(/,/g, ' ');

/* ── 상태바 ───────────────────────────────────── */
map.on('pointermove', evt => {
  const [lon, lat] = ol.proj.toLonLat(evt.coordinate);
  const code = $('crs').value;
  $('sb-ll').textContent = `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
  try {
    if (code === '4326') {
      $('sb-xy').textContent = `${lon.toFixed(6)}°, ${lat.toFixed(6)}°`;
    } else {
      const p = proj4('EPSG:4326', `EPSG:${code}`, [lon, lat]);
      $('sb-xy').textContent = `X ${fmtM(p[0])}  Y ${fmtM(p[1])}`;
    }
  } catch {
    $('sb-xy').textContent = '—';
  }
});

function refreshScale() {
  const res = map.getView().getResolution();
  const lat = ol.proj.toLonLat(map.getView().getCenter())[1];
  const mpp = res * Math.cos(rad(lat));
  $('sb-scale').textContent = `1 : ${Math.round(mpp * 3780 / 10) * 10}  ·  ${mpp.toFixed(2)} m/px`;
}

/* ── 필지 미리보기 ────────────────────────────── */
let previewTimer = null;
function schedulePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(loadParcelPreview, 450);
}

async function loadParcelPreview() {
  const wantParcel = document.querySelector('[data-lay="parcel"]').checked
    || document.querySelector('[data-lay="pnu"]').checked;
  if (!wantParcel || !CFG || !CFG.has_vworld_key || map.getView().getZoom() < 16) {
    parcelSource.clear();
    return;
  }
  const ext = map.getView().calculateExtent(map.getSize());
  const [minLon, minLat] = ol.proj.toLonLat([ext[0], ext[1]]);
  const [maxLon, maxLat] = ol.proj.toLonLat([ext[2], ext[3]]);
  const box = { minLon, minLat, maxLon, maxLat };
  if (metrics(box).km2 > CFG.max_area_km2 * 3) {
    parcelSource.clear();
    return;
  }
  try {
    const r = await fetch(`/api/parcels?bbox=${minLon},${minLat},${maxLon},${maxLat}`);
    if (!r.ok) { parcelSource.clear(); return; }
    const gj = await r.json();
    parcelSource.clear();
    parcelSource.addFeatures(new ol.format.GeoJSON().readFeatures(gj, {
      dataProjection: 'EPSG:4326',
      featureProjection: map.getView().getProjection(),
    }));
  } catch {
    parcelSource.clear();
  }
}

map.on('moveend', () => { refreshScale(); schedulePreview(); });

/* ── 컨트롤 배선 ──────────────────────────────── */
document.querySelectorAll('[data-tool]').forEach(b => b.onclick = () => {
  document.querySelectorAll('[data-tool]').forEach(x => x.setAttribute('aria-pressed', x === b));
  tool = b.dataset.tool;
  $('map').className = tool;
});
document.querySelectorAll('[data-bm]').forEach(b => b.onclick = () => {
  document.querySelectorAll('[data-bm]').forEach(x => x.setAttribute('aria-pressed', x === b));
  currentBasemap = b.dataset.bm;
  baseLayer.setSource(basemapSource(currentBasemap));
});
document.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => {
  document.querySelectorAll('[data-mode]').forEach(x => x.setAttribute('aria-pressed', x === b));
  $('coordinput').classList.toggle('on', b.dataset.mode === 'coord');
});
document.querySelectorAll('[data-lay]').forEach(c => c.onchange = () => {
  refreshSummary();
  loadParcelPreview();
});
$('crs').onchange = () => { refreshSummary(); refreshCornerCoords(); };
$('clearBtn').onclick = clearSelection;
$('chipX').onclick = clearSelection;
$('zin').onclick = () => map.getView().animate({ zoom: map.getView().getZoom() + 1, duration: 200 });
$('zout').onclick = () => map.getView().animate({ zoom: map.getView().getZoom() - 1, duration: 200 });

$('applyCoord').onclick = () => {
  const v = id => parseFloat($(id).value);
  const s = {
    minLon: v('in-minlon'), minLat: v('in-minlat'),
    maxLon: v('in-maxlon'), maxLat: v('in-maxlat'),
  };
  if (Object.values(s).some(n => !isFinite(n))) {
    alert('경위도 네 값을 모두 숫자로 입력하세요.');
    return;
  }
  setSelection({
    minLon: Math.min(s.minLon, s.maxLon), maxLon: Math.max(s.minLon, s.maxLon),
    minLat: Math.min(s.minLat, s.maxLat), maxLat: Math.max(s.minLat, s.maxLat),
  });
  map.getView().fit(ol.proj.transformExtent(
    [s.minLon, s.minLat, s.maxLon, s.maxLat], 'EPSG:4326', map.getView().getProjection()
  ), { padding: [60, 60, 60, 60], duration: 300 });
};

$('themeBtn').onclick = () => {
  const cur = document.documentElement.getAttribute('data-theme')
    || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', cur === 'dark' ? 'light' : 'dark');
  selLayer.setStyle(new ol.style.Style({
    stroke: new ol.style.Stroke({ color: cssVar('--accent'), width: 1.8 }),
    fill: new ol.style.Fill({ color: 'rgba(15,95,115,0.10)' }),
  }));
  parcelLayer.changed();
};

/* ── 주소 검색 (V-World 지오코더 대신 Nominatim) ── */
$('search').addEventListener('keydown', async e => {
  if (e.key !== 'Enter') return;
  const q = e.target.value.trim();
  if (!q) return;
  try {
    const r = await fetch(
      'https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=kr&q='
      + encodeURIComponent(q));
    const hits = await r.json();
    if (!hits.length) { alert('검색 결과가 없습니다.'); return; }
    map.getView().animate({
      center: ol.proj.fromLonLat([parseFloat(hits[0].lon), parseFloat(hits[0].lat)]),
      zoom: 17, duration: 400,
    });
  } catch {
    alert('주소 검색 서비스에 연결할 수 없습니다.');
  }
});

/* ── 지번 즐겨찾기 ──────────────────────────────
   로그인이 없으므로 이 브라우저에만 저장한다(localStorage).
   저장할 때 화면 중앙에 걸린 필지의 지번을 기본 이름으로 채워 준다. */
const FAV_KEY = 'ksFavorites';

function favLoad() {
  try { return JSON.parse(localStorage.getItem(FAV_KEY)) || []; }
  catch { return []; }
}
function favSave(list) {
  localStorage.setItem(FAV_KEY, JSON.stringify(list));
  favRender();
}

/* 지도 중앙에 있는 필지의 지번을 찾는다. 미리보기가 떠 있을 때만 된다. */
function jibunAtCenter() {
  const c = map.getView().getCenter();
  let hit = null;
  parcelSource.forEachFeatureAtCoordinateDirect(c, f => { hit = hit || f; });
  if (!hit) {
    // 필지 안이 아니면 가장 가까운 필지로 대신한다
    let best = Infinity;
    parcelSource.forEachFeature(f => {
      const e = f.getGeometry().getExtent();
      const d = Math.hypot((e[0] + e[2]) / 2 - c[0], (e[1] + e[3]) / 2 - c[1]);
      if (d < best) { best = d; hit = f; }
    });
    if (best > 60) hit = null;   // 60 m 넘게 떨어지면 쓰지 않는다
  }
  if (!hit) return '';
  const j = hit.get('jibun') || '';
  const m = hit.get('jimok') || '';
  return j ? (m ? `${j} ${m}` : j) : '';
}

function favRender() {
  const list = favLoad();
  $('favCount').textContent = list.length || '';
  const box = $('favList');
  if (!list.length) {
    box.innerHTML = `<div class="fav-empty">저장된 지번이 없습니다.<br>
      지도를 옮긴 뒤 ★ 버튼을 누르면 추가됩니다.</div>`;
    return;
  }
  box.innerHTML = list.map((f, i) => `
    <div class="fav" data-i="${i}">
      <div class="fav-body">
        <div class="fav-name">${f.name.replace(/</g, '&lt;')}</div>
        <div class="fav-meta">${f.lat.toFixed(5)}, ${f.lon.toFixed(5)} · 축척 ${Math.round(f.zoom)}</div>
      </div>
      <button class="fav-del" data-del="${i}" title="삭제" aria-label="삭제">✕</button>
    </div>`).join('');

  box.querySelectorAll('.fav').forEach(el => el.onclick = e => {
    if (e.target.closest('.fav-del')) return;
    const f = favLoad()[+el.dataset.i];
    if (!f) return;
    goToFavorite(f);
    $('favPanel').classList.remove('on');
    $('favToggle').classList.remove('on');
  });
  box.querySelectorAll('.fav-del').forEach(b => b.onclick = e => {
    e.stopPropagation();
    const list = favLoad();
    list.splice(+b.dataset.del, 1);
    favSave(list);
  });
}

/* 즐겨찾기로 이동한다. 그 지점을 화면 정중앙에 놓고 별 표식을 남긴다.
   저장할 때의 축척이 너무 멀면 지번이 안 보이므로 최소 17까지 당긴다. */
function goToFavorite(f) {
  const center = ol.proj.fromLonLat([f.lon, f.lat]);
  favMarkSource.clear();
  const mark = new ol.Feature(new ol.geom.Point(center));
  mark.set('name', f.name);
  favMarkSource.addFeature(mark);

  map.getView().animate({
    center,
    zoom: Math.max(f.zoom || 17, 17),
    duration: 480,
  });
}

function clearFavMarker() {
  favMarkSource.clear();
}

$('favAdd').onclick = () => {
  const v = map.getView();
  const [lon, lat] = ol.proj.toLonLat(v.getCenter());
  const guess = jibunAtCenter() || $('search').value.trim()
    || `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
  const name = prompt('즐겨찾기 이름 (지번)', guess);
  if (name === null) return;
  const trimmed = name.trim();
  if (!trimmed) return;
  const list = favLoad();
  list.unshift({ name: trimmed, lon, lat, zoom: v.getZoom(), at: Date.now() });
  favSave(list.slice(0, 100));
  $('favAdd').classList.add('saved');
  setTimeout(() => $('favAdd').classList.remove('saved'), 900);
};

$('favToggle').onclick = () => {
  const on = $('favPanel').classList.toggle('on');
  $('favToggle').classList.toggle('on', on);
  if (on) favRender();
};
$('favClose').onclick = () => {
  $('favPanel').classList.remove('on');
  $('favToggle').classList.remove('on');
};

favRender();

/* ── 지도 우클릭 메뉴 ──────────────────────────────
   클릭한 지점의 주소를 보거나, 그 지점을 즐겨찾기에 담는다.
   주소는 V-World 지오코더를 서버가 대신 불러 준다. */
let ctxPoint = null;          // {lon, lat, px, py}

function ctxClose() {
  $('ctxMenu').classList.remove('on');
}
function addrClose() {
  $('addrPop').classList.remove('on');
}

map.getViewport().addEventListener('contextmenu', e => {
  e.preventDefault();
  // 지도가 아직 그려지지 않았으면 좌표를 얻을 수 없다. 조용히 넘긴다.
  const coord = map.getEventCoordinate(e);
  if (!coord) return;
  const rect = map.getViewport().getBoundingClientRect();
  const px = e.clientX - rect.left, py = e.clientY - rect.top;
  const [lon, lat] = ol.proj.toLonLat(coord);
  ctxPoint = { lon, lat, px, py };

  $('ctxCoord').textContent = `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
  const m = $('ctxMenu');
  m.classList.add('on');
  // 지도 밖으로 삐져나가지 않게 붙인다
  const mw = m.offsetWidth, mh = m.offsetHeight;
  m.style.left = Math.min(px, rect.width - mw - 8) + 'px';
  m.style.top = Math.min(py, rect.height - mh - 8) + 'px';
  addrClose();
});

map.getViewport().addEventListener('pointerdown', ctxClose);
map.on('movestart', () => { ctxClose(); addrClose(); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    ctxClose(); addrClose(); clearFavMarker();
    $('favPanel').classList.remove('on'); $('favToggle').classList.remove('on');
  }
});

async function fetchAddress(lon, lat) {
  const r = await fetch(`/api/address?lon=${lon}&lat=${lat}`);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `주소를 가져오지 못했습니다 (HTTP ${r.status})`);
  }
  return r.json();
}

/* 주소 보기 */
$('ctxAddr').onclick = async () => {
  if (!ctxPoint) return;
  const { lon, lat, px, py } = ctxPoint;
  ctxClose();
  const pop = $('addrPop');
  pop.style.left = px + 'px';
  pop.style.top = (py - 12) + 'px';
  $('addrBody').innerHTML = '<div class="addr-load">주소를 찾는 중…</div>';
  pop.classList.add('on');
  try {
    const d = await fetchAddress(lon, lat);
    const rows = [
      ['지번주소', d.parcel],
      ['도로명주소', d.road],
    ].map(([k, v]) => `<div class="addr-row"><div class="addr-k">${k}</div>
      <div class="addr-v${v ? '' : ' none'}">${v ? v.replace(/</g, '&lt;') : '이 지점에는 없습니다'}</div></div>`).join('');
    $('addrBody').innerHTML = rows +
      `<button class="addr-copy" id="addrCopyBtn">주소 복사</button>`;
    $('addrCopyBtn').onclick = () => {
      const txt = d.parcel || d.road || `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
      navigator.clipboard?.writeText(txt);
      $('addrCopyBtn').textContent = '복사했습니다';
      setTimeout(() => { const b = $('addrCopyBtn'); if (b) b.textContent = '주소 복사'; }, 1200);
    };
  } catch (e) {
    $('addrBody').innerHTML = `<div class="addr-row"><div class="addr-v none">${e.message}</div></div>`;
  }
};

/* 이 지점 즐겨찾기 추가 — 이름은 주소로 채워 준다 */
$('ctxFav').onclick = async () => {
  if (!ctxPoint) return;
  const { lon, lat } = ctxPoint;
  ctxClose();
  let guess = '';
  try {
    const d = await fetchAddress(lon, lat);
    guess = d.parcel || d.road || '';
  } catch { /* 주소를 못 받아도 좌표로 저장할 수 있게 계속 진행 */ }
  if (!guess) guess = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;

  const name = prompt('즐겨찾기 이름 (지번)', guess);
  if (name === null) return;
  const trimmed = name.trim();
  if (!trimmed) return;
  const list = favLoad();
  list.unshift({ name: trimmed, lon, lat, zoom: map.getView().getZoom(), at: Date.now() });
  favSave(list.slice(0, 100));
};

/* 좌표 복사 */
$('ctxCopy').onclick = () => {
  if (!ctxPoint) return;
  navigator.clipboard?.writeText(`${ctxPoint.lat.toFixed(6)}, ${ctxPoint.lon.toFixed(6)}`);
  ctxClose();
};

$('addrClose').onclick = addrClose;

/* ── 공지사항 팝업 ──────────────────────────────
   '오늘 하루 보지 않기'는 공지 하나 단위로 기억한다. 새 공지가 올라오면
   이전에 숨겼더라도 다시 뜬다. */
const NOTICE_SKIP_KEY = 'ksNoticeSkip';
const KIND_LABEL = { info: '안내', warn: '주의', event: '소식' };

function noticeSkipMap() {
  try { return JSON.parse(localStorage.getItem(NOTICE_SKIP_KEY)) || {}; }
  catch { return {}; }
}

function todayKey() {
  const d = new Date();
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

async function loadNotices() {
  let list;
  try {
    const r = await fetch('/api/notices');
    if (!r.ok) return;
    list = (await r.json()).notices || [];
  } catch { return; }

  const skip = noticeSkipMap();
  const today = todayKey();
  const show = list.filter(n => skip[n.id] !== today);
  if (!show.length) return;

  $('noticeTitle').textContent = show.length > 1 ? `공지사항 ${show.length}건` : '공지사항';
  $('noticeList').innerHTML = show.map(n => `
    <div class="notice-item ${n.kind}">
      <div class="notice-top">
        <span class="notice-badge ${n.kind}">${KIND_LABEL[n.kind] || '안내'}</span>
        <span class="notice-t">${esc(n.title)}</span>
        <span class="notice-date">${new Date(n.created * 1000)
          .toLocaleDateString('ko-KR', { month: '2-digit', day: '2-digit' })}</span>
      </div>
      ${n.body ? `<div class="notice-b">${esc(n.body)}</div>` : ''}
    </div>`).join('');

  $('noticeSkip').checked = false;
  $('noticeScrim').classList.add('on');

  const close = () => {
    if ($('noticeSkip').checked) {
      const m = noticeSkipMap();
      show.forEach(n => { m[n.id] = today; });
      localStorage.setItem(NOTICE_SKIP_KEY, JSON.stringify(m));
    }
    $('noticeScrim').classList.remove('on');
  };
  $('noticeClose').onclick = close;
  $('noticeX').onclick = close;
  $('noticeScrim').onclick = e => { if (e.target === $('noticeScrim')) close(); };
}

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/* ── 공지 게시판 ────────────────────────────────
   상단 '공지사항' 버튼으로 연다. 팝업으로 뜨지 않는 공지도 여기서 볼 수 있다. */
const BOARD_SEEN_KEY = 'ksBoardSeen';

function noticeCard(n) {
  return `
    <div class="notice-item ${n.kind}">
      <div class="notice-top">
        <span class="notice-badge ${n.kind}">${KIND_LABEL[n.kind] || '안내'}</span>
        <span class="notice-t">${esc(n.title)}</span>
        <span class="notice-date">${new Date(n.created * 1000)
          .toLocaleDateString('ko-KR', { year: '2-digit', month: '2-digit', day: '2-digit' })}</span>
      </div>
      ${n.body ? `<div class="notice-b">${esc(n.body)}</div>` : ''}
    </div>`;
}

async function openBoard() {
  $('boardList').innerHTML = '<div class="board-empty">불러오는 중…</div>';
  $('boardScrim').classList.add('on');
  try {
    const r = await fetch('/api/notices?all=1');
    const list = (await r.json()).notices || [];
    $('boardList').innerHTML = list.length
      ? list.map(noticeCard).join('')
      : '<div class="board-empty">등록된 공지가 없습니다.</div>';
    if (list.length) {
      localStorage.setItem(BOARD_SEEN_KEY, String(Math.max(...list.map(n => n.id))));
      markBoardRead();
    }
  } catch {
    $('boardList').innerHTML = '<div class="board-empty">공지를 불러오지 못했습니다.</div>';
  }
}

function markBoardRead() {
  $('boardBadge').classList.remove('on');
  $('boardBadge').textContent = '';
}

/* 안 본 공지 개수를 상단 버튼에 표시한다 */
async function refreshBoardBadge() {
  try {
    const r = await fetch('/api/notices?all=1');
    const list = (await r.json()).notices || [];
    const seen = Number(localStorage.getItem(BOARD_SEEN_KEY) || 0);
    const fresh = list.filter(n => n.id > seen).length;
    if (fresh) {
      $('boardBadge').textContent = fresh;
      $('boardBadge').classList.add('on');
    } else {
      markBoardRead();
    }
  } catch { /* 조용히 넘어간다 */ }
}

$('boardBtn').onclick = openBoard;
$('boardX').onclick = () => $('boardScrim').classList.remove('on');
$('boardClose').onclick = () => $('boardScrim').classList.remove('on');
$('boardScrim').onclick = e => {
  if (e.target === $('boardScrim')) $('boardScrim').classList.remove('on');
};

/* ── 생성 · 폴링 · 다운로드 ────────────────────── */
let pollTimer = null;

$('genBtn').onclick = async () => {
  if (!selection) return;
  const body = {
    bbox: [selection.minLon, selection.minLat, selection.maxLon, selection.maxLat],
    crs: $('crs').value,
    layers: selectedLayers(),
    options: {
      version: $('ver').value,
      unit: $('unit').value,
      text_height: $('txth').value,
      origin_shift: $('sw2').checked,
      reference_marks: $('sw3').checked,
    },
  };

  buildStageList();
  $('progSub').textContent =
    `${$('s-area').textContent} · EPSG:${$('crs').value} · ${selectedLayers().length}개 레이어`;
  $('bar').style.width = '0%';
  $('progScrim').classList.add('on');

  let res;
  try {
    res = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    showError('서버에 연결할 수 없습니다.');
    return;
  }
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    showError(d.detail || `요청이 거부되었습니다 (HTTP ${res.status}).`);
    return;
  }
  const { id } = await res.json();
  poll(id);
};

function buildStageList() {
  const ul = $('stages');
  ul.innerHTML = '';
  (CFG.stages || []).forEach(s => {
    ul.insertAdjacentHTML('beforeend',
      `<li data-k="${s.key}"><span class="ic"></span>${s.label}<span class="t">—</span></li>`);
  });
}

function poll(id) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    let st;
    try {
      const r = await fetch(`/api/jobs/${id}`);
      if (!r.ok) throw new Error();
      st = await r.json();
    } catch {
      clearInterval(pollTimer);
      showError('작업 상태를 조회할 수 없습니다.');
      return;
    }

    const keys = (CFG.stages || []).map(s => s.key);
    const at = keys.indexOf(st.stage);
    document.querySelectorAll('#stages li').forEach((li, i) => {
      li.className = i < at ? 'done' : i === at ? 'doing' : '';
      if (i < at) li.querySelector('.t').textContent = '완료';
      else if (i === at) li.querySelector('.t').textContent =
        st.stage_progress > 0 ? `${Math.round(st.stage_progress * 100)}%` : '진행 중';
    });
    $('bar').style.width = `${Math.round(st.progress * 100)}%`;

    if (st.state === 'done') {
      clearInterval(pollTimer);
      showResult(id, st);
    } else if (st.state === 'error') {
      clearInterval(pollTimer);
      showError(st.error);
    }
  }, 600);
}

const LAY_COLOR = {
  'D-PARCEL': '--l-parcel', 'D-PNU-TEXT': '--l-label', 'A-REF': '--l-ref',
};

function showResult(id, st) {
  $('progScrim').classList.remove('on');
  $('doneTitle').textContent = '추출 완료';
  $('doneSub').textContent = `${st.elapsed.toFixed(1)}초 소요 · 파일은 24시간 후 자동 삭제됩니다.`;
  if (st.warnings && st.warnings.length) {
    $('errBox').style.display = '';
    $('errBox').textContent = '일부 레이어가 빠졌습니다 — ' + st.warnings.join(' / ');
  } else {
    $('errBox').style.display = 'none';
  }
  $('fileCard').style.display = 'flex';
  $('r-name').textContent = st.filename;
  $('r-meta').textContent =
    `${(st.size / 1048576).toFixed(2)} MB · ${$('ver').selectedOptions[0].textContent} · ${$('unit').selectedOptions[0].textContent}`;

  const bd = $('r-bd');
  bd.style.display = '';
  bd.innerHTML = st.layers.map(l => `
    <div class="bd-row">
      <span class="swatch fill" style="background:var(${LAY_COLOR[l.layer] || '--text-3'})"></span>
      <span>${l.name}</span><span class="code">${l.layer}</span>
      <span class="n">${l.count.toLocaleString()}</span>
    </div>`).join('');

  $('dlBtn').style.display = '';
  $('dlBtn').onclick = () => { window.location.href = `/api/jobs/${id}/download`; };
  $('doneScrim').classList.add('on');
}

function showError(msg) {
  $('progScrim').classList.remove('on');
  $('doneTitle').textContent = '추출 실패';
  $('doneSub').textContent = '아래 원인을 확인한 뒤 다시 시도하세요.';
  $('errBox').style.display = '';
  $('errBox').textContent = msg;
  $('fileCard').style.display = 'none';
  $('r-bd').style.display = 'none';
  $('dlBtn').style.display = 'none';
  $('doneScrim').classList.add('on');
}

$('closeDone').onclick = () => $('doneScrim').classList.remove('on');
$('doneScrim').onclick = e => { if (e.target === $('doneScrim')) $('doneScrim').classList.remove('on'); };

/* ── 부팅 ─────────────────────────────────────── */
(async function boot() {
  try {
    CFG = await (await fetch('/api/config')).json();
  } catch {
    $('keyMsg').textContent = '서버에 연결할 수 없습니다';
    $('keyDot').classList.add('off');
    return;
  }

  const sel = $('crs');
  CFG.crs.forEach(g => {
    const og = document.createElement('optgroup');
    og.label = g.group;
    g.items.forEach(c => {
      crsInfo[c.code] = c;
      const o = document.createElement('option');
      o.value = c.code;
      o.textContent = `${c.name} · EPSG:${c.code}`;
      o.selected = c.code === CFG.default_crs;
      og.appendChild(o);
    });
    sel.appendChild(og);
  });

  if (CFG.has_vworld_key) {
    $('keyMsg').textContent = '연속지적도 다운로드 가능';
  } else {
    $('keyMsg').textContent = '연속지적도 다운로드 안됨';
    $('keyDot').classList.add('off');
  }

  // CFG를 받은 뒤에야 배경지도 소스를 정할 수 있다(직결/중계 판단).
  baseLayer.setSource(basemapSource(currentBasemap));

  refreshScale();
  refreshSummary();
  loadParcelPreview();
  loadNotices();
  refreshBoardBadge();
})();


// ── 도시계획 · 지역지구 고르기 ────────────────────────────────
// 서버가 주는 목록으로 만든다. 여기 목록을 손댈 일이 없도록.
(async () => {
  let d;
  try { d = await (await fetch('/api/layers')).json(); } catch { return; }
  const box = document.getElementById('planGroups');
  if (!box || !d.layers) return;

  const esc = s => String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  box.innerHTML = d.groups.map(g => {
    const items = d.layers.filter(l => l.group === g);
    if (!items.length) return '';
    return `<details class="plangrp" data-grp="${esc(g)}">
      <summary>${esc(g)}<span class="cnt">0 / ${items.length}</span></summary>
      <div class="body">
        ${items.map(l => `<label class="lay">
          <input type="checkbox" data-lay="${esc(l.key)}" data-grp="${esc(g)}">
          <span class="swatch" style="background:var(--text-3)"></span>
          <span class="lay-name">${esc(l.label)}</span>
          <span class="lay-code">${esc(l.layer)}</span></label>`).join('')}
        <button type="button" class="all">이 묶음 모두</button>
      </div>
    </details>`;
  }).join('');

  const tally = () => {
    box.querySelectorAll('.plangrp').forEach(g => {
      const cs = [...g.querySelectorAll('input[data-lay]')];
      const on = cs.filter(c => c.checked).length;
      const el = g.querySelector('.cnt');
      el.textContent = `${on} / ${cs.length}`;
      el.classList.toggle('on', on > 0);
    });
  };

  box.addEventListener('change', () => { tally(); refreshSummary(); });
  box.querySelectorAll('.all').forEach(b => b.onclick = () => {
    const cs = [...b.closest('.plangrp').querySelectorAll('input[data-lay]')];
    const on = cs.every(c => c.checked);
    cs.forEach(c => { c.checked = !on; });
    tally();
    refreshSummary();
  });

  if (d.unavailable && d.unavailable.length) {
    const h = document.getElementById('planHelp');
    if (h) {
      h.innerHTML = h.innerHTML +
        `<br><b>V-World에 없어 못 넣는 것</b> ${d.unavailable.length}종 — ` +
        d.unavailable.map(u => esc(u.label)).join(', ');
    }
  }
  tally();
})();
