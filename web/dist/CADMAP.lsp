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
(setq *cm:version* "1.0.1")

(setq *cm:crslist*
  '(("5186"  . "중부원점 (세계측지계)")
    ("5185"  . "서부원점 (세계측지계)")
    ("5187"  . "동부원점 (세계측지계)")
    ("5188"  . "동해원점 (세계측지계)")
    ("5179"  . "UTM-K 단일원점")
    ("5174"  . "중부원점 (구 지적)")
    ("32652" . "UTM 52N")))

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
(defun cm:Dialog (/ dcl_path fp dcl_id result idx names codes)
  (setq codes (mapcar 'car *cm:crslist*))
  (setq names (mapcar '(lambda (p) (strcat "EPSG:" (car p) "  " (cdr p))) *cm:crslist*))
  (setq dcl_path (vl-filename-mktemp "cmdlg_" nil ".dcl"))
  (setq fp (open dcl_path "w"))
  (write-line "cm_dlg : dialog {" fp)
  (write-line "  label = \"지적도 가져오기\";" fp)
  (write-line "  : boxed_column {" fp)
  (write-line "    label = \"출력 좌표계\";" fp)
  (write-line "    : popup_list { key=\"crs\"; width=38; }" fp)
  (write-line "    : text { label=\"현재 도면 좌표가 이 좌표계여야 위치가 맞습니다.\"; }" fp)
  (write-line "  }" fp)
  (write-line "  : boxed_column {" fp)
  (write-line "    label = \"발급키\";" fp)
  (write-line "    : edit_box { key=\"lic\"; width=38; }" fp)
  (write-line "    : text { key=\"licpc\"; label=\"\"; }" fp)
  (write-line "  }" fp)
  (write-line "  : toggle { key=\"explode\"; label=\"삽입 후 분해\"; }" fp)
  (write-line "  : row {" fp)
  (write-line "    : button { key=\"accept\"; label=\"확인\"; is_default=true; }" fp)
  (write-line "    : button { key=\"cancel\"; label=\"종료\"; is_cancel=true; }" fp)
  (write-line "  }" fp)
  (write-line "}" fp)
  (close fp)

  (setq dcl_id (load_dialog dcl_path))
  (setq result nil)
  (cond
    ((< dcl_id 0)
      (alert "설정 창을 열 수 없습니다."))
    (T
      (if (not (new_dialog "cm_dlg" dcl_id))
        (alert "대화상자 정의를 찾을 수 없습니다.")
        (progn
          (start_list "crs")
          (foreach nm names (add_list nm))
          (end_list)
          (setq idx (vl-position (assoc *cm:crs* *cm:crslist*) *cm:crslist*))
          (set_tile "crs" (itoa (if idx idx 0)))
          (set_tile "explode" (if *cm:explode* "1" "0"))
          (set_tile "lic" (cm:n *cm:key* ""))
          (set_tile "licpc" (strcat "이 PC 번호  " (cm:machine)))
          (action_tile "accept"
            (strcat
              "(setq *cm:crs* (nth (atoi (get_tile \"crs\")) '("
              (apply 'strcat (mapcar '(lambda (k) (strcat "\"" k "\" ")) codes))
              ")))"
              "(setq *cm:explode* (= (get_tile \"explode\") \"1\"))"
              "(cm:setkey (get_tile \"lic\"))"
              "(done_dialog 1)"))
          (action_tile "cancel" "(done_dialog 0)")
          (setq result (start_dialog))))))
  (vl-file-delete dcl_path)
  ;; 확인을 눌렀으면 다음에도 쓰도록 저장해 둔다
  (if (= result 1) (cm:save))
  (= result 1))

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
  (cm:regput "Crs"     *cm:crs*)
  (cm:regput "Explode" (if *cm:explode* "1" "0"))
  (cm:regput "Server"  *cm:server*)
  T)

(defun cm:load ( / v)
  (setq *cm:key* (cm:regget "Key" ""))
  (setq v (cm:regget "Crs" nil))
  (if (and v (assoc v *cm:crslist*)) (setq *cm:crs* v))
  (setq *cm:explode* (= (cm:regget "Explode" "1") "1"))
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
       (vla-AddMenuItem  m 1 "지적도 가져오기"  (cm:mac "DXFMAP"))
       (vla-AddMenuItem  m 2 "좌표 기입"        (cm:mac "PTLABEL"))
       (vla-AddSeparator m 3)
       (vla-AddMenuItem  m 4 "지도 설정"        (cm:mac "MAPCFG"))
       (vla-AddMenuItem  m 5 "발급키 등록"      (cm:mac "CMKEY"))
       (vla-AddSeparator m 6)
       (vla-AddMenuItem  m 7 "업데이트 확인"    (cm:mac "CMUPDATE"))
       (vla-AddMenuItem  m 8 "홈페이지 열기"    (cm:mac "CMHOME"))
       (setq bar (vla-get-MenuBar acad))
       (vla-InsertInMenuBar m (vla-get-Count bar))
       (if (= (getvar "MENUBAR") 0) (setvar "MENUBAR" 1))))
  (princ))

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
(defun C:DXFMAP (/ p1 p2 x0 y0 x1 y1 w h area body res code txt jid
                    state stage last prog tries path before after
                    ok elapsed size oldecho lic)
  (setq oldecho (getvar "CMDECHO"))
  (setvar "CMDECHO" 0)
  ;; 좌표/옵션 설정 팝업
  (if (not (cm:Dialog))
    (progn (cm:msg "취소했습니다.") (setvar "CMDECHO" oldecho))
  ;; 확인 시 진행
  (progn
  ;; 서버 연결 확인 (경고만)
  (cm:ensure-server)

  ;; 발급키 확인. 서버가 승인해야만 다음으로 넘어간다.
  (cm:msg "발급키를 확인하는 중...")
  (setq lic (cm:license))
  (if (not (car lic))
    (progn
      (cm:msg (strcat "쓸 수 없습니다.  " (cdr lic)))
      (cm:msg (strcat "  발급키 등록 : 발급키  명령"))
      (cm:msg (strcat "  사용 신청   : " *cm:server* "/cad")))
  (progn
  (cm:msg (strcat "발급키 확인됨  " (cdr lic)))
  (cm:msg (strcat "출력 좌표계  EPSG:" *cm:crs* "   " (cm:crsname *cm:crs*)))

  (setq p1 (getpoint "\n\n영역 첫째 모서리: "))
  (setq p2 (if p1 (getcorner p1 "반대쪽 모서리: ")))

  (cond
    ((not p2) (cm:msg "취소했습니다."))
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
       (T
        (setq body
          (strcat "{\"bbox\":[" (cm:num x0) "," (cm:num y0) ","
                                (cm:num x1) "," (cm:num y1) "],"
                  "\"bbox_crs\":\"" *cm:crs* "\","
                  "\"crs\":\"" *cm:crs* "\","
                  "\"layers\":[" (cm:quotelist *cm:layers*) "],"
                  "\"options\":{\"version\":\"AC1024\",\"unit\":\"m\","
                  "\"text_height\":\"auto\","
                  "\"contour_interval\":" (cm:num *cm:interval*) ","
                  "\"contour_z\":true,\"origin_shift\":false,"
                  "\"reference_marks\":false}}"))

        (cm:msg "서버에 요청하는 중...")
        (setq res  (cm:http "POST" (strcat *cm:server* "/api/jobs") body)
              code (car res)
              txt  (cadr res))

        (cond
          ((null txt)
           (cm:msg (strcat "서버에 연결할 수 없습니다:  " *cm:server*))
           (cm:msg "네트워크 연결 또는 지도설정(MAPCFG)의 서버 주소를 확인하세요."))

          ((/= code 202)
           (cm:msg (strcat "요청이 거부되었습니다.  HTTP " (itoa code)))
           (if (cm:jstr txt "detail")
             (cm:msg (strcat "   " (cm:jstr txt "detail")))))

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
                 ;; 단계가 바뀔 때만 찍는다. 매초 찍으면 명령행이 넘친다.
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
              (cm:msg (strcat "완료   " (rtos elapsed 2 1) "초   "
                              (rtos (/ size 1048576.0) 2 2) " MB"))
              (if (cm:jstr txt "label")
                (cm:msg (strcat "표고자료  " (cm:jstr txt "label"))))
              (if (vl-string-search "\"warnings\":[\"" txt)
                (cm:msg "경고 있음 - 웹 화면에서 상세 내용을 확인하세요."))

              (setq path (strcat (getvar "TEMPPREFIX") "cadmap_" jid ".dxf"))
              (cm:msg "내려받는 중...")
              (if (not (cm:download
                         (strcat *cm:server* "/api/jobs/" jid "/download") path))
                (cm:msg "파일을 내려받지 못했습니다.")
                (progn
                  (cm:msg "도면에 삽입하는 중...")
                  (setq before (entlast))
                  ;; 경로에 공백이 있을 수 있으므로 따옴표로 감싼다
                  (setq ok (not (vl-catch-all-error-p
                                  (vl-catch-all-apply
                                    '(lambda ()
                                       (command "_.-INSERT"
                                                (strcat "\"" path "\"")
                                                "0,0" 1 1 0))))))
                  (setq after (entlast))
                  (cond
                    ((or (not ok) (eq before after))
                     (cm:msg "삽입에 실패했습니다. 아래 파일을 직접 여세요:")
                     (cm:msg (strcat "   " path)))
                    (T
                     (if *cm:explode*
                       (vl-catch-all-apply
                         '(lambda () (command "_.EXPLODE" after))))
                     (cm:msg "삽입을 마쳤습니다.  ZOOM Extents 로 확인하세요.")))))))))))))
  ))
  (setvar "CMDECHO" oldecho)
  (princ))))

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
(defun C:지도설정     () (C:MAPCFG))
(defun C:좌표         () (C:PTLABEL))
(defun C:발급키       () (C:CMKEY))
(defun C:지적도업데이트 () (C:CMUPDATE))
(defun C:지적도홈     () (C:CMHOME))

;; --------------------------------------------------------------- 시작 처리
(cm:load)                                ; 저장해 둔 좌표계·발급키 복원
(cm:menu)                                ; 풀다운 메뉴 만들기

(cm:msg "==========================================================")
(cm:msg (strcat "  지적도 DXF 가져오기  " *cm:version*
                "   (주)경성엔지니어링"))
(cm:msg "    지적도        영역을 지정해 연속지적도 가져오기")
(cm:msg "    지도설정      좌표계 / 발급키 / 서버 주소")
(cm:msg "    발급키        발급키 등록 및 확인")
(cm:msg "    좌표          클릭한 점의 좌표를 도면에 기입")
(cm:msg "    지적도업데이트  새 버전 받기")
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
