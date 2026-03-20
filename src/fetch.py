"""
네이버부동산 내부 API 호출 모듈.
구별 아파트 매매 매물을 수집하고 원본 JSON을 반환한다.

토큰 획득: Playwright로 new.land.naver.com 접속 후
Authorization Bearer 토큰을 인터셉트하여 사용.
"""

import json
import os
import random
import time
import requests

BASE_URL = "https://new.land.naver.com/api/articles"
NAVER_HOME = "https://new.land.naver.com/complexes"

# 런타임에 채워질 헤더 (get_auth_headers() 호출 후 사용)
_runtime_headers: dict = {}


def _base_headers(auth_token: str = "", cookie: str = "") -> dict:
    h = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Referer": "https://new.land.naver.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    }
    if auth_token:
        h["Authorization"] = auth_token
    if cookie:
        h["Cookie"] = cookie
    return h


def get_auth_headers() -> dict:
    """
    Playwright로 Naver 부동산에 접속해 Authorization Bearer 토큰과 쿠키를 획득.
    실패 시 환경변수 NAVER_COOKIES만 사용한 헤더 반환.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        cookie = os.environ.get("NAVER_COOKIES", "")
        return _base_headers(cookie=cookie)

    auth_token = ""
    cookie_str = ""
    captured = {"done": False}

    def handle_request(request):
        if captured["done"]:
            return
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer ") and "land.naver.com/api" in request.url:
            auth_token_holder[0] = auth
            captured["done"] = True

    auth_token_holder = [""]

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            page.on("request", handle_request)

            try:
                page.goto(NAVER_HOME, timeout=20000, wait_until="domcontentloaded")
            except PWTimeout:
                pass

            # 토큰이 인터셉트될 때까지 최대 15초 대기
            for _ in range(30):
                if captured["done"]:
                    break
                time.sleep(0.5)

            # 쿠키 수집
            cookies = context.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            auth_token = auth_token_holder[0]
            browser.close()

    except Exception:
        pass

    # Playwright 실패 시 환경변수 쿠키 폴백
    if not cookie_str:
        cookie_str = os.environ.get("NAVER_COOKIES", "")

    return _base_headers(auth_token=auth_token, cookie=cookie_str)


def _debug_auth_status(headers: dict) -> str:
    auth = headers.get("Authorization", "")
    cookie = headers.get("Cookie", "")
    auth_info = f"token={'YES' if auth else 'NO'}"
    cookie_info = f"cookie={'YES(len=' + str(len(cookie)) + ')' if cookie else 'NO'}"
    return f"{auth_info}, {cookie_info}"


def _request_with_retry(url: str, params: dict, headers: dict, max_retry: int = 1) -> dict | None:
    """단일 GET 요청. 실패 시 1회 재시도."""
    for attempt in range(max_retry + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            response.encoding = "utf-8-sig"
            return response.json()
        except requests.exceptions.HTTPError as e:
            if attempt < max_retry:
                time.sleep(3)
                continue
            raise RuntimeError(f"HTTP 오류 {e.response.status_code}: {url}") from e
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < max_retry:
                time.sleep(3)
                continue
            raise RuntimeError(f"네트워크 오류: {e}") from e
        except (ValueError, KeyError) as e:
            raise RuntimeError(f"API 응답 파싱 실패 — 구조 변경 의심: {e}") from e


def fetch_region(region: dict, max_price_10k: int, headers: dict) -> list[dict]:
    """
    단일 구의 아파트 매매 매물 전체를 수집한다.

    Args:
        region: {"name": "강남구", "cortarNo": "1168000000"}
        max_price_10k: 호가 상한 (만원 단위, 예: 200000 = 20억)
        headers: Authorization + Cookie 포함 헤더

    Returns:
        매물 dict 리스트 (articleList 필드)
    """
    cortar_no = region["cortarNo"]
    region_name = region["name"]
    all_articles = []
    page = 1

    while True:
        params = {
            "cortarNo": cortar_no,
            "realEstateType": "APT",
            "tradeType": "A1",
            "priceMin": 0,
            "priceMax": max_price_10k,
            "areaMin": 0,
            "areaMax": 900000,
            "sameAddressGroup": "false",
            "showArticle": "false",
            "page": page,
            "order": "rank",
        }

        data = _request_with_retry(BASE_URL, params, headers)

        if data is None:
            break

        if "articleList" not in data:
            raise RuntimeError(
                f"API 응답에 'articleList' 필드 없음 — 구조 변경 감지 ({region_name})"
            )

        articles = data["articleList"]
        if not articles:
            break

        for article in articles:
            article["_region"] = region_name

        all_articles.extend(articles)

        is_more = data.get("isMoreData", False)
        if not is_more:
            break

        page += 1
        time.sleep(random.uniform(1.0, 3.0))

    return all_articles


def fetch_all_regions(regions: list[dict], max_price_10k: int) -> tuple[dict, dict]:
    """
    5개 구 순차 수집. 개별 구 실패 시 스킵하고 로그에 기록.

    Returns:
        ({"강남구": [...], ...}, {"실패구": "에러메시지", ...})
    """
    headers = get_auth_headers()

    results = {}
    errors = {}

    for i, region in enumerate(regions):
        name = region["name"]
        try:
            articles = fetch_region(region, max_price_10k, headers)
            results[name] = articles
        except RuntimeError as e:
            errors[name] = str(e)

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
