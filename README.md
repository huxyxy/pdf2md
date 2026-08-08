# pdf2md

将研报、募集及财报等金融 PDF 转换为结构清晰的 Markdown。

这是一个由 AI Agent 驱动的应用：脚本负责 OCR、清洗、裁剪和最终组装，AI Agent 负责多篇 PDF 的流程编排、图表视觉分析和结果复核。完整流程需要在能够读取本仓库文件并执行命令的 AI Agent 下运行；只单独运行 Python 脚本，无法完成图表分析和多篇文档调度。

## 功能

- 提取 PDF 正文和标题
- 将表格转换为 Markdown 表格
- 裁剪图表并保留上下文
- 对图表生成文字描述、Mermaid 流程图或 Markdown 表格
- 输出最终的 Markdown 文件

## 环境要求

- Python 3
- PaddleOCR API Token
- `requests`
- `pypdfium2`
- `pillow`

## 安装

以下命令以 Linux、macOS 或 WSL 为例。Windows 用户可以把 `python3` 换成 `python`。

```bash
git clone https://github.com/huxyxy/pdf2md.git
cd pdf2md

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -r requirements.txt
```

复制环境变量模板：

```bash
cp .env.example .env
```

然后编辑 `.env`，至少填写 `PADDLEOCR_TOKEN`：

```dotenv
PADDLEOCR_TOKEN=你的PaddleOCR_TOKEN
PADDLEOCR_MODEL=PaddleOCR-VL-1.6
PADDLEOCR_JOB_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs
```

不要把 `.env` 或真实 Token 上传到 GitHub。`.env.example` 可以公开，它只包含配置格式。

## 使用方法

### 推荐方式：交给 AI Agent 执行

1. 将需要处理的全部 PDF 放入 `input/`。
2. 在项目根目录启动 AI Agent。
3. 将下面的 Prompt 原样发送给 Agent：

```text
先阅读 skills/pdf2md/SKILL.md 并严格按其中的流程执行：
处理 input/ 下的全部 PDF。按 SKILL.md 的多篇并行节奏推进：
先连续 submit 全部文件，谁先解析完就处理谁，等待 fetch 的间隙去做上一篇的视觉分析。
每篇工作目录为 work/{文件名}/，产出到 output/。
视觉分析必须遵守第④节协议和反幻觉负面清单；assemble 校验失败时只重做被点名的图。
全部完成后逐篇按自查清单核对并汇报结果。
```

Agent 应先阅读 [`skills/pdf2md/SKILL.md`](skills/pdf2md/SKILL.md)，并严格遵守其中的视觉分析协议、反幻觉负面清单和产出自查标准。

### 脚本流程（由 Agent 调度）

#### 1. 放入 PDF

把待处理的 PDF 放入 `input/`，例如：

```text
input/example.pdf
```

`input/` 中的原始文件只读取，不会被程序修改。

#### 2. 提交 OCR 任务

```bash
python3 scripts/paddleocr_api.py submit "input/example.pdf" "work/example"
```

#### 3. 等待并下载 OCR 结果

```bash
python3 scripts/paddleocr_api.py fetch "work/example"
```

#### 4. 清洗正文并裁剪图表

```bash
python3 scripts/prepare.py "work/example"
```

这一步会生成 `draft.md`、`figures.json` 和图表裁剪图。

#### 5. 分析图表

读取 `work/example/figures.json`，逐个分析 `figures/` 中的图表，并为每个图表创建：

```text
work/example/vision/fig01.json
```

文件格式如下：

```json
{
  "fig_id": "fig01",
  "action": "describe",
  "evidence": "从图中实际看到的依据（如：纵轴刻度0-300，2024年柱最高）",
  "result": "图表中可见的趋势、差异或结构。"
}
```

`action` 可以是：

- `describe`：描述折线图、柱状图、饼图等
- `mermaid`：表示流程图、组织结构图或股权关系图
- `table`：表示结构化表格
- `drop`：忽略装饰图、Logo 或无研究价值的图片

详细规则见 [`skills/pdf2md/SKILL.md`](skills/pdf2md/SKILL.md)。

#### 6. 校验并组装 Markdown

```bash
python3 scripts/assemble.py "work/example"
```

最终文件会生成在：

```text
output/example.md
```

如果组装失败，脚本会指出缺失或格式错误的 `figXX.json`，修正后重新执行本步骤即可。

## 目录说明

```text
pdf2md/
├── input/              # 原始 PDF
├── output/             # 最终 Markdown
├── work/               # OCR、裁剪和图表分析等中间文件
├── scripts/            # OCR、清洗和组装脚本
├── skills/pdf2md/      # AI 图表分析规则
├── .env.example        # 环境变量模板
└── README.md           # 项目说明
```

## 上传到 GitHub 前的注意事项

- 不要上传 `.env`、API Token 或其他密码。
- 确认 `input/` 中的 PDF 可以公开发布，尤其注意版权和隐私。
- 检查 `work/`、`output/` 中是否包含不应公开的中间结果或文档内容。
