# LINE Vercel 翻譯機器人

使用 Gemini 進行繁體中文、泰文、越南文與英文翻譯的 LINE Bot。

## 修改內容

1. 多 Project Gemini API Key 平均分配。
2. 429 自動切換下一把 Key。
3. 主模型空白、503 或逾時時自動切換備援模型。
4. 兩個 Gemini 模型都失敗時，可改用 Apps Script LanguageApp。
5. 每個群組可選擇泰文、越南文或英文環境，並偵測原樣回傳。
6. 保留數字、金額、@Mention、人物關係及 KTV 常用語規則。
7. 使用原發話者頭像顯示翻譯結果。

## 使用方式

在 Vercel 設定 `.env.example` 列出的 Environment Variables，然後部署
GitHub Repository 的 `main` 分支。

## 部署後測試

|輸入              |預期輸出          |
|----------------|--------------|
|วันนี้ฉันยังทำงานอยู่   |我今天還在工作。      |
|พรุ่งนี้เช้าไปที่สนามบิน|明天早上去機場。      |
|我今天還在工作。        |วันนี้ฉันยังทำงานอยู่ |
|Khách đã về rồi |客人已經回去了。|
|客人延長到 1:00（越南文模式）|Khách gia hạn đến 1:00.|
|ห้อง 5           |房間 5          |
|@N. ลูกค้า2 21:42 |@N. 客人 2 21:42|
|22:15           |22:15         |

## Vercel Log 檢查

正常會看到：

```text
翻譯結果檢查：direction=TH→ZH-TW ... same_as_input=False
```

如果第一次原樣回傳並成功重試，會先看到：

```text
Gemini 原樣回傳，使用固定方向短 Prompt 重試：TH→ZH-TW
```

正常 Log 也會顯示 `key_index`、模型名稱與 Gemini API 實際耗時。

## 群組語言模式

- 舊群組沒有設定紀錄時，預設維持泰文模式。
- 新群組加入機器人時，會顯示中文、泰文、越南文與英文說明，並提供泰文、越南文、英文三個按鈕。
- 所有群組成員都能輸入 `語言設定`，或點選語言按鈕切換模式。
- 中文會翻成群組語言；群組語言會翻成中文。
- 泰文／越南文模式收到英文時，會輸出中文加群組語言。
- 英文模式收到泰文或越南文時，會輸出中文加英文。

## 永久保存群組設定

請在 Vercel Marketplace 為專案連接 Upstash Redis，並確認 Production 環境存在：

```text
UPSTASH_REDIS_REST_URL
UPSTASH_REDIS_REST_TOKEN
```

若在 Vercel Marketplace 使用 `UPSTASH_REDIS_REST` 自訂前綴，程式也會自動讀取 `UPSTASH_REDIS_REST_KV_REST_API_URL` 與 `UPSTASH_REDIS_REST_KV_REST_API_TOKEN`。

程式只保存聊天室 ID 的 SHA-256 雜湊與語言代碼，不保存聊天內容。若尚未設定 Redis，按鈕仍能暫時切換，但 Vercel 重新啟動後會恢復泰文模式，機器人也會在確認訊息中提示。
