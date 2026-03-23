"""
Slack Incoming Webhook 알림 전송 모듈.
[급매] / [완료] / [에러] 접두어로 메시지 유형 구분.
"""

import os
import json
import requests
from datetime import datetime


def _get_webhook_url() -> str:
    url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        raise RuntimeError("SLACK_WEBHOOK_URL 환경변수가 설정되지 않았습니다.")
    return url


def _send(text: str, max_retry: int = 1) -> bool:
    """Webhook POST 전송. 실패 시 1회 재시도."""
    url = _get_webhook_url()
    payload = {"text": text}

    for attempt in range(max_retry + 1):
        try:
            resp = requests.post(
                url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if resp.status_code == 200:
                return True
            if attempt < max_retry:
                continue
        except requests.exceptions.RequestException:
            if attempt < max_retry:
                continue
    return False


def notify_urgent(article: dict) -> bool:
    """
    급매 또는 다주택자_의심 매물 개별 알림.

    포함 필드: 단지명, 지역구, 호가, 면적, URL
    """
    try:
        price = int(str(article.get("호가", 0)).replace(",", "") or 0)
    except (ValueError, TypeError):
        price = 0
    price_str = f"{price // 10000}억 {price % 10000:,}만원" if price >= 10000 else f"{price:,}만원"

    text = (
        f"[급매] {article.get('단지명', '알수없음')} | {article.get('지역구', '')}\n"
        f"호가: {price_str} | {article.get('면적', '')}㎡\n"
        f"{article.get('매물_URL', '')}"
    )
    return _send(text)


def notify_complete(total_collected: int) -> bool:
    """실행 완료 요약 알림."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    text = f"[완료] 오늘 수집 총 {total_collected:,}건 | {now}"
    return _send(text)


def notify_error(message: str) -> bool:
    """에러 알림. 파싱 실패·실행 중단 시 사용."""
    text = f"[에러] {message}"
    return _send(text)


def send_urgent_alerts(articles: list[dict]) -> int:
    """
    급매/다주택자_의심 매물 일괄 알림 전송.

    Returns:
        전송 성공 건수
    """
    sent = 0
    for article in articles:
        if article.get("급매") or article.get("다주택자_의심"):
            success = notify_urgent(article)
            if success:
                sent += 1
    return sent
