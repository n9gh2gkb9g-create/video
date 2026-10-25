"""从霞鹜文楷（LXGW WenKai，SIL OFL 1.1 开源可商用）中只保留用到的字，生成小体积 woff2。
用法: python3 tools/subset_font.py <LXGWWenKai-Medium.ttf>
"""
import os, sys, string
from fontTools import subset

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(os.environ.get("VIDEO_DIR", REPO))  # 视频目录，如 videos/fenshu
chars = set(string.printable) | set("×·—，。！？：“”《》、（）")
for p in ("web/index.html", "script/narration.json"):
    chars |= set(open(os.path.join(ROOT, p), encoding="utf-8").read())
text = "".join(sorted(c for c in chars if c.isprintable()))
out = os.path.join(ROOT, "web", "fonts", "wenkai-medium.woff2")
opt = subset.Options(); opt.flavor = "woff2"; opt.layout_features = ["*"]
font = subset.load_font(sys.argv[1], opt)
missing = [c for c in text if ord(c) > 127 and ord(c) not in font.getBestCmap()]
s = subset.Subsetter(opt); s.populate(text=text); s.subset(font)
subset.save_font(font, out, opt)
print(f"{len(text)} 字 → {out} ({os.path.getsize(out)//1024} KB)；字体缺字: {''.join(missing) or '无'}")
