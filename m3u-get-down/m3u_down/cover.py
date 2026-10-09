"""封面图本地化：把详情页封面下载到 <番剧目录>/image/，简介.md 用相对路径引用。

设计见《Design/项目设计文档.md》§21：
- 图片是远程图床链接，站点清理图片会**先于**视频失效 → 落盘本地，简介改引本地文件
- 幂等：image/cover.* 已存在直接复用（简介.md 每集重写，不能每集重下）
- 扩展名按 Content-Type 判定（兜底 .jpg），非图片响应视为失败——图床失效常见
  "HTTP 200 + HTML 错误页"，只看状态码会把网页存成图片
- 失败只告警不抛错：封面是附加资料，不能因它中断整季下载
"""
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from . import config
from .session import build_session

IMAGE_DIR = "image"       # 番剧目录下的固定子目录名
_BASENAME = "cover"       # 固定 ASCII 基名（Markdown 相对链接无中文编码坑）
_MAX_TRIES = 3            # 重试上限（再与 config.retry_times 取小）

# Content-Type → 扩展名；未命中时按 URL 后缀猜，再兜底 .jpg
_EXT_BY_TYPE = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/pjpeg": ".jpg",
    "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
    "image/avif": ".avif", "image/bmp": ".bmp", "image/x-icon": ".ico",
}
_URL_EXTS = (".jpeg", ".jpg", ".png", ".webp", ".gif", ".avif", ".bmp")


# ---------- 查询 ----------

def existing(anime_dir):
    """返回已落盘的本地封面相对路径（如 'image/cover.jpg'），没有则 None。

    以"文件存在且非空"为唯一判据，供幂等复用；.part 半截文件不算
    （stem 为 'cover.jpg' 而非 'cover'，天然不匹配）。
    """
    d = Path(anime_dir) / IMAGE_DIR
    if not d.is_dir():
        return None
    for f in sorted(d.iterdir()):
        try:
            if f.is_file() and f.stem.lower() == _BASENAME and f.stat().st_size > 0:
                return f"{IMAGE_DIR}/{f.name}"
        except OSError:
            continue
    return None


# ---------- 下载 ----------

def _absolute(url, page_url=""):
    """补全协议相对（//img/…）与站点相对（/img/…）地址；无法补全返回空串。"""
    url = (url or "").strip()
    if not url or url.startswith("data:"):
        return ""
    if url.startswith("//"):
        return f"{urlparse(page_url).scheme or 'https'}:{url}"
    if url.startswith("http"):
        return url
    return urljoin(page_url, url) if page_url else ""


def _guess_ext(url, content_type):
    """扩展名判定：Content-Type 优先 → URL 后缀 → 兜底 .jpg。"""
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in _EXT_BY_TYPE:
        return _EXT_BY_TYPE[ctype]
    if ctype.startswith("image/"):
        sub = ctype.split("/", 1)[1]
        if sub == "jpeg":
            return ".jpg"
        if re.fullmatch(r"[a-z0-9]{2,5}", sub):   # 未知但合法的子类型原样用
            return f".{sub}"
    path = urlparse(url).path.lower()
    for ext in _URL_EXTS:
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


def _referer_plans(url, referer):
    """Referer 尝试序列 [(说明, Referer), ...] —— 应对图床防盗链的三种口味。

    实测（v0.7.4，ikanbot 的封面托管在豆瓣图床）：
      · 带页面 Referer       → 403（豆瓣只认自家域名）
      · 不带 Referer         → 418（反爬）
      · 图片自身完整 URL      → 418
      · 图片站根地址（origin）→ 200 ✅
    所以先按调用方给的页面 Referer 试（多数站点需要它），失败再退回"图片站自身
    Referer"，最后才不带 Referer。
    """
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}/" if p.scheme and p.netloc else ""
    plans = []
    if referer:
        plans.append(("页面 Referer", referer))
    if origin and origin != referer:
        plans.append(("图片站自身 Referer", origin))
    plans.append(("不带 Referer", ""))
    return plans


def fetch(anime_dir, url, referer="", insecure=None, proxy=None,
          direct_first=False):
    """下载封面到 <anime_dir>/image/cover.<ext>；成功返回相对路径，失败 None。

    会话参数与页面抓取/下载一致（同出口）；Referer 按 _referer_plans 逐档回退。
    同一档内只对"网络层/服务端错误"退避重试——4xx（防盗链）重试同一档没意义，
    直接换下一档 Referer。
    """
    url = _absolute(url, referer)
    if not url:
        return None
    out_dir = Path(anime_dir) / IMAGE_DIR
    tries = max(1, min(config.RETRY_TIMES, _MAX_TRIES))
    last_err = "未知错误"
    for plan_name, ref in _referer_plans(url, referer):
        session = build_session(referer=ref or None, insecure=insecure,
                                proxy=proxy, direct_first=direct_first)
        host_dead = False        # 连接层不通：换 Referer 也没用，直接放弃后面的档
        for attempt in range(tries):
            part = None
            resp = None
            try:
                resp = session.get(url, timeout=config.TIMEOUT, stream=True)
                resp.raise_for_status()
                ctype = resp.headers.get("Content-Type", "")
                if not ctype.lower().startswith("image/"):
                    raise RuntimeError(f"响应不是图片（Content-Type: {ctype or '空'}）")
                out_dir.mkdir(parents=True, exist_ok=True)
                part = out_dir / f"{_BASENAME}{_guess_ext(url, ctype)}.part"
                with open(part, "wb") as fh:   # 先写 .part，避免半截文件被误判为已完成
                    for chunk in resp.iter_content(64 * 1024):
                        if chunk:
                            fh.write(chunk)
                if part.stat().st_size == 0:
                    raise RuntimeError("图片内容为空")
                final = out_dir / part.name[: -len(".part")]
                os.replace(part, final)        # 原子改名：要么有完整图，要么没有
                note = "" if plan_name == "页面 Referer" else f"（改用{plan_name}）"
                print(f"[封面] 已保存本地: {IMAGE_DIR}/{final.name}{note}")
                return f"{IMAGE_DIR}/{final.name}"
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                last_err = f"HTTP {status}"
                if part is not None:
                    Path(part).unlink(missing_ok=True)
                # 4xx 说明这一档 Referer 不被接受 → 立刻换下一档，别浪费退避时间
                if 400 <= status < 500:
                    break
                if attempt + 1 < tries:
                    time.sleep(config.RETRY_BACKOFF)
            except requests.RequestException as e:
                last_err = str(e)              # 连接/超时：同一档退避重试
                if part is not None:
                    Path(part).unlink(missing_ok=True)
                if attempt + 1 < tries:
                    time.sleep(config.RETRY_BACKOFF)
                else:
                    host_dead = True
                    break
            except Exception as e:
                last_err = str(e)              # 拿到响应但不是图片/空文件 → 换下一档
                if part is not None:
                    Path(part).unlink(missing_ok=True)
                break
            finally:
                if resp is not None:
                    resp.close()
        if host_dead:
            break
    print(f"[封面] 下载失败，已跳过（不影响剧集下载）: {last_err}")
    return None


def prepare(anime_dir, meta, referer="", insecure=None, proxy=None,
            direct_first=False):
    """确保番剧目录里有一份本地封面，并把结果写回 meta['cover_local']。

    返回值：相对路径（'image/cover.jpg'）或 None（无封面 / 下载失败）。
    meta['cover_local'] 三态：路径 = 有本地图；"" = 尝试过但没成功（简介只留文字提示）；
    调用方据此渲染，不再使用远程链接。
    """
    if not isinstance(meta, dict):
        return None
    local = existing(anime_dir)     # 幂等：已有本地封面就完全不发请求
    if local:
        meta["cover_local"] = local
        print(f"[封面] 已存在，复用: {local}")
        return local
    url = str(meta.get("cover") or "").strip()
    if not url:
        meta["cover_local"] = ""
        return None
    local = fetch(anime_dir, url, referer=referer, insecure=insecure,
                  proxy=proxy, direct_first=direct_first)
    meta["cover_local"] = local or ""
    return local
