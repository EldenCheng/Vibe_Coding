"""序列执行器：按给定顺序跑一串操作，默认跑完再汇总。"""

import time
import traceback
from dataclasses import dataclass

HEADER = "─" * 46


@dataclass
class Result:
    """单个操作的执行结果。"""

    op: object
    ok: bool
    detail: str = ""
    seconds: float = 0.0


def run_sequence(plan: list, make_context, fail_fast: bool = False) -> list:
    """执行 plan 里的操作。

    make_context(op) 负责准备该操作的运行环境；操作抛出的任何异常都只记在自己名下。
    """
    results = []
    for index, op in enumerate(plan, start=1):
        print(f"\n{HEADER}")
        print(f"[{index}/{len(plan)}] ({op.number}) {op.name} — {op.title}")
        print(HEADER)

        started = time.monotonic()
        try:
            context = make_context(op)
            op.module.run(context)
            results.append(Result(op, True, seconds=time.monotonic() - started))
        except KeyboardInterrupt:
            results.append(Result(op, False, "用户中断", time.monotonic() - started))
            print("\n收到中断，停止执行后续操作。")
            break
        except Exception as exc:  # 单个操作失败不影响整串执行
            detail = _describe(exc)
            results.append(Result(op, False, detail, time.monotonic() - started))
            print(f"  [失败] {detail}")
            if fail_fast:
                print("已指定 --fail-fast，停止执行后续操作。")
                break

    return results


def _describe(exc: Exception) -> str:
    """异常摘要：自带中文说明的异常直接透出，其余保留类型名。"""
    message = str(exc).strip()
    if message and type(exc).__name__ in {"AdbError", "ConfigError", "RegistryError", "ParamsError"}:
        return message
    if message:
        return f"{type(exc).__name__}: {message}"
    return traceback.format_exception_only(type(exc), exc)[0].strip()


def summarize(results: list, planned: int) -> int:
    """打印汇总，返回进程退出码：0 全成功，1 有失败。"""
    succeeded = sum(1 for r in results if r.ok)
    failed = [r for r in results if not r.ok]
    skipped = planned - len(results)

    print(f"\n{HEADER}")
    print("执行汇总")
    for r in results:
        mark = "成功" if r.ok else "失败"
        line = f"  {mark}  ({r.op.number}) {r.op.name}  {r.seconds:.1f}s"
        if r.detail:
            line += f"  {r.detail.splitlines()[0]}"
        print(line)

    total_note = f"共 {planned} 项"
    if skipped:
        print(f"\n{total_note}：成功 {succeeded}，失败 {len(failed)}，未执行 {skipped}。")
    else:
        print(f"\n{total_note}：成功 {succeeded}，失败 {len(failed)}。")

    return 1 if failed or skipped else 0
