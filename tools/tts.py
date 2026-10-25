"""生成旁白：逐句合成 → 语音识别校对 → 排时间轴 → 输出配音、字幕和 timeline.json。

用法: python3 tools/tts.py --models <模型目录>
模型目录需包含 kokoro-multi-lang-v1_1/ 和 sherpa-onnx-paraformer-zh-small-2024-03-09/
（均来自 https://github.com/k2-fsa/sherpa-onnx/releases ）。
"""
import argparse, json, os
import numpy as np, soundfile as sf, sherpa_onnx as so

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR = 48000


def load_tts(models, threads=8):
    k = os.path.join(models, "kokoro-multi-lang-v1_1") + "/"
    return so.OfflineTts(so.OfflineTtsConfig(model=so.OfflineTtsModelConfig(
        kokoro=so.OfflineTtsKokoroModelConfig(
            model=k + "model.onnx", voices=k + "voices.bin", tokens=k + "tokens.txt",
            data_dir=k + "espeak-ng-data", dict_dir=k + "dict",
            lexicon=k + "lexicon-us-en.txt," + k + "lexicon-zh.txt"),
        num_threads=threads)))


def load_asr(models, threads=8):
    p = os.path.join(models, "sherpa-onnx-paraformer-zh-small-2024-03-09") + "/"
    return so.OfflineRecognizer.from_paraformer(
        paraformer=p + "model.int8.onnx", tokens=p + "tokens.txt", num_threads=threads)


class GeminiTTS:
    """Gemini 语音合成（参考教程的做法）：用自然语言描述语气，逐句合成。
    API Key 取自环境变量 GEMINI_API_KEY，或仓库根目录 .env 里的 GEMINI_API_KEY=...（.env 不入库）。
    同一句话 + 同样设置的结果缓存在 build/tts_cache/，重跑不重复计费。"""

    def __init__(self, cfg):
        self.model = cfg.get("model", "gemini-2.5-flash-preview-tts")
        self.voice = cfg.get("voice", "Leda")
        self.style = cfg.get("style", "")
        self.key = os.environ.get("GEMINI_API_KEY") or self._dotenv()
        if not self.key:
            raise SystemExit("缺少 GEMINI_API_KEY（环境变量或 .env）")
        self.cache = os.path.join(ROOT, "build", "tts_cache"); os.makedirs(self.cache, exist_ok=True)

    @staticmethod
    def _dotenv():
        p = os.path.join(ROOT, ".env")
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                k, _, v = line.strip().partition("=")
                if k.strip() == "GEMINI_API_KEY":
                    return v.strip().strip('"\'')

    def say(self, text):
        import base64, hashlib, time, urllib.request, urllib.error
        prompt = f"{self.style}\n{text}" if self.style else text
        h = hashlib.sha1(f"{self.model}|{self.voice}|{prompt}".encode()).hexdigest()[:16]
        fp = os.path.join(self.cache, h + ".wav")
        if os.path.exists(fp):
            x, sr = sf.read(fp, dtype="float32"); return x, sr
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}}},
        }).encode()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        for attempt in range(5):
            req = urllib.request.Request(url, body, {"Content-Type": "application/json", "x-goog-api-key": self.key})
            try:
                d = json.load(urllib.request.urlopen(req, timeout=120)); break
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="ignore")[:300]
                if e.code in (429, 500, 503) and attempt < 4:
                    time.sleep(2 ** attempt * 3); continue
                raise SystemExit(f"Gemini 请求失败 {e.code}: {msg}")
        pcm = base64.b64decode(d["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
        x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768  # 24 kHz 单声道 16 位 PCM
        sf.write(fp, x, 24000)
        return x, 24000


def resample(x, sr_in, sr_out):
    n = int(round(len(x) * sr_out / sr_in))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def trim(x, thresh=0.01, pad=0.04):
    idx = np.where(np.abs(x) > thresh)[0]
    if len(idx) == 0:
        return x
    a = max(0, idx[0] - int(pad * SR))
    b = min(len(x), idx[-1] + int(pad * SR))
    return x[a:b]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--sid", type=int)
    ap.add_argument("--engine", choices=["kokoro", "gemini"], default="kokoro")
    args = ap.parse_args()

    cfg = json.load(open(os.path.join(ROOT, "script", "narration.json"), encoding="utf-8"))
    sid = args.sid if args.sid is not None else cfg["voice"]["sid"]
    asr = load_asr(args.models)
    if args.engine == "gemini":
        gem = GeminiTTS(cfg.get("gemini", {}))
    else:
        kokoro = load_tts(args.models)

    t = cfg["lead_in"]
    clips, timeline = [], {"title": cfg["title"], "scenes": [], "segments": []}
    for si, sc in enumerate(cfg["scenes"]):
        if si:
            t += cfg["scene_gap"]
        scene = {"id": sc["id"], "start": round(t, 3)}
        t += sc["pre"]
        for gi, seg in enumerate(sc["segments"]):
            if gi:
                t += cfg["gap"]
            if args.engine == "gemini":
                x, sr_in = gem.say(seg["tts"])
            else:
                a = kokoro.generate(seg["tts"], sid=sid, speed=cfg["voice"]["speed"])
                x, sr_in = np.asarray(a.samples, dtype=np.float32), a.sample_rate
            s = asr.create_stream(); s.accept_waveform(sr_in, x); asr.decode_stream(s)
            x = trim(resample(x, sr_in, SR))
            d = len(x) / SR
            print(f"{seg['id']:>4} {t:6.2f}s +{d:4.2f}s  {seg['tts']}\n      识别: {s.result.text}")
            clips.append((t, x))
            timeline["segments"].append({"id": seg["id"], "scene": sc["id"], "start": round(t, 3),
                                         "end": round(t + d, 3), "sub": seg["sub"]})
            t += d
        t += sc["post"]
        scene["end"] = round(t, 3)
        timeline["scenes"].append(scene)
    t += cfg["tail"]
    timeline["duration"] = round(t, 3)
    timeline["scenes"][-1]["end"] = timeline["duration"]

    voice = np.zeros(int(t * SR) + 1, dtype=np.float32)
    for st, x in clips:
        i = int(st * SR); voice[i:i + len(x)] += x
    voice *= 0.89 / max(1e-6, np.abs(voice).max())
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    sf.write(os.path.join(ROOT, "build", "voice.wav"), voice, SR)
    json.dump(timeline, open(os.path.join(ROOT, "build", "timeline.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    def ts(v):
        ms = int(round(v * 1000)); return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}"
    with open(os.path.join(ROOT, "output", "乘号的由来.srt"), "w", encoding="utf-8") as f:
        for i, g in enumerate(timeline["segments"], 1):
            f.write(f"{i}\n{ts(g['start'])} --> {ts(g['end'] + 0.25)}\n{g['sub']}\n\n")
    print(f"总时长 {t:.2f}s")


if __name__ == "__main__":
    main()
