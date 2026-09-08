# LINE Vercel 翻譯機器人修正版

這個壓縮包修正「泰文輸入被 Gemini 原樣回傳」的問題。

## 修改內容

1. `app/api/line_webhook.py`
  - 將已偵測的 `direction` 傳入 `translate()`。
2. `app/services/translation_service.py`
  - 依固定方向建立 Prompt。
  - 偵測中文／泰文原樣回傳。
  - 原樣回傳時使用短 Prompt 自動重試一次。
  - 重試仍失敗時回傳翻譯失敗訊息，不再把錯誤原文當成譯文。
3. `app/prompts/translation_prompt.py`
  - 在原有完整規則前後加入本次固定方向。
  - 保留數字、金額、@Mention、人物關係及酒店／KTV 用語規則。
4. `app/utils/language_detector.py`
  - 英文方向名稱改成 `EN→ZH-TW+TH`，與現有 Prompt 行為一致。

## 使用方式

把壓縮包內的 `app` 資料夾覆蓋到 GitHub Repository 根目錄的 `app`。

請勿刪除或修改：

- `app/services/gemini_service.py`
- Vercel Environment Variables
- LINE Channel Secret
- LINE Channel Access Token
- Gemini API Keys

提交到 GitHub 的 `main` 後，等待 Vercel 自動部署完成。

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

這次修改不會改變多 API Key 輪詢、429 cooldown 或 LINE 真正 @Mention
