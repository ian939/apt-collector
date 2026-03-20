"""
일별 실행 로그 저장 모듈.
/output/logs/YYYY-MM-DD.log 에 기록하며 GitHub에 커밋됨.
"""

import os
from datetime import datetime


def get_log_path(log_dir: str = "output/logs") -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, f"{today}.log")


def write_log(entries: list[str], log_dir: str = "output/logs") -> str:
    """
    로그 항목 리스트를 파일에 기록한다.

    Args:
        entries: 로그 라인 리스트
        log_dir: 로그 디렉터리 경로

    Returns:
        작성된 로그 파일 경로
    """
    path = get_log_path(log_dir)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(path, "a", encoding="utf-8") as f:
        f.write(f"=== 실행 시작: {now} ===\n")
        for entry in entries:
            f.write(f"{entry}\n")
        f.write("\n")

    return path


class RunLogger:
    """실행 전반의 로그를 수집하고 파일로 저장하는 헬퍼."""

    def __init__(self, log_dir: str = "output/logs"):
        self.log_dir = log_dir
        self._entries: list[str] = []

    def info(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] INFO  {message}"
        self._entries.append(entry)
        print(entry)

    def warning(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] WARN  {message}"
        self._entries.append(entry)
        print(entry)

    def error(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] ERROR {message}"
        self._entries.append(entry)
        print(entry)

    def save(self) -> str:
        return write_log(self._entries, self.log_dir)
