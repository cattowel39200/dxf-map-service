# 인터넷에 공개하기

무료로 쓸 수 있는 방법 두 가지다. 어느 쪽이든 **배포한 주소를 V-World 인증키에
등록해야** 배경지도와 지적 레이어가 나온다. 이건 자동화할 수 없는 수동 절차다.

## 어디에 올릴까

| | Hugging Face Spaces | Render 무료 |
|---|---|---|
| CPU / RAM | 2 vCPU / 16 GB | 0.1 CPU / 512 MB |
| 신용카드 | 불필요 | 불필요 |
| 잠들기 | 장기간 미사용 시 | 15분 미사용 시 |
| 깨어나는 시간 | 30초 안팎 | 1분 안팎 |
| 추출 속도 | 로컬과 비슷 | 조금 느림 |

지적도만 뽑으므로 CPU 부담이 크지 않아 어느 쪽이든 쓸 만하다.
무료 등급 사양이 넉넉한 **Hugging Face Spaces** 를 권한다.

## Hugging Face Spaces (권장)

1. <https://huggingface.co/join> 에서 가입 (무료)
2. <https://huggingface.co/settings/tokens> 에서 **write** 권한 토큰 발급
3. 프로젝트 폴더에서 한 줄 실행

```powershell
.\.venv\Scripts\python.exe deploy\deploy_hf.py --token hf_여기에토큰
```

Space 생성, 인증키 등록, 코드 업로드가 한 번에 끝나고 주소가 출력된다.
도커 이미지를 만드는 데 3~6분 걸리며, 현황 페이지에서 `Building` 이 `Running` 으로
바뀌면 접속된다.

주소는 `https://<계정>-dxf-map-service.hf.space` 형태다.

비공개로 만들려면 `--private`, 다른 이름으로 만들려면 `--space 이름` 을 붙인다.
코드를 고친 뒤 다시 올릴 때도 같은 명령을 그대로 쓰면 된다.

## Render

1. <https://render.com> 가입 후 GitHub 계정 연결
2. **New → Blueprint** → 이 저장소 선택 (`render.yaml` 을 읽는다)
3. 만들어진 서비스의 **Environment** 에서 `VWORLD_KEY` 값을 입력
4. 배포된 실제 주소로 `VWORLD_DOMAIN` 값을 수정

## 배포 후 반드시 할 일

**V-World 인증키에 배포 주소를 등록한다.**

<https://www.vworld.kr> → 마이페이지 → 인증키 관리 → 해당 키 수정 →
**활용 URL** 에 배포 주소를 추가한다. `localhost` 는 그대로 두면 개발도 계속 된다.

등록하지 않으면 배경지도 타일이 비고, 지적 레이어는
`인증키 정보가 올바르지 않습니다` 로 거부된다.

환경변수 `VWORLD_DOMAIN` 도 같은 도메인이어야 한다. 서버에서 부르는 Data API 는
Referer 가 없어 이 값으로 도메인을 판단하기 때문이다.

## 배포판에서 달라지는 것

**산출물 보관** — 컨테이너가 다시 뜨면 `/app/output` 이 비워진다. 만든 DXF 는
바로 받는 것이 안전하다. Render 는 `OUTPUT_TTL_HOURS` 를 6으로 줄여 두었다.

**동시 작업 수** — 워커가 하나이고 작업 상태를 메모리에 두므로 동시 2건으로
제한한다(`MAX_CONCURRENT_JOBS`). 넘으면 HTTP 429 와 함께 잠시 후 다시 시도하라는
안내가 나간다.

## 주소를 공개할 때 알아 둘 것

로그인 없이 누구나 쓸 수 있는 상태다. 주소를 아는 사람은 모두 귀사의 V-World
할당량을 소모한다. 나중에 막고 싶으면 알려 달라 — 비밀번호 한 겹은 금방 넣는다.

## AutoCAD 리습도 함께 바꾸기

배포 후에는 리습이 로컬 대신 배포 주소를 보게 해야 한다.

```
명령: 지도설정
바꿀 항목 [좌표계/레이어/간격/서버/분해/종료]: 서버
서버 주소 <http://localhost:8000>: https://계정-dxf-map-service.hf.space
```
