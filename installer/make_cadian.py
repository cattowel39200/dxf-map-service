"""AutoCAD용 CADMAP.lsp 에서 캐디안(IntelliCAD 계열)용을 만들어 낸다.

    ..\\.venv\\Scripts\\python.exe make_cadian.py

두 벌을 손으로 관리하면 반드시 어긋난다. 원본 하나만 고치고 이 스크립트를
다시 돌리면 캐디안용이 따라온다.

원본(installer/CADMAP.lsp)과 지금 서비스는 건드리지 않는다.
결과는 web/dist/cadian/ 에만 쌓인다.

바꾸는 것
  1. ActiveX 없이 도는 통신 길을 하나 더 붙인다.
     AutoCAD 는 COM 개체(ServerXMLHTTP·WinHttp·WScript.Shell)를 만들 수
     있지만 다른 CAD 는 못 하는 일이 있다. startapp 은 핵심 AutoLISP 이라
     어디서나 되므로, 그것으로 curl 을 돌리고 결과 파일을 기다린다.
  2. 색상표(acad_colordlg)가 없으면 목록에서 고르게 한다.
  3. 판 번호에 -ic 를 붙여 어느 쪽인지 한눈에 보이게 한다.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
SRC = HERE / "CADMAP.lsp"                 # 원본 - 읽기만 한다
OUT_DIR = ROOT / "web" / "dist" / "cadian"
OUT_LSP = OUT_DIR / "CADMAP.lsp"


# ── 1. ActiveX 없이 도는 통신 ────────────────────────────────
HTTP_FREE = r'''
;;; --- 기다리기 (DELAY 가 없는 CAD 도 있다) ---
(defun cm:sleep (ms / t0 sec)
  (if (not (vl-catch-all-error-p
             (vl-catch-all-apply '(lambda () (command "_.DELAY" ms)))))
    T
    ;; DELAY 가 없으면 시계를 보며 기다린다. 곱게 도는 방법은 아니지만
    ;; 통신이 끝나기를 기다리는 잠깐뿐이다.
    (progn
      (setq sec (/ ms 1000.0) t0 (getvar "DATE"))
      (while (< (* 86400.0 (- (getvar "DATE") t0)) sec))
      T)))

;;; --- ActiveX 없이 curl 돌리기 ---
;;; startapp 은 핵심 AutoLISP 이라 어느 CAD 에서나 된다. 다만 끝날 때까지
;;; 기다려 주지 않으므로, 다 됐다는 표시 파일이 생기는지 지켜본다.
(defun cm:http-startapp (method url body / tmp bodyf respf codef donef
                                          cmdline code txt i)
  (setq tmp (getvar "TEMPPREFIX"))
  (if (or (null tmp) (= tmp "")) (setq tmp (strcat (getenv "TEMP") "\\")))
  (setq bodyf (strcat tmp "cmic_body.json")
        respf (strcat tmp "cmic_resp.json")
        codef (strcat tmp "cmic_code.txt")
        donef (strcat tmp "cmic_done.txt"))
  (foreach f (list respf codef donef)
    (if (findfile f) (vl-file-delete f)))
  (if body
    (progn (setq i (open bodyf "w")) (princ body i) (close i)))

  (setq cmdline
    (strcat "/c curl.exe -s -k -X " method
            " -H \"Content-Type: application/json\""
            " -H \"User-Agent: CADMAP/ic\""
            (if body (strcat " --data-binary @\"" bodyf "\"") "")
            " -w \"%{http_code}\" -o \"" respf "\""
            " \"" url "\" > \"" codef "\""
            " & echo ok > \"" donef "\""))
  (vl-catch-all-apply '(lambda () (startapp "cmd.exe" cmdline)))

  ;; 다 됐다는 표시가 뜰 때까지 최대 3분
  (setq i 0)
  (while (and (< i 900) (not (findfile donef)))
    (cm:sleep 200)
    (setq i (1+ i)))

  (setq code 0 txt nil)
  (if (findfile codef) (setq code (atoi (cm:readfile codef))))
  (if (findfile respf) (setq txt (cm:readfile respf)))
  (list (cond ((> code 0) code) (txt 200) (T 0)) txt))

;;; --- ActiveX 없이 파일 내려받기 ---
(defun cm:download-startapp (url path / tmp donef cmdline i ok)
  (setq tmp (getvar "TEMPPREFIX"))
  (if (or (null tmp) (= tmp "")) (setq tmp (strcat (getenv "TEMP") "\\")))
  (setq donef (strcat tmp "cmic_dl.txt"))
  (if (findfile donef) (vl-file-delete donef))
  (if (findfile path) (vl-file-delete path))
  (setq cmdline
    (strcat "/c curl.exe -s -k -L -H \"User-Agent: CADMAP/ic\""
            " -o \"" path "\" \"" url "\""
            " & echo ok > \"" donef "\""))
  (vl-catch-all-apply '(lambda () (startapp "cmd.exe" cmdline)))
  (setq i 0)
  (while (and (< i 900) (not (findfile donef)))
    (cm:sleep 200)
    (setq i (1+ i)))
  (and (findfile path) (> (vl-file-size path) 0)))

'''

HTTP_OLD = '''(defun cm:http (method url body / r)
  ;; ServerXMLHTTP → WinHttp → curl.exe 3단 폴백
  (setq r (cm:http-sxh method url body))
  (if (and (listp r) (numberp (car r)) (> (car r) 0))
    r
    (progn
      (setq r (cm:http-winhttp method url body))
      (if (and (listp r) (numberp (car r)) (> (car r) 0))
        r
        (cm:http-curl method url body)))))'''

HTTP_NEW = '''(defun cm:ok (r) (and (listp r) (numberp (car r)) (> (car r) 0)))

(defun cm:http (method url body / r)
  ;; ServerXMLHTTP → WinHttp → curl(WScript) → curl(startapp) 4단 폴백.
  ;; 앞의 셋은 COM 개체를 만들어야 하는데, AutoCAD 아닌 CAD 는 그것을
  ;; 못 하는 일이 있다. 마지막 길은 핵심 AutoLISP 만 쓰므로 어디서나 된다.
  (setq r (cm:http-sxh method url body))
  (if (cm:ok r) r
    (progn
      (setq r (cm:http-winhttp method url body))
      (if (cm:ok r) r
        (progn
          (setq r (cm:http-curl method url body))
          (if (cm:ok r) r
            (cm:http-startapp method url body)))))))'''


# ── 2. 색상표가 없을 때 ──────────────────────────────────────
COLOR_HELPER = r'''
;;; --- 색 고르기 (색상표가 없는 CAD 대비) ---
;;; acad_colordlg 는 AutoCAD 것이다. 없으면 목록에서 고르게 한다.
(defun cm:havecolor ()
  (if (car (atoms-family 1 '("ACAD_COLORDLG"))) T nil))

(defun cm:askcolor (cur / p id res names codes)
  (if (cm:havecolor)
    (acad_colordlg (atoi cur) nil)
    (progn
      (setq codes (mapcar 'car *cm:collist*)
            names (mapcar '(lambda (q) (strcat (cdr q) "  (" (car q) ")"))
                          *cm:collist*))
      (setq p (cm:dcl (list
        "cm_col : dialog {"
        "  label = \"색 고르기\";"
        "  : popup_list { key = \"c\"; width = 24; }"
        "  : row {"
        "    : button { key = \"accept\"; label = \"확인\"; is_default = true; width = 12; }"
        "    : button { key = \"cancel\"; label = \"취소\"; is_cancel = true; width = 12; }"
        "  }"
        "}")))
      (setq id (load_dialog p) res nil)
      (if (and (>= id 0) (new_dialog "cm_col" id))
        (progn
          (start_list "c") (foreach n names (add_list n)) (end_list)
          (set_tile "c" (itoa (cm:idx cur *cm:collist*)))
          (action_tile "accept"
            (strcat "(setq *cm:pick* (nth (atoi (get_tile \"c\")) '("
                    (cm:codes *cm:collist*) ")))(done_dialog 1)"))
          (action_tile "cancel" "(done_dialog 0)")
          (setq res (start_dialog))))
      (if (>= id 0) (unload_dialog id))
      (vl-file-delete p)
      (if (= res 1) (atoi *cm:pick*) nil))))

'''

COLOR_OLD_P = '''(defun cm:pickpcol ( / n)
  (if (setq n (acad_colordlg (atoi *cm:pcol*) nil))'''
COLOR_NEW_P = '''(defun cm:pickpcol ( / n)
  (if (setq n (cm:askcolor *cm:pcol*))'''
COLOR_OLD_T = '''(defun cm:picktcol ( / n)
  (if (setq n (acad_colordlg (atoi *cm:tcol*) nil))'''
COLOR_NEW_T = '''(defun cm:picktcol ( / n)
  (if (setq n (cm:askcolor *cm:tcol*))'''


def balanced(t: str) -> tuple[int, int]:
    """괄호가 맞는지. (남은깊이, 최상위폼수)"""
    i, n, depth, forms = 0, len(t), 0, 0
    while i < n:
        c = t[i]
        if c == ";":
            while i < n and t[i] != "\n":
                i += 1
            continue
        if c == '"':
            i += 1
            while i < n:
                if t[i] == "\\":
                    i += 2
                    continue
                if t[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth < 0:
                return -1, forms
            if depth == 0:
                forms += 1
        i += 1
    return depth, forms


def main() -> int:
    t = SRC.read_bytes().decode("cp949").replace("\r\n", "\n")
    ver = re.search(r'\(setq \*cm:version\*\s+"([^"]+)"\)', t).group(1)

    def sub1(old: str, new: str, why: str) -> None:
        nonlocal t
        if t.count(old) != 1:
            raise SystemExit(f"[{why}] 앵커가 {t.count(old)}개 - 원본이 바뀌었다")
        t = t.replace(old, new, 1)

    # 통신
    sub1(HTTP_OLD, HTTP_NEW, "http 폴백")
    sub1(";;; --- 파일 전체 읽기 ---",
         HTTP_FREE.strip() + "\n\n;;; --- 파일 전체 읽기 ---", "http 무ActiveX")
    sub1('''  ;; 실패 시 WinHttp 폴백
  (if (not ok)
    (setq ok (cm:download-winhttp url path)))
  ok)''',
         '''  ;; 실패 시 WinHttp -> startapp 폴백
  (if (not ok) (setq ok (cm:download-winhttp url path)))
  (if (not ok) (setq ok (cm:download-startapp url path)))
  ok)''', "내려받기 폴백")

    # 색
    sub1(";;; --- 색 고르기 (색상표가 없는 CAD 대비) ---".replace(";;; ", "@@NEVER@@")
         if False else "(defun cm:pickpcol ( / n)",
         COLOR_HELPER.strip() + "\n\n(defun cm:pickpcol ( / n)", "색 도우미")
    sub1(COLOR_OLD_P, COLOR_NEW_P, "필지선 색")
    sub1(COLOR_OLD_T, COLOR_NEW_T, "글자 색")

    # 판 번호
    sub1(f'(setq *cm:version* "{ver}")', f'(setq *cm:version* "{ver}-ic")', "판 번호")

    # 시작 알림에 어느 판인지
    sub1('(cm:msg (strcat "  지적도 DXF 가져오기  " *cm:version*\n'
         '                "   (주)경성엔지니어링"))',
         '(cm:msg (strcat "  지적도 DXF 가져오기  " *cm:version*\n'
         '                "   (주)경성엔지니어링"))\n'
         '(cm:msg "    * AutoCAD 아닌 CAD 용입니다. 이상하면 지적도점검 을 쳐 주세요.")',
         "시작 알림")

    depth, forms = balanced(t)
    if depth != 0:
        raise SystemExit(f"!! 괄호가 맞지 않는다 (남은 깊이 {depth})")
    print(f"괄호 검사 통과 - 최상위 폼 {forms}개, {len(t.splitlines())}줄")

    for fn in ("cm:http-startapp", "cm:download-startapp", "cm:sleep",
               "cm:askcolor", "cm:havecolor"):
        if f"(defun {fn}" not in t:
            raise SystemExit(f"!! {fn} 가 없다")
    if "acad_colordlg" in t and "cm:havecolor" not in t:
        raise SystemExit("!! 색상표 대체가 안 걸렸다")
    print("정의 확인 통과")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw = t.replace("\n", "\r\n").encode("cp949")
    OUT_LSP.write_bytes(raw)

    (OUT_DIR / "version.json").write_text(json.dumps({
        "version": f"{ver}-ic",
        "notice": "AutoCAD 아닌 CAD(캐디안 등)용 시험판입니다.",
        "min_version": "0.0.0",
        "files": {"lisp": "/dist/cadian/CADMAP.lsp"},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (OUT_DIR / "설치방법.txt").write_text(f'''캐디안 등 AutoCAD 아닌 CAD 에서 쓰기  ({ver}-ic)

이 판은 아직 실제 캐디안에서 검증하지 못했습니다. 되는지부터
확인해 주십시오.

1. CADMAP.lsp 를 아무 폴더에나 둡니다.
   (보기)  C:\\KS지적도\\CADMAP.lsp

2. CAD 를 켜고 APPLOAD 명령으로 그 파일을 불러옵니다.
   명령창에 아래처럼 쳐도 됩니다.
       (load "C:/KS지적도/CADMAP.lsp")
   경로의 \\ 는 / 로 바꿔 적으셔야 합니다.

3. 명령창에  지적도점검  을 칩니다.
   되는 것과 안 되는 것을 알려 줍니다.
   그 내용을 그대로 알려 주시면 맞춰 고쳐 드립니다.

4. 판정이 "쓰실 수 있습니다" 로 나오면  지적도삽입  으로 씁니다.

켤 때마다 저절로 불리게 하려면 APPLOAD 창의 "시작 세트"에 넣으십시오.

문의  (주)경성엔지니어링   https://ks-down-map.com
''', encoding="utf-8")

    h = hashlib.sha256(raw).hexdigest()[:12]
    print(f"\n캐디안용 {ver}-ic   {len(raw):,} bytes   sha256 {h}")
    print(f"  {OUT_LSP}")
    print(f"  원본은 {ver} 그대로 (건드리지 않음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
