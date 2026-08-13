import logging
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

import config

_BOT_HEADER = "📰 [브리핑봇]\n"   # briefing-bot-server 식별 헤더


def send_telegram(message: str) -> bool:
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    # 텔레그램 최대 4096자 제한으로 분할 발송
    tagged  = _BOT_HEADER + message
    chunks = [tagged[i:i+4000] for i in range(0, len(tagged), 4000)]
    for chunk in chunks:
        try:
            res = requests.post(
                url,
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": chunk,
                },
                timeout=30,
            )
            if res.status_code != 200:
                print(f"Telegram send failed: {res.text}")
                return False
        except Exception as e:
            print(f"Telegram send error: {e}")
            return False

    return True


# ── 이메일 발송 잠정 중단 (2026-08-13 사용자 결정) ────────────
#   사유: Gmail 앱 비밀번호 만료로 매 발송마다 SMTP 534 오류가 누적됨.
#         텔레그램이 주 채널이므로 이메일은 잠정 중단한다.
#   재개: config.py에 EMAIL_ENABLED = True 를 두거나 아래 기본값을 True로.
#   ★ '비활성'과 '실패'를 구분한다 — 의도된 중단을 실패로 기록하면
#     조용한 실패(B유형) 감시가 오염된다. 비활성은 None을 반환한다.
def _email_enabled() -> bool:
    return bool(getattr(config, "EMAIL_ENABLED", False))


def send_email(subject: str, message: str):
    """반환: True=성공 / False=실패 / None=비활성(의도된 중단)"""
    if not _email_enabled():
        logging.info("[이메일] 비활성 상태 — 발송 생략 (config.EMAIL_ENABLED=False)")
        return None
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config.SMTP_USER
        msg["To"] = ", ".join(config.EMAIL_RECIPIENTS)

        html = f"""
<html>
<body style="font-family: Arial, sans-serif; background:#0f0f17; color:#e2e8f0; padding:20px;">
<div style="max-width:600px; margin:0 auto; background:#1a1a2e; padding:24px; border-radius:12px;">
<pre style="white-space: pre-wrap; color:#e2e8f0; font-size:14px; line-height:1.6;">
{message}
</pre>
</div>
</body>
</html>"""

        msg.attach(MIMEText(message, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_USER, config.EMAIL_RECIPIENTS, msg.as_string())

        logging.info("Email send succeeded")
        return True
    except Exception as e:
        logging.error(f"Email send error: {e}")
        return False


def send_all(message: str, subject: str | None = None) -> dict:
    if subject is None:
        subject = f"Investment briefing {datetime.now(timezone(timedelta(hours=9))).strftime('%Y.%m.%d')}"

    tg = send_telegram(message)
    em = send_email(subject, message)      # None이면 비활성 (실패 아님)
    return {
        "telegram": tg,
        "email": em,
        "email_status": ("sent" if em else "disabled" if em is None else "failed"),
    }


if __name__ == "__main__":
    from analyzer import analyze
    from collector import get_market_data

    data = get_market_data()
    msg = analyze(data)
    ok = send_telegram(msg)
    print("Telegram send succeeded" if ok else "Telegram send failed")
