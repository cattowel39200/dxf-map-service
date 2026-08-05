;;; ==========================================================================
;;;  CADMAP.LSP - 지적도 / 지형도 DXF 가져오기
;;;
;;;  AutoCAD 안에서 영역을 지정하면 서버에서 해당 범위의 연속지적도와
;;;  지형 자료를 받아 현재 도면에 삽입한다.
;;;
;;;  명령어
;;;    지적도       (DXFMAP)   두 점으로 영역을 지정해 도면 가져오기
;;;    지도설정     (MAPCFG)   좌표계 / 발급키 / 서버 주소 설정
;;;    발급키       (CMKEY)    발급키 등록 및 확인
;;;    좌표         (PTLABEL)  클릭한 점의 좌표를 도면에 기입
;;;    지적도업데이트 (CMUPDATE) 새 버전 내려받기
;;;    지적도홈     (CMHOME)   홈페이지 열기
;;;
;;;  쓰기 전에
;;;    1. 홈페이지에서 사용 신청을 하면 메일로 발급키가 온다
;;;    2. 발급키 명령으로 키를 등록한다 (한 번만 하면 된다)
;;;    3. 도면 좌표계를 출력 좌표계와 맞춘다 (지도설정)
;;;
;;;  발급키는 PC 한 대에만 등록된다. PC 를 바꾸시려면 관리자에게 문의.
;;; ==========================================================================

(vl-load-com)

;; --------------------------------------------------------------- 기본 설정
;; 서버 주소 고정 (로드 시마다 강제 설정)
(setq *cm:server* "https://ks-down-map.com")
(if (not *cm:crs*)      (setq *cm:crs*      "5187"))
;; 지적도 전용 (필지경계+지번지목)
(setq *cm:layers* "parcel,pnu")
(if (not *cm:interval*) (setq *cm:interval* 5.0))
(if (not *cm:explode*)  (setq *cm:explode*  T))
;; 1회 추출 한도 고정 (km2)
(setq *cm:limit* 1.0)
;; 이 파일의 판. 서버 version.json 과 견주어 업데이트를 알린다.
(setq *cm:version* "1.1.0")

(setq *cm:crslist*
  '(("5186"  . "중부원점 (세계측지계)")
    ("5185"  . "서부원점 (세계측지계)")
    ("5187"  . "동부원점 (세계측지계)")
    ("5188"  . "동해원점 (세계측지계)")
    ("5179"  . "UTM-K 단일원점")
    ("5174"  . "중부원점 (구 지적)")
    ("32652" . "UTM 52N")))

;; 삽입한 도면에 입힐 값. 설정창에서 바꾸면 레지스트리에 남는다.
(if (not *cm:plyr*)   (setq *cm:plyr*   "지적도선"))
(if (not *cm:pcol*)   (setq *cm:pcol*   "1"))
(if (not *cm:tlyr*)   (setq *cm:tlyr*   "지적도문자"))
(if (not *cm:tcol*)   (setq *cm:tcol*   "2"))
(if (not *cm:tsize*)  (setq *cm:tsize*  2.5))
(if (not *cm:tstyle*) (setq *cm:tstyle* "AN_XLS"))

;; 서버가 만들어 주는 원래 레이어 이름. 후처리로 사용자 이름으로 바꾼다.
(setq *cm:srclyr* "D-PARCEL"
      *cm:srctxt* "D-PNU-TEXT")

(setq *cm:collist*
  '(("1"   . "빨강")   ("2"   . "노랑")   ("3"   . "초록")
    ("4"   . "하늘")   ("5"   . "파랑")   ("6"   . "자주")
    ("7"   . "흰색")   ("8"   . "진회색") ("9"   . "연회색")
    ("30"  . "주황")   ("140" . "청록")   ("214" . "연보라")))

;; --------------------------------------------------------------- 보조 함수
(defun cm:normsrv (s)
  ;; 서버 주소 끝의 / 제거 (이중 슬래시 405 방지)
  (while (and s (> (strlen s) 1)
              (= (substr s (strlen s) 1) "/"))
    (setq s (substr s 1 (1- (strlen s)))))
  s)

(defun cm:msg (s) (princ (strcat "\n" s)) (princ))

(defun cm:crsname (code / hit)
  (if (setq hit (assoc code *cm:crslist*)) (cdr hit) code))

;; --------------------------------------------------------------- 좌표 설정 팝업
(defun cm:Dialog (licnote / p id res names codes cols colnames styles)
  (setq codes    (mapcar 'car *cm:crslist*)
        names    (mapcar '(lambda (q) (strcat "EPSG:" (car q) "  " (cdr q)))
                         *cm:crslist*)
        cols     (mapcar 'car *cm:collist*)
        colnames (mapcar '(lambda (q) (strcat (cdr q) " (" (car q) ")")) *cm:collist*)
        styles   (cm:styles))

  (setq p (cm:dcl (list
    "cm_ins : dialog {"
    "  label = \"지적도 삽입\";"
    "  : boxed_row {"
    "    label = \"출력 좌표계\";"
    "    : popup_list { key = \"crs\"; width = 40; }"
    "  }"
    "  : boxed_column {"
    "    label = \"필지선\";"
    "    : row {"
    "      : edit_box   { key = \"plyr\"; label = \"레이어명\"; edit_width = 14; }"
    "      : popup_list { key = \"pcol\"; label = \"색상\";     width = 13; }"
    "    }"
    "  }"
    "  : boxed_column {"
    "    label = \"지번 글자\";"
    "    : row {"
    "      : edit_box   { key = \"tsize\";  label = \"크기\";   edit_width = 8; }"
    "      : popup_list { key = \"tstyle\"; label = \"스타일\"; width = 18; }"
    "    }"
    "    : row {"
    "      : edit_box   { key = \"tlyr\"; label = \"레이어명\"; edit_width = 14; }"
    "      : popup_list { key = \"tcol\"; label = \"색상\";     width = 13; }"
    "    }"
    "  }"
    "  : text { key = \"note\"; label = \"\"; }"
    "  : row {"
    "    : button { key = \"accept\"; label = \"영역선택\"; is_default = true; width = 14; }"
    "    : button { key = \"cancel\"; label = \"닫기\"; is_cancel = true; width = 14; }"
    "  }"
    "}")))

  (setq id (load_dialog p) res nil)
  (if (or (< id 0) (not (new_dialog "cm_ins" id)))
    (alert "설정 창을 열 수 없습니다.")
    (progn
      (start_list "crs")    (foreach n names    (add_list n)) (end_list)
      (start_list "pcol")   (foreach n colnames (add_list n)) (end_list)
      (start_list "tcol")   (foreach n colnames (add_list n)) (end_list)
      (start_list "tstyle") (foreach n styles   (add_list n)) (end_list)

      (set_tile "crs"    (itoa (cm:idx *cm:crs*  *cm:crslist*)))
      (set_tile "pcol"   (itoa (cm:idx *cm:pcol* *cm:collist*)))
      (set_tile "tcol"   (itoa (cm:idx *cm:tcol* *cm:collist*)))
      (set_tile "tstyle" (itoa (cm:n (vl-position *cm:tstyle* styles) 0)))
      (set_tile "plyr"  *cm:plyr*)
      (set_tile "tlyr"  *cm:tlyr*)
      (set_tile "tsize" (rtos *cm:tsize* 2 2))
      (set_tile "note"  (cm:n licnote ""))

      (action_tile "accept"
        (strcat
          "(setq *cm:crs*    (nth (atoi (get_tile \"crs\"))    '(" (cm:codes *cm:crslist*) ")))"
          "(setq *cm:pcol*   (nth (atoi (get_tile \"pcol\"))   '(" (cm:codes *cm:collist*) ")))"
          "(setq *cm:tcol*   (nth (atoi (get_tile \"tcol\"))   '(" (cm:codes *cm:collist*) ")))"
          "(setq *cm:tstyle* (nth (atoi (get_tile \"tstyle\")) '(" (cm:strs styles) ")))"
          "(setq *cm:plyr*  (cm:lname (get_tile \"plyr\")  \"지적도선\"))"
          "(setq *cm:tlyr*  (cm:lname (get_tile \"tlyr\")  \"지적도문자\"))"
          "(setq *cm:tsize* (cm:posnum (get_tile \"tsize\") *cm:tsize*))"
          "(done_dialog 1)"))
      (action_tile "cancel" "(done_dialog 0)")
      (setq res (start_dialog))))

  (if (>= id 0) (unload_dialog id))
  (vl-file-delete p)
  (if (= res 1) (cm:save))
  (= res 1))

;; rtos 는 도면 단위 설정을 타므로 통신용 숫자는 이 함수로 만든다
(defun cm:num (v) (rtos v 2 6))

(defun cm:jstr (json key / tag p q)
  (setq tag (strcat "\"" key "\":\""))
  (if (and json (setq p (vl-string-search tag json)))
    (progn
      (setq p (+ p (strlen tag)))
      (setq q (vl-string-search "\"" json p))
      (if q (substr json (1+ p) (- q p))))))

(defun cm:jnum (json key / tag p q ch s)
  (setq tag (strcat "\"" key "\":"))
  (if (and json (setq p (vl-string-search tag json)))
    (progn
      (setq p (+ p (strlen tag)) q p s "")
      (while (and (< q (strlen json))
                  (setq ch (substr json (1+ q) 1))
                  (member ch '("0" "1" "2" "3" "4" "5" "6" "7" "8" "9"
                               "." "-" "e" "E" "+")))
        (setq s (strcat s ch) q (1+ q)))
      (if (> (strlen s) 0) (atof s)))))

(defun cm:n (v d) (if v v d))

;; "a, b ,c" -> "\"a\",\"b\",\"c\""
(defun cm:quotelist (s / out cur i ch)
  (setq out "" cur "" i 0)
  (repeat (strlen s)
    (setq i (1+ i) ch (substr s i 1))
    (cond
      ((= ch ",")
       (if (/= cur "")
         (setq out (strcat out (if (= out "") "" ",") "\"" cur "\"")))
       (setq cur ""))
      ((/= ch " ") (setq cur (strcat cur ch)))))
  (if (/= cur "")
    (setq out (strcat out (if (= out "") "" ",") "\"" cur "\"")))
  out)

;; --------------------------------------------------------------- 설정창 도구
(defun cm:dcl (lines / p f)
  ;; 줄 목록으로 임시 DCL 파일을 만들고 그 경로를 돌려준다.
  (setq p (vl-filename-mktemp "cmdlg_" nil ".dcl") f (open p "w"))
  (foreach l lines (write-line l f))
  (close f)
  p)

(defun cm:codes (alist)
  ;; 팝업 목록에서 고른 자리를 코드로 되돌리기 위한 LISP 목록 글자
  (apply 'strcat (mapcar '(lambda (k) (strcat "\"" (car k) "\" ")) alist)))

(defun cm:strs (lst)
  (apply 'strcat (mapcar '(lambda (k) (strcat "\"" k "\" ")) lst)))

(defun cm:idx (code alist / i)
  (setq i (vl-position (assoc code alist) alist))
  (if i i 0))

(defun cm:posnum (s d / v)
  ;; 글자를 양수로. 빈칸이나 0 이하이면 원래 값을 그대로 둔다.
  (setq v (atof s))
  (if (> v 0) v d))

(defun cm:lname (s d / out i ch)
  ;; 레이어 이름에 쓸 수 없는 글자를 걸러 낸다. 남는 게 없으면 원래 값.
  (setq out "" i 0)
  (repeat (strlen s)
    (setq i (1+ i) ch (substr s i 1))
    (if (not (vl-string-search ch "<>/\\\":;?*|,='`")) (setq out (strcat out ch))))
  (while (and (> (strlen out) 0) (= (substr out 1 1) " "))
    (setq out (substr out 2)))
  (while (and (> (strlen out) 0) (= (substr out (strlen out) 1) " "))
    (setq out (substr out 1 (1- (strlen out)))))
  (if (= out "") d out))

(defun cm:styles ( / e n out)
  ;; 지금 도면에 있는 글자 스타일 이름을 모은다.
  (setq out '() e (tblnext "STYLE" T))
  (while e
    (setq n (cdr (assoc 2 e)))
    (if (and n (/= n "")) (setq out (cons n out)))
    (setq e (tblnext "STYLE")))
  (setq out (reverse out))
  ;; 저장해 둔 스타일이 이 도면에 없더라도 목록에는 보여 준다.
  (if (and *cm:tstyle* (not (member *cm:tstyle* out)))
    (setq out (cons *cm:tstyle* out)))
  (if out out (list "Standard")))

;; --------------------------------------------------------------- 글 상자
(defun cm:textbox (title lines / p id)
  ;; 여러 줄을 읽기만 하는 창. 줄이 많아도 스크롤된다.
  (setq p (cm:dcl (list
    "cm_txt : dialog {"
    (strcat "  label = \"" title "\";")
    "  : list_box { key = \"body\"; width = 74; height = 22; }"
    "  : row { : button { key = \"accept\"; label = \"닫기\";"
    "           is_default = true; is_cancel = true; width = 14; } }"
    "}")))
  (setq id (load_dialog p))
  (if (and (>= id 0) (new_dialog "cm_txt" id))
    (progn
      (start_list "body")
      (foreach l lines (add_list l))
      (end_list)
      (action_tile "accept" "(done_dialog 0)")
      (start_dialog)))
  (if (>= id 0) (unload_dialog id))
  (vl-file-delete p)
  (princ))

;; --------------------------------------------------------------- HTTP 통신
(defun cm:http (method url body / r)
  ;; ServerXMLHTTP → WinHttp → curl.exe 3단 폴백
  (setq r (cm:http-sxh method url body))
  (if (and (listp r) (numberp (car r)) (> (car r) 0))
    r
    (progn
      (setq r (cm:http-winhttp method url body))
      (if (and (listp r) (numberp (car r)) (> (car r) 0))
        r
        (cm:http-curl method url body)))))

;;; --- 파일 전체 읽기 ---
(defun cm:readfile (f / fp line all)
  (setq all "")
  (setq fp (open f "r"))
  (if fp
    (progn
      (while (setq line (read-line fp))
        (setq all (if (= all "") line (strcat all "\n" line))))
      (close fp)))
  all)

;;; --- 숨김 동기 실행 (WScript.Shell.Run) ---
(defun cm:runhidden (cmdline / wsh r ok)
  (setq wsh (vl-catch-all-apply 'vlax-create-object (list "WScript.Shell")))
  (if (vl-catch-all-error-p wsh)
    nil
    (progn
      (setq r (vl-catch-all-apply
                '(lambda () (vlax-invoke wsh 'Run cmdline 0 :vlax-true))))
      (setq ok (not (vl-catch-all-error-p r)))
      (vlax-release-object wsh)
      ok)))

;;; --- curl.exe 경유 (TLS1.2/1.3, Cloudflare 연결용) ---
(defun cm:http-curl (method url body / tmp bodyf respf codef f cmdline code txt)
  (setq tmp (getvar "TEMPPREFIX"))
  (if (or (null tmp) (= tmp "")) (setq tmp (strcat (getenv "TEMP") "\\")))
  (setq bodyf (strcat tmp "cm_body.json")
        respf (strcat tmp "cm_resp.json")
        codef (strcat tmp "cm_code.txt"))
  (if (findfile respf) (vl-file-delete respf))
  (if (findfile codef) (vl-file-delete codef))
  ;; body 파일
  (if body
    (progn (setq f (open bodyf "w")) (princ body f) (close f)))
  ;; curl 명령 (-k SSL무시, -w http_code, -o body)
  (setq cmdline
    (strcat "cmd /c curl -s -k -X " method
            " -H \"Content-Type: application/json\" -H \"User-Agent: CADMAP/1.0\""
            (if body (strcat " --data-binary @\"" bodyf "\"") "")
            " -w \"%{http_code}\" -o \"" respf "\""
            " \"" url "\" > \"" codef "\""))
  (cm:runhidden cmdline)
  (setq code 0 txt nil)
  (if (findfile codef) (setq code (atoi (cm:readfile codef))))
  (if (findfile respf) (setq txt (cm:readfile respf)))
  (list (cond ((> code 0) code) (txt 200) (T 0)) txt))

;;; --- ServerXMLHTTP (TLS 1.2 기본 지원) ---
(defun cm:http-sxh (method url body / h txt st err)
  (setq txt nil st 0)
  (setq h (vl-catch-all-apply
            'vlax-create-object (list "MSXML2.ServerXMLHTTP.6.0")))
  (if (vl-catch-all-error-p h)
    (list 0 nil)
    (progn
      (setq err
        (vl-catch-all-apply
          '(lambda ()
             (vlax-invoke h 'setTimeouts 8000 8000 30000 180000)
             (vlax-invoke h 'open method url :vlax-false)
             ;; 인증서 오류 무시 (SXH_SERVER_CERT_IGNORE_ALL = 13056)
             (vl-catch-all-apply '(lambda () (vlax-invoke h 'setOption 2 13056)))
             (vlax-invoke h 'setRequestHeader "User-Agent" "CADMAP/1.0")
             (vlax-invoke h 'setRequestHeader "Content-Type" "application/json")
             (if body (vlax-invoke h 'send body) (vlax-invoke h 'send))
             (setq st (vlax-get h 'status) txt (vlax-get h 'responseText)))))
      (vlax-release-object h)
      (if (vl-catch-all-error-p err) (list 0 nil) (list st txt)))))

;;; --- WinHttp (폴백) ---
(defun cm:http-winhttp (method url body / h txt st err)
  (setq txt nil st 0)
  (setq h (vl-catch-all-apply
            'vlax-create-object (list "WinHttp.WinHttpRequest.5.1")))
  (if (vl-catch-all-error-p h)
    (list 0 nil)
    (progn
      (setq err
        (vl-catch-all-apply
          '(lambda ()
             (vlax-invoke h 'SetTimeouts 8000 8000 30000 180000)
             (vlax-invoke h 'Open method url :vlax-false)
             (vl-catch-all-apply '(lambda () (vlax-put-property h 'Option 9 10880)))
             (vl-catch-all-apply '(lambda () (vlax-put-property h 'Option 4 13056)))
             (vlax-invoke h 'SetRequestHeader "User-Agent" "CADMAP/1.0")
             (vlax-invoke h 'SetRequestHeader "Content-Type" "application/json")
             (if body (vlax-invoke h 'Send body) (vlax-invoke h 'Send))
             (setq st (vlax-get h 'Status) txt (vlax-get h 'ResponseText)))))
      (vlax-release-object h)
      (if (vl-catch-all-error-p err) (list 0 nil) (list st txt)))))

(defun cm:alive ( / r st)
  ;; 원격 서버 응답 확인 (GET /)
  (setq r (vl-catch-all-apply 'cm:http (list "GET" *cm:server* nil)))
  (if (vl-catch-all-error-p r)
    nil
    (progn (setq st (car r)) (and (numberp st) (> st 0)))))

(defun cm:ensure-server ( / )
  (setq *cm:server* (cm:normsrv *cm:server*))
  ;; 원격 서버 연결 확인 (실패해도 경고만 하고 진행 - 실제 통신은 요청 시)
  (if (cm:alive)
    (cm:msg "지도 서버 연결 확인.")
    (cm:msg (strcat "서버 사전 확인 실패(무시하고 진행): " *cm:server*)))
  T)

(defun cm:download (url path / cmdline ok)
  ;; curl.exe 로 바이너리 다운로드 (TLS 1.2/1.3, Cloudflare 대응)
  (setq ok nil)
  (if (findfile path) (vl-file-delete path))
  (setq cmdline
    (strcat "cmd /c curl -s -k -L"
            " -H \"User-Agent: CADMAP/1.0\""
            " -o \"" path "\""
            " \"" url "\""))
  (cm:runhidden cmdline)
  ;; 파일 생성 + 크기 확인
  (if (and (findfile path)
           (> (vl-file-size path) 0))
    (setq ok T))
  ;; 실패 시 WinHttp 폴백
  (if (not ok)
    (setq ok (cm:download-winhttp url path)))
  ok)

(defun cm:download-winhttp (url path / h ok stream err)
  (setq ok nil)
  (setq h (vl-catch-all-apply
            'vlax-create-object (list "WinHttp.WinHttpRequest.5.1")))
  (if (vl-catch-all-error-p h)
    nil
    (progn
      (setq err
        (vl-catch-all-apply
          '(lambda ()
             (vlax-invoke h 'SetTimeouts 8000 8000 30000 180000)
             (vlax-invoke h 'Open "GET" url :vlax-false)
             (vlax-invoke h 'Send)
             (if (= (vlax-get h 'Status) 200)
               (progn
                 (setq stream (vlax-create-object "ADODB.Stream"))
                 (vlax-put stream 'Type 1)
                 (vlax-invoke stream 'Open)
                 (vlax-invoke stream 'Write (vlax-get h 'ResponseBody))
                 (vlax-invoke stream 'SaveToFile path 2)
                 (vlax-invoke stream 'Close)
                 (vlax-release-object stream)
                 (setq ok T))))))
      (vlax-release-object h)
      (if (vl-catch-all-error-p err) nil ok))))

;; ====================================================== 설정 저장 (레지스트리)
;; 좌표계와 발급키를 PC 에 남겨, 다음에 켤 때 다시 넣지 않아도 되게 한다.
(setq *cm:reg* "HKEY_CURRENT_USER\\Software\\KyoungsungEng\\CADMAP")

(defun cm:regget (name dflt / v)
  (setq v (vl-catch-all-apply 'vl-registry-read (list *cm:reg* name)))
  (if (or (vl-catch-all-error-p v) (null v) (= v "")) dflt v))

(defun cm:regput (name val)
  (vl-catch-all-apply 'vl-registry-write (list *cm:reg* name val))
  val)

(defun cm:save ( / )
  (cm:regput "Crs"    *cm:crs*)
  (cm:regput "Server" *cm:server*)
  (cm:regput "PLyr"   *cm:plyr*)
  (cm:regput "PCol"   *cm:pcol*)
  (cm:regput "TLyr"   *cm:tlyr*)
  (cm:regput "TCol"   *cm:tcol*)
  (cm:regput "TSize"  (rtos *cm:tsize* 2 4))
  (cm:regput "TStyle" *cm:tstyle*)
  T)

(defun cm:load ( / v)
  (setq *cm:key* (cm:regget "Key" ""))
  (setq v (cm:regget "Crs" nil))
  (if (and v (assoc v *cm:crslist*)) (setq *cm:crs* v))
  (setq *cm:plyr*   (cm:regget "PLyr"   *cm:plyr*)
        *cm:pcol*   (cm:regget "PCol"   *cm:pcol*)
        *cm:tlyr*   (cm:regget "TLyr"   *cm:tlyr*)
        *cm:tcol*   (cm:regget "TCol"   *cm:tcol*)
        *cm:tstyle* (cm:regget "TStyle" *cm:tstyle*))
  (setq *cm:tsize* (cm:posnum (cm:regget "TSize" "") *cm:tsize*))
  ;; 삽입한 것을 후처리해야 하므로 분해는 늘 한다.
  (setq *cm:explode* T)
  T)

;; ====================================================== PC 지문
;; 서버는 발급키를 PC 한 대에 묶는다. 그 PC 를 가리키는 짧은 번호를 만든다.
;; 컴퓨터이름·사용자이름·C드라이브 일련번호를 섞어 숫자로 줄인다.
;; 한글 이름이 섞여도 통신에 문제가 없도록 결과는 영문·숫자만 남긴다.
(defun cm:hash (s seed mul / h i c)
  (setq h (float seed) i 0)
  (repeat (strlen s)
    (setq i (1+ i)
          c (ascii (substr s i 1))
          h (rem (+ (* h mul) c) 2147483647.0)))
  (itoa (fix h)))

(defun cm:volser ( / fso drv v)
  (setq v "")
  (setq fso (vl-catch-all-apply 'vlax-create-object
                                (list "Scripting.FileSystemObject")))
  (if (not (vl-catch-all-error-p fso))
    (progn
      (setq drv (vl-catch-all-apply '(lambda () (vlax-invoke fso 'GetDrive "C:"))))
      (if (not (vl-catch-all-error-p drv))
        (progn
          (setq v (vl-catch-all-apply '(lambda () (vlax-get drv 'SerialNumber))))
          (setq v (if (vl-catch-all-error-p v) "" (vl-princ-to-string v)))
          (vl-catch-all-apply 'vlax-release-object (list drv))))
      (vl-catch-all-apply 'vlax-release-object (list fso))))
  v)

(defun cm:machine ( / raw)
  (if (not *cm:machine*)
    (progn
      (setq raw (strcat (cm:n (getenv "COMPUTERNAME") "?") "|"
                        (cm:n (getenv "USERNAME") "?") "|"
                        (cm:volser)))
      (setq *cm:machine*
            (strcat "M" (cm:hash raw 5381 131) "-" (cm:hash raw 7919 37)))))
  *cm:machine*)

;; ====================================================== 발급키
(defun cm:strip (s / out i ch)
  (setq out "" i 0)
  (repeat (strlen s)
    (setq i (1+ i) ch (substr s i 1))
    (if (and (/= ch " ") (/= ch "\t")) (setq out (strcat out ch))))
  out)

(defun cm:setkey (k)
  (setq *cm:key* (strcase (cm:strip (cm:n k ""))))
  (cm:regput "Key" *cm:key*)
  *cm:key*)

(defun cm:licnote (txt / kind days)
  (setq kind (cm:n (cm:jstr txt "kind") "")
        days (cm:jnum txt "days_left"))
  (cond
    ((= kind "full") "정품")
    (days (strcat "데모 " (rtos days 2 0) "일 남음"))
    (T "사용 가능")))

;; 서버에 발급키를 물어본다.  (T . 안내문) 또는 (nil . 사유) 를 돌려준다.
;; 확인은 서버에서만 하므로 파일을 복사해도 다른 PC 에서는 열리지 않는다.
(defun cm:license ( / body res txt)
  (if (= (cm:n *cm:key* "") "")
    (cons nil "발급키가 없습니다.  발급키 명령으로 등록해 주세요.")
    (progn
      (setq body (strcat "{\"key\":\"" *cm:key* "\","
                         "\"machine\":\"" (cm:machine) "\"}"))
      (setq res (cm:http "POST" (strcat *cm:server* "/api/license/check") body)
            txt (cadr res))
      (cond
        ((null txt)
         (cons nil "서버에 연결할 수 없어 발급키를 확인하지 못했습니다."))
        ((vl-string-search "\"ok\":true" txt)
         (cons T (cm:licnote txt)))
        (T (cons nil (cm:n (cm:jstr txt "reason")
                           "사용할 수 없는 발급키입니다.")))))))

(defun C:CMKEY ( / k cur r)
  (setq cur (cm:n *cm:key* ""))
  (cm:msg "===== 발급키 =====")
  (cm:msg (strcat "  등록된 키 : " (if (= cur "") "없음" cur)))
  (cm:msg (strcat "  이 PC 번호 : " (cm:machine)))
  (cm:msg (strcat "  신청하기   : " *cm:server* "/cad"))
  (setq k (getstring T "\n발급키 (KS-XXXX-XXXX-XXXX, 그냥 엔터면 그대로): "))
  (if (/= k "") (cm:setkey k))
  (if (= (cm:n *cm:key* "") "")
    (cm:msg "등록된 발급키가 없습니다.")
    (progn
      (cm:msg "서버에 확인하는 중...")
      (setq r (cm:license))
      (if (car r)
        (cm:msg (strcat "확인되었습니다.  " (cdr r)))
        (cm:msg (strcat "쓸 수 없습니다.  " (cdr r))))))
  (princ))

;; ====================================================== 자동 업데이트
(defun cm:verinfo ( / res)
  (setq res (cm:http "GET"
              (strcat *cm:server* "/api/cad/version?current=" *cm:version*) nil))
  (cadr res))

(defun cm:today () (itoa (fix (getvar "DATE"))))

;; quiet 이면 새 버전이 있을 때만 알린다 (켤 때 하루 한 번 부른다)
(defun cm:checkupdate (quiet / txt latest note)
  (setq txt (vl-catch-all-apply 'cm:verinfo nil))
  (if (or (vl-catch-all-error-p txt) (null txt))
    (progn (if (not quiet) (cm:msg "업데이트 정보를 확인하지 못했습니다.")) nil)
    (progn
      (setq latest (cm:n (cm:jstr txt "version") "")
            note   (cm:jstr txt "notice"))
      (cond
        ((vl-string-search "\"update\":true" txt)
         (cm:msg (strcat "새 버전 " latest " 이 나왔습니다.  (지금 "
                         *cm:version* ")"))
         (if note (cm:msg (strcat "   " note)))
         (cm:msg "   지적도업데이트  를 치시면 받아집니다.")
         T)
        (T (if (not quiet)
             (cm:msg (strcat "최신 버전입니다.  " *cm:version*)))
           nil)))))

(defun C:CMUPDATE ( / txt latest url path new bak)
  (cm:msg "업데이트를 확인하는 중...")
  (setq txt (vl-catch-all-apply 'cm:verinfo nil))
  (cond
    ((or (vl-catch-all-error-p txt) (null txt))
     (cm:msg "서버에 연결할 수 없습니다."))
    ((not (vl-string-search "\"update\":true" txt))
     (cm:msg (strcat "이미 최신 버전입니다.  " *cm:version*)))
    (T
     (setq latest (cm:n (cm:jstr txt "version") "")
           url    (strcat *cm:server* (cm:n (cm:jstr txt "url") "/dist/CADMAP.lsp"))
           path   (cm:regget "Path" nil))
     (if (or (null path) (not (findfile path)))
       (setq path (findfile "CADMAP.lsp")))
     (cond
       ((null path)
        (cm:msg "설치된 CADMAP.lsp 를 찾지 못했습니다.")
        (cm:msg (strcat "   홈페이지에서 직접 받아 주세요.  " *cm:server* "/cad")))
       (T
        (setq new (strcat path ".new") bak (strcat path ".bak"))
        (cm:msg (strcat "새 버전 " latest " 을 내려받는 중..."))
        (if (not (cm:download url new))
          (cm:msg "내려받지 못했습니다. 홈페이지에서 직접 받아 주세요.")
          (progn
            (if (findfile bak) (vl-file-delete bak))
            (vl-file-rename path bak)
            (if (vl-file-rename new path)
              (progn
                (cm:msg (strcat "업데이트를 마쳤습니다.  "
                                *cm:version* " -> " latest))
                (cm:msg "AutoCAD 를 다시 켜면 새 버전으로 바뀝니다."))
              (progn
                (vl-file-rename bak path)
                (vl-file-delete new)
                (cm:msg "파일을 바꾸지 못했습니다.")
                (cm:msg "   AutoCAD 를 끄고 다시 설치해 주세요.")))))))))
  (princ))

(defun C:CMHOME ( / u)
  (setq u (strcat *cm:server* "/cad"))
  (vl-catch-all-apply '(lambda () (startapp "explorer" u)))
  (cm:msg (strcat "홈페이지  " u))
  (princ))

;; --------------------------------------------------------------- 도움말
(defun C:CMHELP ( / )
  (cm:textbox "지적도 DXF 가져오기 - 도움말"
    (list
      "■ 무엇을 하는 프로그램인가"
      "   화면에서 두 점으로 네모를 그리면, 그 안의 연속지적도를"
      "   내려받아 지금 도면에 바로 넣어 줍니다."
      ""
      "■ 쓰는 순서"
      "   1. 메뉴 [지적도] - [지적도삽입] 을 누릅니다."
      "   2. 출력 좌표계를 고릅니다."
      "      지금 도면의 좌표계와 반드시 같아야 위치가 맞습니다."
      "   3. 필지선과 지번 글자의 레이어명·색상·크기·스타일을 정합니다."
      "   4. [영역선택] 을 누르고 화면에서 두 점을 찍습니다."
      "   5. 1~3분 뒤 도면에 들어오고, 정한 레이어로 자동 정리됩니다."
      "   6. 설정창이 다시 열립니다. 이어서 다른 곳도 받으실 수 있습니다."
      "      그만하시려면 [닫기] 를 누르십시오."
      ""
      "■ 설정은 저장됩니다"
      "   레이어명·색상·글자크기·스타일·좌표계는 이 PC 에 남습니다."
      "   AutoCAD 를 껐다 켜도 그대로입니다."
      ""
      "■ 한 번에 받을 수 있는 넓이"
      "   1회 1 km2 까지입니다. 넓은 곳은 나눠서 받으십시오."
      ""
      "■ 정품 신청 방법"
      "   1. 메뉴 [지적도] - [정품신청] 을 누릅니다."
      "   2. 창에 적힌 계좌로 입금하십시오."
      "      금액은 44,000원이며 부가세가 포함된 금액입니다."
      "   3. 입금하실 때 [보내는 분] 이름 자리에 창에 표시된"
      "      PC 번호를 그대로 넣어 주십시오."
      "      이름으로 넣으시면 누구의 입금인지 확인이 늦어집니다."
      "   4. 세금계산서가 필요하시면 [세금계산서] 를 켜고"
      "      사업자등록번호·상호·주소·업종을 적어 주십시오."
      "   5. [정품 신청하기] 를 누르면 접수됩니다."
      "   6. 입금이 확인되면 정품으로 바뀝니다. 다시 설치하실 필요 없습니다."
      ""
      "■ 주의하실 점"
      "   · 발급키는 PC 한 대에서만 쓸 수 있습니다."
      "     처음 쓰신 PC 에 묶이며, 다른 PC 에서는 열리지 않습니다."
      "   · PC 를 바꾸시거나 윈도우를 다시 까셨다면 30일 뒤"
      "     스스로 옮겨집니다. 그전에 옮기시려면 연락 주십시오."
      "   · 데모는 처음 실행한 때부터 3일간 쓰실 수 있습니다."
      "   · 인터넷이 연결되어 있어야 합니다."
      "   · 도면 좌표계가 다르면 엉뚱한 곳에 들어갑니다."
      "     좌표계를 먼저 확인하십시오."
      "   · 받은 자료는 연속지적도라 실제 경계와 다를 수 있습니다."
      "     경계 확정이나 측량 성과로는 쓰실 수 없습니다."
      ""
      "■ 문의"
      "   (주)경성엔지니어링    https://ks-down-map.com"))
  (princ))

;; --------------------------------------------------------------- 정품 신청
(defun cm:bizdlg ( / p id res)
  ;; 세금계산서에 필요한 사업자 정보를 받는다.
  (setq p (cm:dcl (list
    "cm_biz : dialog {"
    "  label = \"세금계산서 정보\";"
    "  : boxed_column {"
    "    label = \"사업자 정보\";"
    "    : edit_box { key = \"bno\";  label = \"사업자등록번호\"; edit_width = 22; }"
    "    : edit_box { key = \"bnm\";  label = \"상호        \";   edit_width = 30; }"
    "    : edit_box { key = \"badr\"; label = \"주소        \";   edit_width = 44; }"
    "    : edit_box { key = \"btp\";  label = \"업종        \";   edit_width = 30; }"
    "  }"
    "  : text { label = \"적어 주신 내용으로 세금계산서를 발행해 드립니다.\"; }"
    "  : row {"
    "    : button { key = \"accept\"; label = \"확인\"; is_default = true; width = 12; }"
    "    : button { key = \"cancel\"; label = \"취소\"; is_cancel = true; width = 12; }"
    "  }"
    "}")))
  (setq id (load_dialog p) res nil)
  (if (and (>= id 0) (new_dialog "cm_biz" id))
    (progn
      (set_tile "bno"  (cm:n *cm:bno* ""))
      (set_tile "bnm"  (cm:n *cm:bnm* ""))
      (set_tile "badr" (cm:n *cm:badr* ""))
      (set_tile "btp"  (cm:n *cm:btp* ""))
      (action_tile "accept"
        (strcat "(setq *cm:bno*  (get_tile \"bno\"))"
                "(setq *cm:bnm*  (get_tile \"bnm\"))"
                "(setq *cm:badr* (get_tile \"badr\"))"
                "(setq *cm:btp*  (get_tile \"btp\"))"
                "(done_dialog 1)"))
      (action_tile "cancel" "(done_dialog 0)")
      (setq res (start_dialog))))
  (if (>= id 0) (unload_dialog id))
  (vl-file-delete p)
  (= res 1))

(defun cm:buystate ( / res txt)
  ;; 서버에 지금 신청 상태를 물어본다.
  (setq res (cm:http "GET"
              (strcat *cm:server* "/api/purchase?key=" (cm:n *cm:key* "")) nil)
        txt (cadr res))
  (if txt
    (progn
      (if (cm:jstr txt "biz_no")   (setq *cm:bno*  (cm:jstr txt "biz_no")))
      (if (cm:jstr txt "biz_name") (setq *cm:bnm*  (cm:jstr txt "biz_name")))
      (if (cm:jstr txt "biz_addr") (setq *cm:badr* (cm:jstr txt "biz_addr")))
      (if (cm:jstr txt "biz_type") (setq *cm:btp*  (cm:jstr txt "biz_type")))
      (if (vl-string-search "\"want_invoice\":true" txt) (setq *cm:want* T))
      (vl-string-search "\"requested\":true" txt))))

(defun cm:buysend ( / body res txt)
  (setq body
    (strcat "{\"key\":\"" (cm:n *cm:key* "") "\","
            "\"machine\":\"" (cm:machine) "\","
            "\"want_invoice\":" (if *cm:want* "true" "false") ","
            "\"biz_no\":\""   (cm:n *cm:bno*  "") "\","
            "\"biz_name\":\"" (cm:n *cm:bnm*  "") "\","
            "\"biz_addr\":\"" (cm:n *cm:badr* "") "\","
            "\"biz_type\":\"" (cm:n *cm:btp*  "") "\"}"))
  (setq res (cm:http "POST" (strcat *cm:server* "/api/purchase") body)
        txt (cadr res))
  (cond
    ((null txt) (cons nil "서버에 연결할 수 없습니다."))
    ((vl-string-search "\"ok\":true" txt) (cons T ""))
    (T (cons nil (cm:n (cm:jstr txt "detail") "신청하지 못했습니다.")))))

(defun C:CMBUY ( / p id res sent r)
  (if (= (cm:n *cm:key* "") "")
    (progn
      (alert (strcat "먼저 발급키를 등록해 주세요.\n\n"
                     "홈페이지에서 사용 신청을 하시면 메일로 보내 드립니다.\n"
                     *cm:server* "/cad"))
      (princ))
    (progn
      (cm:msg "신청 상태를 확인하는 중...")
      (setq sent (cm:buystate))

      (setq p (cm:dcl (list
        "cm_buy : dialog {"
        "  label = \"정품 신청\";"
        "  : boxed_column {"
        "    label = \"구매 안내\";"
        "    : text { label = \"금 액     44,000 원   (부가세 포함)\"; }"
        "    : text { label = \"계 좌     농협  301-0019-9326-91\"; }"
        "    : text { label = \"예금주    안세종\"; }"
        "    : spacer { height = 0.4; }"
        "    : text { label = \"입금하실 때 [보내는 분] 이름 자리에\"; }"
        "    : text { label = \"아래 PC 번호를 그대로 넣어 주십시오.\"; }"
        "    : text { key = \"pc\"; label = \"\"; }"
        "  }"
        "  : boxed_column {"
        "    label = \"세금계산서\";"
        "    : toggle { key = \"want\"; label = \"세금계산서를 받겠습니다\"; }"
        "    : text { key = \"biz\"; label = \"\"; }"
        "    : button { key = \"bizbtn\"; label = \"사업자 정보 적기\"; width = 20; }"
        "  }"
        "  : text { key = \"state\"; label = \"\"; }"
        "  : row {"
        "    : button { key = \"accept\"; label = \"정품 신청하기\"; is_default = true; width = 18; }"
        "    : button { key = \"cancel\"; label = \"닫기\"; is_cancel = true; width = 12; }"
        "  }"
        "}")))

      (setq id (load_dialog p) res nil)
      (if (and (>= id 0) (new_dialog "cm_buy" id))
        (progn
          (set_tile "pc" (strcat "        PC 번호   " (cm:machine)))
          (set_tile "want" (if *cm:want* "1" "0"))
          (set_tile "biz" (cm:bizsummary))
          (set_tile "state"
            (if sent
              (strcat "정품신청중입니다.  입금자명 " (cm:machine))
              "입금 뒤 [정품 신청하기] 를 눌러 주십시오."))
          (action_tile "want" "(setq *cm:want* (= $value \"1\"))")
          (action_tile "bizbtn"
            "(if (cm:bizdlg) (progn (setq *cm:want* T) (set_tile \"want\" \"1\") (set_tile \"biz\" (cm:bizsummary))))")
          (action_tile "accept" "(done_dialog 1)")
          (action_tile "cancel" "(done_dialog 0)")
          (setq res (start_dialog))))
      (if (>= id 0) (unload_dialog id))
      (vl-file-delete p)

      (if (= res 1)
        (progn
          (if (and *cm:want* (= (cm:n *cm:bno* "") ""))
            (alert "세금계산서를 받으시려면 사업자등록번호가 있어야 합니다.\n[사업자 정보 적기] 를 눌러 적어 주십시오.")
            (progn
              (cm:msg "신청을 보내는 중...")
              (setq r (cm:buysend))
              (if (car r)
                (progn
                  (cm:msg "")
                  (cm:msg "===== 정품신청중 =====")
                  (cm:msg (strcat "  입금자명   " (cm:machine)))
                  (cm:msg  "  금 액      44,000 원 (부가세 포함)")
                  (cm:msg  "  계 좌      농협 301-0019-9326-91  예금주 안세종")
                  (cm:msg  "  입금이 확인되면 정품으로 바뀝니다.")
                  (cm:msg "======================")
                  (alert (strcat "정품신청중입니다.\n\n"
                                 "입금자명   " (cm:machine) "\n"
                                 "금 액      44,000 원 (부가세 포함)\n"
                                 "계 좌      농협 301-0019-9326-91\n"
                                 "예금주     안세종\n\n"
                                 "입금하실 때 보내는 분 이름 자리에\n"
                                 "위 PC 번호를 그대로 넣어 주십시오.")))
                (alert (strcat "신청하지 못했습니다.\n\n" (cdr r))))))))))
  (princ))

(defun cm:bizsummary ( / )
  (if (= (cm:n *cm:bno* "") "")
    "   아직 적지 않으셨습니다."
    (strcat "   " (cm:n *cm:bno* "") "   " (cm:n *cm:bnm* ""))))

;; --------------------------------------------------------------- 정보
(defun C:CMABOUT ( / p id res lic)
  (setq lic (if (= (cm:n *cm:key* "") "")
              (cons nil "발급키가 없습니다")
              (cm:license)))
  (setq p (cm:dcl (list
    "cm_abt : dialog {"
    "  label = \"정보\";"
    "  : boxed_column {"
    "    label = \"지적도 DXF 가져오기\";"
    "    : text { key = \"ver\"; label = \"\"; }"
    "    : text { key = \"key\"; label = \"\"; }"
    "    : text { key = \"pc\";  label = \"\"; }"
    "    : text { key = \"st\";  label = \"\"; }"
    "    : text { key = \"srv\"; label = \"\"; }"
    "  }"
    "  : boxed_column {"
    "    label = \"만든 곳\";"
    "    : text { label = \"(주)경성엔지니어링\"; }"
    "    : text { label = \"https://ks-down-map.com\"; }"
    "  }"
    "  : row {"
    "    : button { key = \"upd\";    label = \"업데이트 확인\"; width = 16; }"
    "    : button { key = \"keyb\";   label = \"발급키 등록\";   width = 14; }"
    "    : button { key = \"accept\"; label = \"닫기\"; is_default = true; is_cancel = true; width = 10; }"
    "  }"
    "}")))
  (setq id (load_dialog p) res nil)
  (if (and (>= id 0) (new_dialog "cm_abt" id))
    (progn
      (set_tile "ver" (strcat "판 번호    " *cm:version*))
      (set_tile "key" (strcat "발급키     " (if (= (cm:n *cm:key* "") "")
                                             "없음" *cm:key*)))
      (set_tile "pc"  (strcat "PC 번호    " (cm:machine)))
      (set_tile "st"  (strcat "상 태      "
                              (if (car lic) (cdr lic) (cdr lic))))
      (set_tile "srv" (strcat "서 버      " *cm:server*))
      (action_tile "upd"    "(done_dialog 2)")
      (action_tile "keyb"   "(done_dialog 3)")
      (action_tile "accept" "(done_dialog 0)")
      (setq res (start_dialog))))
  (if (>= id 0) (unload_dialog id))
  (vl-file-delete p)
  (cond ((= res 2) (C:CMUPDATE))
        ((= res 3) (C:CMKEY)))
  (princ))

;; ====================================================== 풀다운 메뉴
;; 파일을 건드리지 않고 메모리에만 만든다. AutoCAD 를 끄면 사라지고
;; 다시 켤 때 이 파일이 불리면서 새로 만들어진다.
(defun cm:mac (cmd)
  ;; 메뉴에 넣을 명령을 만든다.
  ;; 메뉴 파일(cuix)로 불러온 매크로는 AutoCAD 가 "^C^C" 를 취소로 바꿔 주지만,
  ;; 여기처럼 ActiveX 로 만든 메뉴는 바꿔 주지 않고 글자 그대로 명령창에 찍는다.
  ;; 그래서 취소에 해당하는 글자 (chr 3) 을 직접 넣는다. 끝의 빈칸은 엔터다.
  (strcat (chr 3) (chr 3) cmd " "))

(defun cm:menu ( / )
  (vl-catch-all-apply
    '(lambda ( / acad mnu m bar)
       (setq acad (vlax-get-acad-object)
             mnu  (vla-get-Menus (vla-Item (vla-get-MenuGroups acad) 0)))
       ;; 이미 있으면 지운다 (다시 불러도 겹치지 않게)
       (vl-catch-all-apply '(lambda () (vla-Delete (vla-Item mnu "지적도"))))
       (setq m (vla-Add mnu "지적도"))
       (vla-AddMenuItem  m 1 "지적도삽입" (cm:mac "DXFMAP"))
       (vla-AddSeparator m 2)
       (vla-AddMenuItem  m 3 "도움말"     (cm:mac "CMHELP"))
       (vla-AddMenuItem  m 4 "정품신청"   (cm:mac "CMBUY"))
       (vla-AddMenuItem  m 5 "정보"       (cm:mac "CMABOUT"))
       (setq bar (vla-get-MenuBar acad))
       (vla-InsertInMenuBar m (vla-get-Count bar))
       (if (= (getvar "MENUBAR") 0) (setvar "MENUBAR" 1))))
  (princ))

;; --------------------------------------------------------------- 삽입 후처리
;; 서버가 준 도면은 D-PARCEL / D-PNU-TEXT 두 레이어로 들어온다.
;; 이것을 설정창에서 고른 이름·색·글자크기·스타일로 바꿔 준다.
(defun cm:mklayer (name col)
  (if (not (tblsearch "LAYER" name))
    (vl-catch-all-apply '(lambda () (command "_.-LAYER" "_N" name ""))))
  (vl-catch-all-apply '(lambda () (command "_.-LAYER" "_C" col name "")))
  (princ))

(defun cm:settxt (ed / out)
  ;; 글자 높이와 스타일을 바꾼 목록을 돌려준다.
  (setq out ed)
  (if (assoc 40 out)
    (setq out (subst (cons 40 *cm:tsize*) (assoc 40 out) out)))
  (if (and (assoc 7 out) (tblsearch "STYLE" *cm:tstyle*))
    (setq out (subst (cons 7 *cm:tstyle*) (assoc 7 out) out)))
  out)

(defun cm:post (before / e ed lay typ nl nt)
  (cm:mklayer *cm:plyr* *cm:pcol*)
  (cm:mklayer *cm:tlyr* *cm:tcol*)
  (setq nl 0 nt 0)
  (setq e (if before (entnext before) (entnext)))
  (while e
    (setq ed  (entget e)
          lay (cdr (assoc 8 ed))
          typ (cdr (assoc 0 ed)))
    (cond
      ((= lay *cm:srclyr*)
       (vl-catch-all-apply
         '(lambda () (entmod (subst (cons 8 *cm:plyr*) (assoc 8 ed) ed))))
       (setq nl (1+ nl)))
      ((= lay *cm:srctxt*)
       (setq ed (subst (cons 8 *cm:tlyr*) (assoc 8 ed) ed))
       (if (member typ '("TEXT" "MTEXT")) (setq ed (cm:settxt ed)))
       (vl-catch-all-apply '(lambda () (entmod ed)))
       (setq nt (1+ nt))))
    (setq e (entnext e)))
  ;; 비어 버린 원래 레이어는 지운다. 도면이 지저분해지지 않게.
  (foreach n (list *cm:srclyr* *cm:srctxt* "A-REF")
    (if (tblsearch "LAYER" n)
      (vl-catch-all-apply '(lambda () (command "_.-PURGE" "_LA" n "_N")))))
  (list nl nt))

;; --------------------------------------------------------------- 설정 명령
(defun C:MAPCFG (/ k opt n again)
  (setq again T)
  (while again
    (setq again nil)
    (cm:msg "===== 지도 가져오기 설정 =====")
    (cm:msg (strcat "  서버       : " *cm:server*))
    (cm:msg (strcat "  좌표계     : EPSG:" *cm:crs* "   " (cm:crsname *cm:crs*)))
    (cm:msg (strcat "  레이어     : " *cm:layers*))
    (cm:msg (strcat "  등고선간격 : " (cm:num *cm:interval*) " m"))
    (cm:msg (strcat "  삽입후분해 : " (if *cm:explode* "예" "아니오")))
    (cm:msg (strcat "  발급키     : " (if (= (cm:n *cm:key* "") "")
                                        "없음 (발급키 명령으로 등록)" *cm:key*)))
    (initget "좌표계 레이어 간격 서버 분해 발급키 종료")
    (setq opt (getkword
      "\n바꿀 항목 [좌표계/레이어/간격/서버/분해/발급키/종료] <종료>: "))
    (cond
      ((= opt "좌표계")
       (cm:msg "사용 가능한 좌표계")
       (foreach p *cm:crslist* (cm:msg (strcat "    " (car p) "   " (cdr p))))
       (setq k (getstring "\nEPSG 코드: "))
       (if (assoc k *cm:crslist*)
         (progn (setq *cm:crs* k)
                (cm:msg (strcat "EPSG:" k " 로 바꿨습니다.")))
         (if (/= k "") (cm:msg "목록에 없는 코드입니다.")))
       (setq again T))
      ((= opt "레이어")
       (cm:msg "parcel=필지경계  pnu=지번지목  contour=등고선")
       (cm:msg "building=건물   road=도로     water=수계   (쉼표 구분)")
       (setq k (getstring T (strcat "\n레이어 <" *cm:layers* ">: ")))
       (if (/= k "") (setq *cm:layers* k))
       (setq again T))
      ((= opt "간격")
       (if (setq n (getreal (strcat "\n등고선 간격 m <" (cm:num *cm:interval*) ">: ")))
         (setq *cm:interval* n))
       (setq again T))
      ((= opt "서버")
       (setq k (getstring T (strcat "\n서버 주소 <" *cm:server* ">: ")))
       (if (/= k "") (setq *cm:server* (cm:normsrv k)))
       (setq again T))
      ((= opt "분해")
       (setq *cm:explode* (not *cm:explode*))
       (setq again T))
      ((= opt "발급키")
       (C:CMKEY)
       (setq again T))
      (T (cm:save) (cm:msg "설정을 마쳤습니다."))))
  (princ))

;; --------------------------------------------------------------- 주 명령
(defun cm:run (x0 y0 x1 y1 / body res code txt jid state stage last prog
                             tries path before ins ok elapsed size cnt)
  (setq body
    (strcat "{\"bbox\":[" (cm:num x0) "," (cm:num y0) ","
                          (cm:num x1) "," (cm:num y1) "],"
            "\"bbox_crs\":\"" *cm:crs* "\","
            "\"crs\":\"" *cm:crs* "\","
            "\"layers\":[" (cm:quotelist *cm:layers*) "],"
            "\"options\":{\"version\":\"AC1024\",\"unit\":\"m\","
            "\"text_height\":" (cm:num *cm:tsize*) ","
            "\"contour_interval\":" (cm:num *cm:interval*) ","
            "\"contour_z\":true,\"origin_shift\":false,"
            "\"reference_marks\":false}}"))

  (cm:msg "서버에 요청하는 중...")
  (setq res  (cm:http "POST" (strcat *cm:server* "/api/jobs") body)
        code (car res)
        txt  (cadr res))

  (cond
    ((null txt)
     (cm:msg (strcat "서버에 연결할 수 없습니다:  " *cm:server*)))

    ((/= code 202)
     (cm:msg (strcat "요청이 거부되었습니다.  HTTP " (itoa code)))
     (if (cm:jstr txt "detail") (cm:msg (strcat "   " (cm:jstr txt "detail")))))

    ((null (setq jid (cm:jstr txt "id")))
     (cm:msg "작업 번호를 받지 못했습니다."))

    (T
     (cm:msg (strcat "작업 " jid " 진행 중.  지역에 따라 1~3분 걸립니다."))
     (setq state "" last "" tries 0)
     (while (and (/= state "done") (/= state "error") (< tries 400))
       (setvar "CMDECHO" 0) (command "_.DELAY" 1000)
       (setq res (cm:http "GET" (strcat *cm:server* "/api/jobs/" jid) nil)
             txt (cadr res))
       (if txt
         (progn
           (setq state (cm:n (cm:jstr txt "state") "")
                 stage (cm:n (cm:jstr txt "stage_label") "")
                 prog  (cm:n (cm:jnum txt "progress") 0.0))
           (if (and (/= stage "") (/= stage last))
             (progn
               (cm:msg (strcat "   " (itoa (fix (* prog 100))) "%   " stage))
               (setq last stage)))))
       (setq tries (1+ tries)))

     (cond
       ((= state "error")
        (cm:msg (strcat "실패: " (cm:n (cm:jstr txt "error") "원인 불명"))))
       ((/= state "done")
        (cm:msg "시간 안에 끝나지 않았습니다. 웹 화면에서 확인하세요."))
       (T
        (setq elapsed (cm:n (cm:jnum txt "elapsed") 0.0)
              size    (cm:n (cm:jnum txt "size") 0.0))
        (cm:msg (strcat "받았습니다   " (rtos elapsed 2 1) "초   "
                        (rtos (/ size 1048576.0) 2 2) " MB"))

        (setq path (strcat (getvar "TEMPPREFIX") "cadmap_" jid ".dxf"))
        (cm:msg "내려받는 중...")
        (if (not (cm:download (strcat *cm:server* "/api/jobs/" jid "/download") path))
          (cm:msg "파일을 내려받지 못했습니다.")
          (progn
            (cm:msg "도면에 삽입하는 중...")
            (setq before (entlast))
            (setq ok (not (vl-catch-all-error-p
                            (vl-catch-all-apply
                              '(lambda ()
                                 (command "_.-INSERT" (strcat "\"" path "\"")
                                          "0,0" 1 1 0))))))
            ;; 삽입이 실제로 되었을 때만 분해한다. 실패했는데 분해하면
            ;; 원래 도면에 있던 마지막 객체를 건드리게 된다.
            (setq ins (entlast))
            (if (and ok ins (not (eq before ins)))
              (setq ok (not (vl-catch-all-error-p
                              (vl-catch-all-apply
                                '(lambda () (command "_.EXPLODE" ins))))))
              (setq ok nil))
            (if (not ok)
              (progn
                (cm:msg "삽입에 실패했습니다. 아래 파일을 직접 여세요:")
                (cm:msg (strcat "   " path)))
              (progn
                (cm:msg "레이어와 글자를 바꾸는 중...")
                (setq cnt (cm:post before))
                (cm:msg (strcat "마쳤습니다.  필지선 " (itoa (car cnt))
                                " 개 -> " *cm:plyr*
                                ",  지번 " (itoa (cadr cnt))
                                " 개 -> " *cm:tlyr*))))))))))
  (princ))

(defun cm:extract ( / p1 p2 x0 y0 x1 y1 w h area)
  (setq p1 (getpoint "\n영역 첫째 모서리 (ESC 로 취소): "))
  (setq p2 (if p1 (getcorner p1 "반대쪽 모서리: ")))
  (cond
    ((not p2) (cm:msg "영역 선택을 취소했습니다."))
    (T
     (setq x0 (min (car p1) (car p2))   x1 (max (car p1) (car p2))
           y0 (min (cadr p1) (cadr p2)) y1 (max (cadr p1) (cadr p2))
           w  (- x1 x0)  h (- y1 y0)
           area (/ (* w h) 1000000.0))
     (cm:msg (strcat "선택 영역  " (rtos w 2 1) " x " (rtos h 2 1)
                     " m   =   " (rtos area 2 4) " km2"))
     (cond
       ((> area *cm:limit*)
        (cm:msg (strcat "1회 추출 한도 " (rtos *cm:limit* 2 2)
                        " km2 를 넘었습니다. 영역을 줄이세요.")))
       ((< area 0.000001)
        (cm:msg "영역이 너무 작습니다."))
       (T (cm:run x0 y0 x1 y1)))))
  (princ))

;; 설정창 -> 영역선택 -> 삽입 -> 후처리 -> 다시 설정창. 닫기를 누를 때까지.
(defun C:DXFMAP (/ lic go oldecho)
  (setq oldecho (getvar "CMDECHO"))
  (setvar "CMDECHO" 0)
  (cm:ensure-server)
  (cm:msg "발급키를 확인하는 중...")
  (setq lic (cm:license))
  (if (not (car lic))
    (progn
      (cm:msg (strcat "쓸 수 없습니다.  " (cdr lic)))
      (cm:msg "   발급키 등록 : 발급키   명령")
      (cm:msg "   정품 신청   : 정품신청 명령"))
    (progn
      (cm:msg (strcat "발급키 확인됨  " (cdr lic)))
      (setq go T)
      (while go
        (if (cm:Dialog (strcat "발급키 " (cdr lic)))
          (cm:extract)
          (setq go nil)))
      (cm:msg "지적도 삽입을 마쳤습니다.")))
  (setvar "CMDECHO" oldecho)
  (princ))

;; --------------------------------------------------------------- 좌표 기입
(defun C:PTLABEL (/ pt h n mode dx)
  (initget "두줄 한줄")
  (setq mode (getkword "\n표기 형식 [두줄/한줄] <두줄>: "))
  (if (not mode) (setq mode "두줄"))
  (setq h (getvar "TEXTSIZE"))
  (if (or (null h) (<= h 0)) (setq h 1.0))
  (if (setq n (getreal (strcat "\n문자 높이 <" (rtos h 2 2) ">: ")))
    (setq h n))
  (setq dx (* h 0.8))
  (cm:msg "점을 클릭하세요.  엔터 또는 ESC 로 끝냅니다.")
  (while (setq pt (getpoint "\n점 지정: "))
    (command "_.POINT" pt)
    (if (= mode "한줄")
      (command "_.TEXT" (list (+ (car pt) dx) (cadr pt)) h 0
               (strcat "X=" (rtos (car pt) 2 3) "  Y=" (rtos (cadr pt) 2 3)))
      (progn
        (command "_.TEXT" (list (+ (car pt) dx) (+ (cadr pt) (* h 0.6))) h 0
                 (strcat "X=" (rtos (car pt) 2 3)))
        (command "_.TEXT" (list (+ (car pt) dx) (- (cadr pt) (* h 0.8))) h 0
                 (strcat "Y=" (rtos (cadr pt) 2 3))))))
  (princ))

;; --------------------------------------------------------------- 한글 별칭
(defun C:지적도       () (C:DXFMAP))
(defun C:지적도삽입   () (C:DXFMAP))
(defun C:지도설정     () (C:MAPCFG))
(defun C:좌표         () (C:PTLABEL))
(defun C:발급키       () (C:CMKEY))
(defun C:정품신청     () (C:CMBUY))
;; 도움말·정보는 AutoCAD 자체 명령과 겹칠 수 있어 앞에 지적도를 붙인다.
(defun C:지적도도움말 () (C:CMHELP))
(defun C:지적도정보   () (C:CMABOUT))
(defun C:지적도업데이트 () (C:CMUPDATE))
(defun C:지적도홈     () (C:CMHOME))

;; --------------------------------------------------------------- 시작 처리
(cm:load)                                ; 저장해 둔 좌표계·발급키 복원
(cm:menu)                                ; 풀다운 메뉴 만들기

(cm:msg "==========================================================")
(cm:msg (strcat "  지적도 DXF 가져오기  " *cm:version*
                "   (주)경성엔지니어링"))
(cm:msg "    지적도삽입    영역을 지정해 연속지적도 가져오기")
(cm:msg "    정품신청      구매 안내 · 세금계산서 신청")
(cm:msg "    지적도도움말  사용법과 주의사항")
(cm:msg "    지적도정보    판 번호 · 발급키 · PC 번호")
(cm:msg "    발급키        발급키 등록 및 확인")
(cm:msg "    좌표          클릭한 점의 좌표를 도면에 기입")
(cm:msg (strcat "  좌표계  EPSG:" *cm:crs* "   " (cm:crsname *cm:crs*)))
(cm:msg (strcat "  발급키  " (if (= (cm:n *cm:key* "") "")
                               "없음 - 발급키 명령으로 등록해 주세요"
                               *cm:key*)))
(cm:msg "==========================================================")

;; 새 버전 알림은 하루에 한 번만. 켤 때마다 서버를 부르지 않는다.
(if (/= (cm:regget "LastCheck" "") (cm:today))
  (progn (cm:regput "LastCheck" (cm:today))
         (vl-catch-all-apply 'cm:checkupdate (list T))))

(princ)
