# 📈 Brad's Daily Stock Picks

매일 오전 9시 KST, AI가 국내/해외 주식 및 ETF 강력 추천을 자동 갱신하는 개인 대시보드입니다.

**🔗 접근 URL:** https://brad-k-dev.github.io/daily-stock-picks/

---

## 📁 파일 구성

| 파일 | 설명 |
|------|------|
| `index.html` | 주식 추천 웹페이지 |
| `deploy.sh` | 최초 배포 스크립트 (한 번만 실행) |
| `update_picks.py` | AI 자동 갱신 Python 스크립트 |
| `.github/workflows/daily-update.yml` | 매일 오전 9시 자동 실행 워크플로우 |

---

## 🚀 최초 배포 방법

```bash
# 터미널에서 실행
bash deploy.sh
```

GitHub 사용자명과 PAT 토큰을 입력하면 저장소 생성 → 파일 업로드 → GitHub Pages 활성화까지 자동 처리됩니다.

---

## 🤖 AI 자동 갱신 설정

1. [Anthropic API Key 발급](https://console.anthropic.com/settings/keys)

2. GitHub Secrets에 등록:
   `Settings → Secrets and variables → Actions → New repository secret`

   | Name | Value |
   |------|-------|
   | `ANTHROPIC_API_KEY` | `sk-ant-...` |

3. 이후 매일 오전 9시 자동 실행
   수동 실행: `Actions` 탭 → `📈 Daily Stock Picks Update` → `Run workflow`

---

## 📡 실시간 주가

별도 설정 없이 페이지 접근 시 Yahoo Finance에서 자동으로 현재 주가를 불러옵니다.

- 🇰🇷 국내: KRX 현재가 (005930.KS 형식)
- 🇺🇸 해외: NYSE/NASDAQ 현재가 (NVDA, META 등)
- 장 마감 후에는 마지막 거래가 표시
