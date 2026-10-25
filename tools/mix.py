"""用代码合成音效和背景音乐（八音盒风格），按 build/cues.json 的时刻铺音效，
旁白出现时自动压低音乐，最后响度标准化，输出 build/mix.wav 和 output/音频分轨/。
"""
import json, os, subprocess
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR = 48000
R = np.random.default_rng(2026)


def env(n, a=0.005, d=None, curve=6.0):
    t = np.arange(n) / SR
    e = np.exp(-t * curve) if d is None else np.clip(1 - t / d, 0, 1) ** 2
    att = np.clip(t / a, 0, 1)
    return e * att


def tone(f, dur, curve=6.0, harm=((1, 1.0),), a=0.004):
    n = int(dur * SR); t = np.arange(n) / SR
    f = np.broadcast_to(np.asarray(f, dtype=float), (n,)) if np.ndim(f) else np.full(n, float(f))
    ph = 2 * np.pi * np.cumsum(f) / SR
    return sum(g * np.sin(ph * k) for k, g in harm) * env(n, a, curve=curve)


def noise(dur):
    return R.standard_normal(int(dur * SR))


def band(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], btype="band", fs=SR, output="sos"), x)


def sweep_band(x, f0, f1, width=1.0, steps=24):
    """分段带通，模拟中心频率扫过（“嗖”声）"""
    out = np.zeros_like(x); L = len(x); seg = L // steps + 1
    for i in range(steps):
        fc = f0 * (f1 / f0) ** (i / (steps - 1))
        lo, hi = fc / (1 + width), min(fc * (1 + width), SR / 2 - 100)
        a, b = i * seg, min(L, (i + 1) * seg + 2048)
        y = band(x[a:b], lo, hi)
        w = np.ones(b - a); fade = min(1024, (b - a) // 2)
        if i: w[:fade] = np.linspace(0, 1, fade)
        out[a:b] += y * w
    return out


def add(*xs):
    out = np.zeros(max(len(x) for x in xs))
    for x in xs:
        out[:len(x)] += x
    return out


def bell(f, dur=1.4, g=1.0):
    return g * tone(f, dur, curve=3.5, harm=((1, 1), (2.76, 0.35), (5.4, 0.12)))


def sfx(kind):
    if kind == "pop":
        n = int(0.11 * SR); t = np.arange(n) / SR
        return 0.8 * tone(520 * np.exp(-t * 18) + 260, 0.11, curve=30)
    if kind == "tick":
        return 0.5 * tone(1700, 0.05, curve=80)
    if kind == "draw":
        x = band(noise(0.32), 1800, 6000) * env(int(0.32 * SR), 0.03, d=0.32)
        return 0.35 * x / np.abs(x).max()
    if kind == "ding":
        return add(0.5 * bell(1318.5), 0.25 * bell(1975.5, 1.2))
    if kind == "stamp":
        return add(0.9 * tone(95, 0.25, curve=18), 0.25 * band(noise(0.08), 200, 2000) * env(int(0.08 * SR), 0.001, curve=40))
    if kind == "whoosh":
        d = 0.55; x = sweep_band(noise(d), 400, 3000, 0.6) * np.sin(np.linspace(0, np.pi, int(d * SR))) ** 2
        return 0.6 * x / np.abs(x).max()
    if kind == "paper":
        d = 0.45; x = band(noise(d), 1500, 7000) * (R.random(int(d * SR)) < 0.08) * np.sin(np.linspace(0, np.pi, int(d * SR)))
        return 0.5 * x / (np.abs(x).max() + 1e-9)
    if kind == "scratch":
        d = 1.5; n = int(d * SR); x = band(noise(d), 2500, 8000)
        g = (np.sin(np.arange(n) / SR * 2 * np.pi * 7) > 0.2).astype(float)
        x = x * sosfilt(butter(1, 30, fs=SR, output="sos"), g) * np.sin(np.linspace(0, np.pi, n)) ** 0.5
        return 0.22 * x / np.abs(x).max()
    if kind == "rewind":
        d = 3.0; n = int(d * SR); t = np.arange(n) / SR
        f = 900 * (220 / 900) ** (t / d) * (1 + 0.04 * np.sin(2 * np.pi * 9 * t))
        x = tone(f, d, curve=0.0, harm=((1, 1), (2, 0.3))) * np.sin(np.linspace(0, np.pi, n)) ** 1.5
        w = sweep_band(noise(d), 4000, 500, 0.5) * np.sin(np.linspace(0, np.pi, n)) ** 2
        return 0.25 * x + 0.25 * w / np.abs(w).max()
    if kind == "forward":
        d = 1.1; n = int(d * SR); t = np.arange(n) / SR
        x = tone(300 * 4 ** (t / d), d, curve=0, harm=((1, 1), (2, 0.25))) * np.sin(np.linspace(0, np.pi, n))
        w = sweep_band(noise(d), 500, 5000, 0.5) * np.sin(np.linspace(0, np.pi, n)) ** 2
        return 0.22 * x + 0.3 * w / np.abs(w).max()
    if kind == "boing":
        d = 0.6; t = np.arange(int(d * SR)) / SR
        return 0.45 * tone(260 + 140 * np.exp(-t * 6) * np.sin(2 * np.pi * 12 * t), d, curve=5)
    if kind == "wobble":
        d = 0.7; t = np.arange(int(d * SR)) / SR
        return 0.35 * tone(520 - 160 * t / d + 25 * np.sin(2 * np.pi * 8 * t), d, curve=3, harm=((1, 1), (2, 0.4), (3, 0.15)), a=0.03)
    if kind == "drop":
        d = 0.16; t = np.arange(int(d * SR)) / SR
        return 0.7 * tone(700 + 1400 * (t / d) ** 0.5, d, curve=25)
    if kind == "sparkle":
        out = np.zeros(int(1.4 * SR))
        for i, f in enumerate([1568, 2093, 2637, 3136, 4186]):
            b = bell(f, 1.0, 0.25); a = int(i * 0.07 * SR); out[a:a + len(b)] += b[:len(out) - a]
        return out
    if kind == "tada":
        out = np.zeros(int(2.4 * SR))
        for i, f in enumerate([523.25, 659.25, 783.99, 1046.5]):
            b = bell(f, 2.2, 0.32); a = int(i * 0.09 * SR); out[a:a + len(b)] += b[:len(out) - a]
        return out
    raise ValueError(kind)


def music(dur, quiet_end):
    """八音盒 + 柔和低音：C–Am–F–G 循环，每分钟 92 拍，确定性生成。"""
    bpm = 92; beat = 60 / bpm; bar = 4 * beat
    chords = [(60, 64, 67), (57, 60, 64), (53, 57, 60), (55, 59, 62)]
    hz = lambda m: 440 * 2 ** ((m - 69) / 12)
    out = np.zeros(int((dur + 3) * SR)); rr = np.random.default_rng(7)
    nbars = int(np.ceil(dur / bar))
    for b in range(nbars):
        ch = chords[b % 4]; t0 = b * bar
        # 低音
        for k, m in enumerate((ch[0] - 12, ch[0] - 12)):
            x = 0.30 * tone(hz(m), bar * 0.9, curve=1.6, harm=((1, 1), (2, 0.2)), a=0.05)
            i = int((t0 + k * 2 * beat) * SR); out[i:i + len(x)] += x[:len(out) - i]
        # 旋律：八分音符，从和弦音与五声音阶里挑
        scale = [ch[0] + 12, ch[1] + 12, ch[2] + 12, ch[0] + 24, 74, 76]
        for e in range(8):
            if e % 2 and rr.random() < 0.45:
                continue
            m = scale[int(rr.integers(0, len(scale)))] if e else ch[0] + 12 + (12 if b % 8 >= 4 else 0)
            x = 0.16 * tone(hz(m), 1.2, curve=4.5, harm=((1, 1), (3, 0.12), (5.2, 0.05)))
            i = int((t0 + e * beat / 2) * SR); out[i:i + len(x)] += x[:len(out) - i]
    out = out[:int(dur * SR)]
    t = np.arange(len(out)) / SR
    out *= np.clip(t / 1.5, 0, 1) * np.clip((dur - t) / 2.5, 0, 1)
    return out


def main():
    tl = json.load(open(os.path.join(ROOT, "build", "timeline.json"), encoding="utf-8"))
    cues = json.load(open(os.path.join(ROOT, "build", "cues.json"), encoding="utf-8"))
    voice, sr = sf.read(os.path.join(ROOT, "build", "voice.wav"), dtype="float32")
    assert sr == SR
    n = int(tl["duration"] * SR); voice = np.pad(voice, (0, max(0, n - len(voice))))[:n]

    fx = np.zeros(n + SR * 3)
    for c in cues:
        x = sfx(c["type"]) * c.get("gain", 1); i = int(c["t"] * SR); fx[i:i + len(x)] += x
    fx = fx[:n]

    bgm = music(tl["duration"], 0)
    # 旁白出现时把音乐压低（侧链闪避）
    act = np.zeros(n)
    for g in tl["segments"]:
        act[int((g["start"] - 0.15) * SR):int((g["end"] + 0.25) * SR)] = 1
    k = int(0.25 * SR); act = np.convolve(act, np.ones(k) / k, mode="same")
    bgm *= 1 - 0.55 * act

    def db(x, d): return x * 10 ** (d / 20)
    m = voice + db(fx, -9) + db(bgm, -13)
    out_dir = os.path.join(ROOT, "output", "音频分轨"); os.makedirs(out_dir, exist_ok=True)
    sf.write(os.path.join(out_dir, "旁白.wav"), voice, SR)
    sf.write(os.path.join(out_dir, "背景音乐.wav"), db(bgm, -13).astype(np.float32), SR)
    sf.write(os.path.join(out_dir, "音效.wav"), db(fx, -9).astype(np.float32), SR)
    raw = os.path.join(ROOT, "build", "mix_raw.wav")
    sf.write(raw, np.stack([m, m], 1).astype(np.float32), SR, subtype="FLOAT")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-ar", str(SR), os.path.join(ROOT, "build", "mix.wav")], check=True)
    print("混音 →", os.path.join(ROOT, "build", "mix.wav"))


if __name__ == "__main__":
    main()
