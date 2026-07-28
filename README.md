# LINE Translator Bot｜Vercel 最佳化版

本專案保留原本的 Flask、LINE Messaging API、Gemini、真正 LINE mention、
語言判斷及翻譯 Prompt，並調整成適合 Vercel Python Runtime 的結構。

## 已完成的最佳化

- 根目錄新增官方可辨識的 `app.py` Flask 入口
- 新增 `vercel.json`
- 新增 `.vercelignore`，排除測試、快取和本機檔案
- 移除 Vercel 不需要的 `Dockerfile`、`Procfile` 和 `gunicorn`
- 不包含 `.env`，避免金鑰上傳 GitHub
- Gemini Client 在暖實例中快取重用
- Vercel Logs 會顯示 Gemini 與整個 Webhook 的耗時
- 群組／多人聊天室不再先查詢 LINE Profile，少一次外部 API 請求
- 保留一對一聊天的 LINE 顯示名稱
- `MAX_OUTPUT_TOKENS` 可透過環境變數調整

## 專案入口

```text
app.py
```

它會載入：

```python
from app.main import app
```

## 上傳 GitHub

解壓縮後，請把資料夾內的檔案上傳到 GitHub Repository 根目錄。

確認 GitHub 最外層直接看得到：

```text
app.py
vercel.json
requirements.txt
app/
```

不要讓它多包一層資料夾，也不要上傳真正的 `.env`。

## Vercel 部署

1. 登入 Vercel。
2. 選擇 **Add New → Project**。
3. 匯入 GitHub Repository。
4. Framework Preset 選 **Other** 或保持自動偵測。
5. Root Directory 保持 Repository 根目錄。
6. Build Command、Output Directory、Install Command 都保持預設。
7. 設定環境變數後按 **Deploy**。

## 必要環境變數

在 **Project → Settings → Environment Variables** 新增：

```text
GEMINI_API_KEY
LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN
GEMINI_MODEL
MAX_OUTPUT_TOKENS
LOG_LEVEL
```

建議值：

```text
GEMINI_MODEL=gemini-3.1-flash-lite
MAX_OUTPUT_TOKENS=256
LOG_LEVEL=INFO
```

修改環境變數後必須重新部署，舊 Deployment 不會自動套用新值。

## LINE Webhook

假設 Vercel 網址為：

```text
https://your-project.vercel.app
```

LINE Developers 的 Webhook URL 設定為：

```text
https://your-project.vercel.app/callback
```

然後：

1. 按 **Verify**
2. 開啟 **Use webhook**
3. 關閉 LINE Official Account Manager 的自動回應，避免重複回覆

## 部署後測試

首頁：

```text
https://your-project.vercel.app/
```

健康檢查：

```text
https://your-project.vercel.app/health
```

正常會回傳：

```json
{"status":"ok"}
```

## 查看速度

到 Vercel 的 **Project → Logs**，會看到：

```text
Gemini 回應完成：model=... elapsed=3.25s
LINE Webhook 完成：elapsed=3.62s
```

兩者差距若很小，表示主要延遲來自 Gemini；差距很大時，再檢查 LINE API
或 Vercel 冷啟動。

## 本機執行

1. 將 `.env.example` 複製成 `.env`
2. 填入金鑰
3. 執行：

```bash
pip install -r requirements.txt
python run.py
```

預設網址：

```text
http://localhost:8080
```
