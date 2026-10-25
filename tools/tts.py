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
    args = ap.parse_args()

    cfg = json.load(open(os.path.join(ROOT, "script", "narration.json"), encoding="utf-8"))
    sid = args.sid if args.sid is not None else cfg["voice"]["sid"]
    tts, asr = load_tts(args.models), load_asr(args.models)

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
            a = tts.generate(seg["tts"], sid=sid, speed=cfg["voice"]["speed"])
            x = np.asarray(a.samples, dtype=np.float32)
            s = asr.create_stream(); s.accept_waveform(a.sample_rate, x); asr.decode_stream(s)
            x = trim(resample(x, a.sample_rate, SR))
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
