"""命令行入口：py -m m3u_down {sniff | get | play | batch}"""
import argparse
import shutil
from pathlib import Path

from . import __version__, config, sites, ytdlp_engine
from .batch import batch as run_batch
from .downloader import run as run_download
from .parser import DRMError, load_playlist
from .player_capture import build_local_player_page, capture as run_capture
from .session import build_session, session_from_sniff
from .sniffer import sniff as run_sniff
from .utils import is_m3u8_url, sanitize_name


def _add_common(p):
    p.add_argument("url", help="m3u8 直链或播放页地址")
    p.add_argument("-o", "--out", default=None, help="输出目录（默认 downloads/<标题>）")
    p.add_argument("--concurrency", type=int, default=None,
                   help=f"并发下载数（默认读 config，{config.CONCURRENCY}）")
    p.add_argument("--proxy", default=None,
                   help="代理，如 http://127.0.0.1:7890（默认读 config）")
    p.add_argument("--insecure", action=argparse.BooleanOptionalAction, default=None,
                   help="跳过 HTTPS 证书校验（默认读 config）")
    # 音频模式（v0.12.0）：只对 yt-dlp 站点（B站/YouTube 等）有效；自研引擎会忽略并提示
    p.add_argument("--audio-only", action="store_true",
                   help="只下载音频（不下视频字节），转封装 + 写标签/封面后存为音频文件"
                        "（仅 yt-dlp 站点：B站/YouTube 等）")
    p.add_argument("--audio-format", choices=("m4a", "mp3", "opus", "flac"), default=None,
                   help="音频格式（配合 --audio-only；默认读 ytdlp_sites.json 的 "
                        "audio_format，缺省 m4a）")
    return p


def _add_keep(p):
    p.add_argument("--keep", action="store_true",
                   help="保留工作目录与中间产物（切片/清单/进度文件），即不做后处理")
    return p


def _check_unsupported(url):
    """命中不推荐站点（sites 配置 unsupported=true）的 URL：打印原因并返回 True。

    调用方应随即退出且不执行任何下载。
    """
    if not url:
        return False
    site = sites.match(url)
    if site is not None and site.unsupported:
        print(f"\n[提示] 站点 {site.name}（{', '.join(site.domains)}）不推荐使用本下载器：")
        print(f"  {site.unsupported_reason}")
        print("已退出，未执行任何下载。")
        return True
    return False


def _run_ytdlp(args):
    """yt-dlp 路由命中时的分派：单集命令下单个视频，batch 下整季/合集。"""
    url = args.url
    if getattr(args, "line", None) is not None or getattr(args, "pick", None) not in (None, 1):
        print("[yt-dlp] 提示：该站点走 yt-dlp 引擎，--line / --pick 不适用（已忽略）")
    audio_only = bool(getattr(args, "audio_only", False))
    audio_format = getattr(args, "audio_format", None)
    if args.cmd == "batch":
        # 音频模式一期只做单集（歌单/合集批量留待后续版本）
        if audio_only:
            raise RuntimeError("批量下载暂不支持 --audio-only（音频模式目前仅支持单集）")
        ytdlp_engine.download_entries(
            url, interval=args.interval, episodes=args.episodes, yes=args.yes,
            proxy=args.proxy, insecure=args.insecure,
            concurrency=args.concurrency, out_dir=args.out)
        return
    if getattr(args, "no_download", False):
        ytdlp_engine.describe(url, proxy=args.proxy, insecure=args.insecure,
                              concurrency=args.concurrency)
        return
    ytdlp_engine.download_single(url, out_dir=args.out, proxy=args.proxy,
                                 insecure=args.insecure,
                                 concurrency=args.concurrency,
                                 audio_only=audio_only,
                                 audio_format=audio_format)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="m3u_down",
        description="m3u8 嗅探/下载/合并工具"
                    "（sniff 嗅探 · get 直链 · play 播放器模式 · batch 列表页批量）")
    ap.add_argument("--version", action="version", version=f"m3u_down {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get", help="直接下载 m3u8 直链")
    _add_common(g)
    _add_keep(g)
    g.add_argument("--referer", help="请求 Referer")
    g.add_argument("--user-agent", help="请求 User-Agent")
    g.add_argument("--cookie", help='Cookie 字符串，如 "k=v; k2=v2"')
    g.add_argument("--quality", choices=("best", "worst"), default="best",
                   help="master 清单选流策略（默认 best）")
    g.add_argument("--variant-index", type=int, default=None,
                   help="手动指定 master 变体序号（从 0 开始）")

    s = sub.add_parser("sniff", help="打开播放页嗅探 m3u8 并下载")
    _add_common(s)
    _add_keep(s)
    s.add_argument("--auto", type=int, metavar="N",
                   help="非交互：出现第 N 个候选时自动选择（测试/脚本用）")
    s.add_argument("--no-download", action="store_true", help="仅嗅探列出候选，不下载")
    s.add_argument("--max-wait", type=int, default=1800, help="嗅探最长等待秒数")
    s.add_argument("--quality", choices=("best", "worst"), default="best")
    s.add_argument("--variant-index", type=int, default=None)

    p = sub.add_parser("play", help="播放器模式：模拟在线播放并缓存切片")
    _add_common(p)
    _add_keep(p)
    p.add_argument("--speed", type=float, default=1.0,
                   help="播放倍速 1~16，>1 可缩短捕获时间")
    p.add_argument("--max-wait", type=int, default=7200, help="最长等待秒数")

    b = sub.add_parser("batch", help="列表页批量下载（解析剧集+生成简介，逐集下载）")
    b.add_argument("--interval", type=int, default=None,
                   help="每集下载间隔秒数（默认读 config.download_interval）")
    b.add_argument("--episodes", default=None,
                   help='集数范围，如 "1-12,15"（配合 --yes；默认交互确认）')
    b.add_argument("--yes", action="store_true", help="跳过选集确认，按范围/全部下载")
    b.add_argument("--pick", type=int, default=1,
                   help="每集嗅探时自动选择第 N 个候选（默认 1）")
    b.add_argument("--line", default=None,
                   help="线路序号或名称（内嵌播放器站点如 mvffm；如 22 或 "
                        "'FLV 22 推薦31'，默认第1条线路）")
    b.add_argument("--no-adopt", dest="adopt", action="store_false",
                   help="不扫描番剧目录里已有的其它 mp4（默认会扫描并把能唯一对应到"
                        "剧集的文件并入 批量进度.json，避免重复下载）")
    _add_common(b)

    args = ap.parse_args(argv)
    try:
        url = getattr(args, "url", None)
        # yt-dlp 路由优先于 unsupported 拦截（用户显式列入清单即放行）。
        # 裸 m3u8 直链跳过路由（get/play 常用），免付解析器匹配开销
        if url and not is_m3u8_url(url) and ytdlp_engine.route(url) == "ytdlp":
            _run_ytdlp(args)
            return 0
        # 走到这里 = 自研引擎：音频参数无意义（自研切片多为音视频混合），提示并忽略
        if getattr(args, "audio_only", False):
            print("[提示] --audio-only 仅对 yt-dlp 站点（B站/YouTube 等）有效；"
                  "当前地址会走自研引擎，音频参数已忽略。")
        # 不推荐站点拦截：命中即提示原因并退出（sniff/get/play/batch 通用）
        if _check_unsupported(url):
            return 3
        if args.cmd == "get":
            _cmd_get(args)
        elif args.cmd == "sniff":
            _cmd_sniff(args)
        elif args.cmd == "play":
            _cmd_play(args)
        else:
            _cmd_batch(args)
    except DRMError as e:
        print(f"\n[失败] {e}")
        print("说明：真 DRM 的密钥由浏览器 CDM 内部申领，明文不经过网络，无法合规获取。")
        return 2
    except KeyboardInterrupt:
        print("\n[中断] 已退出；get/sniff/batch 重跑同一命令可续传/续跑")
        return 130
    except Exception as e:
        print(f"\n[失败] {e}")
        # v0.13.0：若本次因代理端口连不上改走了直连，补一句，免得误判为下载器故障
        note = ytdlp_engine.last_exit_note()
        if note:
            print(f"[提示] 本次代理 {note} 不可用，已改走直连；直连仍失败多为网络问题，"
                  "请检查网络，或改用可用代理后重试。")
        return 1
    return 0


def _postprocess(final, page_url="", title="", keep=False, flatten=True):
    """单集后处理（get/sniff/play）：清洗命名 → 扁平 → 清理中间产物。

    - keep=True 时什么都不做（保留工作目录与全部中间产物）
    - title 提供且站点配置（按 page_url 域名匹配）有 title_subs 规则时，
      成品改名为清洗后的标题（无规则/无配置则用整页标题；无标题保持原名）
    - flatten=True 且未用 -o 指定输出目录时，成品扁平到 downloads/ 根目录，
      随后清理 segments/、filelist.txt、playlist.m3u8、progress.json 并删除空目录
    """
    if keep or not final:
        return
    final = Path(final)
    if not final.exists():
        return
    out_dir = final.parent
    name = ""
    if title:
        site = sites.match(page_url) if page_url else None
        name = sanitize_name(site.clean_title(title) if site else title)
    if name and name != final.stem:
        # 重名自动加序号，避免覆盖
        target = (Path(config.OUTPUT_DIR) if flatten else out_dir) / f"{name}{final.suffix}"
        k = 2
        while target.exists():
            target = target.with_name(f"{name}_{k}{final.suffix}")
            k += 1
        shutil.move(str(final), str(target))
        final = target
        print(f"[后处理] 已重命名: {final}")
    # 清理中间产物
    for f in ("filelist.txt", "playlist.m3u8", "progress.json"):
        try:
            (out_dir / f).unlink(missing_ok=True)
        except OSError:
            pass
    segs = out_dir / "segments"
    if segs.is_dir():
        shutil.rmtree(segs, ignore_errors=True)
    # 目录已空（成品已移走）则一并删除
    if out_dir != final.parent:
        try:
            out_dir.rmdir()
        except OSError:
            pass


def _cmd_get(args):
    # get 的 URL 通常是 CDN 直链（域名与站点配置不同）——匹配不到就用默认
    # 「代理优先」；偶然匹配到站点（如站点自家 m3u8）则按站点出口偏好
    cfg = sites.match(args.url)
    df = bool(cfg and cfg.proxy_policy == "direct_first")
    session = build_session(referer=args.referer, user_agent=args.user_agent,
                            cookie=args.cookie, insecure=args.insecure,
                            proxy=args.proxy, direct_first=df)
    playlist = load_playlist(session, args.url, quality=args.quality,
                             variant_index=args.variant_index)
    final = run_download(session, playlist, out_dir=args.out,
                         concurrency=args.concurrency)
    _postprocess(final, keep=args.keep, flatten=args.out is None)


def _cmd_sniff(args):
    result = run_sniff(args.url, auto=args.auto, max_wait=args.max_wait)
    print(f"\n[嗅探] 已选择: {result.url}")
    if args.no_download:
        return
    cfg = sites.match(args.url)
    df = bool(cfg and cfg.proxy_policy == "direct_first")
    session = session_from_sniff(result, insecure=args.insecure, proxy=args.proxy,
                                 direct_first=df)
    playlist = load_playlist(session, result.url, quality=args.quality,
                             variant_index=args.variant_index)
    # 有页面标题时优先用标题命名输出目录
    out_dir = args.out
    if not out_dir and result.title:
        out_dir = str(Path(config.OUTPUT_DIR) / sanitize_name(result.title))
    final = run_download(session, playlist, out_dir=out_dir,
                         concurrency=args.concurrency)
    _postprocess(final, page_url=args.url, title=result.title,
                 keep=args.keep, flatten=args.out is None)


def _cmd_play(args):
    url = args.url
    if url.lower().split("?")[0].endswith((".m3u8", ".m3u")):
        print("[播放模式] 输入为裸 m3u8，生成本地 hls.js 播放页代播"
              "（若站点未开 CORS 可能失败，建议提供播放页地址）")
        url = build_local_player_page(url)
    final = run_capture(url, out_dir=args.out, speed=args.speed,
                        max_wait=args.max_wait, insecure=args.insecure,
                        proxy=args.proxy)
    _postprocess(final, keep=args.keep, flatten=args.out is None)


def _cmd_batch(args):
    run_batch(args.url, interval=args.interval, episodes=args.episodes,
              yes=args.yes, pick=args.pick, line=args.line, insecure=args.insecure,
              proxy=args.proxy, concurrency=args.concurrency, out_dir=args.out,
              adopt=args.adopt)
