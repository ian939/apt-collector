# 네이버부동산 내부 API 엔드포인트 명세

> 비공식 내부 API. 언제든 변경 가능. 파싱 실패 시 Slack [에러] 알림 후 수동 대응.
> 최초 확인: 2026-03-18 | 브라우저 Network 탭 분석 기반

---

## 주요 엔드포인트

### 1. 매물 목록 조회 (articleList)

```
GET https://new.land.naver.com/api/articles
```

#### 쿼리 파라미터

| 파라미터 | 타입 | 예시 | 설명 |
|---------|------|------|------|
| `cortarNo` | string | `1168000000` | 법정동 코드 (구 단위) |
| `realEstateType` | string | `APT` | 매물 종류: APT=아파트 |
| `tradeType` | string | `A1` | 거래 유형: A1=매매, B1=전세, B2=월세 |
| `priceMin` | int | `0` | 최저 호가 (만원 단위) |
| `priceMax` | int | `200000` | 최고 호가 (만원 단위, 20억=200000) |
| `areaMin` | int | `0` | 최소 면적 |
| `areaMax` | int | `900000` | 최대 면적 |
| `sameAddressGroup` | string | `false` | 동일 주소 그룹화 여부 |
| `showArticle` | string | `false` | |
| `page` | int | `1` | 페이지 번호 (1부터 시작) |
| `order` | string | `rank` | 정렬 기준 |

#### 응답 구조

```json
{
  "isMoreData": true,
  "articleList": [
    {
      "articleNo": "2405001234",
      "articleName": "레미안 대치팰리스",
      "tradeTypeName": "매매",
      "dealOrWarrantPrc": "185000",
      "areaName": "84.9",
      "area1": "84.9",
      "area2": "120.5",
      "floorInfo": "15/20",
      "roomCount": 3,
      "articleFeatureDesc": "초등학교 도보 3분, 급매합니다",
      "tagList": ["초품아", "역세권", "학군지"],
      "realtorName": "OO부동산",
      "representativeImgUrl": "..."
    }
  ]
}
```

#### 주요 응답 필드

| 필드 | 설명 |
|------|------|
| `articleNo` | 매물 고유 ID |
| `articleName` | 단지명 |
| `dealOrWarrantPrc` | 호가 (만원 단위 문자열, 쉼표 있을 수 있음) |
| `areaName` / `area1` | 전용면적 (㎡) |
| `floorInfo` | 층 정보 (예: "15/20") |
| `roomCount` | 방 개수 |
| `articleFeatureDesc` | 매물 설명 원문 |
| `tagList` | 단지 태그 배열 |
| `isMoreData` | 다음 페이지 존재 여부 |

---

## 구별 법정동 코드 (cortarNo)

| 지역구 | cortarNo |
|--------|----------|
| 강남구 | `1168000000` |
| 강동구 | `1174000000` |
| 광진구 | `1121500000` |
| 송파구 | `1171000000` |
| 서초구 | `1165000000` |

> **참고**: 위 코드는 구(區) 단위 코드입니다. 동(洞) 단위로 세분화하려면 하위 cortarNo를 사용해야 합니다.

---

## 요청 헤더 (필수)

```python
HEADERS = {
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Host": "new.land.naver.com",
    "Referer": "https://new.land.naver.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
}
```

> ⚠️ **헤더 없이 요청하면 403 또는 캡챠 페이지 응답.** Referer와 User-Agent는 필수.

---

## 주의사항

1. **비공식 API**: 네이버가 공식 제공하지 않으므로 엔드포인트/파라미터 구조가 예고 없이 변경될 수 있음
2. **요청 간 딜레이**: 짧은 시간에 대량 요청 시 IP 차단 위험. 구간 딜레이(1~3초) 필수
3. **GitHub Actions IP**: 데이터센터 IP에서 호출 시 차단될 수 있음. 차단 발생 시 `notify_error`로 알림 후 대응
4. **페이지네이션**: `isMoreData: false` 또는 `articleList: []` 응답 시 수집 중단

---

## 미확인 사항 (실제 API 호출로 검증 필요)

- [ ] `priceMax` 파라미터가 실제로 서버 레벨에서 필터링되는지 확인
- [ ] `roomCount` 필드가 모든 매물에 존재하는지 확인 (없으면 filter.py 로직 수정 필요)
- [ ] `tagList` 필드 형식 확인 (배열인지 문자열인지)
- [ ] 페이지당 최대 매물 수 확인
- [ ] GitHub Actions ubuntu-latest IP에서 차단 여부 확인

---

## 변경 이력

| 날짜 | 변경 내용 |
|------|---------|
| 2026-03-18 | 초기 엔드포인트 확인 (웹 검색 기반, 실제 Network 탭 미검증) |
