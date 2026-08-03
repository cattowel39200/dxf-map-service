;;; ==========================================================================
;;;  CADMAP.LSP - 지적도 / 지형도 DXF 가져오기
;;;
;;;  AutoCAD 안에서 영역을 지정하면 서버에서 해당 범위의 연속지적도와
;;;  지형 자료를 받아 현재 도면에 삽입한다.
;;;
;;;  명령어
;;;    지적도   (DXFMAP)  두 점으로 영역을 지정해 도면 가져오기
;;;    지도설정 (MAPCFG)  좌표계 / 레이어 / 등고선간격 / 서버 주소 설정
;;;    좌표     (PTLABEL) 클릭한 점의 좌표를 도면에 기입
;;;
;;;  준비
;;;    1. run.ps1 로 서버를 실행한다 (http://localhost:8000)
;;;    2. APPLOAD 로 이 파일을 불러온다
;;;    3. 도면 좌표계를 서버 설정과 맞춘다 (지도설정)
;;; ==========================================================================

(vl-load-com)

;; --------------------------------------------------------------- 기본 설정
(if (not *cm:server*)   (setq *cm:server*   "http://localhost:8000"))
(if (not *cm:crs*)      (setq *cm:crs*      "5186"))
(if (not *cm:layers*)   (setq *cm:layers*   "parcel,pnu,contour,building,road,water"))
(if (not *cm:interval*) (setq *cm:interval* 5.0))
(if (not *cm:explode*)  (setq *cm:explode*  T))
(if (not *cm:limit*)    (setq *cm:limit*    1.0))

(setq *cm:crslist*
  '(("5186"  . "중부원점 (세계측지계)")
    ("5185"  . "서부원점 (세계측지계)")
    ("5187"  . "동부원점 (세계측지계)")
    ("5188"  . "동해원점 (세계측지계)")
    ("5179"  . "UTM-K 단일원점")
    ("5174"  . "중부원점 (구 지적)")
    ("32652" . "UTM 52N")))

;; --------------------------------------------------------------- 보조 함수
(defun cm:msg (s) (princ (strcat "\n" s)) (princ))

(defun cm:crsname (code / hit)
  (if (setq hit (assoc code *cm:crslist*)) (cdr hit) code))

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
(defun cm:http (method url body / h txt st err)
  (setq txt nil st 0)
  (setq h (vl-catch-all-apply
            'vlax-create-object (list "WinHttp.WinHttpRequest.5.1")))
  (if (vl-catch-all-error-p h)
    (progn (cm:msg "WinHttp 를 만들 수 없습니다. 윈도우 구성 요소를 확인하세요.")
           (list 0 nil))
    (progn
      (setq err
        (vl-catch-all-apply
          '(lambda ()
             (vlax-invoke h 'SetTimeouts 8000 8000 30000 120000)
             (vlax-invoke h 'Open method url :vlax-false)
             (vlax-invoke h 'SetRequestHeader "Content-Type" "application/json")
             (if body (vlax-invoke h 'Send body) (vlax-invoke h 'Send))
             (setq st (vlax-get h 'Status) txt (vlax-get h 'ResponseText)))))
      (vlax-release-object h)
      (if (vl-catch-all-error-p err) (list 0 nil) (list st txt)))))

(defun cm:download (url path / h ok stream err)
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
    (initget "좌표계 레이어 간격 서버 분해 종료")
    (setq opt (getkword "\n바꿀 항목 [좌표계/레이어/간격/서버/분해/종료] <종료>: "))
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
       (if (/= k "") (setq *cm:server* k))
       (setq again T))
      ((= opt "분해")
       (setq *cm:explode* (not *cm:explode*))
       (setq again T))
      (T (cm:msg "설정을 마쳤습니다."))))
  (princ))

;; --------------------------------------------------------------- 주 명령
(defun C:DXFMAP (/ p1 p2 x0 y0 x1 y1 w h area body res code txt jid
                    state stage last prog tries path before after
                    ok elapsed size)
  (cm:msg (strcat "출력 좌표계  EPSG:" *cm:crs* "   " (cm:crsname *cm:crs*)))
  (cm:msg "현재 도면 좌표가 이 좌표계여야 위치가 맞습니다.  (변경: 지도설정)")

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
           (cm:msg "run.ps1 로 서버를 먼저 실행하세요."))

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
             (command "_.DELAY" 1000)
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
(defun C:지적도   () (C:DXFMAP))
(defun C:지도설정 () (C:MAPCFG))
(defun C:좌표     () (C:PTLABEL))

(cm:msg "==========================================================")
(cm:msg "  CADMAP 로드 완료")
(cm:msg "    지적도    영역을 지정해 지적도/지형도 가져오기")
(cm:msg "    지도설정  좌표계 / 레이어 / 서버 주소 설정")
(cm:msg "    좌표      클릭한 점의 좌표를 도면에 기입")
(cm:msg (strcat "  현재 좌표계  EPSG:" *cm:crs* "   " (cm:crsname *cm:crs*)))
(cm:msg "==========================================================")
(princ)
