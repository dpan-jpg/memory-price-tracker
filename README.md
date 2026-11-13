# 記憶體報價追蹤

每天抓 memorymarket.com/price → 存 SQLite → 算指標 → 寄日報／警示信 → 更新儀表板 (docs/index.html)。

## 部署（GitHub Actions，免費）
1. 建一個 GitHub repo，把這個資料夾全部上傳。
2. Settings → Secrets and variables → Actions，新增：
   - `SMTP_USER`：寄件 Gmail
   - `SMTP_PASS`：Gmail「應用程式密碼」（需先開兩步驟驗證）
   - `MAIL_TO`：收件信箱
3. Actions 頁籤 → daily → Run workflow，手動跑第一次。
4. Settings → Pages → Branch 選 main、資料夾選 /docs，儀表板網址就會出現。
之後每天台灣時間 15:30 自動執行。

## 本機試跑
    pip install -r requirements.txt
    python main.py          # 沒設 SMTP 時，信會存成 out/mail_*.html
    python tests/test_smoke.py

## 調整
所有門檻、產業鏈配對都在 config.py。
