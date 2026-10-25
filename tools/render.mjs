// 逐帧渲染：无头浏览器把 web/index.html 跳到每一帧的时刻截图，经管道交给 FFmpeg 编码。
// 用法: node tools/render.mjs [--sub 0|1] [--names 0|1] [--fps 30] [--out build/video.mp4] [--from 秒 --to 秒] [--stills 秒,秒,...]
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const { chromium } = createRequire(import.meta.url)("playwright"); // 兼容全局安装（NODE_PATH）
const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i > 0 ? process.argv[i + 1] : d; };
const fps = +arg("fps", 30), sub = arg("sub", "1") === "1", names = arg("names", "1") === "1";
const out = path.resolve(ROOT, arg("out", "build/video.mp4"));
const tl = JSON.parse(fs.readFileSync(path.join(ROOT, "build/timeline.json"), "utf8"));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.addInitScript(() => { window.__RENDER__ = true; });
await page.goto(pathToFileURL(path.join(ROOT, "web/index.html")).href);
await page.evaluate(async ([tl, opt]) => {
  await document.fonts.load('500 40px "WenKai"');
  if (!document.fonts.check('500 40px "WenKai"')) throw new Error("字体未加载");
  document.body.style.margin = "0"; document.getElementById("bar").remove();
  const c = document.getElementById("c"); c.style.width = "1920px"; c.style.maxWidth = "none";
  window.setup(tl, opt);
}, [tl, { sub, names }]);
fs.mkdirSync(path.join(ROOT, "build"), { recursive: true });
fs.writeFileSync(path.join(ROOT, "build/cues.json"), JSON.stringify(await page.evaluate(() => window.cues()), null, 1));

const grab = async t => {
  await page.evaluate(t => window.renderAt(t), t);
  return page.screenshot({ type: "png", clip: { x: 0, y: 0, width: 1920, height: 1080 } });
};

const stills = arg("stills");
if (stills) {
  const dir = path.join(ROOT, "build/stills"); fs.mkdirSync(dir, { recursive: true });
  for (const s of stills.split(",")) fs.writeFileSync(path.join(dir, `t${(+s).toFixed(2)}.png`), await grab(+s));
  console.log("stills →", dir);
} else {
  const from = +arg("from", 0), to = +arg("to", tl.duration), n = Math.round((to - from) * fps);
  const ff = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(fps), "-i", "-",
    "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p", "-r", String(fps), out], { stdio: ["pipe", "inherit", "inherit"] });
  const t0 = Date.now();
  for (let i = 0; i < n; i++) {
    const buf = await grab(from + i / fps);
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once("drain", r));
    if (i % 150 === 0) console.log(`帧 ${i}/${n}  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
  ff.stdin.end(); await new Promise(r => ff.on("close", r));
  console.log("视频 →", out);
}
await browser.close();
