"""추출 작업 큐.

넓은 영역은 수십 초가 걸리므로 요청을 즉시 반환하고 진행률을 폴링하게 한다.
단일 프로세스용 메모리 저장소이므로, 다중 워커로 늘릴 때 Redis + RQ로 교체한다.
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .contour import build_contours
from .dxfgen import DxfBuilder
from .geom import BBox
from .sources import dem, osm, vworld

STAGES = [
    ("parcel", "연속지적도 필지 조회"),
    ("terrain", "지형지물 조회"),
    ("contour", "수치표고 등고선 생성"),
    ("assemble", "좌표 변환 및 DXF 조립"),
]


@dataclass
class Job:
    id: str
    created: float = field(default_factory=time.time)
    state: str = "queued"          # queued | running | done | error
    stage: str = ""
    progress: float = 0.0
    stage_progress: float = 0.0
    error: str = ""
    path: Path | None = None
    filename: str = ""
    size: int = 0
    layers: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    dem: dict | None = None
    elapsed: float = 0.0

    def as_dict(self):
        return {
            "id": self.id,
            "state": self.state,
            "stage": self.stage,
            "stage_label": dict(STAGES).get(self.stage, ""),
            "progress": round(self.progress, 4),
            "stage_progress": round(self.stage_progress, 4),
            "error": self.error,
            "filename": self.filename,
            "size": self.size,
            "layers": self.layers,
            "warnings": self.warnings,
            "dem": self.dem,
            "elapsed": round(self.elapsed, 2),
        }


JOBS: dict[str, Job] = {}


def create(request: dict) -> Job:
    job = Job(id=uuid.uuid4().hex[:12])
    JOBS[job.id] = job
    asyncio.create_task(_run(job, request))
    return job


def get(job_id: str) -> Job | None:
    return JOBS.get(job_id)


async def _run(job: Job, req: dict):
    started = time.time()
    job.state = "running"
    try:
        box = BBox(*req["bbox"])
        layers = set(req["layers"])
        options = req.get("options", {})
        target = req["crs"]

        def stage(key, frac_done):
            job.stage = key
            job.stage_progress = 0.0
            job.progress = frac_done

        def sub(p):
            job.stage_progress = max(0.0, min(1.0, p))

        # 1) 지적
        parcels = []
        stage("parcel", 0.02)
        if layers & {"parcel", "pnu"}:
            parcels = await vworld.fetch_parcels(box, progress=sub)
        job.stage_progress = 1.0

        # 2) 지형지물 — 공용 OSM 서버가 붐빌 때 전체 추출을 날리지 않는다.
        features = {"building": [], "road": [], "water": []}
        stage("terrain", 0.32)
        osm_want = layers & {"building", "road", "water"}
        if osm_want:
            try:
                features = await osm.fetch_features(box)
            except osm.OverpassError as exc:
                job.warnings.append(str(exc))
                osm_want = set()
        job.stage_progress = 1.0

        # 3) 등고선 — 가장자리가 잘리지 않게 여유를 두고 표고를 받는다.
        contours = []
        stage("contour", 0.52)
        if "contour" in layers:
            pad = box.expanded(max(120.0, box.width_m() * 0.08))
            grid, lons, lats, dem_meta = await dem.load_dem(pad, progress=sub)
            interval = float(options.get("contour_interval", 5))
            raw = build_contours(grid, lons, lats, interval)
            contours = [c for c in raw if _touches(c["pts"], box)]
            job.dem = _dem_summary(dem_meta, grid, interval, job)
        job.stage_progress = 1.0

        # 요청한 레이어가 전부 실패했다면 빈 도면을 주는 대신 원인을 알린다.
        if not parcels and not contours and not osm_want:
            raise RuntimeError(job.warnings[0] if job.warnings
                               else "선택한 영역에서 추출할 데이터를 찾지 못했습니다.")

        # 4) 변환 + 조립 — CPU 작업이라 이벤트 루프를 막지 않게 스레드로 뺀다.
        stage("assemble", 0.78)
        result = await asyncio.to_thread(
            _assemble, job.id, box, target, options, layers, parcels, contours,
            features, osm_want,
        )
        job.path, job.filename, job.size, job.layers = result
        job.progress = 1.0
        job.stage_progress = 1.0
        job.state = "done"

    except Exception as exc:  # noqa: BLE001 — 사용자에게 원인을 그대로 보여준다
        job.state = "error"
        job.error = str(exc) or exc.__class__.__name__
    finally:
        job.elapsed = time.time() - started


def _touches(pts, box: BBox):
    return any(box.contains(p[0], p[1]) for p in pts)


LABELS = {"local": "국토지리정보원 수치표고모델", "aws": "AWS Terrain Tiles (전지구)"}


def _dem_summary(meta, grid, interval, job):
    """어떤 표고 자료를 썼는지, 요청한 등고선 간격이 그 자료에 맞는지 정리한다."""
    import numpy as np

    vals = np.unique(grid[np.isfinite(grid)])
    step = 0.0
    if vals.size > 1:
        diffs = np.diff(vals)
        diffs = diffs[diffs > 1e-6]
        step = float(np.min(diffs)) if diffs.size else 0.0

    info = {
        "source": meta["source"],
        "label": LABELS.get(meta["source"], meta["source"]),
        "file": meta.get("file", ""),
        "grid_m": meta.get("grid_m"),
        "vertical_step_m": round(step, 3),
        "interval_m": interval,
    }

    # 원자료의 표고 분해능보다 촘촘한 등고선은 지형이 아니라 격자 계단을 그린다.
    if step and interval < step * 2:
        job.warnings.append(
            f"등고선 간격 {interval:g} m는 이 표고자료의 분해능({step:g} m)보다 촘촘해 "
            f"실제 지형이 아니라 격자 계단이 그려집니다. {max(step * 2, 5):g} m 이상을 권합니다."
        )
    if meta["source"] == "aws":
        job.warnings.append(
            "이 지역에는 국토지리정보원 수치표고모델이 없어 전지구 자료(격자 "
            f"{meta.get('grid_m')} m)로 등고선을 만들었습니다. 개략 검토용입니다."
        )
    return info


def _assemble(job_id, box, target, options, layers, parcels, contours,
              features, osm_want):
    b = DxfBuilder(target, options, box)
    if layers & {"parcel", "pnu"}:
        b.add_parcels(parcels,
                      draw_boundary="parcel" in layers,
                      draw_label="pnu" in layers)
    if "contour" in layers:
        b.add_contours(contours, with_z=bool(options.get("contour_z", True)))
    if osm_want:
        b.add_osm(features, osm_want)
    if options.get("reference_marks", True):
        b.add_reference_marks()

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    name = _filename(box, target)
    path = config.OUTPUT_DIR / f"{job_id}_{name}"
    b.save(path)
    return path, name, path.stat().st_size, b.stats()


def _filename(box: BBox, target):
    lon, lat = box.center
    return f"cadastral_{lat:.5f}N_{lon:.5f}E_EPSG{target}.dxf"


def sweep_expired():
    """TTL이 지난 산출물과 작업 기록을 지운다."""
    cutoff = time.time() - config.OUTPUT_TTL_HOURS * 3600
    for jid, job in list(JOBS.items()):
        if job.created < cutoff:
            if job.path and job.path.exists():
                job.path.unlink(missing_ok=True)
            JOBS.pop(jid, None)
    if config.OUTPUT_DIR.exists():
        for f in config.OUTPUT_DIR.glob("*.dxf"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
