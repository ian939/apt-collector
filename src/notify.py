"""
Slack Incoming Webhook 알림 전송 모듈.
[수집완료] / [에러] 접두어로 메시지 유형 구분.
개별 매물 알림 없음 — 요약 1건만 전송.
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


def notify_summary(
    total_raw: int,
    new_count: int,
    updated_count: int,
    urgent_count: int,
    chopo_urgent_count: int,
) -> bool:
    """
    수집 완료 요약 알림 1건 전송.

    Args:
        total_raw: 전체 수집 건수 (필터 전)
        new_count: CSV 신규 저장 건수
        updated_count: CSV 갱신 건수
        urgent_count: 급매 후보 건수
        chopo_urgent_count: 급매 중 초품아 건수
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    text = (
        f"[수집완료] {now}\n"
        f"수집: {total_raw:,}건 | 신규저장: {new_count:,}건 | 갱신: {updated_count:,}건\n"
        f"급매: {urgent_count:,}건 | 급매+초품아: {chopo_urgent_count:,}건"
    )
    return _send(text)


def notify_error(message: str) -> bool:
    """에러 알림. 파싱 실패·실행 중단 시 사용."""
    text = f"[에러] {message}"
    return _send(text)
