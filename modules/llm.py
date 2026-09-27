import json
import base64
import os
import io
import requests
from PIL import Image


class LLM_engine():
    def __init__(self):
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
        self.config = self.read_settings()
        self.model = self.config.get("model", "qwen3.5:0.8b")
        self.max_tokens = self.config.get("max_tokens", 300)
        self.prompt = self.config.get("gpt_prompt", "")
        self.api_url = f"http://{self.config['IP']}:{self.config['PORT']}/api/chat"
        self.timeout = 300

    def read_settings(self):
        file_name = os.path.join(self.config_path, 'settings.json')
        try:
            with open(file_name, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error reading {file_name}: {e}")
            return {}

    def encode_image(self, image_path):
        try:
            image = Image.open(image_path)
            image_rgb = image.convert("RGB")
            buf = io.BytesIO()
            image_rgb.save(buf, format="JPEG", quality=95)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as e:
            print(f"Error encoding image: {e}")
            return None

    def request_answer(self, question, image=None):
        # Refresh model and prompt from current settings
        self.model = self.config.get("model", "qwen3.5:0.8b")
        self.prompt = self.config.get("gpt_prompt", self.prompt)
        if image is not None:
            b64 = self.encode_image(image)
            if b64 is None:
                return "Error: failed to encode image"
            user_msg = {"role": "user", "content": question, "images": [b64]}
        else:
            user_msg = {"role": "user", "content": question}

        # Add language to prompt
        lang = self.config.get("language", "ru")
        lang_names = {"ru": "Russian", "en": "English", "zh": "Chinese", "es": "Spanish"}
        lang_str = lang_names.get(lang, "Russian")
        system_prompt = self.prompt + f" Respond in {lang_str}."

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                user_msg,
            ],
            "stream": False,
            "think": False,
            "options": {"num_predict": self.max_tokens, "temperature": 0.7},
        }

        try:
            resp = requests.post(self.api_url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "").strip()
        except Exception as e:
            return f"LLM error: {e}"


if __name__ == "__main__":
    gpt = LLM_engine()
    print(f"Model: {gpt.model}")
    print(f"API: {gpt.api_url}")
    answer = gpt.request_answer("Привет, кто ты?")
    print(f"Answer: {answer}")