"""설치 프로그램(install.exe)을 만든다.

  ..\\.venv\\Scripts\\python.exe build.py

CADMAP.lsp 를 exe 안에 묶고, 결과를 web/dist/install.exe 로 내보낸다.
version.json 의 version 도 리습의 *cm:version* 과 맞는지 확인한다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
DIST = ROOT / "web" / "dist"
LSP = HERE / "CADMAP.lsp"


def lisp_version() -> str:
    m = re.search(r'\(setq \*cm:version\*\s+"([^"]+)"\)',
                  LSP.read_bytes().decode("cp949"))
    return m.group(1) if m else ""


def main() -> int:
    if not LSP.exists():
        print(f"!! {LSP} 가 없습니다."); return 1

    lv = lisp_version()
    jv = json.loads((DIST / "version.json").read_text(encoding="utf-8"))["version"]
    iv = re.search(r'^VERSION = "([^"]+)"',
                   (HERE / "install.py").read_text(encoding="utf-8"),
                   re.M).group(1)
    print(f"판 번호   리습 {lv}   version.json {jv}   설치기 {iv}")
    if not (lv == jv == iv):
        print("!! 세 곳의 판 번호가 다릅니다. 맞춘 뒤 다시 실행하세요.")
        return 1

    for d in (HERE / "build", HERE / "dist"):
        shutil.rmtree(d, ignore_errors=True)

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onefile", "--windowed", "--name", "install",
           "--add-data", f"{LSP};.",
           "--distpath", str(HERE / "dist"),
           "--workpath", str(HERE / "build"),
           "--specpath", str(HERE),
           str(HERE / "install.py")]
    ico = HERE / "install.ico"
    if ico.exists():
        cmd[cmd.index("--name"):cmd.index("--name")] = ["--icon", str(ico)]

    print("\n" + " ".join(cmd) + "\n")
    r = subprocess.run(cmd, cwd=HERE)
    if r.returncode:
        print("!! 빌드 실패"); return r.returncode

    out = HERE / "dist" / "install.exe"
    if not out.exists():
        print("!! install.exe 가 만들어지지 않았습니다."); return 1

    DIST.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out, DIST / "install.exe")
    shutil.copyfile(LSP, DIST / "CADMAP.lsp")
    mb = (DIST / "install.exe").stat().st_size / 1048576
    print(f"\n완료   {DIST / 'install.exe'}   {mb:.1f} MB")
    print(f"       {DIST / 'CADMAP.lsp'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
