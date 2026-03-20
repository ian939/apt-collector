"""
LLM 기반 초품아·다주택자 판별 모듈 (anthropic SDK).
10~20건씩 배치 처리하여 JSON structured output 반환.
"""

import json
import os
import anthropic

BATCH_SIZE = 15
MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """당신은 한국 아파트 매물의 초품아 여부와 다주택자 매물 여부를 판별하는 전문가입니다.

## 초품아 판별 기준 (false negative 완화 — 조금이라도 근거 있으면 True)
다음 표현 중 하나라도 포함되면 True로 판별합니다:
- "초품아", "초등학교 품은", "초등품아" 등 직접 표현
- "초등학교 도보 N분" 형태의 표현
- "OO초 인근", "OO초등학교 담장", "OO초 도보" 등 특정 학교명 + 인접 표현
- "초등학교 바로 옆", "단지 내 초등학교", "창문에서 초등학교"
- 단지 태그에 '초품아', '학교', '초등학교' 등이 포함된 경우

애매한 경우 True를 반환하세요. 누락(false negative)이 포함(false positive)보다 더 나쁩니다.

## 다주택자 의심 판별 기준
매물 설명에 아래와 같이 명시된 경우에만 True:
- "다주택자 매물", "다주택 매물", "다주택자매물" 등 명시적 표현
단순히 여러 채를 소유했을 가능성 추측은 False로 처리합니다.

## 출력 형식
반드시 아래 JSON 배열만 출력하세요. 설명 텍스트나 마크다운 없이 JSON만:
[
  {"id": "매물ID", "초품아": true/false, "다주택자_의심": true/false, "판별_사유": "근거 텍스트"},
  ...
]"""


def _build_user_prompt(batch: list[dict]) -> str:
    lines = ["다음 매물들을 판별해주세요:\n"]
    for item in batch:
        lines.append(f"=== 매물 ID: {item['id']} ===")
        lines.append(f"단지명: {item.get('단지명', '')}")
        lines.append(f"태그: {item.get('태그', '')}")
        lines.append(f"설명: {item.get('설명', '')}")
        lines.append("")
    return "\n".join(lines)


def _parse_response(text: str) -> list[dict]:
    """LLM 응답에서 JSON 배열 추출."""
    text = text.strip()
    # JSON 블록만 추출 (```json ... ``` 형식 처리)
    if "```" in text:
        start = text.find("[", text.find("```"))
        end = text.rfind("]") + 1
    else:
        start = text.find("[")
        end = text.rfind("]") + 1

    if start == -1 or end == 0:
        raise ValueError(f"JSON 배열을 찾을 수 없음: {text[:200]}")

    return json.loads(text[start:end])


def _prepare_batch_input(batch: list[dict]) -> list[dict]:
    """API 응답에서 LLM 판별에 필요한 필드만 추출."""
    items = []
    for article in batch:
        items.append({
            "id": article.get("articleNo", article.get("_id", "")),
            "단지명": article.get("articleName", ""),
            "태그": ", ".join(article.get("tagList", [])) if isinstance(article.get("tagList"), list) else str(article.get("tagList", "")),
            "설명": article.get("articleFeatureDesc", ""),
        })
    return items


def analyze_listings(listings: list[dict]) -> list[dict]:
    """
    초품아·다주택자 판별. 10~20건씩 배치 처리.

    Args:
        listings: filter.py를 통과한 매물 리스트

    Returns:
        [{"id": "...", "초품아": bool, "다주택자_의심": bool, "판별_사유": str}, ...]
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")

    client = anthropic.Anthropic(api_key=api_key)
    results = []

    for i in range(0, len(listings), BATCH_SIZE):
        batch = listings[i:i + BATCH_SIZE]
        batch_input = _prepare_batch_input(batch)
        user_prompt = _build_user_prompt(batch_input)

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            text = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            batch_results = _parse_response(text)
            results.extend(batch_results)

        except (ValueError, json.JSONDecodeError) as e:
            # 파싱 실패 시 해당 배치 매물 전부 '불확실' 처리
            for item in batch_input:
                results.append({
                    "id": item["id"],
                    "초품아": "불확실",
                    "다주택자_의심": False,
                    "판별_사유": f"LLM 응답 파싱 실패: {e}",
                })

    return results
