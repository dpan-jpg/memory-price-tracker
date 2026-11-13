import gzip, pathlib, re, sqlite3
import requests
from bs4 import BeautifulSoup
import config

HEADERS = {"User-Agent": "Mozilla/5.0 (personal price tracker; once a day)"}
TS = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})")
SCHEMA = """
CREATE TABLE IF NOT EXISTS prices(
  item_id TEXT, category TEXT, name TEXT, price REAL, prev_price REAL,
  currency TEXT, quote_time TEXT, fetched_at TEXT,
  PRIMARY KEY(item_id, quote_time));
CREATE TABLE IF NOT EXISTS alerts(item_id TEXT, rule TEXT, direction INT, alert_date TEXT);
"""


def connect():
    pathlib.Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.executescript(SCHEMA)
    return con


def fetch():
    r = requests.get(config.URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def save_raw(html, day):
    p = pathlib.Path(config.RAW_DIR)
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{day}.html.gz").write_bytes(gzip.compress(html.encode("utf-8")))


def _num(s):
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def parse(html):
    """每個 <table> → 往前找最近的 h4(類別) 與時間戳記(報價時間)。"""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for t in soup.find_all("table"):
        h, ts = t.find_previous(["h4", "h3"]), t.find_previous(string=TS)
        if not h or not ts:
            continue
        qt = TS.search(ts).group(1)
        for tr in t.find_all("tr"):
            td = tr.find_all("td")
            a = td[0].find("a") if len(td) >= 5 else None
            price = _num(td[1].get_text()) if a else None
            if price is None:
                continue
            rows.append(dict(
                item_id=a["href"].rstrip("/").split("/")[-1],
                category=h.get_text(strip=True), name=a.get_text(strip=True),
                price=price, prev_price=_num(td[2].get_text()),
                currency=td[4].get_text(strip=True) or "USD", quote_time=qt))
    return rows


def parse_index(html, year):
    """NAND / DRAM 價格指數（頁面上依序出現）。解析失敗就回傳空，不影響主流程。"""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    found = re.findall(r"Index:\s*[▲▼]?\s*([\d,]+\.?\d*)[^\d]+?[\d.]+\s*\(-?[\d.]+%\)\s*(\d{2}-\d{2})", text)
    out = []
    for (val, md), (iid, name) in zip(found, [("idx_nand", "NAND 指數"), ("idx_dram", "DRAM 指數")]):
        out.append(dict(item_id=iid, category="Price Index", name=name, price=_num(val),
                        prev_price=None, currency="pt", quote_time=f"{year}-{md} 00:00"))
    return out


def health_check(rows, con):
    problems = []
    if len(rows) < config.MIN_ITEMS:
        problems.append(f"只解析到 {len(rows)} 個品項（預期至少 {config.MIN_ITEMS}），頁面結構可能改版。")
    ids = {r["item_id"] for r in rows}
    known = {x[0] for x in con.execute("select distinct item_id from prices")}
    missing = known - ids
    if known and len(missing) > 0.2 * len(known):
        problems.append(f"{len(missing)} 個已知品項這次消失了，例如：{sorted(missing)[:5]}")
    bad = [r["name"] for r in rows if r["price"] <= 0]
    if bad:
        problems.append(f"價格 ≤ 0 的品項：{bad[:5]}")
    return problems


def store(rows, con, fetched_at):
    """只寫入「新的報價時間」。回傳這次新增的報價，附上變動前價格 before。"""
    new = []
    for r in rows:
        last = con.execute("select price from prices where item_id=? order by quote_time desc limit 1",
                           (r["item_id"],)).fetchone()
        cur = con.execute("insert or ignore into prices values(?,?,?,?,?,?,?,?)",
                          (r["item_id"], r["category"], r["name"], r["price"], r["prev_price"],
                           r["currency"], r["quote_time"], fetched_at))
        if cur.rowcount:
            new.append({**r, "before": last[0] if last else r["prev_price"]})
    con.commit()
    return new
