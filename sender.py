import logging
import smtplib
from datetime import datetime
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


def send_email(subject: str, message: str) -> bool:
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
        subject = f"Investment briefing {datetime.now().strftime('%Y.%m.%d')}"

    return {
        "telegram": send_telegram(message),
        "email": send_email(subject, message),
    }


if __name__ == "__main__":
    from analyzer import analyze
    from collector import get_market_data

    data = get_market_data()
    msg = analyze(data)
    ok = send_telegram(msg)
    print("Telegram send succeeded" if ok else "Telegram send failed")
