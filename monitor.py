import csv
import json
import os
from datetime import datetime, timedelta, timezone
import requests

# 1. 모니터링할 도서 목록 (BOOK_ID: "표시할 도서명")
BOOKS_JSON = os.getenv("BOOKS_JSON", "{}")
try:
    BOOKS = json.loads(BOOKS_JSON)
except Exception as e:
    print(f"도서 목록 파싱 실패: {e}")
    BOOKS = {}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

STATUS_FILE = "stock_status.json"
LOG_FILE = "stock_log.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
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


def fetch_stock(book_id):
    url = f"https://product.kyobobook.co.kr/api/gw/pdt/v2/product/{book_id}/location-inventory"
    headers = HEADERS.copy()
    headers["Referer"] = f"https://product.kyobobook.co.kr/detail/{book_id}"

    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        current_stock = {}
        for area in data.get("data", []):
            for store in area.get("list", []):
                current_stock[store["strName"]] = store["realInvnQntt"]
        return current_stock
    except Exception as e:
        print(f"[{book_id}] 재고 조회 실패: {e}")
        return {}


def append_to_csv(now_kst, book_title, current_stock):
    file_exists = os.path.exists(LOG_FILE)
    timestamp = now_kst.strftime("%Y-%m-%d %H:%M:%S")

    with open(LOG_FILE, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["일시", "도서명", "지점명", "재고수량"])

        for store_name, qty in current_stock.items():
            writer.writerow([timestamp, book_title, store_name, qty])


def main():
    now_kst = get_kst_now()
    current_hour = now_kst.hour

    if current_hour >= 22 or current_hour < 9:
        print(
            f"[{now_kst.strftime('%H:%M')}] 야간 시간대이므로 실행을 건너뜁니다."
        )
        return

    # 기존 JSON 상태 데이터 로드
    prev_all_stock = {}
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                prev_all_stock = json.load(f)
        except Exception:
            prev_all_stock = {}

    current_all_stock = {}
    all_changes = []
    nine_am_messages = []

    is_nine_am = current_hour == 9 and now_kst.minute < 10

    # 도서별 순회 로직
    for book_id, book_title in BOOKS.items():
        current_stock = fetch_stock(book_id)
        if not current_stock:
            continue

        current_all_stock[book_title] = current_stock
        total_qty = sum(current_stock.values())

        # -------------------------------------------------------------
        # [수정 1] 무조건 호출되던 append_to_csv(now_kst, book_title, current_stock) 제거
        # -------------------------------------------------------------

        # 2. 9시 정기 메시지 구성
        if is_nine_am:
            lines = [f"📚 <b>[{book_title}]</b> (총 {total_qty}권)"]
            for name, qty in current_stock.items():
                lines.append(f"{name:<10} : {qty}권")
            nine_am_messages.append("\n".join(lines))

        # 3. 변동 알림 메시지 구성
        else:
            prev_stock = prev_all_stock.get(book_title, {})
            if prev_stock:
                book_changes = []
                for name, qty in current_stock.items():
                    prev_qty = prev_stock.get(name, 0)
                    if qty != prev_qty:
                        diff = qty - prev_qty
                        diff_str = f"+{diff}" if diff > 0 else f"{diff}"
                        book_changes.append(
                            f"• <b>{name}</b>: {prev_qty}권 ➡️ <b>{qty}권</b> ({diff_str})"
                        )

                if book_changes:
                    all_changes.append(
                        f"📖 <b>[{book_title}]</b> (총 {total_qty}권)\n"
                        + "\n".join(book_changes)
                    )

    # -------------------------------------------------------------
    # [수정 2] 메시지 발송 및 CSV 조건부 기록 처리
    # -------------------------------------------------------------
    should_save_csv = False

    # 1) 오전 9시 정기 알림 발생 시
    if is_nine_am and nine_am_messages:
        header = f"☀️ <b>[오전 9시 정기 재고 현황]</b>\n📅 {now_kst.strftime('%Y-%m-%d %H:%M')}\n\n"
        send_telegram(header + "\n\n".join(nine_am_messages))
        should_save_csv = True

    # 2) 재고 변동 발생 시
    elif all_changes:
        header = f"🚨 <b>[교보문고 재고 변동 알림]</b>\n⏰ {now_kst.strftime('%Y-%m-%d %H:%M')}\n\n"
        send_telegram(header + "\n\n".join(all_changes))
        should_save_csv = True

    # 3) 최초 실행이거나 상태 기준점이 없는 경우 (기준점 기록용)
    elif not prev_all_stock and current_all_stock:
        should_save_csv = True

    else:
        if not is_nine_am:
            print("재고 변동 없음 (CSV 및 JSON 저장 스킵)")

    # 업데이트 요소가 있을 때만 CSV 및 JSON 기록
    if should_save_csv:
        for book_title, stock_data in current_all_stock.items():
            append_to_csv(now_kst, book_title, stock_data)

        # 최신 전체 상태를 JSON 파일에 저장
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(current_all_stock, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
