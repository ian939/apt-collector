"""
CSV upsert 모듈.
매물 ID 기준으로 신규 추가 또는 기존 행 갱신.
"""

import os
import re
import time
from datetime import datetime

import pandas as pd


def _parse_price(raw) -> int:
    """만원 단위 호가 파싱. '8억5,000', '15억', '5000' 등 모두 지원."""
    if not raw:
        return 0
    s = str(raw).replace(",", "").replace(" ", "")
    if s.isdigit():
        return int(s)
    m = re.match(r'(\d+)억(\d*)', s)
    if m:
        return int(m.group(1)) * 10000 + (int(m.group(2)) if m.group(2) else 0)
    nums = re.findall(r'\d+', s)
    return int(nums[0]) if nums else 0

CSV_COLUMNS = [
    "매물ID", "수집일자", "지역구", "단지명", "동호수",
    "방개수", "호가", "실거래가", "실거래_날짜", "면적", "초품아", "급매",
    "다주택자_의심", "판별_사유", "매물_설명", "매물_URL", "확인매물", "상태", "최종_업데이트",
]


def _build_url(article: dict) -> str:
    article_no = str(article.get("articleNo", ""))
    complex_no = article.get("complexNo", "")
    lat = article.get("latitude", "")
    lng = article.get("longitude", "")
    if complex_no and lat and lng:
        return (
            f"https://new.land.naver.com/complexes/{complex_no}"
            f"?ms={lat},{lng},16&a=APT:PRE&b=A1&e=RETAIL&articleNo={article_no}"
        )
    if lat and lng:
        return (
            f"https://new.land.naver.com/"
            f"?ms={lat},{lng},16&a=APT:PRE&b=A1&e=RETAIL&articleNo={article_no}"
        )
    return f"https://new.land.naver.com/articles/{article_no}"


def _to_row(article: dict, analysis: dict) -> dict:
    """API 응답 + 분석 결과를 CSV 행 형태로 변환."""
    article_no = str(article.get("articleNo", ""))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")

    price_raw = article.get("dealOrWarrantPrc", "") or article.get("prc", "")
    price = _parse_price(price_raw)

    # 면적
    area = article.get("area1", "") or article.get("areaName", "")

    # 동/층
    floor_info = article.get("floorInfo", "")

    # 확인매물 날짜: YYYYMMDD → YY.MM.DD. 형식
    confirm_ymd_raw = str(article.get("articleConfirmYmd", "") or "")
    if len(confirm_ymd_raw) == 8 and confirm_ymd_raw.isdigit():
        confirm_ymd = f"{confirm_ymd_raw[2:4]}.{confirm_ymd_raw[4:6]}.{confirm_ymd_raw[6:8]}."
    else:
        confirm_ymd = confirm_ymd_raw

    return {
        "매물ID": article_no,
        "수집일자": today,
        "지역구": article.get("_region", ""),
        "단지명": article.get("articleName", ""),
        "동호수": floor_info,
        "방개수": article.get("roomCount", 0),
        "호가": price,
        "실거래가": article.get("_real_price", ""),
        "실거래_날짜": article.get("_real_price_date", ""),
        "면적": area,
        "초품아": analysis.get("초품아", False),
        "급매": article.get("급매", False),
        "다주택자_의심": analysis.get("다주택자_의심", False) or article.get("다주택자_의심", False),
        "판별_사유": analysis.get("판별_사유", ""),
        "매물_설명": article.get("articleFeatureDesc", ""),
        "매물_URL": _build_url(article),
        "확인매물": confirm_ymd,
        "상태": "활성",
        "최종_업데이트": now,
    }


def upsert_listings(
    articles: list[dict],
    analysis_map: dict[str, dict],
    csv_path: str,
) -> dict:
    """
    CSV에 매물을 upsert한다.

    Args:
        articles: 필터 통과 매물 리스트
        analysis_map: {article_no: {초품아, 다주택자_의심, 판별_사유}}
        csv_path: 누적 CSV 경로

    Returns:
        {"new": int, "updated": int, "total": int}
    """
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    # 기존 CSV 로드 또는 빈 DataFrame 생성
    if os.path.exists(csv_path):
        existing = pd.read_csv(csv_path, dtype={"매물ID": str})
        # 컬럼 추가/변경 시 기존 파일에 없는 컬럼을 빈값으로 추가
        for col in CSV_COLUMNS:
            if col not in existing.columns:
                existing[col] = ""
        existing = existing[CSV_COLUMNS]  # 컬럼 순서 통일
    else:
        existing = pd.DataFrame(columns=CSV_COLUMNS)

    existing["매물ID"] = existing["매물ID"].astype(str)
    # 문자열 컬럼이 빈 값으로 인해 float64로 읽히는 경우 방지
    for col in ["실거래가", "실거래_날짜", "확인매물", "동호수", "판별_사유", "매물_설명"]:
        if col in existing.columns:
            existing[col] = existing[col].astype(object)

    # 입력 매물 중복 제거 (같은 articleNo가 여러 페이지에 걸쳐 중복 수집될 수 있음)
    seen = set()
    deduped = []
    for a in articles:
        aid = str(a.get("articleNo", ""))
        if aid and aid not in seen:
            seen.add(aid)
            deduped.append(a)
    articles = deduped

    new_count = 0
    updated_count = 0
    rows_to_upsert = []

    for article in articles:
        article_no = str(article.get("articleNo", ""))
        if not article_no:
            continue

        analysis = analysis_map.get(article_no, {})
        new_row = _to_row(article, analysis)

        if article_no in existing["매물ID"].values:
            # 갱신: 호가·설명·최종_업데이트만 업데이트 (상태는 건드리지 않음)
            idx = existing.index[existing["매물ID"] == article_no][0]
            existing.at[idx, "호가"] = new_row["호가"]
            existing.at[idx, "매물_설명"] = new_row["매물_설명"]
            existing.at[idx, "수집일자"] = new_row["수집일자"]
            existing.at[idx, "최종_업데이트"] = new_row["최종_업데이트"]
            existing.at[idx, "초품아"] = new_row["초품아"]
            existing.at[idx, "급매"] = new_row["급매"]
            existing.at[idx, "다주택자_의심"] = new_row["다주택자_의심"]
            existing.at[idx, "판별_사유"] = new_row["판별_사유"]
            existing.at[idx, "확인매물"] = new_row["확인매물"]
            if new_row.get("실거래가"):
                existing.at[idx, "실거래가"] = new_row["실거래가"]
                existing.at[idx, "실거래_날짜"] = new_row["실거래_날짜"]
            updated_count += 1
        else:
            rows_to_upsert.append(new_row)
            new_count += 1

    if rows_to_upsert:
        new_df = pd.DataFrame(rows_to_upsert, columns=CSV_COLUMNS)
        existing = pd.concat([existing, new_df], ignore_index=True)

    # 매물 ID 유일성 검증
    if existing["매물ID"].duplicated().any():
        dupes = existing[existing["매물ID"].duplicated()]["매물ID"].tolist()
        raise RuntimeError(f"CSV upsert 후 중복 매물 ID 발견: {dupes}")

    for attempt in range(5):
        try:
            existing.to_csv(csv_path, index=False, encoding="utf-8-sig")
            break
        except PermissionError:
            if attempt == 4:
                raise RuntimeError(
                    f"CSV 저장 실패: '{csv_path}' 파일이 다른 프로그램(Excel 등)에서 열려 있습니다. 닫고 다시 실행하세요."
                )
            print(f"[upsert] CSV 파일 잠김, {3}초 후 재시도 ({attempt+1}/5)...")
            time.sleep(3)

    return {
        "new": new_count,
        "updated": updated_count,
        "total": len(existing),
    }
