"""
TTS test (Silero) via system audio output.
Run: python3 test_tts.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.tts import TTS

print("Initializing Silero TTS...")
tts = TTS()
print(f"Model: {tts.model_id}, voice: {tts.speaker}, sample rate: {tts.sample_rate} Hz")

phrases = [
    "Привет. Я сканер из Сабнотики. Готов к работе.",
    "Обнаружен: кружка керамическая. Ёмкость около 300 миллилитров. Представляет нулевую угрозу.",
    "Внимание! Обнаружена неизвестная форма жизни. Рекомендуется осторожность.",
]

for i, phrase in enumerate(phrases, 1):
    print(f"\n[{i}/{len(phrases)}] \"{phrase}\"")
    input("Press ENTER to play...")
    try:
        tts.synthesize_and_play(phrase)
    except Exception as e:
        print(f"Error: {e}")

print("\nTest finished.")
