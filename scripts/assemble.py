#!/usr/bin/env python3
"""assemble: draft.md + vision/*.json → output/{文档名}.md

信任边界：校验全部 vision JSON（schema/枚举/表格行列），不合格点名退出，不出半成品。
用法: python3 scripts/assemble.py <work_dir>
"""
import json
import logging
import os
import re
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
log = logging.getLogger("assemble")

ACTIONS = {"describe", "mermaid", "table", "drop"}
DESC_LIMIT = 100


def _norm(s: str) -> str:
    return re.sub(r"[\s，、：:；;（）()《》\-—.%％]", "", s)


def validate_vision(work_dir: str, fig_ids: list) -> tuple:
    """返回 (results: {fig_id: json}, errors: [str])"""
    results, errors = {}, []
    vision_dir = os.path.join(work_dir, "vision")
    titles = {}
    fj_path = os.path.join(work_dir, "figures.json")
    if os.path.exists(fj_path):
        titles = {f["fig_id"]: f.get("title", "") for f in json.load(open(fj_path, encoding="utf-8"))}
    for fid in fig_ids:
        path = os.path.join(vision_dir, f"{fid}.json")
        if not os.path.exists(path):
            errors.append(f"{fid}: 缺 vision/{fid}.json")
            continue
        try:
            v = json.load(open(path, encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{fid}: JSON 解析失败 {e}")
            continue
        action = v.get("action")
        if action not in ACTIONS:
            errors.append(f"{fid}: action 非法 {action!r}")
            continue
        result = (v.get("result") or "").strip()
        if action != "drop" and not result:
            errors.append(f"{fid}: action={action} 但 result 为空")
            continue
        if action in ("describe", "mermaid") and not (v.get("evidence") or "").strip():
            errors.append(f"{fid}: 缺 evidence（必须先读图并写明从图中看到的依据）")
            continue
        if action == "describe":
            nr, nt = _norm(result), _norm(titles.get(fid, ""))
            if nt and (nr in nt or nt in nr):
                errors.append(f"{fid}: 标题级描述不合格，需真正读图后重写")
                continue
            if len(result) > DESC_LIMIT * 1.5:
                log.warning("%s: 描述 %d 字，超过 %d 字限制", fid, len(result), DESC_LIMIT)
        if action == "mermaid":
            if not re.match(r"^(graph|flowchart)\s+(TB|TD|LR|RL|BT)", result):
                errors.append(f"{fid}: mermaid 未以 graph/flowchart 开头")
                continue
        if action == "table":
            rows = [r for r in result.splitlines() if r.strip().startswith("|")]
            widths = {r.count("|") for r in rows}
            if len(widths) > 1:
                errors.append(f"{fid}: 表格列数不一致 {widths}")
                continue
        results[fid] = v
    return results, errors


def build_replacement(v: dict) -> str:
    action = v["action"]
    result = (v.get("result") or "").strip()
    if action == "drop":
        return ""
    if action == "describe":
        return result
    if action == "mermaid":
        return "```mermaid\n" + result + "\n```"
    if action == "table":
        return result
    raise AssertionError(action)


def make_toc(md: str) -> str:
    """从 heading 生成纯文本层级目录（无页码无链接）。"""
    entries = []
    for line in md.splitlines():
        m = re.match(r"^(#{2,6})\s+(.*)", line)
        if m and m.group(2).strip() != "目录":
            entries.append("  " * (len(m.group(1)) - 2) + "- " + m.group(2).strip())
    return "## 目录\n\n" + "\n".join(entries) if entries else ""


def assemble(work_dir: str) -> str:
    with open(os.path.join(work_dir, "draft.md"), encoding="utf-8") as f:
        draft = f.read()
    fig_ids = re.findall(r"\{\{FIG:(fig\d+)\}\}", draft)

    results, errors = validate_vision(work_dir, fig_ids)
    if errors:
        for e in errors:
            log.error(e)
        raise SystemExit(f"{len(errors)} 个图表未通过校验，请重做后重跑")

    md = draft
    for fid in fig_ids:
        md = md.replace("{{FIG:" + fid + "}}", build_replacement(results[fid]))

    # 目录插在 H1 及紧随的作者行之后
    toc = make_toc(md)
    if toc:
        m = re.search(r"^## ", md, re.MULTILINE)
        if m:
            md = md[:m.start()] + toc + "\n\n" + md[m.start():]

    # 硬性产出校验
    assert "<img" not in md and "![" not in md, "产出含图片引用"
    assert "{{FIG:" not in md, "有图表占位未替换"

    name = os.path.splitext(os.path.basename(
        json.load(open(os.path.join(work_dir, "job.json"), encoding="utf-8"))["pdf"]))[0]
    out_dir = os.path.join(os.path.dirname(__file__), "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, name + ".md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    log.info("输出: %s (%d chars)", out_path, len(md))
    return out_path


if __name__ == "__main__":
    assemble(sys.argv[1])
