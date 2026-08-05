"""지적도 DXF 가져오기 - 설치 프로그램

CADMAP.lsp 를 사용자 폴더에 넣고, 설치된 AutoCAD 가 켜질 때
스스로 불러오도록 등록한다. 관리자 권한은 필요 없다.

  설치 위치   %LOCALAPPDATA%\\KyoungsungEng\\CADMAP
  자동 실행   HKCU\\Software\\Autodesk\\AutoCAD\\<판>\\<제품>\\Applications\\CADMAP
  프로그램 설정 HKCU\\Software\\KyoungsungEng\\CADMAP
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import winreg
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

APP_NAME = "지적도 DXF 가져오기"
COMPANY = "(주)경성엔지니어링"
VERSION = "1.4.0"
SITE = "https://ks-down-map.com"

LSP_NAME = "CADMAP.lsp"
APP_KEY = "CADMAP"                       # AutoCAD 에 등록할 이름
DEST = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "KyoungsungEng" / "CADMAP"
SETTINGS = r"Software\KyoungsungEng\CADMAP"

# 정식 AutoCAD 와 LT 는 레지스트리 자리가 다르다. 둘 다 찾아 보고,
# LT 는 목록에 보여 주되 설치는 막는다. 왜 안 되는지 알려 드리려는 것이다.
ACAD_ROOTS = [
    (r"Software\Autodesk\AutoCAD", False),
    (r"Software\Autodesk\AutoCAD LT", True),
]

# 레지스트리의 판 번호를 연도로 옮긴다. 2010(R18.0)부터 쓸 수 있다.
YEARS = {
    "R18.0": 2010, "R18.1": 2011, "R18.2": 2012,
    "R19.0": 2013, "R19.1": 2014,
    "R20.0": 2015, "R20.1": 2016,
    "R21.0": 2017, "R22.0": 2018,
    "R23.0": 2019, "R23.1": 2020,
    "R24.0": 2021, "R24.1": 2022, "R24.2": 2023, "R24.3": 2024,
    "R25.0": 2025, "R25.1": 2026,
}
LT_YEARS = {"R29": 2023, "R30": 2024, "R31": 2025, "R32": 2026}
MIN_YEAR = 2010

# LT 는 vlax-create-object 를 지원하지 않는다. 이 프로그램은 그 기능으로
# 서버와 주고받으므로 LT 에서는 리습이 있어도 동작하지 않는다.
LT_REASON = ("AutoCAD LT 는 지원하지 않습니다.\n"
             "LT 2024부터 리습이 들어왔지만 외부 프로그램을 불러오는 기능이\n"
             "빠져 있어, 서버와 통신하는 이 프로그램은 동작하지 않습니다.")

KEY_RE = re.compile(r"^KS-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")


# ─────────────────────────────────────────────────── 묶여 들어온 파일 찾기
def bundled(name: str) -> Path:
    """PyInstaller 로 묶였으면 임시 폴더, 아니면 이 파일 옆에서 찾는다."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    p = base / name
    if p.exists():
        return p
    for alt in (Path(__file__).parent / name,
                Path(__file__).parent.parent / "web" / "dist" / name,
                Path(sys.argv[0]).parent / name):
        if alt.exists():
            return alt
    raise FileNotFoundError(name)


# ─────────────────────────────────────────────────── AutoCAD 찾기
def find_autocad() -> list[dict]:
    """설치된 AutoCAD 를 모두 찾는다.

    [{release, product, path, label, lt, year, ok, why}]
    ok 가 False 면 설치할 수 없는 것이고, why 에 까닭이 담긴다.
    """
    found = []
    for acad_root, is_lt in ACAD_ROOTS:
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, acad_root)
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    rel = winreg.EnumKey(root, i)          # 예: R24.2
                except OSError:
                    break
                if not rel.upper().startswith("R"):
                    continue
                try:
                    relkey = winreg.OpenKey(root, rel)
                except OSError:
                    continue
                with relkey:
                    for j in range(winreg.QueryInfoKey(relkey)[0]):
                        try:
                            prod = winreg.EnumKey(relkey, j)   # 예: ACAD-8001:409
                        except OSError:
                            break
                        if ":" not in prod:
                            continue
                        # 정식 AutoCAD 자리에 LT 가 들어앉는 경우도 있다
                        lt = is_lt or prod.upper().startswith("ACLT")
                        sub = f"{acad_root}\\{rel}\\{prod}"
                        found.append(_describe(sub, rel, prod, lt))
    return found


def _describe(sub: str, rel: str, prod: str, lt: bool) -> dict:
    year = (LT_YEARS if lt else YEARS).get(rel)
    label = _product_name(sub) or (
        f"AutoCAD{' LT' if lt else ''} {year}" if year
        else f"AutoCAD{' LT' if lt else ''} {rel}")

    ok, why = True, ""
    if lt:
        ok, why = False, "LT 는 지원하지 않습니다"
    elif year and year < MIN_YEAR:
        ok, why = False, f"{MIN_YEAR} 이전 버전입니다"

    return {"release": rel, "product": prod, "path": sub, "label": label,
            "lt": lt, "year": year, "ok": ok, "why": why}


def _product_name(sub: str) -> str:
    """레지스트리에 적힌 제품 이름. 없으면 빈 글자."""
    for name in ("ProductName", "ProductNameShort"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as k:
                v = winreg.QueryValueEx(k, name)[0]
                if v:
                    return str(v)
        except OSError:
            pass
    return ""


# ─────────────────────────────────────────────────── 설치 / 제거
def register(acad: dict, loader: Path) -> None:
    """AutoCAD 가 켜질 때 이 리습을 스스로 불러오게 한다."""
    path = f"{acad['path']}\\Applications\\{APP_KEY}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
        winreg.SetValueEx(k, "DESCRIPTION", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(k, "LOADER", 0, winreg.REG_SZ, str(loader))
        winreg.SetValueEx(k, "LOADCTRLS", 0, winreg.REG_DWORD, 2)   # 시작할 때
        winreg.SetValueEx(k, "MANAGED", 0, winreg.REG_DWORD, 1)


def unregister(acad: dict) -> bool:
    path = f"{acad['path']}\\Applications\\{APP_KEY}"
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        return True
    except OSError:
        return False


def save_setting(name: str, value: str) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def read_setting(name: str, default: str = "") -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return default


def do_install(targets: list[dict], key: str, log) -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    src = bundled(LSP_NAME)
    dst = DEST / LSP_NAME
    shutil.copyfile(src, dst)
    log(f"파일 복사   {dst}")

    save_setting("Path", str(dst))
    save_setting("Version", VERSION)
    if key:
        save_setting("Key", key)
        log(f"발급키 등록 {key}")

    for a in targets:
        register(a, dst)
        log(f"자동 실행   {a['label']}  ({a['release']})")


def do_uninstall(all_acad: list[dict], log) -> None:
    n = sum(1 for a in all_acad if unregister(a))
    log(f"자동 실행 해제  {n}개")
    if DEST.exists():
        shutil.rmtree(DEST, ignore_errors=True)
        log(f"파일 삭제   {DEST}")
    log("발급키는 남겨 두었습니다. 다시 설치하면 그대로 쓰입니다.")


# ─────────────────────────────────────────────────── 화면
BG, FG, SUB, LINE, ACC = "#ffffff", "#1a1a1a", "#6b6b6b", "#dcdcdc", "#1f6feb"


class Installer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} 설치")
        self.configure(bg=BG)
        self.resizable(False, False)
        self._center(520, 560)

        self.acad = find_autocad()
        self.vars: list[tuple[tk.BooleanVar, dict]] = []
        self._build()

    def _center(self, w, h):
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 3
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build(self):
        pad = {"padx": 26}

        tk.Label(self, text=APP_NAME, bg=BG, fg=FG,
                 font=("맑은 고딕", 16, "bold")).pack(anchor="w", pady=(22, 0), **pad)
        tk.Label(self, text=f"{COMPANY}   ·   {VERSION}", bg=BG, fg=SUB,
                 font=("맑은 고딕", 9)).pack(anchor="w", pady=(2, 14), **pad)
        tk.Frame(self, bg=LINE, height=1).pack(fill="x", **pad)

        # ── AutoCAD 목록
        tk.Label(self, text="설치할 AutoCAD", bg=BG, fg=FG,
                 font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(16, 6), **pad)

        box = tk.Frame(self, bg=BG)
        box.pack(fill="x", **pad)
        if not self.acad:
            tk.Label(box, text="AutoCAD 를 찾지 못했습니다.\n"
                              "AutoCAD 를 한 번 실행한 뒤 다시 시도해 주세요.",
                     bg=BG, fg="#b3261e", justify="left",
                     font=("맑은 고딕", 9)).pack(anchor="w")
        for a in self.acad:
            v = tk.BooleanVar(value=a["ok"])
            label = f"{a['label']}   ({a['release']})"
            if not a["ok"]:
                label += f"   —  {a['why']}"
            tk.Checkbutton(box, text=label, variable=v, bg=BG,
                           fg=(FG if a["ok"] else "#b3261e"), activebackground=BG,
                           selectcolor=BG, font=("맑은 고딕", 10), anchor="w",
                           state=("normal" if a["ok"] else "disabled"),
                           disabledforeground="#b3261e").pack(anchor="w", fill="x")
            self.vars.append((v, a))

        if any(a["lt"] for a in self.acad):
            tk.Label(box, text=LT_REASON, bg=BG, fg=SUB, justify="left",
                     font=("맑은 고딕", 8)).pack(anchor="w", pady=(6, 0))
        elif self.acad and not any(a["ok"] for a in self.acad):
            tk.Label(box, text=f"AutoCAD {MIN_YEAR} 이상이 필요합니다.",
                     bg=BG, fg="#b3261e", justify="left",
                     font=("맑은 고딕", 9)).pack(anchor="w", pady=(6, 0))

        # ── 발급키
        tk.Label(self, text="발급키  (없으면 비워 두세요)", bg=BG, fg=FG,
                 font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(18, 6), **pad)
        self.key = tk.StringVar(value=read_setting("Key"))
        e = tk.Entry(self, textvariable=self.key, font=("Consolas", 11),
                     relief="solid", bd=1)
        e.pack(fill="x", ipady=5, **pad)
        tk.Label(self, text="비워 두시면 AutoCAD 에서 '지적도삽입' 을 처음 누를 때\n"
                            "이 PC 앞으로 3일 데모 발급키가 저절로 만들어집니다.\n"
                            "이미 받으신 키가 있으면 여기에 넣어 주십시오.",
                 bg=BG, fg=SUB, justify="left",
                 font=("맑은 고딕", 8)).pack(anchor="w", pady=(5, 0), **pad)

        # ── 기록
        tk.Frame(self, bg=LINE, height=1).pack(fill="x", pady=(16, 0), **pad)
        self.log_box = tk.Text(self, height=7, bg="#fafafa", fg=SUB, relief="flat",
                               font=("맑은 고딕", 8), wrap="word", state="disabled")
        self.log_box.pack(fill="both", expand=True, pady=(10, 0), **pad)

        # ── 단추
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", pady=16, **pad)
        tk.Button(bar, text="제거", command=self.on_uninstall, width=9,
                  relief="solid", bd=1, bg=BG, fg=SUB,
                  font=("맑은 고딕", 9)).pack(side="left")
        tk.Button(bar, text="닫기", command=self.destroy, width=9,
                  relief="solid", bd=1, bg=BG, fg=SUB,
                  font=("맑은 고딕", 9)).pack(side="right")
        self.btn = tk.Button(bar, text="설치", command=self.on_install, width=12,
                             relief="flat", bg=ACC, fg="white",
                             font=("맑은 고딕", 10, "bold"))
        self.btn.pack(side="right", padx=(0, 8))
        usable = [a for a in self.acad if a["ok"]]
        if not usable:
            self.btn.configure(state="disabled", bg="#c9c9c9")

        self.log(f"AutoCAD {len(self.acad)}개를 찾았습니다."
                 + (f"  (설치 가능 {len(usable)}개)"
                    if len(usable) != len(self.acad) else ""))
        self.log(f"설치 위치  {DEST}")

    def log(self, s: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", s + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.update_idletasks()

    def on_install(self):
        targets = [a for v, a in self.vars if v.get() and a["ok"]]
        if not targets:
            messagebox.showwarning("설치", "설치할 AutoCAD 를 하나 이상 골라 주세요.")
            return

        key = self.key.get().strip().upper().replace(" ", "")
        if key and not KEY_RE.match(key):
            if not messagebox.askyesno(
                    "발급키 확인",
                    f"'{key}' 는 발급키 형태(KS-XXXX-XXXX-XXXX)와 다릅니다.\n"
                    "이대로 진행할까요?"):
                return

        self.btn.configure(state="disabled")
        try:
            do_install(targets, key, self.log)
        except Exception as e:                        # noqa: BLE001
            self.log(f"실패  {e}")
            messagebox.showerror("설치 실패", str(e))
            self.btn.configure(state="normal")
            return

        self.log("설치를 마쳤습니다.")
        self.btn.configure(state="normal")
        messagebox.showinfo(
            "설치 완료",
            "설치를 마쳤습니다.\n\n"
            "AutoCAD 를 다시 켜시면 상단에 '지적도' 메뉴가 생깁니다.\n"
            "[지적도삽입] 을 누르시면 발급키가 저절로 만들어져\n"
            "3일간 바로 써 보실 수 있습니다.\n\n"
            f"안내  {SITE}/cad")

    def on_uninstall(self):
        if not messagebox.askyesno("제거", "설치한 파일과 자동 실행 등록을 지울까요?"):
            return
        do_uninstall(self.acad, self.log)
        messagebox.showinfo("제거 완료", "제거를 마쳤습니다.\n"
                                      "AutoCAD 를 다시 켜면 메뉴가 사라집니다.")


def main() -> int:
    if os.name != "nt":
        print("이 프로그램은 Windows 전용입니다.")
        return 1
    try:
        bundled(LSP_NAME)
    except FileNotFoundError:
        tk.Tk().withdraw()
        messagebox.showerror("설치 파일 오류",
                             f"{LSP_NAME} 을 찾을 수 없습니다.\n"
                             "설치 파일을 다시 내려받아 주세요.")
        return 1
    Installer().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
