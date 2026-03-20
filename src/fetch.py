"""
네이버부동산 내부 API 호출 모듈.
구별 아파트 매매 매물을 수집하고 원본 JSON을 반환한다.
"""

import json
import os
import random
import time
import requests

BASE_URL = "https://new.land.naver.com/api/articles"

_cookie = os.environ.get("NAVER_COOKIES", "")

HEADERS = {
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Host": "new.land.naver.com",
    "Referer": "https://new.land.naver.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    **({"Cookie": _cookie} if _cookie else {}),
}


def _request_with_retry(url: str, params: dict, max_retry: int = 1) -> dict | None:
    """단일 GET 요청. 실패 시 1회 재시도."""
    for attempt in range(max_retry + 1):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=15)
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


def fetch_region(region: dict, max_price_10k: int) -> list[dict]:
    """
    단일 구의 아파트 매매 매물 전체를 수집한다.

    Args:
        region: {"name": "강남구", "cortarNo": "1168000000"}
        max_price_10k: 호가 상한 (만원 단위, 예: 200000 = 20억)

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

        data = _request_with_retry(BASE_URL, params)

        if data is None:
            break

        # API 응답 구조 검증
        if "articleList" not in data:
            raise RuntimeError(
                f"API 응답에 'articleList' 필드 없음 — 구조 변경 감지 ({region_name})"
            )

        articles = data["articleList"]
        if not articles:
            break  # 빈 페이지 → 수집 완료

        # 각 매물에 지역구 정보 부착
        for article in articles:
            article["_region"] = region_name

        all_articles.extend(articles)

        # 마지막 페이지 여부 확인
        is_more = data.get("isMoreData", False)
        if not is_more:
            break

        page += 1
        # 구간 딜레이 (1~3초 랜덤)
        time.sleep(random.uniform(1.0, 3.0))

    return all_articles


def fetch_all_regions(regions: list[dict], max_price_10k: int) -> dict[str, list]:
    """
    5개 구 순차 수집. 개별 구 실패 시 스킵하고 로그에 기록.

    Returns:
        {"강남구": [...], "강동구": [...], ...}
        실패한 구는 포함되지 않음
    """
    results = {}
    errors = {}

    for i, region in enumerate(regions):
        name = region["name"]
        try:
            articles = fetch_region(region, max_price_10k)
            results[name] = articles
        except RuntimeError as e:
            errors[name] = str(e)

        # 구 사이 딜레이 (2~5초)
        if i < len(regions) - 1:
            time.sleep(random.uniform(2.0, 5.0))

    return results, errors


def save_raw(articles_by_region: dict, output_dir: str) -> None:
    """구별 원본 JSON을 임시 파일로 저장."""
    import os
    os.makedirs(output_dir, exist_ok=True)
    for region_name, articles in articles_by_region.items():
        path = os.path.join(output_dir, f"raw_{region_name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
