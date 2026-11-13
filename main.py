import datetime as dt, sys, traceback
import pandas as pd
import analyze, report, scrape


def main():
    today = pd.Timestamp.now("UTC").tz_localize(None).normalize()
    try:
        html = scrape.fetch()
        scrape.save_raw(html, today.date())          # 先存原始 HTML，之後改版也能重新解析
        rows = scrape.parse(html) + scrape.parse_index(html, today.year)
    except Exception:
        report.send("[爬蟲異常] 抓取失敗", f"<pre>{traceback.format_exc()}</pre>")
        sys.exit(1)
    con = scrape.connect()
    problems = scrape.health_check(rows, con)
    if problems:
        report.send("[爬蟲異常] 資料檢查未通過", "<ul>" + "".join(f"<li>{p}</li>" for p in problems) + "</ul>"
                    "<p>原始 HTML 已保存在 data/raw/，這次的資料沒有寫入資料庫。</p>")
        sys.exit(1)
    new = scrape.store(rows, con, dt.datetime.utcnow().isoformat(timespec="seconds"))
    df = analyze.load()
    M, S = analyze.metrics(df, today)
    alerts = analyze.find_alerts(new, M, con, today)
    cr = analyze.chains(M)
    report.send(f"[記憶體報價] 日報 {today:%Y-%m-%d}", report.daily_html(today, new, M, alerts, cr))
    if alerts:
        names = "、".join(dict.fromkeys(a["name"] for a in alerts))[:80]
        report.send(f"[警示] {len(alerts)} 項價格異動：{names}",
                    report.daily_html(today, [], M, alerts, []).split("<h3>今日有新報價")[0])
        analyze.record(con, alerts, today)
    report.dashboard(M, S, df)


if __name__ == "__main__":
    main()
