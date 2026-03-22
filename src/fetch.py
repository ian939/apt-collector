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
# 강남구 아파트 매매 목록 — 로드 시 api/articles 요청 자동 발생
NAVER_LISTING_URL = (
    "https://new.land.naver.com/complexes"
    "?ms=37.4979,127.0276,13"
    "&a=APT"
    "&b=A1"
    "&e=RETAIL"
    "&h=1168010300"  # 강남구 법정동코드
)


_INTERCEPT_SCRIPT = """
    window.__capturedAuth = null;

    // fetch 오버라이드
    const _origFetch = window.fetch;
    window.fetch = async function(url, opts) {
        try {
            const hdrs = opts && opts.headers ? opts.headers : {};
            const auth = hdrs['authorization'] || hdrs['Authorization'];
            if (auth && String(url).includes('/api/')) {
                window.__capturedAuth = auth;
            }
        } catch(e) {}
        return _origFetch.apply(this, arguments);
    };

    // XMLHttpRequest 오버라이드
    const _origOpen = XMLHttpRequest.prototype.open;
    const _origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.open = function(method, url) {
        this.__url = url;
        return _origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        if (name.toLowerCase() === 'authorization' && String(this.__url || '').includes('/api/')) {
            window.__capturedAuth = value;
        }
        return _origSetHeader.apply(this, arguments);
    };
"""


def _get_auth_token_via_playwright() -> tuple[str, str]:
    """
    Playwright headed 브라우저로 Naver를 방문해 fetch/XHR을 후킹,
    Authorization 토큰을 캡처해 반환한다.
    실패 시 ("", "") 반환.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

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
        # 페이지 JS 실행 전에 인터셉터 주입
        page.add_init_script(_INTERCEPT_SCRIPT)

        # 환경변수 쿠키를 Playwright 컨텍스트에 주입 (Naver 404 방지)
        env_cookie = os.environ.get("NAVER_COOKIES", "")
        if env_cookie:
            cookie_list = []
            for part in env_cookie.split("; "):
                if "=" in part:
                    name, val = part.split("=", 1)
                    for domain in ["new.land.naver.com", ".naver.com"]:
                        cookie_list.append({
                            "name": name.strip(),
                            "value": val.strip(),
                            "domain": domain,
                            "path": "/",
                        })
            context.add_cookies(cookie_list)
            print(f"[fetch] 쿠키 {len(env_cookie)//2}자 주입 완료")

        print("[fetch] Playwright: 페이지 로딩 중 (토큰 후킹)...")
        try:
            page.goto(NAVER_LISTING_URL, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(8000)  # JS 토큰 초기화 대기
        except PWTimeout:
            print("[fetch] Playwright: 로딩 타임아웃 (계속 진행)")
        except Exception as e:
            print(f"[fetch] Playwright goto 오류: {e}")

        auth_token = ""
        try:
            auth_token = page.evaluate("() => window.__capturedAuth || ''") or ""
            cookies = context.cookies("https://new.land.naver.com")
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies) or env_cookie
        except Exception as e:
            print(f"[fetch] 토큰 읽기 오류: {e}")
            cookie_str = env_cookie
        finally:
            browser.close()

    if auth_token:
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
