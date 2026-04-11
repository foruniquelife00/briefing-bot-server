import logging
import requests
import config

def send_telegram(message: str) -> bool:
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    # 텔레그램 최대 4096자 제한으로 분할 발송
    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
    for chunk in chunks:
        try:
            res = requests.post(url, json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text":    chunk,
            }, timeout=30)
            if res.status_code != 200:
                print(f"발송 실패: {res.text}")
                return False
        except Exception as e:
            print(f"발송 오류: {e}")
            return False
    return True

if __name__ == "__main__":
    from collector import get_market_data
    from analyzer  import analyze
    data   = get_market_data()
    msg    = analyze(data)
    ok     = send_telegram(msg)
    print("발송 성공!" if ok else "발송 실패")


def send_email(subject: str, message: str) -> bool:
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = config.SMTP_USER
        msg["To"]      = ", ".join(config.EMAIL_RECIPIENTS)

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

        logging.info(f"이메일 발송 성공")
        return True
    except Exception as e:
        logging.error(f"이메일 오류: {e}")
        return False


def send_all(message: str, subject: str = None) -> dict:
    from datetime import datetime
    if subject is None:
        subject = f"📊 투자 브리핑 {datetime.now().strftime('%Y.%m.%d')}"
    tg_ok     = send_telegram(message)
    email_ok  = send_email(subject, message)
    kakao_ok  = send_kakao(message)
    return {
        "telegram": tg_ok,
        "email":    email_ok,
        "kakao":    kakao_ok,
    }


def refresh_kakao_token() -> str:
    try:
        import re
        res = requests.post(
            "https://kauth.kakao.com/oauth/token",
            data={
                "grant_type":    "refresh_token",
                "client_id":     config.KAKAO_CLIENT_ID,
                "client_secret": config.KAKAO_CLIENT_SECRET,
                "refresh_token": config.KAKAO_REFRESH_TOKEN,
            }
        )
        data      = res.json()
        new_token = data.get("access_token")
        if new_token:
            with open("/root/briefing-bot/config.py", "r") as f:
                content = f.read()
            content = re.sub(r'KAKAO_ACCESS_TOKEN\s*=\s*".*"', f'KAKAO_ACCESS_TOKEN  = "{new_token}"', content)
            new_refresh = data.get("refresh_token")
            if new_refresh:
                content = re.sub(r'KAKAO_REFRESH_TOKEN\s*=\s*".*"', f'KAKAO_REFRESH_TOKEN = "{new_refresh}"', content)
            with open("/root/briefing-bot/config.py", "w") as f:
                f.write(content)
            return new_token
    except Exception as e:
        logging.error(f"카카오 토큰 갱신 오류: {e}")
    return config.KAKAO_ACCESS_TOKEN


def send_kakao(message: str) -> bool:
    import json
    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
    token  = config.KAKAO_ACCESS_TOKEN
    for chunk in chunks:
        try:
            template = json.dumps({
                "object_type": "text",
                "text":        chunk,
                "link": {
                    "web_url":        "http://briefmung.duckdns.org:8501",
                    "mobile_web_url": "http://briefmung.duckdns.org:8501",
                }
            })
            res  = requests.post(
                "https://kapi.kakao.com/v2/api/talk/memo/default/send",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
                data={"template_object": template},
                timeout=10
            )
            data = res.json()
            if data.get("code") == -401:
                logging.info("카카오 토큰 만료 — 갱신 중...")
                token = refresh_kakao_token()
                res   = requests.post(
                    "https://kapi.kakao.com/v2/api/talk/memo/default/send",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
                    data={"template_object": template},
                    timeout=10
                )
                data = res.json()
            if data.get("result_code") == 0:
                logging.info("카카오 발송 성공")
            else:
                logging.error(f"카카오 발송 실패: {data}")
                return False
        except Exception as e:
            logging.error(f"카카오 발송 오류: {e}")
            return False
    return True
