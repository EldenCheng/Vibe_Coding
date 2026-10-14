"""v0.11.0 续跑链路本地验证（不依赖真实站点）。

覆盖四项：
1. _single_episode_plan：裸 m3u8 → 单集计划（label 取文件名 / 去 query / 域名兜底）
2. _BatchProgress：list_url 写入、旧文件（无新键）兼容读取、resume_hint 写入
3. batch 裸 m3u8 直链全流程：本地 http 服务 + ffmpeg 真实切片 →
   下载/合并/进度/简介；批量进度顶层带 list_url 与 resume_hint
4. 同一 URL 重跑：已完成集跳过（manifest：日志出现"已完成，跳过"且 0 次下载）

运行：py -3.14 本地验证\run_resume_test.py
生成物只落在系统临时目录，不污染项目目录。
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from m3u_down.batch import (Episode, _BatchProgress, _single_episode_plan,  # noqa: E402
                            batch)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "OK " if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" —— {detail}" if detail and not cond else ""))


def make_segments(work):
    """用 ffmpeg 生成 3 段真实 mpegts 切片 + 一个明文 media 清单。"""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=3:size=64x48:rate=5",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "5",
         "-f", "segment", "-segment_time", "1", "-reset_timestamps", "1",
         str(work / "seg%d.ts")],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 生成切片失败: {r.stderr}")
    segs = sorted(work.glob("seg*.ts"))
    if len(segs) < 2:
        raise RuntimeError(f"切片数量异常: {[p.name for p in segs]}")
    m3u8 = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:1",
            "#EXT-X-MEDIA-SEQUENCE:0"]
    for i in range(len(segs)):
        m3u8 += ["#EXTINF:1.0,", f"seg{i}.ts"]
    m3u8.append("#EXT-X-ENDLIST")
    (work / "index.m3u8").write_text("\n".join(m3u8) + "\n", encoding="utf-8")
    return len(segs)


def serve(directory):
    """把 directory 作为根起一个本地 http 服务，返回 (base_url, stop_fn)。"""
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def stop():
        httpd.shutdown()
        httpd.server_close()
    return base, stop


def main():
    os.environ["NO_PROXY"] = "*"          # 本地服务不走系统代理
    tmp = Path(tempfile.mkdtemp(prefix="m3u_resume_"))
    print(f"临时目录: {tmp}\n")

    # ---------- 1. 单集计划 ----------
    print("== 1. _single_episode_plan ==")
    label, meta, eps = _single_episode_plan("https://cdn.x.com/hls/index.m3u8?token=abc")
    check("直链 label = 文件名去扩展名", label == "index", f"got {label!r}")
    check("meta.list_url = 原 URL", meta.get("list_url").endswith("index.m3u8?token=abc"))
    check("episodes 恰好 1 集且 url 原样", len(eps) == 1 and eps[0].url.endswith("token=abc"))
    check("episode 无 alts（无备用线路）", eps[0].alts in (None, []))

    label2, _, _ = _single_episode_plan("https://cdn.x.com/")   # 路径为空
    check("路径为空时回退域名", label2 == "cdn.x.com", f"got {label2!r}")

    # ---------- 2. _BatchProgress ----------
    print("\n== 2. _BatchProgress ==")
    p = tmp / "new.json"
    prog = _BatchProgress(p, list_url="https://eacg.net/voddetail/87441.html")
    check("list_url 写入 data", prog.data.get("list_url") == "https://eacg.net/voddetail/87441.html")
    prog.mark_url("https://eacg.net/vodplay/87441-2-1.html", "第01集", "done", "第01集.mp4")
    saved = json.loads(p.read_text(encoding="utf-8"))
    check("list_url 随 save 落盘", saved.get("list_url") == "https://eacg.net/voddetail/87441.html")
    check("episodes 正常", saved["episodes"]["https://eacg.net/vodplay/87441-2-1.html"]["status"] == "done")

    # 旧文件（v0.11.0 之前的结构）：无 list_url / resume_hint / 甚至无 episodes
    old = tmp / "old.json"
    old.write_text(json.dumps({"episodes": {
        "https://x/1": {"label": "第1集", "status": "done", "file": "第01集.mp4"}}}),
        encoding="utf-8")
    prog_old = _BatchProgress(old, list_url="https://x/list")
    check("旧文件 episodes 兼容读取", prog_old.status("https://x/1") == "done")
    check("旧文件补写 list_url", prog_old.data.get("list_url") == "https://x/list")

    broken = tmp / "broken.json"
    broken.write_text("{ 坏 json", encoding="utf-8")
    prog_bad = _BatchProgress(broken, list_url="https://x/y")
    check("坏 json 不崩且 episodes 为空 dict",
          prog_bad.data.get("episodes") == {} and prog_bad.data["list_url"] == "https://x/y")

    prog_h = _BatchProgress(tmp / "hint.json", list_url="https://x/list")
    prog_h.set_resume_hint("22", 2)
    check("resume_hint 写入", prog_h.data.get("resume_hint") == {"line": "22", "pick": 2})
    prog_h.set_resume_hint("22", 2)
    check("resume_hint 同值不重复落盘（幂等）",
          json.loads((tmp / "hint.json").read_text(encoding="utf-8"))["resume_hint"]
          == {"line": "22", "pick": 2})
    prog_h.set_resume_hint(None, None)
    check("空 line/默认 pick 归一", prog_h.data["resume_hint"] == {"line": "", "pick": 1})

    # 防回归：batch() 里纳管循环曾用 `for line in ...` 把 --line 参数同名覆盖，
    # 导致 resume_hint.line 被写成纳管日志行（v0.11.0 开发中现形）。此处静态断言
    # batch.py 里不再有遮蔽参数的同名循环变量。
    import re as _re
    src = (ROOT / "m3u_down" / "batch.py").read_text(encoding="utf-8")
    check("batch() 无遮蔽 --line 参数的同名循环变量",
          not _re.search(r"for\s+line\s+in\s+external\.format_report", src))

    # ---------- 3+4. 直链 batch 全流程 + 重跑跳过 ----------
    print("\n== 3. batch 裸 m3u8 全流程 ==")
    work = tmp / "srv"
    work.mkdir()
    n_seg = make_segments(work)
    print(f"已生成 {n_seg} 个切片 + index.m3u8（ffmpeg testsrc）")
    base, stop = serve(work)
    try:
        url = f"{base}/index.m3u8"
        out = tmp / "out"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            batch(url, yes=True, out_dir=str(out), interval=0, insecure=True)
        log1 = buf.getvalue()
        check("日志声明单集直链模式", "按单集批量下载" in log1)

        anime_dir = out / "index"
        final = anime_dir / "index.mp4"
        check("成品落盘 番剧目录/index.mp4", final.exists() and final.stat().st_size > 0)
        check("中间产物已清理（segments/_work 不残留）",
              not (anime_dir / "segments").exists() and not (anime_dir / "_work").exists())

        pj = json.loads((anime_dir / "批量进度.json").read_text(encoding="utf-8"))
        check("进度顶层 list_url = 直链 URL", pj.get("list_url") == url)
        check("进度顶层 resume_hint 默认值", pj.get("resume_hint") == {"line": "", "pick": 1})
        rec = pj["episodes"].get(url) or {}
        check("唯一一集状态 done", rec.get("status") == "done" and len(pj["episodes"]) == 1)
        check("该集记录了 ffprobe 分辨率", bool(rec.get("resolution")), f"rec={rec}")

        info = (anime_dir / "简介.md").read_text(encoding="utf-8")
        check("简介含来源直链行", f"来源列表页：{url}" in info)
        check("简介状态为完成", "| 完成 |" in info)
        check("直链模式无封面误导文案", "封面图未能保存到本地" not in info)

        print("\n== 4. 同一 URL 重跑（跳过验证） ==")
        before = final.stat().st_mtime_ns
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            batch(url, yes=True, out_dir=str(out), interval=0, insecure=True)
        log2 = buf2.getvalue()
        check("重跑日志出现'已完成，跳过'", "已完成，跳过" in log2)
        check("成品未被重写（mtime 不变）", final.stat().st_mtime_ns == before)
        check("重跑无 [下载] 新任务行", "[下载] 输出目录" not in log2)
    finally:
        stop()

    print(f"\n===== 汇总: 通过 {len(PASS)} / 失败 {len(FAIL)} =====")
    if FAIL:
        print("失败项:", *FAIL, sep="\n  - ")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
