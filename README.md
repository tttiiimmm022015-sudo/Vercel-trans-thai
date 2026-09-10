# LINE Vercel 翻譯機器人

使用 Gemini 進行繁體中文、泰文與英文翻譯的 LINE Bot。

## 修改內容

1. 多 Project Gemini API Key 平均分配。
2. 429 自動切換下一把 Key。
3. 主模型空白、503 或逾時時自動切換備援模型。
4. 固定中泰英翻譯方向，並偵測原樣回傳。
5. 保留數字、金額、@Mention、人物關係及 KTV 常用語規則。
6. 使用原發話者頭像顯示翻譯結果。

## 使用方式

在 Vercel 設定 `.env.example` 列出的 Environment Variables，然後部署
GitHub Repository 的 `main` 分支。

## 部署後測試

|輸入              |預期輸出          |
|----------------|--------------|
|วันนี้ฉันยังทำงานอยู่   |我今天還在工作。      |
|พรุ่งนี้เช้าไปที่สนามบิน|明天早上去機場。      |
|我今天還在工作。        |วันนี้ฉันยังทำงานอยู่ |
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
