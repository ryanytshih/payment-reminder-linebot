"""
Payment Reminder Linebot
"""

import os
import sys
import json
import logging
import calendar
from argparse import ArgumentParser
from datetime import datetime, timedelta

from pprint import pprint
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request, abort
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage
)

from chat import ChatModel


app = Flask(__name__)

# get channel_secret and channel_access_token from your environment variable
channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)

if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)

handler = WebhookHandler(channel_secret)

configuration = Configuration(
    access_token=channel_access_token
)

DATA_FILE_PATH = 'data/reminder_data.json'

if not os.path.exists(DATA_FILE_PATH):
    with open(DATA_FILE_PATH, 'w', encoding="utf-8") as file:
        json.dump({}, file)

gemini_model = ChatModel()

@app.route("/callback", methods=['POST'])
def callback():
    """callback"""
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: %s", body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def message_text(event):
    """message handler"""
    text = event.message.text
    reply_text = ""
    user_id = event.source.user_id

    if text == '新增繳費提醒':
        reply_text = "請輸入要新增的項目名稱:"
        set_user_state(user_id, 'add_reminder')
    elif text == '列出繳費清單':
        reminders = get_reminders(user_id)
        reply_text = format_reminders(reminders)
        set_user_state(user_id, None)
    elif text == '刪除繳費提醒':
        reminders = get_reminders(user_id)
        reply_text = '請輸入要刪除的清單項目編號\n' + format_reminders(reminders)
        set_user_state(user_id, 'delete_reminder')
    elif text == '已繳費':
        reminders = get_reminders(user_id)
        reply_text = '請輸入已繳費的清單項目編號\n' + format_reminders(reminders)
        set_user_state(user_id, 'mark_paid')
    elif get_user_state(user_id) == 'add_reminder':
        reply_text = add_reminder(user_id, text)
    elif get_user_state(user_id) == 'delete_reminder':
        reply_text = delete_reminder(user_id, text)
        set_user_state(user_id, None)
    elif get_user_state(user_id) == 'mark_paid':
        reply_text = mark_paid(user_id, text)
        set_user_state(user_id, None)
    elif text == "說明":
        reply_text = """- 點選「新增提醒」按鈕可以新增繳費提醒
- 點選「列出繳費清單」可以列出目前已新增的繳費提醒
- 點選「刪除提醒」可以刪除已經不需要的繳費提醒
- 輸入「已繳費」告訴我您已經繳費的項目，會在下個月再度提醒"""
    else:
        reply_text = gemini_model.send_message(user_id, text)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

def reminder_job():
    """scheduler job"""
    reminders = get_due_reminders()
    user_cards = {}
    for user_id, item, due_date in reminders:
        if user_id not in user_cards:
            user_cards[user_id] = []
        user_cards[user_id].append((item, due_date))

    current_date = datetime.now()
    for user_id, cards in user_cards.items():
        reminders_num = len(cards)
        message = f"目前有{reminders_num}個項目需要繳費:"
        for item, due_date_text in cards:
            due_date = datetime.strptime(due_date_text, "%Y-%m-%d")
            md = datetime.strftime(due_date, "%m/%d")
            remain = (due_date - current_date).days + 1
            message += f"\n{item} - {md} ({remain}天)"

        message += "\n若已經繳費，請輸入「已繳費」，本月將不再提醒"

        # Enter a context with an instance of the API client
        with ApiClient(configuration) as api_client:
            # Create an instance of the API class
            api_instance = MessagingApi(api_client)
            push_message_request = PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=message)]
            )

            try:
                api_response = api_instance.push_message(push_message_request)
                print("The response of MessagingApi->push_message:\n")
                pprint(api_response)
            except ValueError as e:
                print(f"Exception when calling MessagingApi->push_message: {e}\n")

# initial scheduler
scheduler = BackgroundScheduler(timezone="Asia/Taipei")
scheduler.add_job(reminder_job, 'cron', hour='11,18', minute=30)
scheduler.start()

def to_next_month(date):
    """given a datetime object, move the date to next month"""
    year = date.year + (date.month + 1) // 12
    month = (date.month + 1) % 12
    if month == 0:
        month = 12
    day = min(date.day, calendar.monthrange(year, month)[1])

    return datetime(year, month, day)

add_reminder_state = {}

def add_reminder(user_id, message):
    """add reminder"""
    if user_id not in add_reminder_state:
        add_reminder_state[user_id] = None

    if add_reminder_state[user_id] is None:
        add_reminder_state[user_id] = message
        return f"好的，新增項目為「{message}」。接下來請輸入繳費截止日 (例如: 15)"

    current_date = datetime.now()
    try:
        due_date = datetime.strptime(message, "%d")
    except ValueError:
        return "請輸入正確的日期格式 (例如: 5)"

    card_name = add_reminder_state[user_id]
    add_reminder_state[user_id] = None
    data = load_data()

    if user_id not in data:
        data[user_id] = {}
    if "cards" not in data[user_id]:
        data[user_id]["cards"] = []

    if current_date.day <= due_date.day:
        due_date = datetime(current_date.year, current_date.month, due_date.day)
    else:
        due_date = to_next_month(datetime(current_date.year, current_date.month, due_date.day))

    due_date_text = datetime.strftime(due_date, "%Y-%m-%d")

    data[user_id]["cards"].append({
        'name': card_name,
        'due_date': due_date_text
    })

    data[user_id]["cards"] = sorted(data[user_id]["cards"], key=lambda x: x["due_date"])

    save_data(data)
    set_user_state(user_id, None)
    return f"已新增「{card_name}」的繳費提醒，下次繳費截止日: {due_date_text}"

def get_reminders(user_id):
    """get cards list"""
    data = load_data()
    user = data.get(user_id, {})
    return [] if "cards" not in user else user["cards"]

def delete_reminder(user_id, reminder_id):
    """delete reminder"""
    data = load_data()
    try:
        reminder_id = int(reminder_id) - 1
    except ValueError:
        return "請輸入有效的清單項目編號"

    if user_id in data and 0 <= reminder_id < len(data[user_id]["cards"]):
        card_name = data[user_id]["cards"][reminder_id]["name"]
        del data[user_id]["cards"][reminder_id]
        save_data(data)
        return f"已刪除「{card_name}」的繳費提醒"

    return "發生錯誤，操作未成功"

def mark_paid(user_id, reminder_id):
    """set due date to next month"""
    data = load_data()
    try:
        reminder_id = int(reminder_id) - 1
    except ValueError:
        return "請輸入有效的清單項目編號"

    if user_id in data and 0 <= reminder_id < len(data[user_id]["cards"]):
        due_date = datetime.strptime(data[user_id]["cards"][reminder_id]["due_date"], "%Y-%m-%d")
        due_date = to_next_month(due_date)
        due_date_text = datetime.strftime(due_date, "%Y-%m-%d")
        data[user_id]["cards"][reminder_id]["due_date"] = due_date_text
        card_name = data[user_id]["cards"][reminder_id]["name"]
        data[user_id]["cards"] = sorted(data[user_id]["cards"], key=lambda x: x["due_date"])
        save_data(data)
        return f"好的，已經繳完這個月的{card_name}費用，下次繳費截止日: {due_date_text}"

    return "發生錯誤，操作未成功"

def get_due_reminders():
    """get due reminders"""
    data = load_data()
    current_date = datetime.now()

    reminders = []
    for user_id, items in data.items():
        is_changed = False
        for i, item in enumerate(items["cards"]):
            due_date = datetime.strptime(item['due_date'], '%Y-%m-%d')
            if current_date > due_date + timedelta(days=1):
                due_date = to_next_month(due_date)
                data[user_id]["cards"][i]["due_date"] = datetime.strftime(due_date, "%Y-%m-%d")
                is_changed = True
            if (due_date - current_date).days <= 5:
                reminders.append((user_id, item["name"], item['due_date']))

        if is_changed:
            data[user_id]["cards"] = sorted(data[user_id]["cards"],
                                            key=lambda x: x["due_date"])

    save_data(data)

    return reminders

def format_reminders(reminders):
    """format reminders"""
    if not reminders:
        return '清單是空的'

    formatted_reminders = '\n'.join([f'{index + 1}. {reminder["name"]} - {reminder["due_date"]}'
                                      for index, reminder in enumerate(reminders)])
    return formatted_reminders

def load_data():
    """load data"""
    if os.path.exists(DATA_FILE_PATH):
        with open(DATA_FILE_PATH, 'r', encoding="utf-8") as f:
            return json.load(f)
    else:
        return {}

def save_data(data):
    """save data"""
    with open(DATA_FILE_PATH, 'w', encoding="utf-8") as f:
        json.dump(data, f)

def set_user_state(user_id, state):
    """set user state"""
    data = load_data()

    if user_id not in data:
        data[user_id] = {}

    data[user_id]['state'] = state
    save_data(data)

def get_user_state(user_id):
    """get user state"""
    data = load_data()
    return data.get(user_id, {}).get('state', None)

if __name__ == "__main__":
    arg_parser = ArgumentParser(
        usage='Usage: python ' + __file__ + ' [--port <port>] [--help]'
    )
    arg_parser.add_argument('-p', '--port', default=8000, help='port')
    arg_parser.add_argument('-d', '--debug', default=False, help='debug')
    options = arg_parser.parse_args()

    app.run(host="0.0.0.0", debug=options.debug, port=options.port)

if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
