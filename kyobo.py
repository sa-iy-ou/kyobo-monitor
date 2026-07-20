from playwright.sync_api import sync_playwright


def get_stock(book_id):

    url = f"https://product.kyobobook.co.kr/detail/{book_id}"

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=False)

        page = browser.new_page()

        page.goto(url)

        page.get_by_role("button", name="매장 재고 · 위치").click()

        page.get_by_text("광화문").wait_for(timeout=10000)

        rows = page.locator("tr")

        stock = {}

        for i in range(4, rows.count(), 2):

            stores = rows.nth(i).inner_text().split()

            counts = rows.nth(i + 1).inner_text().split()

            for store, count in zip(stores, counts):

                stock[store] = int(count)

        browser.close()

        return stock