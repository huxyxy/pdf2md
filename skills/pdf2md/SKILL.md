---
name: pdf2md
description: 将金融/评级类 PDF 转为结构化 Markdown。流程 = PaddleOCR-VL 解析（脚本）→ agent 逐图视觉分析 → 组装校验（脚本）。当用户要求把 input/ 中的 PDF 转换为 output/ 中的 md 时使用本 skill。触发词：PDF转md、转换PDF、跑一遍流程、处理这篇PDF。
---

# PDF → Markdown 流水线

agent 全流程驱动。原则：**确定性工作全在脚本里，agent 唯一的自由区是逐图视觉分析**。
全程不要改 `input/`；中间产物在 `work/{文档名}/`；成品在 `output/`。

## 前置条件

- `.env` 有 `PADDLEOCR_TOKEN` / `PADDLEOCR_MODEL` / `PADDLEOCR_JOB_URL`
- 依赖已装：requests、pypdfium2、pillow

## 流程（单篇）

```bash
python3 scripts/paddleocr_api.py submit "input/xxx.pdf" "work/xxx"   # ① 提交，幂等
python3 scripts/paddleocr_api.py fetch "work/xxx"                    # ② 轮询下载 raw.jsonl，幂等
python3 scripts/prepare.py "work/xxx"                                # ③ 确定性清洗+裁剪
# ④ 视觉分析（本 skill 的核心，见下）
python3 scripts/assemble.py "work/xxx"                               # ⑤ 校验+组装 → output/xxx.md
```

多篇并行：先连续 submit 全部 PDF，再按"谁先解析完处理谁"的节奏流水线推进——
某篇在等待 fetch 时，去做上一篇的第④步。脚本全幂等，中断后重跑同命令即可续。

增量约定（不指定具体文件时按此执行）：处理 `input/` 中所有在 `output/` 尚无同名
.md 的 PDF；`work/{文档名}/` 已存在则跳过已完成阶段；已有 `vision/` 但 assemble
不通过的，只重做被拒清单中的图。

## ④ 视觉分析协议（agent 的唯一自由区）

1. 读 `work/xxx/figures.json`，逐组处理（建议每批 5 组左右）。
2. 每组输入：crop 图（`crops`，可能 1~2 张）+ `title` + `footnotes` + `context_before/after`。
   **每组必须先用读图工具实际打开 crop 再写 JSON**；不许凭标题想象。
   **不要**去读 raw.jsonl / blocks.json 里 chart 块的文本（那是读轴估数，污染源）。
3. 每组输出 `work/xxx/vision/{fig_id}.json`：

```json
{"fig_id": "fig01", "action": "describe|mermaid|table|drop",
 "evidence": "从图中实际看到的依据（如：左轴刻度0-300，2024年柱最高无数据标签）",
 "result": "..."}
```

- `evidence`：describe/mermaid 必填（drop 不需要）。写不出 evidence 说明你没读图——
  assemble 会拒绝缺 evidence 的结果。

action 判定：
- **drop**：Logo、装饰图、人物照、重复图、水印、印章等无研究价值的图；**以及确实无法解读的图**
  （占位符会被移除，粗体标题保留在正文中——满足“无法判断的保留图表名称”）。
- **table**：crop 实质是结构化表格 → result 为 md pipe 表格（列数必须一致）。
- **mermaid**：股权图/流程图/组织结构图 → result 为 mermaid 代码。
  组织结构/股权用 `graph TB`，流程用 `graph LR`。**节点文字必须与图内逐字一致**；
  拿不准箭头方向或归属就降级为 describe。
- **describe**（默认）：折线/柱状/饼图/散点/热力/组合图 → result 为 ≤100 字
  高信息密度描述，提取：趋势、拐点、最大/最小、主体差异、结构占比、集中度、
  波动、相关性、离群点、期限分布。

### 反幻觉负面清单（必须遵守）

0. **禁止标题级描述**：result 与标题互相包含（仅换说法、无图中新信息）会被 assemble
   拒绝并点名重做。每个 describe 必须含至少一项视觉证据：趋势/拐点/极值/占比/排序。
1. 只描述图上可见内容；**只能引用图上明确印出的数字**（数据标签、坐标轴刻度）。
   无标签的柱/线/面积图：只写趋势和拐点年份，最多用“约/近”粗粒度量级。
2. 不推断因果、不评价好坏。相关≠因果，除非图中原有标注。
3. 双轴图先确认每条线对应哪个轴再描述；分不清就只写趋势不写数值。
4. 不自报置信度；图中模糊看不清的区域明确在 evidence 里标“不确定”，不强行编造。
5. result 里不要提“图片/裁剪”等处理过程词汇，直接给内容。

## ⑤ 组装失败怎么办

assemble.py 会点名未通过校验的 fig_id 及原因（缺文件/JSON 非法/action 非法/
缺 evidence/标题级描述/表格列数不一致等）。**只重做被点名的图**，
重写对应 vision/{fig_id}.json 后重跑⑤。

## 产出标准（assemble 后逐条自查）

1. 全文无 `![`、无 `<img`（assemble 已硬性断言，仍为 0 才交付）
2. 目录/标题层级清晰，无跳级；跨页段落连贯
3. 表格为精简 md pipe 格式，每行 `|` 数一致
4. 图表标题为粗体段落，数据来源/注为 `> ` 引用块
5. 抽查 2~3 张图的描述与原 PDF 对应页核对
