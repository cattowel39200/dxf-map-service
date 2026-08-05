"""메일 발송.

신청자에게 발급키와 사용법을 보낸다. 지메일은 앱 비밀번호를 써야 한다.
발송은 느리므로 호출한 쪽에서 스레드로 돌린다.
"""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from . import config


class MailError(RuntimeError):
    pass


def configured() -> bool:
    return bool(config.SMTP_USER and config.SMTP_PASS)


def send(to: str, subject: str, body: str, attachments=None) -> None:
    """attachments: [(파일이름, bytes, "application/octet-stream"), ...]"""
    if not configured():
        raise MailError("메일 계정이 설정되지 않았습니다. .env 의 SMTP_USER/SMTP_PASS 확인.")

    msg = EmailMessage()
    msg["From"] = formataddr((config.MAIL_FROM_NAME, config.SMTP_USER))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    for name, data, ctype in (attachments or []):
        main, _, sub = ctype.partition("/")
        msg.add_attachment(data, maintype=main or "application",
                           subtype=sub or "octet-stream", filename=name)

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=45) as s:
            s.ehlo()
            s.starttls(context=ssl.create_default_context())
            s.ehlo()
            s.login(config.SMTP_USER, config.SMTP_PASS)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError("메일 로그인 실패. 앱 비밀번호를 확인하세요.") from exc
    except Exception as exc:  # noqa: BLE001
        raise MailError(f"메일 발송 실패: {type(exc).__name__}: {exc}") from exc


# ── 본문 틀 ───────────────────────────────────────────────
def demo_body(key: str, name: str = "") -> tuple[str, str]:
    who = f"{name}님, " if name else ""
    subject = "[지적도 DXF 추출] 데모 발급키와 사용법"
    body = f"""{who}안녕하세요. 경성엔지니어링입니다.

신청하신 지적도 DXF 추출 프로그램의 데모 발급키를 보내드립니다.

────────────────────────────────
  발급키   {key}
  사용기간 처음 실행한 날부터 {config.DEMO_DAYS}일
  사용대수 PC 1대
────────────────────────────────

■ 설치와 사용법

1. 첨부한 압축을 풀고 install.ps1 을 마우스 오른쪽 버튼 →
   "PowerShell에서 실행"으로 실행합니다.
2. AutoCAD를 다시 켜면 명령어 세 개가 등록됩니다.
     지적도    영역을 지정해 지적도를 도면으로 가져오기
     지도설정  좌표계 · 발급키 · 서버 주소 설정
     좌표      클릭한 점의 좌표 기입
3. AutoCAD 명령행에 지도설정 을 입력하고 위 발급키를 넣습니다.
4. 지적도 를 입력한 뒤 도면에서 두 점을 찍으면 그 범위의
   연속지적도가 현재 도면에 삽입됩니다.

■ 알아두실 점

· 발급키는 처음 사용한 PC에 묶입니다. 다른 PC에서는 동작하지 않습니다.
  PC를 바꾸셔야 하면 회신 주시면 풀어 드립니다.
· 좌표계는 도면과 같은 원점으로 맞추셔야 위치가 맞습니다.
· 연속지적도는 참고용 도면이며 법적 측량 성과가 아닙니다.

■ 정품 이용

데모 기간이 끝난 뒤에는 아래 계좌로 입금해 주시면 정품으로 전환해 드립니다.
전환 시 프로그램을 다시 설치하거나 키를 새로 받으실 필요가 없습니다.
같은 키가 그대로 무기한 사용 가능해집니다.

  {config.BANK_INFO}

입금 후 이 메일에 회신해 주시면 확인하고 바로 전환해 드립니다.

웹에서도 바로 쓰실 수 있습니다.  {config.SITE_URL}

감사합니다.
경성엔지니어링
"""
    return subject, body


def full_body(key: str, name: str = "") -> tuple[str, str]:
    who = f"{name}님, " if name else ""
    subject = "[지적도 DXF 추출] 정품 등록이 완료되었습니다"
    body = f"""{who}안녕하세요. 경성엔지니어링입니다.

입금이 확인되어 정품으로 전환해 드렸습니다. 감사합니다.

────────────────────────────────
  발급키   {key}
  사용기간 무기한
  사용대수 PC 1대
────────────────────────────────

이미 쓰고 계시던 분이라면 다시 설치하실 필요가 없습니다.
쓰시던 키가 그대로 정품으로 바뀌었으니 계속 사용하시면 됩니다.

처음 받으시는 분은 첨부한 압축을 풀고 install.ps1 을 마우스 오른쪽 버튼 →
"PowerShell에서 실행"으로 설치한 뒤, AutoCAD에서 지도설정 명령으로
위 발급키를 입력하시면 됩니다.

■ 알아두실 점

· 발급키는 처음 사용한 PC에 묶입니다. PC를 바꾸셔야 하면 회신 주시면
  풀어 드립니다.
· 연속지적도는 참고용 도면이며 법적 측량 성과가 아닙니다.

웹에서도 바로 쓰실 수 있습니다.  {config.SITE_URL}

감사합니다.
경성엔지니어링
"""
    return subject, body
