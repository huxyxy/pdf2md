# pdf2md

将研报、募集及财报等金融 PDF 转换为结构清晰的 Markdown。

项目使用 PaddleOCR-VL 解析 PDF，再由 AI 逐图分析图表，最后由脚本完成校验和组装。

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
git clone https://github.com/你的用户名/pdf2md.git
cd pdf2md

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install requests pypdfium2 pillow
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

### 1. 放入 PDF

把待处理的 PDF 放入 `input/`，例如：

```text
input/example.pdf
```

`input/` 中的原始文件只读取，不会被程序修改。

### 2. 提交 OCR 任务

```bash
python3 scripts/paddleocr_api.py submit "input/example.pdf" "work/example"
```

### 3. 等待并下载 OCR 结果

```bash
python3 scripts/paddleocr_api.py fetch "work/example"
```

### 4. 清洗正文并裁剪图表

```bash
python3 scripts/prepare.py "work/example"
```

这一步会生成 `draft.md`、`figures.json` 和图表裁剪图。

### 5. 分析图表

读取 `work/example/figures.json`，逐个分析 `figures/` 中的图表，并为每个图表创建：

```text
work/example/vision/fig01.json
```

文件格式如下：

```json
{
  "fig_id": "fig01",
  "action": "describe",
  "result": "图表中可见的趋势、差异或结构。"
}
```

`action` 可以是：

- `describe`：描述折线图、柱状图、饼图等
- `mermaid`：表示流程图、组织结构图或股权关系图
- `table`：表示结构化表格
- `drop`：忽略装饰图、Logo 或无研究价值的图片

详细规则见 [`skills/pdf2md/SKILL.md`](skills/pdf2md/SKILL.md)。

### 6. 校验并组装 Markdown

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
