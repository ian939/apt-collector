"""
네이버부동산 매물 탐색 에이전트 — 진입점.

Step 1: 설정 로드
Step 2: 지역구별 매물 수집
Step 3: 1차 필터링 (방 개수)
Step 4: 급매·다주택자 플래그
Step 5: 초품아 판별 (LLM)
Step 6: CSV upsert
Step 7: Slack 알림
Step 8: 로그 저장

실행: python main.py
"""

import json
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from src.fetch import fetch_all_regions, save_raw
from src.filter import run_filter
from src.analyzer import analyze_listings
from src.upsert import upsert_listings
from src.notify import send_urgent_alerts, notify_complete, notify_error
from src.log import RunLogger

# 로컬 개발 시 .env 파일 로드
load_dotenv()

OUTPUT_DIR = "output"
TEMP_DIR = os.path.join(OUTPUT_DIR, "temp")
LOG_DIR = os.path.join(OUTPUT_DIR, "logs")
CSV_PATH = os.path.join(OUTPUT_DIR, "listings.csv")
CONFIG_PATH = "config.json"


def load_config() -> dict:
    """config.json 로드 및 필수 필드 검증."""
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"config.json 파일이 없습니다: {CONFIG_PATH}")

    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)

    # 필수 필드 검증
    required = ["regions", "filters", "urgent_keywords"]
    for key in required:
        if key not in config:
            raise ValueError(f"config.json에 필수 항목 누락: '{key}'")

    if not isinstance(config["regions"], list) or not config["regions"]:
        raise ValueError("config.json의 'regions'는 비어있지 않은 리스트여야 합니다.")

    return config


def flatten_articles(articles_by_region: dict) -> list[dict]:
    """구별 매물 딕셔너리를 단일 리스트로 병합."""
    result = []
    for articles in articles_by_region.values():
        result.extend(articles)
    return result


def main() -> None:
    logger = RunLogger(LOG_DIR)
    start_time = datetime.now()
    logger.info(f"=== 매물 수집 시작: {start_time.strftime('%Y-%m-%d %H:%M:%S')} ===")

    # ──────────────────────────────────────────
    # Step 1: 설정 로드
    # ──────────────────────────────────────────
    logger.info("Step 1: 설정 로드")
    try:
        config = load_config()
        regions = config["regions"]
        filters = config["filters"]
        urgent_keywords = config["urgent_keywords"]
        max_price_10k = filters.get("max_price_10k", 200000)
        logger.info(f"  대상 지역: {[r['name'] for r in regions]}")
        logger.info(f"  호가 상한: {max_price_10k // 10000}억원, 방 개수 최소: {filters.get('min_rooms', 3)}")
    except Exception as e:
        msg = f"Step 1 실패 — 설정 로드 오류: {e}"
        logger.error(msg)
        notify_error(msg)
        sys.exit(1)

    # ──────────────────────────────────────────
    # Step 2: 지역구별 매물 수집
    # ──────────────────────────────────────────
    logger.info("Step 2: 지역구별 매물 수집")
    try:
        articles_by_region, fetch_errors = fetch_all_regions(regions, max_price_10k)

        for region_name, err in fetch_errors.items():
            logger.warning(f"  {region_name} 수집 실패 (스킵): {err}")

        if not articles_by_region:
            msg = "Step 2 실패 — 모든 구 수집 실패. API 응답 구조 변경 의심."
            logger.error(msg)
            notify_error(msg)
            logger.save()
            sys.exit(1)

        # 구조 변경 감지: 파싱 실패는 fetch.py에서 RuntimeError로 전파됨
        # 수집 건수 로그
        total_raw = sum(len(v) for v in articles_by_region.values())
        for name, articles in articles_by_region.items():
            logger.info(f"  {name}: {len(articles)}건")
        logger.info(f"  총 수집: {total_raw}건")

        # 임시 파일 저장
        os.makedirs(TEMP_DIR, exist_ok=True)
        save_raw(articles_by_region, TEMP_DIR)

    except RuntimeError as e:
        msg = f"Step 2 실패 — {e}"
        logger.error(msg)
        notify_error(msg)
        logger.save()
        sys.exit(1)

    # ──────────────────────────────────────────
    # Step 3 & 4: 1차 필터링 + 급매·다주택자 플래그
    # ──────────────────────────────────────────
    logger.info("Step 3: 1차 필터링 (방 개수)")
    all_articles = flatten_articles(articles_by_region)
    filtered = run_filter(all_articles, filters, urgent_keywords)

    urgent_count = sum(1 for a in filtered if a.get("급매"))
    multihome_count = sum(1 for a in filtered if a.get("다주택자_의심"))
    logger.info(f"  필터 통과: {len(filtered)}건 (전체 {total_raw}건 중)")
    logger.info(f"  급매 후보: {urgent_count}건, 다주택자 의심: {multihome_count}건")

    # ──────────────────────────────────────────
    # Step 5: 초품아 판별 (LLM)
    # ──────────────────────────────────────────
    # LLM 분석은 급매 후보에만 적용 (전체 분석 시 비용/시간 과다)
    urgent_articles = [a for a in filtered if a.get("급매")]
    logger.info(f"Step 5: 초품아 판별 LLM 분석 ({len(urgent_articles)}건 급매 후보 → 배치 처리)")
    analysis_results = []
    if urgent_articles:
        try:
            analysis_results = analyze_listings(urgent_articles)
            chopo_count = sum(1 for r in analysis_results if r.get("초품아") is True)
            uncertain_count = sum(1 for r in analysis_results if r.get("초품아") == "불확실")
            logger.info(f"  초품아: {chopo_count}건, 불확실: {uncertain_count}건")
        except Exception as e:
            logger.warning(f"  LLM 분석 실패 (계속 진행): {e}")

    # 분석 결과를 article_no → 결과 딕셔너리로 매핑
    analysis_map = {str(r["id"]): r for r in analysis_results}

    # ──────────────────────────────────────────
    # Step 6: CSV upsert
    # ──────────────────────────────────────────
    logger.info("Step 6: CSV upsert")
    try:
        upsert_stats = upsert_listings(filtered, analysis_map, CSV_PATH)
        logger.info(
            f"  신규: {upsert_stats['new']}건, 갱신: {upsert_stats['updated']}건, "
            f"전체: {upsert_stats['total']}건"
        )
    except RuntimeError as e:
        msg = f"Step 6 실패 — CSV upsert 오류: {e}"
        logger.error(msg)
        notify_error(msg)
        logger.save()
        sys.exit(1)

    # ──────────────────────────────────────────
    # Step 7: Slack 알림
    # ──────────────────────────────────────────
    logger.info("Step 7: Slack 알림 전송")

    # 급매/다주택자 매물에 upsert 결과 병합하여 Slack 포맷용 필드 추가
    alert_targets = []
    for article in filtered:
        if not (article.get("급매") or article.get("다주택자_의심")):
            continue
        article_no = str(article.get("articleNo", ""))
        analysis = analysis_map.get(article_no, {})
        alert_targets.append({
            **article,
            "호가": article.get("dealOrWarrantPrc") or article.get("prc", 0),
            "면적": article.get("area1") or article.get("areaName", ""),
            "단지명": article.get("articleName", ""),
            "지역구": article.get("_region", ""),
            "매물_URL": f"https://new.land.naver.com/articles/{article_no}",
        })

    sent_count = send_urgent_alerts(alert_targets)
    logger.info(f"  급매 알림 전송: {sent_count}건")

    # 완료 요약 알림
    notify_complete(total_raw)
    logger.info(f"  [완료] 알림 전송 완료")

    # ──────────────────────────────────────────
    # Step 8: 로그 저장 + 임시 파일 정리
    # ──────────────────────────────────────────
    elapsed = (datetime.now() - start_time).seconds
    logger.info(f"=== 실행 완료: 소요 {elapsed}초 ===")
    log_path = logger.save()
    print(f"로그 저장: {log_path}")

    # 임시 파일 삭제
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)


if __name__ == "__main__":
    main()
