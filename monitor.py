import json
import os
from datetime import datetime, timedelta, timezone
import requests

BOOK_ID = "S000220562985"

# 1단계에서 구한 값으로 교체하세요.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8934110718:AAHQnq5wPowhWJqkdsE3Nm41AG980OpEnFg")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "2002952023")

STATUS_FILE = "stock_status.json"
URL = f"https://product.kyobobook.co.kr/api/gw/pdt/v2/product/{BOOK_ID}/location-inventory"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": f"https://product.kyobobook.co.kr/detail/{BOOK_ID}",
    "Accept": "application/json, text/plain, */*",
}


def send_telegram(message):
    telegram_url = (
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        requests.post(telegram_url, json=payload, timeout=10)
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")


def get_kst_now():
    return datetime.now(timezone.utc) + timedelta(hours=9)


def fetch_stock():
    response = requests.get(URL, headers=HEADERS, timeout=10)
    data = response.json()
    current_stock = {}
    for area in data.get("data", []):
        for store in area.get("list", []):
            current_stock[store["strName"]] = store["realInvnQntt"]
    return current_stock


def main():
    now_kst = get_kst_now()
    current_hour = now_kst.hour

    # 테스트를 위해 야간 시간 제한을 잠시 주석 처리하거나 확인합니다.
    if current_hour >= 23 or current_hour < 9:
        print(
            f"[{now_kst.strftime('%H:%M')}] 야간 시간대이므로 실행을 건너뜁니다."
        )
        return

    current_stock = fetch_stock()
    total_qty = sum(current_stock.values())

    prev_stock = {}
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                prev_stock = json.load(f)
        except Exception:
            prev_stock = {}

    # 9시 정기 알림 테스트 조건
    is_nine_am = current_hour == 9 and now_kst.minute < 10

    if is_nine_am:
        lines = [
            f"☀️ <b>[오전 9시 정기 재고 현황]</b>",
            f"📅 {now_kst.strftime('%Y-%m-%d %H:%M')}\n",
        ]
        for name, qty in current_stock.items():
            lines.append(f"{name:<10} : {qty}권")
        lines.append(f"\n<b>총 재고 : {total_qty}권</b>")
        send_telegram("\n".join(lines))

    elif prev_stock:
        changes = []
        for name, qty in current_stock.items():
            prev_qty = prev_stock.get(name, 0)
            if qty != prev_qty:
                diff = qty - prev_qty
                diff_str = f"+{diff}" if diff > 0 else f"{diff}"
                changes.append(
                    f"• <b>{name}</b>: {prev_qty}권 ➡️ <b>{qty}권</b> ({diff_str})"
                )

        if changes:
            msg = [
                f"🚨 <b>[교보문고 재고 변동 알림]</b>",
                f"⏰ {now_kst.strftime('%Y-%m-%d %H:%M')}\n",
            ] + changes + [f"\n<b>총 재고 : {total_qty}권</b>"]
            send_telegram("\n".join(msg))
        else:
            print("재고 변동 없음")
    else:
        print("처음 실행되어 현재 상태를 기록합니다.")

    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(current_stock, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()