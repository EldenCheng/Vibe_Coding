"""各下载器 config.json 的读写。

按设计决策 D3：管理器**直接读写**下载器自己目录下的 config.json，
不另存副本 —— 任务运行时下载器读到的就是这一份，天然一致。

安全与稳健措施：
1. 敏感字段（cookies、代理里的账号密码、Authorization 头等）GET 时不回传明文，
   只回 {"__set__": True}，前端显示为「已设置」；提交时留空 = 不修改。
2. 写入只覆盖表单提交的字段，未知字段原样保留（避免抹掉 _readme 等）。
3. 写前整份备份到 config.json.bak.<时间戳>，可一键恢复。
4. 类型校验失败直接拒绝，绝不写坏配置文件。
"""
import json
import shutil
import time
from pathlib import Path

# 遮罩标记：表示「该字段已设置但值不回传」
MASKED = {"__set__": True}


class ConfigError(Exception):
    """配置读写相关的可预期错误（会转成 400 返回给前端）。"""


# ---------------------------------------------------------------- 路径与备份

def config_path(project_dir):
    return Path(project_dir) / "config.json"


def backup_paths(project_dir):
    """列出该项目的所有备份，新的在前。"""
    p = Path(project_dir)
    if not p.exists():
        return []
    return sorted(p.glob("config.json.bak.*"), reverse=True)


def _backup(project_dir):
    src = config_path(project_dir)
    if not src.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = src.with_name(f"{src.name}.bak.{stamp}")
    # 同一秒内重复备份时加序号，避免互相覆盖
    k = 2
    while dst.exists():
        dst = src.with_name(f"{src.name}.bak.{stamp}-{k}")
        k += 1
    shutil.copy2(src, dst)
    return dst


# ---------------------------------------------------------------- 读取

def load_raw(project_dir):
    """读原始配置（不遮罩），文件不存在时返回空 dict。"""
    path = config_path(project_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"读取 {path} 失败: {exc}") from exc


def _get_path(data, dotted):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None, False
        node = node[part]
    return node, True


def _set_path(data, dotted, value):
    parts = dotted.split(".")
    node = data
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def _is_sensitive(dotted, sensitive_paths):
    """判断某个字段路径是否属于敏感字段。

    规则：路径完全相等，或位于某个「敏感子树」之下
    （声明了 cookies，则 cookies.ipb_member_id 等内部字段也算敏感，
    这样前端才不会把登录态的键名与取值显示出来）。
    """
    for item in sensitive_paths:
        base = item[:-2] if item.endswith(".*") else item
        if dotted == base or dotted.startswith(base + "."):
            return True
    return False


def _mask_copy(data, sensitive_paths):
    """返回遮罩后的副本：敏感子树的整体内容替换为「已设置」标记。

    遮罩的是整棵子树而不是逐个叶子，因为像 cookies 这类字段一旦存在
    （哪怕值是空串），也能说明「配了哪些键」，这本身就是信息。
    """
    out = json.loads(json.dumps(data, ensure_ascii=False, default=str))
    for item in sensitive_paths:
        base = item[:-2] if item.endswith(".*") else item
        value, present = _get_path(out, base)
        if present and value not in (None, "", {}, []):
            _set_path(out, base, dict(MASKED))
    return out


def _strip_sensitive_tree(data, sensitive_paths):
    """从「未声明字段」里递归剔除敏感键，避免遮罩只作用于已声明字段而漏掉。

    例如 schema 里没声明 `cookies`，那它就会落到 extra 里被原样回传；
    这里按敏感路径把整棵子树删掉。
    """
    out = json.loads(json.dumps(data, ensure_ascii=False))
    for item in sensitive_paths:
        base = item[:-2] if item.endswith(".*") else item
        parts = base.split(".")
        node = out
        for part in parts[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict) and parts[-1] in node:
            node[parts[-1]] = {"__set__": True}
    return out


def describe(data, schema, sensitive_paths):
    """把配置整理成前端可渲染的表单结构。

    schema: [{key, label, type, help, default, options?}]，type ∈
            text/number/float/bool/textarea/json/select/password
    返回 {fields: [...], extra: {...未在 schema 中声明的字段...}}

    敏感字段不回传取值，只回 {"__set__": True}（已在遮罩副本里替换好），
    前端据此显示为「已设置」的密码框；提交时留空表示不修改。
    """
    masked = _mask_copy(data or {}, sensitive_paths)
    fields = []
    declared = set()
    for item in schema:
        key = item["key"]
        declared.add(key)
        value, present = _get_path(masked, key)
        raw_value, raw_present = _get_path(data or {}, key)
        sensitive = _is_sensitive(key, sensitive_paths)
        fields.append({
            "key": key,
            "label": item.get("label", key),
            "type": item.get("type", "text"),
            "help": item.get("help", ""),
            "default": item.get("default"),
            "options": item.get("options"),
            "show_for": item.get("show_for"),
            "required": item.get("required", False),
            "placeholder": item.get("placeholder", ""),
            "present": present,
            "value": value if present else item.get("default"),
            "is_sensitive": sensitive,
            "is_set": bool(raw_present and raw_value not in (None, "", [], {})),
        })
    extra = {}
    for key, value in (masked or {}).items():
        if key not in declared:
            extra[key] = value
    extra = _strip_sensitive_tree(extra, sensitive_paths)
    return {"fields": fields, "extra": extra, "path": None}


# ---------------------------------------------------------------- 写入

def _validate_field(item, value):
    """按 schema 声明做类型校验并归一化，返回 (是否通过, 值或错误信息)。"""
    ftype = item.get("type", "text")
    key = item["key"]
    if ftype == "bool":
        if isinstance(value, bool):
            return True, value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return True, value.lower() == "true"
        return False, f"{key} 需要 true/false"
    if ftype == "number":
        try:
            return True, int(value)
        except (TypeError, ValueError):
            return False, f"{key} 需要整数"
    if ftype == "float":
        try:
            return True, float(value)
        except (TypeError, ValueError):
            return False, f"{key} 需要数字"
    if ftype == "json":
        if isinstance(value, (dict, list)):
            return True, value
        try:
            return True, json.loads(value)
        except (TypeError, ValueError):
            return False, f"{key} 不是合法 JSON"
    return True, value


def apply_patch(project_dir, patch, schema, sensitive_paths):
    """把 patch 合并进配置并落盘。

    规则：
    - patch 里值为 None 或空字符串的**敏感字段**视为「不修改」，直接跳过；
    - 其余字段按 schema 校验类型后写入；
    - 未在 schema 中声明的键也允许写（便于扩展），但不做类型校验；
    - 写前自动备份。
    """
    if not isinstance(patch, dict):
        raise ConfigError("提交内容必须是对象")

    current = load_raw(project_dir)
    schema_map = {item["key"]: item for item in schema}
    backup = _backup(project_dir)

    changed = []
    for key, value in patch.items():
        item = schema_map.get(key)
        is_sensitive = _is_sensitive(key, sensitive_paths)

        # 敏感字段留空 = 保持原值不变
        if is_sensitive and (value is None or value == "" or value == MASKED):
            continue
        if isinstance(value, dict) and value.get("__set__"):
            continue

        if item:
            ok, result = _validate_field(item, value)
            if not ok:
                raise ConfigError(result)
            value = result
        _set_path(current, key, value)
        changed.append(key)

    # 原子写入：先写临时文件再替换，避免写一半被下载器读到
    path = config_path(project_dir)
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise ConfigError(f"写入 {path} 失败: {exc}") from exc

    return {"changed": changed, "backup": backup.name if backup else None}


def restore_backup(project_dir, name=None):
    """恢复最近的（或指定的）备份。返回恢复的文件名。"""
    backups = backup_paths(project_dir)
    if not backups:
        raise ConfigError("没有可用的备份")
    target = None
    if name:
        for b in backups:
            if b.name == name:
                target = b
                break
        if target is None:
            raise ConfigError(f"未找到备份 {name}")
    else:
        target = backups[0]
    path = config_path(project_dir)
    try:
        shutil.copy2(target, path)
    except OSError as exc:
        raise ConfigError(f"恢复备份失败: {exc}") from exc
    return target.name
