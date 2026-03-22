"""
네이버부동산 내부 API 호출 모듈.

Playwright headed 브라우저로 홈 페이지를 로드한 뒤,
페이지가 자연스럽게 발생시키는 api/articles 요청을 가로채
Authorization Bearer 토큰을 획득한다.
이후 requests로 나머지 페이지를 수집한다.
"""

import json
import os
import random
import time

import requests

BASE_URL = "https://new.land.naver.com/api/articles"
# 강남구 목록 페이지 — 로드 시 api/articles 요청이 자동 발생
NAVER_LISTING_URL = (
    "https://new.land.naver.com/complexes"
    "?ms=37.4979,127.0276,14"
    "&a=APT&b=A1"
    "&e=RETAIL"
)


def _get_auth_token_via_playwright() -> tuple[str, str]:
    """
    Playwright headed 브라우저로 Naver를 방문해
    (authorization_header, cookie_header) 를 반환한다.
    실패 시 ("", "") 반환.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    auth_token = ""
    cookie_str = ""
    captured = {"done": False}

    def handle_request(request):
        if captured["done"]:
            return
        if "api/articles" in request.url or "api/pre-sale" in request.url:
            hdrs = request.headers
            auth = hdrs.get("authorization", "")
            cookie = hdrs.get("cookie", "")
            if auth:
                auth_token_ref.append(auth)
                cookie_ref.append(cookie)
                captured["done"] = True

    auth_token_ref = []
    cookie_ref = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.on("request", handle_request)

        print("[fetch] Playwright: 페이지 로딩 중 (토큰 대기)...")
        try:
            page.goto(NAVER_LISTING_URL, wait_until="domcontentloaded", timeout=25000)
        except PWTimeout:
            print("[fetch] Playwright: 페이지 로딩 타임아웃")

        # 토큰 캡처될 때까지 최대 15초 대기
        for _ in range(30):
            if captured["done"]:
                break
            time.sleep(0.5)

        browser.close()

    if auth_token_ref:
        auth_token = auth_token_ref[0]
        cookie_str = cookie_ref[0] if cookie_ref else ""
        print(f"[fetch] 토큰 획득 성공: {auth_token[:40]}...")
    else:
        print("[fetch] 토큰 획득 실패 — 환경변수 쿠키로 폴백")

    return auth_token, cookie_str


def _make_headers(auth_token: str, cookie_str: str) -> dict:
    hdrs = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://new.land.naver.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    }
    if auth_token:
        hdrs["Authorization"] = auth_token
    # 쿠키: Playwright 캡처 우선, 없으면 환경변수
    cookie = cookie_str or os.environ.get("NAVER_COOKIES", "")
    if cookie:
        hdrs["Cookie"] = cookie
    return hdrs


def _request_page(params: dict, headers: dict) -> dict:
    resp = requests.get(BASE_URL, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_all_regions(regions: list[dict], max_price_10k: int) -> tuple[dict, dict]:
    """
    5개 구 순차 수집.

    Returns:
        ({"강남구": [...], ...}, {"실패구": "에러메시지", ...})
    """
    auth_token, cookie_str = _get_auth_token_via_playwright()
    headers = _make_headers(auth_token, cookie_str)

    results = {}
    errors = {}

    for i, region in enumerate(regions):
        name = region["name"]
        cortar_no = region["cortarNo"]
        all_articles = []
        page_num = 1

        try:
            while True:
                params = {
                    "cortarNo": cortar_no,
                    "realEstateType": "APT",
                    "tradeType": "A1",
                    "priceMin": "0",
                    "priceMax": str(max_price_10k),
                    "areaMin": "0",
                    "areaMax": "900000",
                    "sameAddressGroup": "false",
                    "showArticle": "false",
                    "page": str(page_num),
                    "order": "rank",
                }
                data = _request_page(params, headers)

                if "articleList" not in data:
                    raise RuntimeError(f"'articleList' 없음 — 구조 변경 의심 ({name})")

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

    return results, errors


def save_raw(articles_by_region: dict, output_dir: str) -> None:
    """구별 원본 JSON을 임시 파일로 저장."""
    os.makedirs(output_dir, exist_ok=True)
    for region_name, articles in articles_by_region.items():
        path = os.path.join(output_dir, f"raw_{region_name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
