import os
import json
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
MAIL_TO   = os.getenv("MAIL_TO")

KEYWORD = os.getenv("KEYWORD", "우마무스메")
STATE_FILE = "bunjang_state.json"

def send_email_html(subject: str, html: str, text_fallback: str = ""):
    if not (SMTP_USER and SMTP_PASS and MAIL_TO):
        raise RuntimeError("Missing SMTP_USER/SMTP_PASS/MAIL_TO")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = MAIL_TO

    if text_fallback:
        msg.attach(MIMEText(text_fallback, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, [MAIL_TO], msg.as_string())

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_pushed_pid": None}

def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def _pick_image_url(p: dict) -> str | None:
    """
    Bunjang 返回字段可能会变，这里做“多字段兜底”：
    - image / img / image_url / product_image 等
    - 如果是 list，就取第一个
    """
    candidates = [
        "image", "img", "image_url", "product_image", "productImage", "thumbnail", "thumb",
        "product_image_url", "productImageUrl",
    ]
    for k in candidates:
        v = p.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
        if isinstance(v, list) and v:
            v0 = v[0]
            if isinstance(v0, str) and v0.startswith("http"):
                return v0

    # 有些会在更深层
    for k in ["images", "pics", "photos"]:
        v = p.get(k)
        if isinstance(v, list) and v:
            v0 = v[0]
            if isinstance(v0, str) and v0.startswith("http"):
                return v0
            if isinstance(v0, dict):
                for kk in ["url", "imageUrl", "src"]:
                    vv = v0.get(kk)
                    if isinstance(vv, str) and vv.startswith("http"):
                        return vv
    return None

def fetch_bunjang(keyword: str, limit: int = 40):
    # 你之前用的公开 JSON 搜索接口
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
        img = _pick_image_url(p)
        items.append({
            "pid": pid,
            "name": name,
            "price": price,
            "link": link,
            "img": img,
        })
    return items

def run_once(keyword: str):
    state = load_state()
    last_pushed_pid = state.get("last_pushed_pid")

    items = fetch_bunjang(keyword, limit=40)
    if not items:
        print("No items returned.")
        return

    # items 通常是最新在前： [newest, ..., older]
    newest_pid = items[0]["pid"]

    # 首次运行：不推送，直接记录最新 pid（避免第一封邮件轰炸）
    if not last_pushed_pid:
        state["last_pushed_pid"] = newest_pid
        save_state(state)
        print(f"Init state. last_pushed_pid={newest_pid}")
        return

    # 找出“比 last_pushed_pid 更新的那段”（从头开始直到遇到 last_pushed_pid）
    new_items = []
    for it in items:
        if it["pid"] == last_pushed_pid:
            break
        new_items.append(it)

    if not new_items:
        print("No new items since last push.")
        return

    # 组 HTML 邮件（合并一封）
    title = f"【Bunjang上新】{keyword}（{len(new_items)}件）"
    rows_html = []
    rows_text = []
    for it in new_items[:20]:
        img_html = ""
        if it["img"]:
            img_html = f'<div style="margin:6px 0;"><img src="{it["img"]}" style="max-width:260px;border-radius:8px;" /></div>'
        rows_html.append(
            f"""
            <div style="padding:12px 0;border-bottom:1px solid #eee;">
              <div style="font-size:16px;font-weight:600;">{it["name"]}</div>
              <div style="color:#666;margin-top:4px;">{it["price"]}원</div>
              {img_html}
              <div style="margin-top:6px;">
                <a href="{it["link"]}">{it["link"]}</a>
              </div>
              <div style="color:#999;margin-top:4px;">pid: {it["pid"]}</div>
            </div>
            """
        )
        rows_text.append(f'{it["name"]}\n{it["price"]}원\n{it["link"]}\npid={it["pid"]}\n')

    html = f"""
    <html>
      <body style="font-family:Arial, sans-serif;">
        <h2 style="margin:0 0 8px 0;">{title}</h2>
        <div style="color:#666;margin-bottom:12px;">关键词：{keyword}</div>
        {''.join(rows_html)}
      </body>
    </html>
    """
    text_fallback = f"{title}\n关键词：{keyword}\n\n" + "\n".join(rows_text)

    send_email_html(title, html, text_fallback)

    # 更新“上次推送点”：本次列表最新 pid
    state["last_pushed_pid"] = newest_pid
    save_state(state)

    print("Sent:", title)

import time
import threading
from flask import Flask

app = Flask(__name__)

@app.get("/")
def home():
    return "ok", 200

def monitor_loop():
    while True:
        try:
            run_once(KEYWORD)
        except Exception as e:
            print("ERROR:", repr(e))
        time.sleep(60)

if __name__ == "__main__":
    # 后台线程跑监控
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()

    # Render 会注入 PORT 环境变量
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
