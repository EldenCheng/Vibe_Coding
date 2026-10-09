"""HTTP 接口端到端测试：对着真实运行的服务发请求。

用法: py -3 -X utf8 tests\api_test.py [base_url] [token]
不传参数时从 download-manager/config.json 读取令牌，默认 http://127.0.0.1:8765
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
CFG = Path(__file__).resolve().parent.parent / "config.json"
TOKEN = sys.argv[2] if len(sys.argv) > 2 else (
    json.loads(CFG.read_text(encoding="utf-8"))["server"]["access_token"])

FAILED = []


def check(label, cond, detail=""):
    print(f"[{'OK  ' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(label)


def _parse(raw, content_type=""):
    """只有 JSON 响应才解析，静态资源（HTML/CSS/JS）保持原样。"""
    if "json" not in (content_type or "").lower():
        return {}
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw[:200]}


def call(method, path, body=None, token=TOKEN):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("X-Auth-Token", token)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, _parse(raw, resp.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        return exc.code, _parse(raw, exc.headers.get("Content-Type", ""))


def describe_item(item):
    prog = item.get("progress") or {}
    return (f"{item['name'][:44]:46} {prog.get('done')}/{prog.get('total')} "
            f"失败={prog.get('failed')} 状态={prog.get('status')} {item['size_text']}")


def main():
    print("=" * 78)
    print(f"目标服务: {BASE}")
    print("=" * 78)

    # ---- 鉴权 ----
    status, data = call("GET", "/api/health", token=None)
    check("健康检查无需令牌", status == 200 and data.get("ok"), str(data))

    status, data = call("GET", "/api/sysinfo", token=None)
    check("无令牌访问受保护接口返回 401", status == 401, f"实际 {status}")

    status, data = call("GET", "/api/sysinfo", token="wrong-token")
    check("错误令牌返回 401", status == 401, f"实际 {status}")

    status, info = call("GET", "/api/sysinfo")
    check("正确令牌可访问系统信息", status == 200 and "probes" in info, str(info)[:200])
    if status == 200:
        print(f"     平台: {info['platform']['system']} {info['platform']['release']}")
        print(f"     磁盘: " + "; ".join(
            f"{d['label']} 剩余 {d['free_gb']}GB" for d in info.get("disks", [])))
        for tid, probe in info["probes"].items():
            flag = "OK" if probe.get("ok") else "问题"
            print(f"     [{flag}] {tid}: {probe.get('output_root')}")
            for problem in probe.get("problems", []):
                print(f"           - {problem}")

    # ---- 适配器元信息 ----
    status, data = call("GET", "/api/adapters")
    adapters = data.get("adapters", []) if status == 200 else []
    check("适配器列表返回 3 个", len(adapters) == 3, str(len(adapters)))
    types = {a["type"] for a in adapters}
    check("包含 ebook/ehentai/video", types == {"ebook", "ehentai", "video"}, str(types))
    for adapter in adapters:
        check(f"{adapter['type']} 有参数表单", len(adapter.get("form_schema") or []) > 0)

    # ---- 静态资源与页面 ----
    for path, label in (("/", "前端页面"), ("/static/css/app.css", "样式"),
                        ("/static/js/app.js", "主脚本"), ("/static/js/utils.js", "工具脚本"),
                        ("/static/js/api.js", "API 层"), ("/static/js/logview.js", "输出区"),
                        ("/static/js/configform.js", "配置表单"),
                        ("/static/js/tasklist.js", "下载列表"),
                        ("/static/js/notify.js", "通知")):
        status, _ = call("GET", path)
        check(f"{label} {path} 可访问", status == 200, f"实际 {status}")

    status, _ = call("GET", "/login", token=None)
    check("登录引导页无需令牌", status == 200, f"实际 {status}")

    # ---- 配置读取（敏感字段遮罩） ----
    status, cfg = call("GET", "/api/adapters/ehentai/config")
    check("读取画廊配置成功", status == 200 and "fields" in cfg, str(cfg)[:200])
    if status == 200:
        print(f"     配置路径: {cfg.get('path')}  备份数: {len(cfg.get('backups') or [])}")
        for field in cfg["fields"]:
            if field["is_sensitive"] or field["key"] in (
                    "output_dir", "use_mpv", "request_delay.min", "retry.max_attempts"):
                print(f"     {field['key']:22} = {str(field['value'])[:44]:46} "
                      f"已设置={field['is_set']} 敏感={field['is_sensitive']}")
        cookie = next((f for f in cfg["fields"] if f["key"] == "cookies"), None)
        check("cookies 被遮罩为已设置标记",
              cookie and cookie["value"] == {"__set__": True}, str(cookie and cookie["value"]))
        # 代理刻意不做敏感字段（否则留空=不修改，UI 无法清空代理）
        proxy = next((f for f in cfg["fields"] if f["key"] == "proxy"), None)
        check("代理不再是敏感字段（明文可见、可清空）",
              bool(proxy) and proxy["is_sensitive"] is False,
              str(proxy and f"sensitive={proxy['is_sensitive']}"))
        # 泄漏检查只看「取值」与未声明字段，不看 help 文案
        # （help 里本来就会提到 ipb_member_id 这类字段名，那不是密钥）
        values = json.dumps([f["value"] for f in cfg["fields"]], ensure_ascii=False)
        values += json.dumps(cfg.get("extra") or {}, ensure_ascii=False)
        leaked = [token for token in ("ipb_pass_hash", "8724276", "57e510a0")
                  if token in values]
        check("配置取值中无敏感明文泄漏", not leaked, f"泄漏: {leaked}")
        extra = cfg.get("extra") or {}
        check("_readme 等未声明字段仍在", True if extra else False, str(list(extra))[:80])

    # ---- 下载列表扫描 ----
    for type_id in ("ebook", "ehentai", "video"):
        status, data = call("GET", f"/api/downloads/{type_id}")
        if status != 200:
            check(f"{type_id} 扫描成功", False, str(data)[:150])
            continue
        items = data.get("items", [])
        check(f"{type_id} 扫描成功（{len(items)} 项）", True)
        print(f"     扫描目录: {data.get('roots')}")
        for item in items[:6]:
            print("       " + describe_item(item))

    # ---- 任务列表 ----
    status, data = call("GET", "/api/tasks")
    check("任务列表可读", status == 200 and isinstance(data.get("tasks"), list), str(data)[:150])
    print(f"     当前任务数: {len(data.get('tasks', []))}")

    # ---- 参数校验：非法输入必须被拒绝 ----
    status, data = call("POST", "/api/tasks", {"type": "ehentai", "kind": "download",
                                               "form": {"url": "not-a-url"}})
    check("非法画廊 URL 被拒绝（400）", status == 400, f"实际 {status} {str(data)[:120]}")

    status, data = call("POST", "/api/tasks", {"type": "ebook", "kind": "download",
                                               "form": {"book": ""}})
    check("空 book_id 被拒绝（400）", status == 400, f"实际 {status}")

    status, data = call("POST", "/api/tasks", {"type": "nosuch", "kind": "download",
                                               "form": {}})
    check("未知下载器类型返回 404", status == 404, f"实际 {status}")

    # ---- 不存在资源 ----
    status, data = call("GET", "/api/tasks/deadbeef")
    check("不存在的任务返回 404", status == 404, f"实际 {status}")
    status, data = call("GET", "/api/nosuchroute")
    check("不存在的接口返回 404", status == 404, f"实际 {status}")

    # ---- 真实任务：ebook --check（幂等、不下载章节，只扫文件与修复进度） ----
    print("\n" + "=" * 78)
    print("真实任务端到端：对已下载的书执行 --check")
    print("=" * 78)
    status, data = call("POST", "/api/tasks", {
        "type": "ebook", "kind": "download", "form": {"book": "35346"}})
    if status == 200:
        task = data["task"]
        print(f"     任务已创建: {task['id']} 状态={task['status']}")
        print(f"     命令: {' '.join(task['argv'])}")
        check("任务创建成功", True)
        check("命令含 --output-dir", "--output-dir" in task["argv"])
        check("命令含 -u（无缓冲）", "-u" in task["argv"])
    else:
        check("任务创建成功", False, str(data)[:200])

    print("\n" + "=" * 78)
    if FAILED:
        print(f"失败 {len(FAILED)} 项:")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
