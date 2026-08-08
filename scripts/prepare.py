#!/usr/bin/env python3
"""prepare: raw.jsonl → draft.md + figures.json + figures/*.png + blocks.json

确定性后处理：过滤辅助块、跨页拼接、图表分组、表格转 pipe、页面裁剪。
用法: python3 scripts/prepare.py <work_dir>
"""
import json
import logging
import os
import re
import sys
from html.parser import HTMLParser

import pypdfium2 as pdfium

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
log = logging.getLogger("prepare")

DROP_LABELS = {"header", "footer", "header_image", "footer_image", "number", "aside_text"}  # 官方 23 类版面标签中的辅助内容
SENTENCE_END = tuple("。！？；：”）】.!?;:")
RENDER_SCALE = 2  # 与 bbox 坐标系一致（1191x1684）
CROP_PAD = 10
CONTEXT_CHARS = 300


# ---------- HTML table → pipe ----------

class _TableParser(HTMLParser):
    """收集单元格 (text, rowspan, colspan)，随后网格填充。"""
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None
        self.rowspan = self.colspan = 1

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
            a = dict(attrs)
            self.rowspan = int(a.get("rowspan", 1))
            self.colspan = int(a.get("colspan", 1))

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            text = " ".join("".join(self.cell).split())
            self.row.append((text, self.rowspan, self.colspan))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if any(c[0] for c in self.row):
                self.rows.append(self.row)
            self.row = None


def html_table_to_md(html: str) -> str:
    p = _TableParser()
    p.feed(html)
    if not p.rows:
        return ""
    # 网格填充：rowspan/colspan 用重复文本占满，保证列对齐
    # ponytail: 不做多行表头合并（源 HTML 有半边错位的双联表，合并不可靠）
    grid, spans = [], {}
    for r, row in enumerate(p.rows):
        out, c = [], 0
        cells = iter(row)
        cell = next(cells, None)
        while cell is not None or (r, c) in spans:
            if (r, c) in spans:
                out.append(spans.pop((r, c)))
                c += 1
                continue
            text, rs, cs = cell
            out.append(text)
            for dr in range(rs):
                for dc in range(cs):
                    if dr or dc:
                        if dr:
                            spans[(r + dr, c + dc)] = text
                        else:
                            out.append(text)
            c += cs
            cell = next(cells, None)
        grid.append(out)
    width = max(len(r) for r in grid)
    rows = [r + [""] * (width - len(r)) for r in grid]
    caption = ""
    if width > 1 and len(rows) > 1 and len(set(rows[0])) == 1 and rows[0][0]:
        caption, rows = "**" + rows[0][0] + "**\n\n", rows[1:]  # 整行跨列表头提升为加粗标题行
    esc = lambda s: s.replace("|", "\\|")
    lines = ["| " + " | ".join(esc(c) for c in rows[0]) + " |",
             "|" + "---|" * width]
    lines += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows[1:]]
    return caption + "\n".join(lines)


# ---------- 块加载与过滤 ----------

def load_pages(work_dir: str) -> list:
    with open(os.path.join(work_dir, "raw.jsonl"), encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    pages = []
    for line in lines:
        for p in line["result"]["layoutParsingResults"]:
            blocks = [{
                "label": b["block_label"],
                "content": b["block_content"],
                "bbox": b["block_bbox"],
            } for b in p["prunedResult"]["parsing_res_list"]]
            pages.append(blocks)
    return pages


def is_toc_page(blocks: list) -> bool:
    return any(b["label"] == "content" for b in blocks)


def salvage_toc_page(blocks: list, page_idx: int) -> list:
    """目录页：保留第一个 content 块之前的标题类块（文档名/作者），丢弃目录本体。"""
    keep = []
    for b in blocks:
        if b["label"] == "content":
            break
        if b["label"] in ("paragraph_title", "text", "doc_title"):
            keep.append(b)
        elif b["label"] == "header" and page_idx == 0:  # 封面作者/日期行；后续页的 header 是页眉
            keep.append({**b, "label": "text"})
    # 标题'目录'/'表目录'本身不要
    return [b for b in keep if b["content"].strip() not in ("目录", "表目录")]


def stitch_pages(pages: list) -> list:
    """跨页断句：页尾 text 非句末标点 + 下页首块为 text → 合并。返回扁平块流 [(page_idx, block)]。"""
    stream = []
    for page_idx, blocks in enumerate(pages):
        kept = [b for b in blocks if b["label"] not in DROP_LABELS]
        if (stream and kept
                and stream[-1][1]["label"] == "text" and kept[0]["label"] == "text"
                and not stream[-1][1]["content"].rstrip().endswith(SENTENCE_END)):
            log.info("拼接跨页段落: page %d -> %d", stream[-1][0], page_idx)
            stream[-1][1]["content"] += kept[0]["content"]
            kept = kept[1:]
        stream.extend((page_idx, b) for b in kept)
    return stream


# ---------- 图表分组 ----------

FIG_BODY = {"chart", "image", "table"}


def group_stream(stream: list) -> list:
    """块流 → 输出单元流。单元: block | figure_group。
    figure_group: {title, bodies[(label,block)], notes[], page}
    ponytail: 只向前看连续的 图/表/脚注 块；中间夹正文就分组失败，占位仍在，人工可修。
    """
    units = []
    i = 0
    while i < len(stream):
        page, b = stream[i]
        if b["label"] == "figure_title":
            bodies, notes, j = [], [], i + 1
            while j < len(stream) and stream[j][1]["label"] in FIG_BODY | {"vision_footnote"}:
                nb = stream[j][1]
                (bodies if nb["label"] in FIG_BODY else notes).append(nb)
                j += 1
            bodies.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))
            units.append({"type": "figure", "page": page, "title": b, "bodies": bodies, "notes": notes})
            i = j
        elif b["label"] in ("chart", "image"):  # 无标题的孤儿图
            units.append({"type": "figure", "page": page, "title": None, "bodies": [b], "notes": []})
            i += 1
        else:
            units.append({"type": "block", "page": page, "block": b})
            i += 1
    return units


# ---------- markdown 渲染 ----------

def heading_level(text: str) -> int:
    m = re.match(r"^(\d+(?:\.\d+)*)[.、\s]", text.strip())
    return min(m.group(1).count(".") + 2, 6) if m else 2


def render_units(units: list, figures: list) -> str:
    out = []
    for u in units:
        if u["type"] == "block":
            b = u["block"]
            if b["label"] == "doc_title":
                out.append("# " + b["content"].strip())
            elif b["label"] == "paragraph_title":
                level = 1 if not out else heading_level(b["content"])  # 全文首个标题=文档名 H1
                out.append("#" * level + " " + b["content"].strip())
            elif b["label"] == "table":
                out.append(html_table_to_md(b["content"]))
            else:  # text / footnote
                out.append(b["content"].strip())
        else:
            parts = []
            if u["title"]:
                parts.append("**" + u["title"]["content"].strip() + "**")
            fig_bodies = [b for b in u["bodies"] if b["label"] in ("chart", "image")]
            table_bodies = [b for b in u["bodies"] if b["label"] == "table"]
            if fig_bodies:
                fig_id = f"fig{len(figures) + 1:02d}"
                figures.append({"fig_id": fig_id, "page": u["page"], "unit": u, "bodies": fig_bodies})
                parts.append("{{FIG:" + fig_id + "}}")
            for t in table_bodies:
                out.append("\n\n".join(parts))
                parts = []
                out.append(html_table_to_md(t["content"]))
            for n in u["notes"]:
                parts.append("> " + " ".join(n["content"].split()))
            out.append("\n\n".join(parts))
    return "\n\n".join(x for x in out if x)


# ---------- 裁剪与上下文 ----------

def crop_figures(work_dir: str, pdf_path: str, figures: list) -> None:
    fig_dir = os.path.join(work_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)
    pdf = pdfium.PdfDocument(pdf_path)
    rendered = {}
    for fig in figures:
        page_idx = fig["page"]
        if page_idx not in rendered:
            rendered[page_idx] = pdf[page_idx].render(scale=RENDER_SCALE).to_pil()
        img = rendered[page_idx]
        w, h = img.size
        crops = []
        for k, b in enumerate(fig["bodies"]):
            x0, y0, x1, y1 = b["bbox"]
            box = (max(0, x0 - CROP_PAD), max(0, y0 - CROP_PAD),
                   min(w, x1 + CROP_PAD), min(h, y1 + CROP_PAD))
            path = os.path.join(fig_dir, f"{fig['fig_id']}_{k}.png")
            img.crop(box).save(path)
            crops.append(os.path.relpath(path, work_dir))
        fig["crops"] = crops


def add_context(stream: list, figures: list) -> None:
    """给每组图配前后正文（各取最近 text/paragraph_title，截断）。"""
    texts = [(i, b["content"].strip()) for i, (_, b) in enumerate(stream)
             if b["label"] in ("text", "paragraph_title")]
    for fig in figures:
        page = fig["page"]
        title_top = fig["unit"]["title"]["bbox"][1] if fig["unit"]["title"] else fig["bodies"][0]["bbox"][1]
        body_bottom = max(b["bbox"][3] for b in fig["unit"]["bodies"])
        before = [t for i, t in texts if stream[i][0] == page and stream[i][1]["bbox"][3] <= title_top]
        after = [t for i, t in texts if stream[i][0] == page and stream[i][1]["bbox"][1] >= body_bottom]
        fig["context_before"] = (before[-1] if before else "")[-CONTEXT_CHARS:]
        fig["context_after"] = (after[0] if after else "")[:CONTEXT_CHARS]


def prepare(work_dir: str) -> None:
    pdf_path = json.load(open(os.path.join(work_dir, "job.json")))["pdf"]
    if not os.path.exists(pdf_path):  # 迁移机器后绝对路径失效，回退 input/ 同名文件
        pdf_path = os.path.join(os.path.dirname(__file__), "..", "input", os.path.basename(pdf_path))
    pages = load_pages(work_dir)
    kept_pages = [salvage_toc_page(p, i) if is_toc_page(p) else p for i, p in enumerate(pages)]
    stream = stitch_pages(kept_pages)
    with open(os.path.join(work_dir, "blocks.json"), "w", encoding="utf-8") as f:
        json.dump([{**b, "page": i} for i, b in stream], f, ensure_ascii=False, indent=1)

    units = group_stream(stream)
    figures = []
    draft = render_units(units, figures)
    crop_figures(work_dir, pdf_path, figures)
    add_context(stream, figures)

    fig_json = [{
        "fig_id": f["fig_id"], "page": f["page"] + 1,
        "title": f["unit"]["title"]["content"].strip() if f["unit"]["title"] else "",
        "footnotes": [" ".join(n["content"].split()) for n in f["unit"]["notes"]],
        "context_before": f["context_before"], "context_after": f["context_after"],
        "crops": f["crops"],
    } for f in figures]
    with open(os.path.join(work_dir, "figures.json"), "w", encoding="utf-8") as f:
        json.dump(fig_json, f, ensure_ascii=False, indent=1)
    with open(os.path.join(work_dir, "draft.md"), "w", encoding="utf-8") as f:
        f.write(draft)
    log.info("blocks=%d, figures=%d, draft=%d chars", len(stream), len(figures), len(draft))

    # 自检（ponytail: 唯一检查，覆盖核心不变量）
    assert figures, "无图表组"
    assert all(os.path.exists(os.path.join(work_dir, c)) for f in figures for c in f["crops"])
    assert "<img" not in draft and "![" not in draft
    for fid in re.findall(r"\{\{FIG:(fig\d+)\}\}", draft):
        assert any(f["fig_id"] == fid for f in figures), f"占位 {fid} 无对应图组"


if __name__ == "__main__":
    prepare(sys.argv[1])
