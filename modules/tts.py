import os
import torch
import soundfile as sf
import subprocess

TTS_LANGS = {
    'ru': {'model': 'v4_ru', 'speaker': 'xenia'},
    'en': {'model': 'v3_en', 'speaker': 'en_0'},
    'zh': {'model': 'v3_en', 'speaker': 'en_0'},  # Silero does not support Chinese
    'es': {'model': 'v3_es', 'speaker': 'es_1'},
}


class TTS:
    def __init__(self, language='ru'):
        self.language = language
        self.device = torch.device('cpu')
        self.audio = None
        self.sample_rate = 48000
        self.output_dir = "data"
        self._model = None
        self._model_lang = None

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def _ensure_model(self):
        """Load language-specific model (lazy)."""
        if self._model is not None and self._model_lang == self.language:
            return
        cfg = TTS_LANGS.get(self.language, TTS_LANGS['ru'])
        self._model, _ = torch.hub.load(
            repo_or_dir='snakers4/silero-models',
            model='silero_tts',
            language=self.language if self.language != 'zh' else 'en',
            speaker=cfg['model'], trust_repo=True,
        )
        self._model.to(self.device)
        self._model_lang = self.language
        self.speaker = cfg['speaker']

    def set_language(self, lang):
        self.language = lang

    def synthesize_and_play(self, text, save_path=None):
        self._ensure_model()
        # Silero TTS limit — truncate long text
        max_chars = 500
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + "..."
        for attempt in range(3):
            try:
                self.audio = self._model.apply_tts(
                    text=text,
                    speaker=self.speaker,
                    sample_rate=self.sample_rate,
                )
                break
            except Exception as e:
                print(f"TTS attempt {attempt+1} error: {e}")
                text = text[:max(50, len(text)//2)].rsplit(" ", 1)[0]
                if attempt == 2:
                    print("TTS: failed to synthesize speech")
                    return
        if save_path is None:
            output_path = os.path.join(self.output_dir, "output.wav")
        else:
            output_path = save_path

        sf.write(output_path, self.audio.numpy(), self.sample_rate)
        print(f"Audio: {output_path}")

        # paplay first (PulseAudio owns I2S/BT); aplay fallback if PA is down
        played = False
        for cmd in (
            ["paplay", output_path],
            ["aplay", "-D", "plughw:0,0", output_path],
            ["aplay", output_path],
        ):
            try:
                r = subprocess.run(cmd, check=False, capture_output=True, text=True)
                if r.returncode == 0:
                    played = True
                    break
                print(f"Playback {cmd[0]} failed: {r.stderr.strip()}")
            except Exception as e:
                print(f"Playback {cmd[0]} error: {e}")
        if not played:
            print("Playback error: all outputs failed")


if __name__ == "__main__":
    tts = TTS(language='ru')
    tts.synthesize_and_play("Привет! Файл успешно сохранён.")
