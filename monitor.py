import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone
import requests

# 1. 환경 변수 로드
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BOOKS_JSON = os.getenv("BOOKS_JSON", "{}")
GIST_TOKEN = os.getenv("GIST_TOKEN")
GIST_ID = os.getenv("GIST_ID")

try:
    BOOKS = json.loads(BOOKS_JSON)
except Exception as e:
    print(f"도서 목록 파싱 실패: {e}")
    BOOKS = {}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json, text/plain, */*",
}


# 2. Gist API 함수 (데이터 로드 및 업데이트)
def get_gist_data():
    """Gist에서 json과 csv 내용 불러오기"""
    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {
        "Authorization": f"token {GIST_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            files = response.json().get("files", {})

            # json 가져오기
            json_file = files.get("stock_status.json", {})
            json_str = json_file.get("content", "{}") if json_file else "{}"
            try:
                prev_stock = json.loads(json_str)
            except Exception as parse_err:
                print(
                    f"⚠️ Gist JSON 파싱 실패 (문법 오류 가능성): {parse_err}"
                )
                prev_stock = {}

            # csv 가져오기
            csv_file = files.get("stock_log.csv", {})
            csv_str = (
                csv_file.get("content", "일시,도서명,지점명,재고수량\n")
                if csv_file
                else "일시,도서명,지점명,재고수량\n"
            )

            return prev_stock, csv_str
        else:
            print(f"Gist 읽기 실패 (상태 코드 {response.status_code})")
    except Exception as e:
        print(f"Gist 데이터 로드 예외 발생: {e}")

    return {}, "일시,도서명,지점명,재고수량\n"


def update_gist_data(status_dict, updated_csv_content):
    """Gist 파일 업데이트"""
    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {
        "Authorization": f"token {GIST_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {
        "files": {
            "stock_status.json": {
                "content": json.dumps(status_dict, ensure_ascii=False, indent=2)
            },
            "stock_log.csv": {"content": updated_csv_content},
        }
    }
    try:
        res = requests.patch(url, headers=headers, json=payload, timeout=10)
        if res.status_code != 200:
            print(f"Gist 업데이트 실패 (상태 코드: {res.status_code}): {res.text}")
        else:
            print("Gist 업데이트 성공")
    except Exception as e:
        print(f"Gist 업데이트 요청 실패: {e}")


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
        res = requests.post(telegram_url, json=payload, timeout=10)
        if res.status_code == 200:
            print("텔레그램 알림 전송 성공")
        else:
            print(f"텔레그램 전송 실패 (상태 코드 {res.status_code}): {res.text}")
    except Exception as e:
        print(f"텔레그램 전송 중 예외 발생: {e}")


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


def main():
    now_kst = get_kst_now()
    current_hour = now_kst.hour

    if current_hour >= 22 or current_hour < 9:
        print(
            f"[{now_kst.strftime('%H:%M')}] 야간 시간대이므로 실행을 건너뜁니다."
        )
        return

    # Gist에서 이전 데이터 가져오기
    prev_all_stock, current_csv_content = get_gist_data()

    current_all_stock = {}
    all_changes = []
    nine_am_messages = []

    is_nine_am = current_hour == 9 and now_kst.minute < 10

    for book_id, book_title in BOOKS.items():
        current_stock = fetch_stock(book_id)
        if not current_stock:
            continue

        current_all_stock[book_title] = current_stock
        total_qty = sum(current_stock.values())

        if is_nine_am:
            lines = [f"📚 <b>[{book_title}]</b> (총 {total_qty}권)"]
            for name, qty in current_stock.items():
                lines.append(f"{name:<10} : {qty}권")
            nine_am_messages.append("\n".join(lines))
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

    should_save = False

    # 1) 9시 정기 보고
    if is_nine_am and nine_am_messages:
        header = f"☀️ <b>[오전 9시 정기 재고 현황]</b>\n📅 {now_kst.strftime('%Y-%m-%d %H:%M')}\n\n"
        send_telegram(header + "\n\n".join(nine_am_messages))
        should_save = True

    # 2) 재고 변동 발생 시
    elif all_changes:
        header = f"🚨 <b>[교보문고 재고 변동 알림]</b>\n⏰ {now_kst.strftime('%Y-%m-%d %H:%M')}\n\n"
        send_telegram(header + "\n\n".join(all_changes))
        should_save = True

    # 3) 최초 실행 또는 이전 기록이 없는 경우
    elif not prev_all_stock and current_all_stock:
        print("이전 재고 기록이 없어 현재 재고 상태를 기준점으로 Gist에 저장합니다.")
        should_save = True

    else:
        if not is_nine_am:
            print("재고 변동 없음 (Gist 업데이트 스킵)")

    # 데이터 업데이트
    if should_save:
        timestamp = now_kst.strftime("%Y-%m-%d %H:%M:%S")
        output = io.StringIO()
        writer = csv.writer(output)

        for book_title, stock_data in current_all_stock.items():
            for store_name, qty in stock_data.items():
                writer.writerow([timestamp, book_title, store_name, qty])

        new_csv_rows = output.getvalue()

        # CSV 줄바꿈 안전 처리
        if current_csv_content and not current_csv_content.endswith("\n"):
            current_csv_content += "\n"

        updated_csv_content = current_csv_content + new_csv_rows

        update_gist_data(current_all_stock, updated_csv_content)


if __name__ == "__main__":
    main()
