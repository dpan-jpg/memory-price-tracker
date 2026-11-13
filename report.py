import json, os, smtplib
from email.message import EmailMessage
import pandas as pd
import analyze, config

UP, DN = "#c8372d", "#1f7a4d"   # 台灣習慣：紅漲綠跌（要改成美式就對調）


def pct(v):
    if v is None or pd.isna(v):
        return "—"
    return f'<span style="color:{UP if v > 0 else DN if v < 0 else "#777"}">{v:+.2f}%</span>'


def table(head, rows):
    th = "".join(f'<th style="text-align:left;padding:4px 10px;border-bottom:2px solid #bbb">{h}</th>' for h in head)
    tr = "".join("<tr>" + "".join(f'<td style="padding:4px 10px;border-bottom:1px solid #eee">{c}</td>' for c in r)
                 + "</tr>" for r in rows)
    return f'<table style="border-collapse:collapse;font-size:13px"><tr>{th}</tr>{tr}</table>'


def streak_txt(s, days):
    return "—" if not s else f'{"連漲" if s > 0 else "連跌"}{abs(s)}次／{days}天'


def daily_html(today, new, M, alerts, chain_rows):
    h = [f"<h2>記憶體報價日報　{today:%Y-%m-%d}</h2>"]
    if alerts:
        h += ["<h3>警示</h3>", table(["規則", "類別", "品項", "現價", "參考價", "變動"],
              [[a["rule"], a["category"], a["name"], f'{a["price"]:g}', f'{a["ref"]:g}', pct(a["pct"])] for a in alerts])]
    ch = [n for n in new if n["before"] and n["price"] != n["before"]]
    h.append(f"<h3>今日有新報價且價格變動（{len(ch)} 項）</h3>")
    h.append(table(["類別", "品項", "前價", "現價", "變動"],
                   [[n["category"], n["name"], f'{n["before"]:g}', f'{n["price"]:g}',
                     pct((n["price"] / n["before"] - 1) * 100)] for n in ch]) if ch else "<p>無。</p>")
    top = M.assign(a=M.chg7.abs()).sort_values("a", ascending=False).head(10)
    top = top[top.a > 0]
    if len(top):
        h += ["<h3>近 7 日累計變動前 10 名</h3>",
              table(["品項", "現價", "7日均價", "30日均價", "週漲跌", "月漲跌", "連續"],
                    [[r["name"], f"{r.price:g}", "—" if pd.isna(r.avg7) else f"{r.avg7:.2f}",
                      "—" if pd.isna(r.avg30) else f"{r.avg30:.2f}", pct(r.chg7), pct(r.chg30),
                      streak_txt(r.streak, r.streak_days)] for _, r in top.iterrows()])]
    if chain_rows:
        h += ["<h3>產業鏈傳導（上游 → 下游）</h3>",
              table(["上游", "下游", "上游7日", "下游7日", "上游30日", "下游30日", "30日落差(pp)", "判讀"],
                    [[c["up"], c["down"], pct(c["up7"]), pct(c["dn7"]), pct(c["up30"]), pct(c["dn30"]),
                      "—" if c["gap30"] is None else f'{c["gap30"]:+.1f}', c["status"]] for c in chain_rows])]
    h.append(f'<p style="color:#888;font-size:12px">其餘 {len(M) - len(ch)} 項今日無價格變動。7/30 日數據需累積足夠天數才會出現。</p>')
    return "".join(h)


def send(subject, html):
    user, pw, to = (os.environ.get(k) for k in ("SMTP_USER", "SMTP_PASS", "MAIL_TO"))
    if not (user and pw and to):            # 沒設定信箱 → 存檔，方便本機試跑
        os.makedirs("out", exist_ok=True)
        path = f"out/mail_{len(os.listdir('out'))}.html"
        open(path, "w", encoding="utf-8").write(f"<!-- {subject} -->\n{html}")
        print("未設定 SMTP，已存成", path)
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content("請用支援 HTML 的信箱檢視。")
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST", "smtp.gmail.com"), 465) as s:
        s.login(user, pw)
        s.send_message(msg)


def dashboard(M, S, df, path="docs/index.html"):
    names = dict(zip(M.item_id, M["name"]))
    hist = {i: [[t.strftime("%Y-%m-%d"), p] for t, p in zip(g.quote_time, g.price)]
            for i, g in df.sort_values("quote_time").groupby("item_id")}
    ch = []
    for label, up, downs in config.CHAINS:
        ids = [i for i in [up] + downs if i in S.columns]
        sub = S[ids].dropna()
        if len(ids) > 1 and len(sub) > 1:
            reb = sub / sub.iloc[0] * 100
            ch.append(dict(label=label, dates=[d.strftime("%Y-%m-%d") for d in sub.index],
                           series={names[i]: [round(v, 2) for v in reb[i]] for i in ids}))
    data = dict(items=json.loads(M.to_json(orient="records", date_format="iso")), hist=hist, chains=ch,
                updated=pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False)))


TEMPLATE = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>記憶體報價追蹤</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js"></script>
<style>
:root{--bg:#fbfbfa;--fg:#1b2430;--mut:#6b7380;--line:#e4e4e0;--up:#c8372d;--dn:#1f7a4d;--ac:#2b5fa8}
@media(prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e8eaed;--mut:#98a0ab;--line:#2a2f37;--up:#ff7468;--dn:#4fc58a;--ac:#6ea2ee}}
body{margin:0 auto;max-width:1080px;padding:20px 16px 48px;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Noto Sans TC",sans-serif}
h1{font-size:22px;margin:0}h2{font-size:16px;margin:32px 0 8px}.mut{color:var(--mut)}
.bar{display:flex;gap:8px;margin:14px 0}select,input{font:inherit;padding:5px 8px;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:4px}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:5px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
tbody tr{cursor:pointer}tbody tr:hover{background:color-mix(in srgb,var(--ac) 10%,transparent)}tr.sel{background:color-mix(in srgb,var(--ac) 18%,transparent)}
.up{color:var(--up)}.dn{color:var(--dn)}canvas{max-height:300px}
</style></head><body>
<h1>記憶體報價追蹤</h1><div class="mut">資料來源 memorymarket.com｜更新 <span id="upd"></span>｜紅漲綠跌</div>
<h2 id="ct">點選下表任一品項查看走勢</h2><canvas id="cv"></canvas>
<div class="bar"><select id="cat"></select><input id="q" placeholder="搜尋品項"></div>
<div class="wrap"><table><thead><tr><th>類別</th><th>品項</th><th>現價</th><th>7日均</th><th>30日均</th><th>週漲跌</th><th>月漲跌</th><th>連續</th></tr></thead><tbody id="tb"></tbody></table></div>
<h2>產業鏈：上游與下游走勢（起點 = 100）</h2><div id="chains"></div>
<script>
const D=__DATA__,$=i=>document.getElementById(i);$('upd').textContent=D.updated;
const pc=v=>v==null?'—':`<span class="${v>0?'up':v<0?'dn':''}">${v>0?'+':''}${v.toFixed(2)}%</span>`;
const f=v=>v==null?'—':v.toFixed(2),st=i=>i.streak?(i.streak>0?'連漲':'連跌')+Math.abs(i.streak)+'次':'—';
$('cat').innerHTML='<option value="">全部類別</option>'+[...new Set(D.items.map(i=>i.category))].map(c=>`<option>${c}</option>`).join('');
const col=['#2b5fa8','#c8372d','#1f7a4d','#d28a00','#7a4fb5','#0e8a9a'];let ch1;
const opt={responsive:true,animation:false,plugins:{legend:{labels:{boxWidth:12}}},scales:{x:{ticks:{maxTicksLimit:8}}}};
function show(id){const it=D.items.find(i=>i.item_id===id),h=D.hist[id];ch1&&ch1.destroy();$('ct').textContent=`${it.name}（${it.currency}）`;
 ch1=new Chart($('cv'),{type:'line',data:{labels:h.map(x=>x[0]),datasets:[{label:it.name,data:h.map(x=>x[1]),stepped:true,borderColor:col[0],pointRadius:2}]},options:opt});render(id)}
function render(sel){const c=$('cat').value,q=$('q').value.toLowerCase();
 const r=D.items.filter(i=>(!c||i.category===c)&&i.name.toLowerCase().includes(q)).sort((a,b)=>Math.abs(b.chg7??0)-Math.abs(a.chg7??0));
 $('tb').innerHTML=r.map(i=>`<tr data-id="${i.item_id}" class="${i.item_id===sel?'sel':''}"><td>${i.category}</td><td>${i.name}</td><td>${i.price}</td><td>${f(i.avg7)}</td><td>${f(i.avg30)}</td><td>${pc(i.chg7)}</td><td>${pc(i.chg30)}</td><td>${st(i)}</td></tr>`).join('')}
$('tb').onclick=e=>{const t=e.target.closest('tr');t&&show(t.dataset.id)};$('cat').onchange=$('q').oninput=()=>render();render();
if(!D.chains.length)$('chains').innerHTML='<p class="mut">累積至少兩天資料後會顯示。</p>';
D.chains.forEach(c=>{const h=document.createElement('h2');h.textContent=c.label;h.style.fontSize='14px';const cv=document.createElement('canvas');$('chains').append(h,cv);
 new Chart(cv,{type:'line',data:{labels:c.dates,datasets:Object.entries(c.series).map(([n,v],k)=>({label:n,data:v,borderColor:col[k%6],pointRadius:0,borderWidth:k?1.5:3}))},options:opt})});
</script></body></html>"""
