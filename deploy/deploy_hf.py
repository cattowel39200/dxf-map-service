"""Hugging Face Spaces에 배포한다.

무료 CPU basic 이 2 vCPU / 16 GB 라 이 서비스에 충분하고 신용카드가 필요 없다.
Space 생성, 인증키 등록, 코드 업로드를 한 번에 처리한다.

    python deploy/deploy_hf.py --token hf_xxxxx
    python deploy/deploy_hf.py --token hf_xxxxx --space 다른이름 --private

토큰은 https://huggingface.co/settings/tokens 에서 write 권한으로 발급한다.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
API = "https://huggingface.co/api"

FRONTMATTER = """---
title: 지적도·지형도 DXF 추출
emoji: 🗺️
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

"""


def run(cmd, cwd=None, quiet=False):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 and not quiet:
        print(f"  명령 실패: {' '.join(cmd)}")
        print("  " + (r.stderr or r.stdout or "").strip()[:500])
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.getenv("HF_TOKEN"),
                    help="Hugging Face write 토큰 (또는 HF_TOKEN 환경변수)")
    ap.add_argument("--space", default="dxf-map-service", help="Space 이름")
    ap.add_argument("--private", action="store_true", help="비공개 Space")
    ap.add_argument("--vworld-key", default=None,
                    help="생략하면 .env 에서 읽는다")
    args = ap.parse_args()

    if not args.token:
        sys.exit("토큰이 필요합니다.  --token hf_xxx  또는 HF_TOKEN 환경변수\n"
                 "발급: https://huggingface.co/settings/tokens  (write 권한)")

    h = {"Authorization": f"Bearer {args.token}"}
    client = httpx.Client(timeout=60, headers=h, follow_redirects=True)

    # 1) 계정 확인
    who = client.get(f"{API}/whoami-v2")
    if who.status_code != 200:
        sys.exit(f"토큰이 올바르지 않습니다 (HTTP {who.status_code})")
    user = who.json()["name"]
    print(f"계정        {user}")

    repo_id = f"{user}/{args.space}"
    host = f"{user}-{args.space}".lower().replace("_", "-")
    url = f"https://{host}.hf.space"
    print(f"Space       {repo_id}")
    print(f"주소        {url}\n")

    # 2) 인증키
    key = args.vworld_key
    if not key:
        envf = ROOT / ".env"
        if envf.exists():
            for line in envf.read_text(encoding="utf-8-sig").splitlines():
                if line.strip().startswith("VWORLD_KEY="):
                    key = line.split("=", 1)[1].strip()
    if not key:
        print("경고: V-World 인증키를 찾지 못했습니다. 지적 레이어는 동작하지 않습니다.")

    # 3) Space 생성
    print("[1/4] Space 생성")
    r = client.post(f"{API}/repos/create", json={
        "type": "space", "name": args.space,
        "private": bool(args.private), "sdk": "docker",
    })
    if r.status_code in (200, 201):
        print("      새로 만들었습니다.")
    elif r.status_code == 409 or "exists" in r.text.lower():
        print("      이미 있는 Space 입니다. 덮어씁니다.")
    else:
        sys.exit(f"      생성 실패 HTTP {r.status_code}: {r.text[:300]}")

    # 4) 인증키는 secret, 도메인은 variable
    print("[2/4] 환경변수 등록")
    if key:
        r = client.post(f"{API}/spaces/{repo_id}/secrets",
                        json={"key": "VWORLD_KEY", "value": key})
        print(f"      VWORLD_KEY (secret)  {'OK' if r.status_code < 300 else r.status_code}")
    for k, v in [("VWORLD_DOMAIN", host + ".hf.space"),
                 ("MAX_AREA_KM2", "1.0"),
                 ("MAX_CONCURRENT_JOBS", "2")]:
        r = client.post(f"{API}/spaces/{repo_id}/variables",
                        json={"key": k, "value": v})
        print(f"      {k:20} {'OK' if r.status_code < 300 else r.status_code}")

    # 5) 코드 업로드 — git 추적 파일만 임시 폴더에 복사해 올린다
    print("[3/4] 코드 업로드")
    tmp = Path(tempfile.mkdtemp(prefix="hfspace_"))
    try:
        files = run(["git", "ls-files"], cwd=ROOT).stdout.split()
        for rel in files:
            src = ROOT / rel
            if not src.exists():
                continue
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        # Space 는 README 앞머리의 설정 블록을 읽는다
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        (tmp / "README.md").write_text(FRONTMATTER + readme, encoding="utf-8")

        run(["git", "init", "-q"], cwd=tmp)
        run(["git", "config", "user.name", user], cwd=tmp)
        run(["git", "config", "user.email", f"{user}@users.noreply.huggingface.co"], cwd=tmp)
        run(["git", "add", "-A"], cwd=tmp)
        run(["git", "commit", "-q", "-m", "지적도·지형도 DXF 추출 서비스"], cwd=tmp)
        remote = f"https://{user}:{args.token}@huggingface.co/spaces/{repo_id}"
        run(["git", "branch", "-M", "main"], cwd=tmp)
        push = run(["git", "push", "-f", remote, "main"], cwd=tmp)
        if push.returncode != 0:
            sys.exit("      업로드 실패. 토큰에 write 권한이 있는지 확인하세요.")
        print(f"      파일 {len(files)}개 업로드 완료")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("[4/4] 빌드 시작됨\n")
    print("=" * 62)
    print(f"  주소   {url}")
    print(f"  현황   https://huggingface.co/spaces/{repo_id}")
    print("=" * 62)
    print("\n  도커 이미지를 만드는 데 3~6분 걸립니다.")
    print("  위 현황 페이지에서 Building 이 Running 으로 바뀌면 접속됩니다.\n")
    print("  ★ 반드시 하셔야 할 일")
    print("     vworld.kr → 마이페이지 → 인증키 관리 에서")
    print(f"     활용 URL 에  {url}  을 추가하세요.")
    print("     등록하지 않으면 배경지도와 지적 레이어가 나오지 않습니다.\n")


if __name__ == "__main__":
    main()
