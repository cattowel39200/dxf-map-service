# Cloudflare Tunnel로 공개하기

이 PC에서 도는 서비스를 `https://map.kyoungsungeng.com` 으로 인터넷에 연다.
공인 IP도 포트포워딩도 필요 없고 HTTPS 인증서는 Cloudflare가 붙여 준다.

호스팅에 올리는 방식과 달리 **성능이 이 PC 그대로**다.

## 준비

`cloudflared` 가 필요하다.

```powershell
winget install Cloudflare.cloudflared
```

## 1. Cloudflare 인증 (한 번만)

```powershell
cloudflared tunnel login
```

브라우저가 열리면 Cloudflare에 로그인하고 **kyoungsungeng.com** 을 선택해 승인한다.
`%USERPROFILE%\.cloudflared\cert.pem` 이 생기면 된 것이다.

## 2. 설정

PowerShell을 **관리자 권한으로** 열고 실행한다.

```powershell
cd deploy\tunnel
.\setup.ps1
```

터널 생성, DNS 연결, API 서버 자동시작 등록, 터널 서비스 등록까지 한 번에 한다.
다른 주소를 쓰려면 `.\setup.ps1 -Hostname dxf.kyoungsungeng.com` 처럼 준다.

| 명령 | 하는 일 |
|---|---|
| `.\setup.ps1` | 설정 |
| `.\setup.ps1 -Status` | 상태 확인 (로컬·공개 주소 모두 점검) |
| `.\setup.ps1 -Remove` | 서비스와 자동시작 제거 |

## 3. V-World에 도메인 등록

<https://www.vworld.kr> → 마이페이지 → 인증키 관리 → 활용 URL 에
`https://map.kyoungsungeng.com` 을 추가한다. `localhost` 는 지운다.

`.env` 의 `VWORLD_DOMAIN` 은 이미 두 개가 들어 있다.

```
VWORLD_DOMAIN=map.kyoungsungeng.com,localhost
```

앞의 것부터 시도하고 거부되면 다음 것으로 넘어가므로, **등록 전에도 등록 후에도
그대로 동작한다.** 등록이 끝나면 첫 번째에서 바로 통과해 호출이 한 번 줄어든다.

## 무엇이 어떻게 도는가

```
인터넷 → Cloudflare → 터널(cloudflared 서비스) → 127.0.0.1:8000 (API 서버)
```

API 서버는 `127.0.0.1` 에만 열려 있다. 터널을 거치지 않으면 같은 사무실
네트워크에서도 직접 닿을 수 없으므로, 공개 통로는 Cloudflare 하나뿐이다.

두 가지가 자동으로 뜬다.

- **cloudflared** — 윈도우 서비스. 부팅과 동시에 시작한다.
- **DXF Map Service** — 작업 스케줄러 항목. 로그온할 때 시작하고, 죽으면 1분 뒤
  최대 3번까지 다시 띄운다.

## 알아 둘 것

**PC가 꺼지면 서비스도 멈춘다.** 절전 모드로 들어가도 마찬가지다. 상시 운영하려면
전원 옵션에서 절전을 끄는 편이 좋다.

**로그온 트리거다.** API 서버는 이 계정으로 로그온해야 뜬다. 재부팅 후 로그인
화면에 머물러 있으면 터널만 살고 서버는 죽어 있어 502가 난다. 자동 로그인을 켜
두거나, 재부팅 후 한 번 로그인해 두면 된다.

**로그인 없이 누구나 쓸 수 있다.** 주소를 아는 사람은 모두 회사 V-World 할당량을
쓴다. 동시 작업은 3건으로 막혀 있다(`MAX_CONCURRENT_JOBS`).

## 잘 안 될 때

먼저 상태부터 본다.

```powershell
.\setup.ps1 -Status
```

**공개 주소만 502** — 터널은 살아 있는데 API 서버가 죽은 것이다.
작업 스케줄러에서 `DXF Map Service` 를 다시 시작한다.

**공개 주소가 아예 안 열림** — DNS 전파에 1~2분 걸린다. 그 뒤에도 안 되면
Cloudflare 대시보드에서 `map` CNAME 레코드가 있는지, 주황색 구름(프록시)이
켜져 있는지 본다.

**필지가 안 나옴** — V-World 활용 URL 등록이 안 된 것이다. 위 3번 참고.

**터널 로그 보기**

```powershell
Get-EventLog -LogName Application -Source cloudflared -Newest 20
```

## AutoCAD 리습

리습의 기본 서버 주소는 공개 주소로 맞춰 두었다. 사무실 다른 PC에서도 서버를
따로 띄울 필요 없이 바로 쓸 수 있다. 바꾸려면 CAD에서 `지도설정` → `서버`.
