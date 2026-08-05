"""추출 작업 큐.

필지가 많은 도심은 조회에 수십 초가 걸리므로 요청을 즉시 반환하고 진행률을
폴링하게 한다. 단일 프로세스용 메모리 저장소이므로, 다중 워커로 늘릴 때는
Redis + RQ로 교체한다.
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import config, layers as layerdef, usage
from .dxfgen import DxfBuilder
from .geom import BBox
from .sources import vworld

STAGES = [
    ("parcel", "연속지적도 필지 조회"),
    ("planning", "도시계획 · 지역지구 조회"),
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
    parcel_count: int = 0
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
            "parcel_count": self.parcel_count,
            "elapsed": round(self.elapsed, 2),
        }


JOBS: dict[str, Job] = {}


class Busy(RuntimeError):
    pass


def running_count() -> int:
    return sum(1 for j in JOBS.values() if j.state in ("queued", "running"))


def create(request: dict) -> Job:
    # 작업 상태를 메모리에 두고 워커가 하나뿐이라 동시 처리량에 한계가 있다.
    # 공개 주소로 열어 두면 동시 요청이 몰릴 수 있어 여기서 막는다.
    if running_count() >= config.MAX_CONCURRENT_JOBS:
        raise Busy(
            f"현재 {running_count()}건이 처리 중입니다. "
            "잠시 후 다시 시도해 주세요."
        )
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

        want_cadastral = bool({"parcel", "pnu"} & set(layers))
        plans = layerdef.pick(layers)

        # 1) 연속지적도 조회
        parcels = []
        if want_cadastral:
            job.stage = "parcel"
            job.progress = 0.03
            parcels = await vworld.fetch_parcels(
                box,
                progress=lambda p: setattr(job, "stage_progress",
                                           max(0.0, min(1.0, p))))
            job.stage_progress = 1.0
            job.parcel_count = len(parcels)

            if not parcels and not plans:
                raise RuntimeError(
                    "선택한 영역에서 필지를 찾지 못했습니다. "
                    "바다나 미등록 지역이거나, 영역이 너무 좁을 수 있습니다."
                )

        # 2) 도시계획 · 지역지구 조회
        # 그 지역에 없는 종류는 빈 채로 넘어간다. 한 종류가 없다고 해서
        # 나머지까지 못 받게 하면 쓸모가 없다.
        shapes = {}
        if plans:
            job.stage = "planning"
            job.progress = 0.25
            job.stage_progress = 0.0
            for i, spec in enumerate(plans):
                try:
                    got = await vworld.fetch_shapes(box, spec["source"])
                except Exception as exc:      # noqa: BLE001
                    got = []
                    job.warnings.append(f"{spec['label']}: {exc}")
                if got:
                    shapes[spec["key"]] = got
                else:
                    job.warnings.append(f"{spec['label']}: 이 영역에는 자료가 없습니다.")
                job.stage_progress = (i + 1) / len(plans)

        if not parcels and not shapes:
            raise RuntimeError(
                "선택한 영역에서 받을 자료가 없습니다. "
                "다른 종류를 고르시거나 영역을 옮겨 보세요."
            )

        # 3) 좌표 변환 + 조립 — CPU 작업이라 이벤트 루프를 막지 않게 스레드로 뺀다.
        job.stage = "assemble"
        job.progress = 0.7
        job.stage_progress = 0.0
        result = await asyncio.to_thread(
            _assemble, job.id, box, target, options, layers, parcels, shapes)
        job.path, job.filename, job.size, job.layers = result
        job.progress = 1.0
        job.stage_progress = 1.0
        job.state = "done"

    except Exception as exc:  # noqa: BLE001 — 사용자에게 원인을 그대로 보여준다
        job.state = "error"
        job.error = str(exc) or exc.__class__.__name__
    finally:
        job.elapsed = time.time() - started
        _log_usage(job, req)


def _assemble(job_id, box, target, options, layers, parcels, shapes=None):
    b = DxfBuilder(target, options, box)
    if parcels:
        b.add_parcels(parcels,
                      draw_boundary="parcel" in layers,
                      draw_label="pnu" in layers)
    for spec in layerdef.pick(layers):
        got = (shapes or {}).get(spec["key"])
        if got:
            b.add_planning(spec, got,
                           sub_layers=options.get("plan_sub_layers", True),
                           draw_label=options.get("plan_labels", False))
    if options.get("reference_marks", True):
        b.add_reference_marks()

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    name = _filename(box, target)
    path = config.OUTPUT_DIR / f"{job_id}_{name}"
    b.save(path)
    return path, name, path.stat().st_size, b.stats()


def _log_usage(job: Job, req: dict):
    """기록 실패가 추출 결과에 영향을 주지 않게 감싼다."""
    try:
        box = BBox(*req["bbox"])
        lon, lat = box.center
        usage.record(job, {
            "ip": req.get("ip"),
            "source": req.get("source"),
            "crs": req.get("crs"),
            "layers": req.get("layers"),
            "area_km2": round(box.area_km2(), 5),
            "lon": round(lon, 5), "lat": round(lat, 5),
        })
    except Exception:  # noqa: BLE001
        pass


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
