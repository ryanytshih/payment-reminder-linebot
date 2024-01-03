"""
ChatModel
"""

import os
import sys
import json

import google.generativeai as genai
from google.generativeai.types.generation_types import BlockedPromptException


INIT_PROMPT_PATH = "prompt.json"
if os.path.exists(INIT_PROMPT_PATH):
    with open(INIT_PROMPT_PATH, "r", encoding="utf-8") as f:
        INIT_PROMPT = json.load(f)
else:
    INIT_PROMPT = []

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

if GOOGLE_API_KEY is None:
    print('Specify GOOGLE_API_KEY as environment variable.')
    sys.exit(1)

genai.configure(api_key=GOOGLE_API_KEY)


class ChatModel:
    """Chat with Gemini"""
    def __init__(self) -> None:
        self.model = genai.GenerativeModel(
            model_name="gemini-pro",
            safety_settings=[
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_NONE",
                }
            ]
        )
        self.user_sessions = {}

    def send_message(self, user_id, message):
        """Send message to Gemini API"""
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = self.model.start_chat(history=INIT_PROMPT)

        chat = self.user_sessions[user_id]
        try:
            response = chat.send_message(message)
        except BlockedPromptException:
            return "您的訊息可能含有騷擾、仇恨言論、煽情露骨或危險的內容，模型無法回應。"

        return response.text
