"""
1차 필터링 및 급매·다주택자 플래그 탐지 모듈.

- 방 개수 필터: roomCount >= min_rooms
- 급매 탐지: 설명란에 urgent_keywords 포함 여부 (엄격 키워드 매칭)
- 다주택자 의심: 설명란에 '다주택자 매물' 등 명시 여부
"""

MULTIHOME_KEYWORDS = ["다주택자 매물", "다주택 매물", "다주택자매물"]


def _get_description(article: dict) -> str:
    """매물 설명 원문 추출. 여러 필드를 순서대로 시도."""
    return (
        article.get("articleFeatureDesc", "")
        or article.get("tagList", "")
        or ""
    )


def _get_room_count(article: dict) -> int:
    """방 개수 추출. 없으면 0 반환."""
    try:
        return int(article.get("roomCount", 0) or 0)
    except (TypeError, ValueError):
        return 0


def apply_room_filter(articles: list[dict], min_rooms: int) -> list[dict]:
    """방 개수 조건 미충족 매물 제거. roomCount 필드 없으면 필터 스킵."""
    if not articles:
        return articles
    # 전체 중 roomCount가 하나라도 있는지 확인
    has_room_field = any(a.get("roomCount") for a in articles)
    if not has_room_field:
        print(f"[filter] roomCount 필드 없음 — 방 개수 필터 스킵 (전체 {len(articles)}건 통과)")
        return articles
    return [a for a in articles if _get_room_count(a) >= min_rooms]


def flag_urgent(articles: list[dict], urgent_keywords: list[str]) -> list[dict]:
    """
    설명란에 urgent_keywords 포함 시 '급매' 플래그 추가.
    엄격 키워드 매칭 (LLM 맥락 판단 없음).
    """
    for article in articles:
        desc = _get_description(article)
        article["급매"] = any(kw in desc for kw in urgent_keywords)
    return articles


def flag_multihome(articles: list[dict]) -> list[dict]:
    """설명란에 다주택자 매물 명시 여부 플래그 추가."""
    for article in articles:
        desc = _get_description(article)
        article["다주택자_의심"] = any(kw in desc for kw in MULTIHOME_KEYWORDS)
    return articles


def apply_area_filter(articles: list[dict], min_area: int) -> list[dict]:
    """면적 조건 미충족 매물 제거."""
    before = len(articles)
    result = [a for a in articles if (a.get("area1") or 0) >= min_area]
    filtered_out = before - len(result)
    if filtered_out:
        print(f"[filter] 면적 {min_area}㎡ 미만 {filtered_out}건 제거 → {len(result)}건 남음")
    return result


def run_filter(articles: list[dict], filters: dict, urgent_keywords: list[str]) -> list[dict]:
    """
    전체 필터 파이프라인 실행.

    Args:
        articles: fetch.py에서 수집한 매물 리스트 (전 구 합산)
        filters: {"min_rooms": 3, "max_price_10k": 200000, "min_area": 80}
        urgent_keywords: ["급매", "급처", ...]

    Returns:
        필터 통과 + 플래그 부착된 매물 리스트
    """
    min_rooms = filters.get("min_rooms", 3)
    min_area = filters.get("min_area", 80)

    filtered = apply_room_filter(articles, min_rooms)
    filtered = apply_area_filter(filtered, min_area)
    filtered = flag_urgent(filtered, urgent_keywords)
    filtered = flag_multihome(filtered)

    return filtered
