# 네이버부동산 매물 탐색 에이전트

> 이 파일은 Claude Code 개발 참조용 문서입니다. `python main.py` 런타임에는 영향 없음.

## 프로젝트 개요

5개 자치구(강남·강동·광진·송파·서초) 내 아파트 매물을 매일 자동으로 수집하여
조건에 맞는 매물을 필터링하고 CSV로 누적 관리한다. 급매 매물은 Slack으로 즉시 알림.

## 아키텍처

```
main.py (오케스트레이터)
  ├── src/fetch.py     ← 구별 매물 수집 (네이버 내부 API)
  ├── src/filter.py    ← 방 개수 필터 + 급매 키워드 탐지
  ├── src/analyzer.py  ← LLM 초품아·다주택자 판별 (anthropic SDK)
  ├── src/upsert.py    ← CSV upsert (매물 ID 기준)
  ├── src/notify.py    ← Slack [급매]/[완료]/[에러] 알림
  └── src/log.py       ← 일별 실행 로그

.github/workflows/collect.yml  ← GitHub Actions cron (매일 07:00 KST)
config.json                    ← 검색 조건 (지역구, 필터, 키워드)
```

## 환경 변수 (GitHub Secrets)

| 변수명 | 설명 |
|--------|------|
| `ANTHROPIC_API_KEY` | Claude API 키 |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL |

로컬 개발 시 `.env` 파일 사용 (`.gitignore`에 포함됨).

## 빠른 시작

```bash
pip install -r requirements.txt
cp .env.example .env    # API 키 설정
python main.py           # 직접 실행
```

## 주요 설계 결정

- **API 차단 대응**: Referer + User-Agent 헤더 + 구간 딜레이 (1~3초)
- **급매 판별**: 스크립트 엄격 키워드 필터 (`config.json > urgent_keywords`)
- **초품아 판별**: LLM (anthropic SDK), false negative 완화 방향
- **LLM 배치**: 15건씩 묶어 처리 (비용·정확도 절충)
- **소멸 매물**: 자동 감지 없음, 수동 처리만
- **CSV**: `.gitignore` 제외, 로그 파일만 GitHub에 커밋

## 미결 항목

`docs/api_endpoints.md` 의 미확인 사항 참조.
브라우저 개발자도구 Network 탭에서 실제 API 요청 확인 후 `src/fetch.py` 조정 필요.
