import sqlite3
import pandas as pd
import config


def load():
    con = sqlite3.connect(config.DB_PATH)
    df = pd.read_sql("select * from prices", con, parse_dates=["quote_time"])
    con.close()
    return df


def daily_series(df, as_of):
    """每日一格、沒報價的日子沿用上一筆（價格是階梯式更新，不是每天都變）。"""
    d = df.assign(d=df.quote_time.dt.normalize()).sort_values("quote_time")
    s = d.groupby(["d", "item_id"]).price.last().unstack()
    return s.reindex(pd.date_range(s.index.min(), max(as_of, s.index.max()), freq="D")).ffill()


def streak(g, as_of):
    """回傳 (連續同向調價次數(+漲/-跌), 這段趨勢已持續幾天)。價格沒變的報價不算。"""
    g = g.sort_values("quote_time")
    p, t = g.price.tolist(), g.quote_time.tolist()
    ch = [(t[i - 1], 1 if p[i] > p[i - 1] else -1) for i in range(1, len(p)) if p[i] != p[i - 1]]
    if not ch:
        return 0, 0
    sign, n, start = ch[-1][1], 0, ch[-1][0]
    for when, s in reversed(ch):
        if s != sign:
            break
        n, start = n + 1, when
    return sign * n, (as_of - start.normalize()).days


def metrics(df, as_of):
    S = daily_series(df, as_of)
    wins = sorted({7, 30} | set(config.WINDOW_RULES))
    last = df.sort_values("quote_time").groupby("item_id").tail(1)
    rows = []
    for _, r in last.iterrows():
        s, p = S[r.item_id].dropna(), r.price
        row = dict(item_id=r.item_id, category=r.category, name=r["name"], price=p,
                   currency=r.currency, quote_time=r.quote_time)
        for n in wins:
            t = as_of - pd.Timedelta(days=n)
            row[f"chg{n}"] = (p / s[t] - 1) * 100 if s.index[0] <= t and s[t] else None
        for n in (7, 30):
            t = as_of - pd.Timedelta(days=n - 1)
            row[f"avg{n}"] = s.loc[t:].mean() if s.index[0] <= t else None
        row["streak"], row["streak_days"] = streak(df[df.item_id == r.item_id], as_of)
        rows.append(row)
    M = pd.DataFrame(rows)
    num = [c for c in M.columns if c.startswith(("chg", "avg"))]
    return M.astype({c: float for c in num}), S


def find_alerts(new, M, con, today):
    out = []
    # 第一層：這次新抓到的報價，與上一筆報價比
    for n in new:
        b = n["before"]
        if not b:
            continue
        pct = (n["price"] / b - 1) * 100
        if abs(pct) >= config.DAILY_ALERT_PCT and abs(n["price"] - b) >= config.MIN_ABS_CHANGE:
            out.append(dict(rule="單次報價", item_id=n["item_id"], category=n["category"],
                            name=n["name"], pct=pct, price=n["price"], ref=b))
    # 第二層：N 日累計（有冷卻期，避免每天重複寄同一件事）
    def cooled(iid, rule, d):
        last = con.execute("select max(alert_date) from alerts where item_id=? and rule=? and direction=?",
                           (iid, rule, d)).fetchone()[0]
        return last is None or (today - pd.Timestamp(last)).days >= config.COOLDOWN_DAYS
    for _, r in M.iterrows():
        for n, thr in config.WINDOW_RULES.items():
            v = r[f"chg{n}"]
            rule, d = f"{n}日累計", (1 if v > 0 else -1)
            if pd.notna(v) and abs(v) >= thr and cooled(r.item_id, rule, d):
                out.append(dict(rule=rule, item_id=r.item_id, category=r.category, name=r["name"],
                                pct=v, price=r.price, ref=r.price / (1 + v / 100)))
    return out


def record(con, alerts, today):
    con.executemany("insert into alerts values(?,?,?,?)",
                    [(a["item_id"], a["rule"], 1 if a["pct"] > 0 else -1, str(today.date())) for a in alerts])
    con.commit()


def _status(u, d):
    if pd.isna(u) or pd.isna(d):
        return "資料不足"
    if u >= 5 and d < u / 2:
        return "上游已漲，下游未跟"
    if u <= -5 and d > u / 2:
        return "上游已跌，下游抗跌"
    return "已傳導" if abs(u) >= 5 else "上游無明顯變動"


def chains(M):
    m, out = M.set_index("item_id"), []
    for label, up, downs in config.CHAINS:
        if up not in m.index:
            continue
        u = m.loc[up]
        for d in downs:
            if d in m.index:
                x = m.loc[d]
                gap = None if pd.isna(u.chg30) or pd.isna(x.chg30) else x.chg30 - u.chg30
                out.append(dict(chain=label, up=u["name"], down=x["name"], up7=u.chg7, dn7=x.chg7,
                                up30=u.chg30, dn30=x.chg30, gap30=gap, status=_status(u.chg30, x.chg30)))
    return out
