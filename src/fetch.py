"""
네이버부동산 내부 API 호출 모듈.

Playwright headed 브라우저로 Naver 페이지를 방문하여 Authorization 토큰을 획득한 후,
동일한 브라우저 컨텍스트에서 fetch()로 API를 호출한다.
(requests 직접 호출 시 TLS 핑거프린팅으로 차단되므로 Playwright 사용)
"""

import json
import os
import random
import time

BASE_URL = "/api/articles"
NAVER_ORIGIN = "https://new.land.naver.com"
NAVER_LISTING_URL = (
    "https://new.land.naver.com/complexes"
    "?ms=37.4979,127.0276,13"
    "&a=APT"
    "&b=A1"
    "&e=RETAIL"
    "&h=1168010300"
)

_INTERCEPT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.__capturedAuth = null;

    let _currentFetch = window.fetch;
    function _wrapFetch(fn) {
        return function(url, opts) {
            try {
                const h = (opts && opts.headers) ? opts.headers : {};
                const auth = h['authorization'] || h['Authorization'];
                if (auth && String(url).includes('/api/')) {
                    window.__capturedAuth = auth;
                }
            } catch(e) {}
            return fn.apply(this, arguments);
        };
    }
    Object.defineProperty(window, 'fetch', {
        configurable: true, enumerable: true,
        get: () => _currentFetch,
        set: (newFn) => { _currentFetch = _wrapFetch(newFn); }
    });
    _currentFetch = _wrapFetch(window.fetch);

    const _origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
    const _origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(m, url) {
        this.__xhrUrl = url; return _origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        if (name.toLowerCase() === 'authorization' && String(this.__xhrUrl||'').includes('/api/')) {
            window.__capturedAuth = value;
        }
        return _origSetHeader.apply(this, arguments);
    };
"""


def fetch_all_regions(regions: list[dict], max_price_10k: int) -> tuple[dict, dict]:
    """
    Playwright headed 브라우저에서 토큰을 획득한 후,
    동일 컨텍스트에서 fetch()로 5개 구 순차 수집.

    Returns:
        ({"강남구": [...], ...}, {"실패구": "에러메시지", ...}, auth_token)
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return {}, {"전체": "playwright 미설치"}, ""

    results = {}
    errors = {}
    _auth_token = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )

        # 환경변수 쿠키 주입
        env_cookie = os.environ.get("NAVER_COOKIES", "")
        if env_cookie:
            cookie_list = []
            for part in env_cookie.split("; "):
                if "=" in part:
                    name, val = part.split("=", 1)
                    for domain in ["new.land.naver.com", ".naver.com"]:
                        cookie_list.append({
                            "name": name.strip(), "value": val.strip(),
                            "domain": domain, "path": "/",
                        })
            context.add_cookies(cookie_list)

        page = context.new_page()
        page.add_init_script(_INTERCEPT_SCRIPT)

        # 페이지 로드 + 토큰 초기화 대기
        print("[fetch] Playwright: 페이지 로딩 중...")
        try:
            page.goto(NAVER_LISTING_URL, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(5000)
        except PWTimeout:
            print("[fetch] 페이지 로딩 타임아웃 (계속)")
        except Exception as e:
            print(f"[fetch] goto 오류: {e}")

        try:
            _auth_token = page.evaluate("() => window.__capturedAuth || ''") or ""
        except Exception:
            pass

        if _auth_token:
            print(f"[fetch] 토큰 획득 성공: {_auth_token[:40]}...")
        else:
            print("[fetch] 토큰 미획득 — 쿠키만으로 시도")

        auth_token = _auth_token  # 로컬 참조용

        # 같은 Playwright 컨텍스트에서 API 호출
        for i, region in enumerate(regions):
            name = region["name"]
            cortar_no = region["cortarNo"]
            all_articles = []
            page_num = 1

            try:
                while True:
                    qs = (
                        f"cortarNo={cortar_no}&realEstateType=APT&tradeType=A1"
                        f"&priceMin=0&priceMax={max_price_10k}"
                        f"&areaMin=0&areaMax=900000"
                        f"&sameAddressGroup=false&showArticle=false"
                        f"&page={page_num}&order=rank"
                    )
                    url = f"{NAVER_ORIGIN}{BASE_URL}?{qs}"

                    data = page.evaluate(f"""
                        async () => {{
                            const auth = window.__capturedAuth || '';
                            const r = await fetch('{url}', {{
                                headers: {{
                                    'Authorization': auth,
                                    'Accept': 'application/json, text/plain, */*',
                                    'Referer': 'https://new.land.naver.com/'
                                }}
                            }});
                            const text = await r.text();
                            if (!r.ok) throw new Error('HTTP ' + r.status + ': ' + text.substring(0, 300));
                            return JSON.parse(text);
                        }}
                    """)

                    if "articleList" not in data:
                        raise RuntimeError(f"'articleList' 없음 ({name})")

                    articles = data["articleList"]
                    if not articles:
                        break

                    for article in articles:
                        article["_region"] = name
                    all_articles.extend(articles)

                    if not data.get("isMoreData", False):
                        break

                    page_num += 1
                    if page_num > 50:  # 안전장치: 최대 50페이지
                        print(f"[fetch] {name}: 50페이지 한도 도달, 수집 중단")
                        break
                    time.sleep(random.uniform(1.0, 2.0))

                results[name] = all_articles
                print(f"[fetch] {name}: {len(all_articles)}건 수집")

            except Exception as e:
                errors[name] = str(e)
                print(f"[fetch] {name} 실패: {e}")

            if i < len(regions) - 1:
                time.sleep(random.uniform(2.0, 5.0))

        browser.close()

    return results, errors, _auth_token


def enrich_with_realprices(articles: list[dict], auth_token: str) -> list[dict]:
    """
    최종 매물(40-50건)에 대해 실거래가·날짜를 추가한다.
    article detail API → complexNo → complex price history API 순으로 호출.
    """
    if not articles or not auth_token:
        return articles

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return articles

    from datetime import datetime
    year = datetime.now().year
    sample_detail_saved = False
    sample_prices_saved = False

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        env_cookie = os.environ.get("NAVER_COOKIES", "")
        if env_cookie:
            cookie_list = []
            for part in env_cookie.split("; "):
                if "=" in part:
                    cname, cval = part.split("=", 1)
                    for domain in ["new.land.naver.com", ".naver.com"]:
                        cookie_list.append({"name": cname.strip(), "value": cval.strip(), "domain": domain, "path": "/"})
            context.add_cookies(cookie_list)

        page = context.new_page()
        page.add_init_script(f"window.__capturedAuth = {json.dumps(auth_token)};")
        try:
            page.goto(NAVER_LISTING_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)
        except Exception:
            pass

        print(f"[fetch] 실거래가 조회 시작: {len(articles)}건")

        for article in articles:
            ano = article.get("articleNo", "")
            if not ano:
                continue
            try:
                detail = page.evaluate(f"""
                    async () => {{
                        const auth = window.__capturedAuth || '';
                        const r = await fetch('https://new.land.naver.com/api/articles/{ano}', {{
                            headers: {{'Authorization': auth, 'Referer': 'https://new.land.naver.com/', 'Accept': 'application/json'}}
                        }});
                        return r.ok ? await r.json() : null;
                    }}
                """)

                if not sample_detail_saved and detail:
                    os.makedirs("output", exist_ok=True)
                    with open("output/sample_detail.json", "w", encoding="utf-8") as f:
                        json.dump(detail, f, ensure_ascii=False, indent=2)
                    sample_detail_saved = True

                if not detail:
                    continue

                # hscpNo(단지번호)와 ptpNo(평형번호) 추출
                article_detail = detail.get("articleDetail") or {}
                hscp_no = str(article_detail.get("hscpNo", ""))
                ptp_no = str(article_detail.get("ptpNo", ""))

                if hscp_no:
                    article["complexNo"] = hscp_no  # URL 생성에 사용


                    price_list = []
                    prices = page.evaluate(f"""
                        async () => {{
                            const auth = window.__capturedAuth || '';
                            const r = await fetch(
                                'https://new.land.naver.com/api/complexes/{hscp_no}/prices/real?complexNo={hscp_no}&tradeType=A1&areaNo={ptp_no}&type=table',
                                {{headers: {{'Authorization': auth, 'Referer': 'https://new.land.naver.com/', 'Accept': 'application/json'}}}}
                            );
                            return r.ok ? await r.json() : null;
                        }}
                    """)

                    if not sample_prices_saved and prices is not None:
                        os.makedirs("output", exist_ok=True)
                        with open("output/sample_prices.json", "w", encoding="utf-8") as f:
                            json.dump(prices, f, ensure_ascii=False, indent=2)
                        print(f"[fetch] 실거래가 응답 구조: {list(prices.keys()) if isinstance(prices, dict) else type(prices)}")
                        sample_prices_saved = True

                    if prices:
                        monthly_list = prices.get("realPriceOnMonthList") or []
                        for month_data in monthly_list:
                            # 월별 묶음 → 안에 실거래 리스트가 있을 수 있음
                            inner = (
                                month_data.get("realPriceList")
                                or month_data.get("list")
                                or []
                            )
                            if inner:
                                latest = inner[0]
                                ym = str(month_data.get("tradeYearMonth", ""))
                                day = str(latest.get("dealDay", ""))
                                date_str = f"{ym[:4]}.{ym[4:6]}.{day.zfill(2)}." if len(ym) == 6 else ym
                                article["_real_price"] = latest.get("dealOrWarrantPrc") or latest.get("prc", "")
                                article["_real_price_date"] = date_str
                                break
                            elif month_data.get("dealOrWarrantPrc") or month_data.get("prc"):
                                # 평탄한 구조
                                ym = str(month_data.get("tradeYearMonth", ""))
                                day = str(month_data.get("dealDay", ""))
                                date_str = f"{ym[:4]}.{ym[4:6]}.{day.zfill(2)}." if len(ym) == 6 else ym
                                article["_real_price"] = month_data.get("dealOrWarrantPrc") or month_data.get("prc", "")
                                article["_real_price_date"] = date_str
                                break

            except Exception as e:
                print(f"[fetch] 실거래가 조회 실패 ({ano}): {e}")

        browser.close()

    print(f"[fetch] 실거래가 조회 완료")
    return articles


def save_raw(articles_by_region: dict, output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    for region_name, articles in articles_by_region.items():
        path = os.path.join(output_dir, f"raw_{region_name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
