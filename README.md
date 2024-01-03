# Payment Reminder Linebot

基於 Line 的聊天機器人。新增繳費提醒，機器人會在截止日前開始提醒使用者繳費。

## Features

- 新增提醒
- 列出提醒清單
- 刪除提醒
- 已繳費

## Development

Install requirements
```
pip install -r requirements.txt
```

Set secrets
```bash
export LINE_CHANNEL_SECRET=your_channel_secret
export LINE_CHANNEL_ACCESS_TOKEN=your_access_token
export GOOGLE_API_KEY=your_api_key
```

Start development server
```
python app.py
```
