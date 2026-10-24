# 인스타 뉴스 카드 자동화 봇

매일 아침 자동으로 **뉴스 수집 → Claude가 선별·요약 → 카드뉴스 7장 생성 → 인스타그램 캐러셀 게시**까지 합니다.
서버 없이 GitHub Actions(무료)로 돌아갑니다.

```
06:52  GitHub Actions 실행
  ├─ 구글뉴스/연합뉴스 RSS에서 최근 24시간 기사 수집 (이미 다룬 기사 제외)
  ├─ Claude가 5개 골라 직접 다시 쓴 원고 + 캡션 + 해시태그 작성
  ├─ 카드 이미지 생성 (표지 1 + 뉴스 5 + 팔로우 유도 1)
  ├─ 이미지를 저장소에 올려 공개 주소 확보
  └─ 인스타 API로 게시
```

---

## 1. 인스타 계정 준비 (10분)

1. 인스타 앱에서 새 계정 생성
2. 설정 → 계정 유형 → **프로페셔널 계정(크리에이터)** 으로 전환 — API 게시는 프로페셔널 계정만 가능
3. 프로필 이름에 검색될 키워드 넣기 (예: `경제뉴스 | 출근길 3분 브리핑`)

## 2. Meta 앱 만들기 → 토큰 받기 (20분)

1. https://developers.facebook.com 접속 → 내 앱 → 앱 만들기 → 유형 **비즈니스**
2. 제품 추가에서 **Instagram** → **Instagram 로그인을 통한 API 설정** 선택
3. 권한: `instagram_business_basic`, `instagram_business_content_publish`
4. "액세스 토큰 생성"에서 새 인스타 계정 연결 → **토큰**과 **Instagram 사용자 ID** 복사
   - 본인 계정에만 쓰는 용도라 앱 검수(App Review) 없이 개발 모드로 사용 가능

## 3. Anthropic API 키

https://console.anthropic.com → API Keys에서 발급 (하루 1회 실행이면 월 몇백 원~천 원대 수준)

## 4. GitHub 저장소 세팅 (15분)

1. GitHub에서 **Public** 저장소 생성 후 이 폴더 내용 업로드
   - 이미지를 인스타가 가져갈 수 있도록 공개 저장소여야 함 (키는 Secret에 저장되어 노출 안 됨)
2. 저장소 Settings → Secrets and variables → Actions → **New repository secret** 4개 추가

| 이름 | 값 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API 키 |
| `IG_ACCESS_TOKEN` | 2단계에서 받은 토큰 |
| `IG_USER_ID` | 2단계에서 받은 사용자 ID |
| `GH_PAT` | GitHub → Settings → Developer settings → Fine-grained token (이 저장소, **Secrets: Read and write**) — 인스타 토큰 자동 연장용 |

3. Settings → Actions → General → Workflow permissions → **Read and write** 체크
4. `config.yaml`에서 `account_name`, `handle` 수정
5. Actions 탭 → `daily-post` → **Run workflow** 로 첫 게시 테스트

이후 매일 아침 자동 게시되고, 토큰은 매월 2번 자동 연장됩니다.

## 5. 커스터마이징

- **주제 바꾸기**: `config.yaml`의 `topic`, `google_news_queries`만 바꾸면 됩니다 (예: 부동산, IT, 육아정책)
- **색상**: `theme`
- **게시 시간**: `.github/workflows/daily.yml`의 cron (UTC 기준, 한국시간 −9시간)
- **미리보기**: 내 PC에서 `pip install -r requirements.txt` 후 `python main.py sample`

---

## 수익화 로드맵 (광고·협찬)

| 단계 | 팔로워 | 할 일 |
|---|---|---|
| 1. 성장 | 0 → 1천 | 매일 게시 유지. 하루 10분은 직접 댓글 답변 + 같은 분야 계정에 진심 댓글 (이건 자동화하지 마세요) |
| 2. 신뢰 | 1천 → 5천 | 인사이트에서 **저장 수** 높은 주제 파악 → `google_news_queries` 조정. 주 1회 릴스(카드 슬라이드 영상) 추가 |
| 3. 첫 수익 | 5천~ | 프로필에 "광고 문의: 이메일" 기재. 재테크 앱·증권사·경제 뉴스레터·도서 출판사에 미디어킷(팔로워, 평균 도달, 저장률) 보내기 |
| 4. 확장 | 1만~ | 브랜드 협찬 정기화, 인스타 자체 수익화 기능(가능 시) 신청 |

협찬 단가는 보통 팔로워·도달·분야에 따라 정해지고, 경제·재테크 분야는 단가가 높은 편입니다.

## 꼭 지킬 것

- **광고 표시**: 협찬 게시물은 첫 줄에 `#광고` 또는 `#협찬` 표기 + 인스타 "유료 파트너십" 라벨 사용 (공정위 추천·보증 심사지침)
- **저작권**: 기사 문장 복사·기사 사진 사용 금지. 이 봇은 Claude가 직접 다시 쓰고 출처만 표기하도록 되어 있습니다
- **금지**: 자동 팔로우/좋아요/DM 봇, 팔로워 구매 — 계정 정지 및 도달 제한의 주요 원인
- **투자 조언 금지**: 종목 추천처럼 보이는 표현은 쓰지 않게 프롬프트에 넣어두었습니다
- **API 한도**: 24시간에 100개 게시까지 (하루 1개면 여유 충분)
- 매일 아침 결과물을 한 번 훑어보세요. AI 요약도 가끔 틀립니다
