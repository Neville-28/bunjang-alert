# bunjang_alert.py
import os, json, requests, smtplib
from email.mime.text import MIMEText

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
MAIL_TO   = os.getenv("MAIL_TO")

KEYWORD = os.getenv("KEYWORD", "우마무스메")
STATE_FILE = "bunjang_seen.json"

def send_email(subject, body):
    if not (SMTP_USER and SMTP_PASS and MAIL_TO):
        raise RuntimeError("Missing SMTP_USER/SMTP_PASS/MAIL_TO")
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = MAIL_TO
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, [MAIL_TO], msg.as_string())

def load_seen():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_seen(seen: set):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen)[-3000:], f, ensure_ascii=False, indent=2)

def fetch_bunjang(keyword: str, limit: int = 30):
    # 这是你之前用的公开 JSON 搜索接口
    url = "https://api.bunjang.co.kr/api/1/find_v2.json"
    params = {"q": keyword, "order": "date"}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    items = []
    for p in data.get("list", [])[:limit]:
        pid = str(p.get("pid", "")).strip()
        if not pid:
            continue
        name = p.get("name", "(no name)")
        price = p.get("price", "")
        link = f"https://m.bunjang.co.kr/products/{pid}"
        items.append((pid, name, price, link))
    return items

def run_once(keyword: str):
    seen = load_seen()
    items = fetch_bunjang(keyword, limit=40)

    new_items = [x for x in items if x[0] not in seen]

    if new_items:
        lines = [f"关键词：{keyword}", "", f"发现 {len(new_items)} 个新上架：", ""]
        for pid, name, price, link in new_items[:20]:
            lines.append(f"- {name}\n  {price}원\n  {link}\n  pid={pid}\n")
        body = "\n".join(lines)
        send_email(f"【Bunjang上新】{keyword}（{len(new_items)}件）", body)

    for pid, *_ in items:
        seen.add(pid)
    save_seen(seen)

if __name__ == "__main__":
    run_once(KEYWORD)
    print("OK")
