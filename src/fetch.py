"""
네이버부동산 내부 API 호출 모듈.

Playwright 헤드리스 브라우저 안에서 fetch()를 실행하므로
Authorization Bearer 토큰이 자동으로 포함된다.
"""

import json
import os
import random
import time

BASE_URL = "https://new.land.naver.com/api/articles"
NAVER_HOME = "https://new.land.naver.com/complexes"


def _build_params(cortar_no: str, max_price_10k: int, page: int) -> dict:
    return {
        "cortarNo": cortar_no,
        "realEstateType": "APT",
        "tradeType": "A1",
        "priceMin": "0",
        "priceMax": str(max_price_10k),
        "areaMin": "0",
        "areaMax": "900000",
        "sameAddressGroup": "false",
        "showArticle": "false",
        "page": str(page),
        "order": "rank",
    }


def _fetch_page_in_browser(page, cortar_no: str, max_price_10k: int, page_num: int) -> dict:
    """Playwright 페이지 컨텍스트 안에서 API 한 페이지 호출."""
    params = _build_params(cortar_no, max_price_10k, page_num)
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE_URL}?{query}"

    result = page.evaluate(f"""
        async () => {{
            const resp = await fetch('{url}', {{
                method: 'GET',
                headers: {{ 'Accept': 'application/json, text/plain, */*' }}
            }});
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return await resp.json();
        }}
    """)
    return result


def fetch_all_regions(regions: list[dict], max_price_10k: int) -> tuple[dict, dict]:
    """
    Playwright 브라우저 안에서 5개 구 순차 수집.
    브라우저 컨텍스트가 Authorization 헤더를 자동 포함한다.

    Returns:
        ({"강남구": [...], ...}, {"실패구": "에러메시지", ...})
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return {}, {"전체": "playwright 미설치 — pip install playwright 후 playwright install chromium"}

    results = {}
    errors = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        bpage = context.new_page()

        # 홈 페이지 로드 — JS가 실행되어 Authorization 토큰이 초기화됨
        print("[fetch] Playwright: 홈 페이지 로딩 중...")
        try:
            bpage.goto(NAVER_HOME, wait_until="networkidle", timeout=30000)
        except PWTimeout:
            print("[fetch] Playwright: 홈 로딩 타임아웃 (계속 진행)")
        # JS 토큰 초기화 충분히 대기
        bpage.wait_for_timeout(6000)
        print("[fetch] Playwright: 홈 로딩 완료, API 수집 시작")

        for i, region in enumerate(regions):
            name = region["name"]
            cortar_no = region["cortarNo"]
            all_articles = []
            page_num = 1

            try:
                while True:
                    data = _fetch_page_in_browser(bpage, cortar_no, max_price_10k, page_num)

                    if "articleList" not in data:
                        raise RuntimeError(
                            f"API 응답에 'articleList' 없음 — 구조 변경 의심 ({name})"
                        )

                    articles = data["articleList"]
                    if not articles:
                        break

                    for article in articles:
                        article["_region"] = name
                    all_articles.extend(articles)

                    if not data.get("isMoreData", False):
                        break

                    page_num += 1
                    time.sleep(random.uniform(1.0, 3.0))

                results[name] = all_articles
                print(f"[fetch] {name}: {len(all_articles)}건 수집")

            except Exception as e:
                errors[name] = str(e)
                print(f"[fetch] {name} 실패: {e}")

            if i < len(regions) - 1:
                time.sleep(random.uniform(2.0, 5.0))

        browser.close()

    return results, errors


def save_raw(articles_by_region: dict, output_dir: str) -> None:
    """구별 원본 JSON을 임시 파일로 저장."""
    os.makedirs(output_dir, exist_ok=True)
    for region_name, articles in articles_by_region.items():
        path = os.path.join(output_dir, f"raw_{region_name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
