"""
Brad's Daily Stock Picks — GitHub Actions 자동 갱신 스크립트
매일 오전 9시 / 오후 2시 KST에 실행되어 index.html 및 history.json을 업데이트합니다.
"""

import os, re, json, requests
import anthropic
from datetime import datetime, timedelta, date, timezone

# ── 설정 ─────────────────────────────────────────────────────
KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
TODAY = NOW.strftime("%Y-%m-%d")
TODAY_KR = NOW.strftime("%Y년 %m월 %d일")
SESSION = "AM" if NOW.hour < 12 else "PM"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
HISTORY_FILE = "history.json"

# 내부 ticker → Yahoo Finance symbol 매핑
TICKER_TO_YAHOO = {
    "000660": "000660.KS", "005930": "005930.KS",
    "012450": "012450.KS", "207940": "207940.KS",
    "005380": "005380.KS", "091160": "091160.KS",
    "476550": "476550.KS", "455850": "455850.KS",
    "261070": "261070.KS", "305720": "305720.KS",
}

def yahoo_sym(ticker):
    return TICKER_TO_YAHOO.get(ticker, ticker)

# ── 주식 데이터 수집 ─────────────────────────────────────────
def fetch_prices():
    """Yahoo Finance에서 현재 가격 수집"""
    tickers = [
        "000660.KS","005930.KS","012450.KS","207940.KS","005380.KS",
        "091160.KS","476550.KS","455850.KS","261070.KS","305720.KS",
        "NVDA","VRT","META","MSFT","FIS",
        "QQQ","SOXX","MGK","VUG","MTUM"
    ]
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={','.join(tickers)}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        quotes = r.json().get("quoteResponse", {}).get("result", [])
        return {q["symbol"]: q for q in quotes}
    except Exception as e:
        print(f"가격 수집 실패: {e}")
        return {}

def search_web(query):
    """간단한 웹 검색 (requests 기반)"""
    try:
        r = requests.get(
            f"https://www.google.com/search?q={requests.utils.quote(query)}&num=5",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8
        )
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "lxml")
        texts = [t.get_text()[:200] for t in soup.select(".BNeawe, .VwiC3b, .s3v9rd")[:8]]
        return "\n".join(texts)
    except Exception as e:
        return f"검색 실패: {e}"

# ── 수익률 히스토리 관리 ─────────────────────────────────────
def load_history():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_updated": "", "picks": []}

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def update_returns(history, prices):
    """기존 추천 종목의 1일/1주/1개월 수익률 업데이트"""
    today = NOW.date()
    updated = 0
    for pick in history["picks"]:
        pick_date = date.fromisoformat(pick["date"])
        days = (today - pick_date).days
        ysym = yahoo_sym(pick["ticker"])
        q = prices.get(ysym, {})
        cur = q.get("regularMarketPrice")

        if not cur or not pick.get("entry_price"):
            continue

        ret = round((cur - pick["entry_price"]) / pick["entry_price"] * 100, 2)

        if days >= 1 and pick["r1d"] is None:
            pick["r1d"] = ret
            updated += 1
        if days >= 7 and pick["r1w"] is None:
            pick["r1w"] = ret
            updated += 1
        if days >= 30 and pick["r1m"] is None:
            pick["r1m"] = ret
            updated += 1

    print(f"  수익률 업데이트: {updated}건")
    return history

def add_picks_to_history(history, picks_data, prices):
    """오늘 추천 종목을 히스토리에 추가 (진입가 기록)"""
    today_str = TODAY

    # 같은 날짜·세션 중복 방지
    history["picks"] = [
        p for p in history["picks"]
        if not (p["date"] == today_str and p.get("session") == SESSION)
    ]

    section_map = {
        "kr_stocks": ("kr", "stock"),
        "kr_etfs":   ("kr", "etf"),
        "us_stocks": ("us", "stock"),
        "us_etfs":   ("us", "etf"),
    }

    added = 0
    for section, (market, asset_type) in section_map.items():
        for item in picks_data.get(section, []):
            ticker = item.get("ticker", "")
            ysym = yahoo_sym(ticker)
            q = prices.get(ysym, {})
            entry_price = q.get("regularMarketPrice")

            history["picks"].append({
                "id":          f"{today_str}-{SESSION}-{ticker}",
                "date":        today_str,
                "session":     SESSION,
                "market":      market,
                "asset_type":  asset_type,
                "ticker":      ticker,
                "name":        item.get("name", ""),
                "entry_price": entry_price,
                "currency":    "KRW" if market == "kr" else "USD",
                "r1d":  None,
                "r1w":  None,
                "r1m":  None,
            })
            added += 1

    # 90일 이상 된 데이터 정리
    cutoff = (NOW.date() - timedelta(days=90)).isoformat()
    history["picks"] = [p for p in history["picks"] if p["date"] >= cutoff]
    history["last_updated"] = NOW.isoformat()

    print(f"  히스토리 추가: {added}건 (세션: {SESSION})")
    return history

# ── Claude AI로 추천 생성 ────────────────────────────────────
def generate_picks(prices):
    if not ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY 없음 — 추천 생성 건너뜀")
        return None

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    price_summary = []
    for sym, q in prices.items():
        p = q.get("regularMarketPrice", "N/A")
        chg = q.get("regularMarketChangePercent", 0)
        price_summary.append(f"{sym}: {p} ({chg:+.2f}%)")

    kr_news   = search_web(f"국내 주식 오늘 기관 외국인 순매수 {TODAY}")
    us_news      = search_web(f"US stocks strong buy momentum institutional analyst upgrade {TODAY}")
    tipranks_news = search_web(f"tipranks top analyst picks best stocks buy rating {TODAY}")
    dataroma_news = search_web(f"dataroma superinvestor guru portfolio buys {TODAY}")
    macro_news    = search_web(f"tradingeconomics US economic indicators interest rate outlook {TODAY}")
    dart_news = search_web(f"DART 자사주 소각 대규모 수주 공시 {TODAY}")

    prompt = f"""오늘 날짜: {TODAY_KR}

현재 주가 데이터:
{chr(10).join(price_summary)}

최신 국내 뉴스/수급:
{kr_news[:800]}

최신 해외 뉴스/수급:
{us_news[:600]}

TipRanks 애널리스트 추천:
{tipranks_news[:400]}

Dataroma 슈퍼인베스터 동향:
{dataroma_news[:400]}

거시경제 지표 (TradingEconomics):
{macro_news[:300]}

DART 최신 공시:
{dart_news[:500]}

위 데이터를 분석하여 다음 형식으로 오늘의 추천 주식 JSON을 생성해 주세요.
국내 주식 5종목, 국내 ETF 5종목, 해외 주식 5종목, 해외 ETF 5종목 (총 20종목).

각 항목 형식:
{{
  "ticker": "종목코드 또는 티커",
  "name": "회사명 또는 ETF명",
  "sector": "섹터 설명",
  "type": "단기모멘텀|중장기|혼합|ETF중장기",
  "price": "현재가 (데이터 없으면 N/A)",
  "change": "등락률 (데이터 없으면 N/A)",
  "confidence": 숫자(60~99),
  "signals": ["신호1", "신호2", "신호3"],
  "reasons": ["근거1 (출처 포함)", "근거2", "근거3", "근거4"],
  "sources": ["ETFcheck", "FnGuide", "DART", "KRX"] // 국내
             또는 ["Finviz", "Fintel", "HedgeFollow", "SEC EDGAR", "Dataroma", "TipRanks", "TradingEconomics", "ETF.com"] // 해외 (해당되는 것만)
}}

JSON만 반환 (설명 없이):
{{
  "date": "{TODAY}",
  "kr_stocks": [...5개...],
  "kr_etfs": [...5개...],
  "us_stocks": [...5개...],
  "us_etfs": [...5개...]
}}"""

    try:
        msg = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        m = re.search(r'\{[\s\S]*\}', raw)
        if m:
            return json.loads(m.group())
    except Exception as e:
        print(f"Claude API 오류: {e}")
    return None

# ── HTML 카드 생성 ────────────────────────────────────────────
CARD_ACCENTS = [
    "linear-gradient(90deg,#76e4c4,#4f8fff)",
    "linear-gradient(90deg,#f5c842,#fb923c)",
    "linear-gradient(90deg,#818cf8,#a78bfa)",
    "linear-gradient(90deg,#ff4f6e,#f97316)",
    "linear-gradient(90deg,#00d4a0,#22d3ee)",
]
FILL_COLORS = [
    "linear-gradient(90deg,#00d4a0,#4f8fff)",
    "linear-gradient(90deg,#f5c842,#fb923c)",
    "linear-gradient(90deg,#818cf8,#a78bfa)",
    "linear-gradient(90deg,#ff4f6e,#f97316)",
    "linear-gradient(90deg,#00d4a0,#22d3ee)",
]
TYPE_BADGE = {
    "단기모멘텀":    ("t-short", "단기 모멘텀"),
    "중장기":        ("t-mid",   "중장기"),
    "혼합":          ("t-mix",   "단기 + 중장기"),
    "ETF중장기":     ("t-etf",   "ETF · 중장기"),
    "ETF단기중장기": ("t-etf",   "ETF · 단기+중장기"),
}

def make_card(item, rank, is_etf=False, is_kr=False):
    i = rank - 1
    acc = CARD_ACCENTS[i]
    fill = FILL_COLORS[i]
    ticker = item.get("ticker","")
    t_type = item.get("type","중장기")
    badge_cls, badge_lbl = TYPE_BADGE.get(t_type, ("t-mid","중장기"))
    exchange = "KOSPI ETF" if is_kr and is_etf else ("KOSPI" if is_kr else ("NASDAQ ETF" if is_etf else "NASDAQ"))
    confidence = item.get("confidence", 80)
    price = item.get("price","—")
    change = item.get("change","—")
    is_up = "▼" not in str(change)
    signals_html = "".join(
        f'<div class="sig"><div class="sd" style="background:{["#00d4a0","#f5c842","#4f8fff","#a78bfa"][j%4]}"></div>{s}</div>'
        for j, s in enumerate(item.get("signals",[])[:4])
    )
    reasons_html = "".join(f'<li>{r}</li>' for r in item.get("reasons",[])[:4])
    sources_html = "".join(f'<span class="csrc">{s}</span>' for s in item.get("sources",[])[:4])
    etf_cls = " etf-card" if is_etf else ""
    return f'''
    <div class="card{etf_cls}" style="--ca:{acc}" data-ticker="{ticker}">
      <div class="rnum">0{rank}</div>
      <div class="ctop">
        <div class="cleft">
          <div class="tbox"><div class="tsym">{ticker}</div><div class="texc">{exchange}</div></div>
          <div><div class="cname">{item.get("name","")}</div><div class="csec">{item.get("sector","")}</div></div>
        </div>
        <div class="cright">
          <span class="tbadge {badge_cls}">{badge_lbl}</span>
          <div><div class="pval">{price}</div><div class="pchg {"up" if is_up else "dn"}">{change}</div></div>
        </div>
      </div>
      <div class="conf-row">
        <div class="conf-lbl">신뢰도</div>
        <div class="conf-trk"><div class="conf-fill" style="width:{confidence}%;--cf:{fill}"></div></div>
        <div class="conf-num">{confidence}</div>
      </div>
      <div class="sigs">{signals_html}</div>
      <div class="cdiv"></div>
      <div class="rtitle">📌 추천 근거</div>
      <ul class="rlist">{reasons_html}</ul>
      <div class="csrcs">{sources_html}</div>
    </div>'''

def make_grid(items, is_etf=False, is_kr=False):
    return "".join(make_card(item, i+1, is_etf, is_kr) for i, item in enumerate(items))

# ── HTML 업데이트 ────────────────────────────────────────────
def update_html(picks):
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    sections = {
        "kr_stocks": (False, True),
        "kr_etfs":   (True,  True),
        "us_stocks": (False, False),
        "us_etfs":   (True,  False),
    }

    for key, (is_etf, is_kr) in sections.items():
        items = picks.get(key, [])
        if not items:
            continue
        grid_html = make_grid(items, is_etf, is_kr)
        pattern = rf'(<!-- SECTION:{key} -->)([\s\S]*?)(<!-- /SECTION:{key} -->)'
        replacement = rf'\1\n<div class="grid">{grid_html}\n</div>\n\3'
        new_html = re.sub(pattern, replacement, html)
        if new_html != html:
            html = new_html
            print(f"  ✅ {key} 업데이트 완료 ({len(items)}종목)")
        else:
            print(f"  ⚠️  {key} 섹션 마커 없음 — 건너뜀")

    # 날짜 업데이트
    html = re.sub(r'(\d{4}-\d{2}-\d{2})(?: \d{2}:\d{2}(?: 🟢실시간)?)?', TODAY, html, count=3)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ index.html 업데이트 완료 ({TODAY})")

# ── 메인 ────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"📈 Brad's Daily Picks 갱신 시작 — {TODAY_KR} ({SESSION})")

    print("  주가 데이터 수집 중...")
    prices = fetch_prices()
    print(f"  {len(prices)}개 종목 가격 수집 완료")

    # ── 히스토리 업데이트 ──────────────────────────────────
    print("  수익률 히스토리 업데이트 중...")
    history = load_history()
    history = update_returns(history, prices)

    print("  AI 추천 생성 중 (Claude API)...")
    picks = generate_picks(prices)

    if picks:
        print("  HTML 업데이트 중...")
        update_html(picks)
        history = add_picks_to_history(history, picks, prices)
    else:
        print("  ⚠️  AI 추천 생성 실패 — 기존 HTML 유지 (가격만 실시간 업데이트됨)")
        with open("index.html", "r") as f:
            html = f.read()
        html = re.sub(r'\d{4}-\d{2}-\d{2}', TODAY, html, count=3)
        with open("index.html", "w") as f:
            f.write(html)

    save_history(history)
    print("  ✅ history.json 저장 완료")

    print("🎉 완료!")
