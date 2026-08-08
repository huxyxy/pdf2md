#!/usr/bin/env python3
"""PaddleOCR-VL API 客户端。

用法:
  python3 scripts/paddleocr_api.py submit <pdf_path> <work_dir>   # 提交，写 job.json（幂等）
  python3 scripts/paddleocr_api.py fetch <work_dir>               # 轮询+下载 raw.jsonl（幂等）
"""
import json
import logging
import os
import sys
import time

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
log = logging.getLogger("paddleocr_api")

OPTIONAL_PAYLOAD = {
    # 服务端过滤页眉/页码等辅助内容（官方「辅助内容解析」）
    "markdownIgnoreLabels": ["header", "footer", "header_image", "footer_image", "number", "aside_text"],
    "useDocOrientationClassify": True,
    "useDocUnwarping": True,
    "useLayoutDetection": True,
    "useChartRecognition": True,
    "useSealRecognition": False,
    "useOcrForImageBlock": True,
    "mergeTables": True,
    "relevelTitles": True,
    "layoutShapeMode": "auto",
    "promptLabel": "spotting",
    "repetitionPenalty": 1,
    "temperature": 0.5,
    "topP": 1,
    "minPixels": 147384,
    "maxPixels": 2822400,
    "layoutNms": True,
    "restructurePages": True,
}

TIMEOUT = (30, 300)
RETRYABLE_STATUS = {429, 502, 503, 504}


def load_env() -> dict:
    env = {}
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    for k in ("PADDLEOCR_TOKEN", "PADDLEOCR_MODEL", "PADDLEOCR_JOB_URL"):
        if not env.get(k):
            raise SystemExit(f".env 缺少 {k}")
    return env


def request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """仅重试临时性错误：429/5xx/网络异常。401/参数错误直接失败。"""
    for attempt in range(3):
        try:
            resp = requests.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as e:
            if attempt == 2:
                raise
            wait = 2 ** attempt * 2
            log.warning("网络异常 %s，%ds 后重试 (%d/3)", e, wait, attempt + 1)
            time.sleep(wait)
            continue
        if resp.status_code not in RETRYABLE_STATUS:
            return resp
        if attempt == 2:
            return resp
        wait = 2 ** attempt * 5
        log.warning("HTTP %d，%ds 后重试 (%d/3)", resp.status_code, wait, attempt + 1)
        time.sleep(wait)
    return resp  # unreachable


def headers() -> dict:
    return {"Authorization": f"bearer {ENV['PADDLEOCR_TOKEN']}"}


def submit(pdf_path: str, work_dir: str) -> str:
    os.makedirs(work_dir, exist_ok=True)
    job_file = os.path.join(work_dir, "job.json")
    if os.path.exists(job_file):
        log.info("已提交过，复用 %s", job_file)
        return json.load(open(job_file))["jobId"]
    data = {"model": ENV["PADDLEOCR_MODEL"], "optionalPayload": json.dumps(OPTIONAL_PAYLOAD)}
    with open(pdf_path, "rb") as f:
        resp = request_with_retry("POST", ENV["PADDLEOCR_JOB_URL"], headers=headers(),
                                  data=data, files={"file": f})
    if resp.status_code != 200:
        raise SystemExit(f"提交失败 {resp.status_code}: {resp.text[:500]}")
    job_id = resp.json()["data"]["jobId"]
    with open(job_file, "w") as f:
        json.dump({"jobId": job_id, "pdf": os.path.abspath(pdf_path)}, f, ensure_ascii=False)
    log.info("jobId: %s", job_id)
    return job_id


def fetch(work_dir: str, poll: bool = True) -> bool:
    """轮询并下载 raw.jsonl。返回 True=已完成。幂等。"""
    out = os.path.join(work_dir, "raw.jsonl")
    if os.path.exists(out):
        log.info("raw.jsonl 已存在，跳过")
        return True
    job_id = json.load(open(os.path.join(work_dir, "job.json")))["jobId"]
    url = f"{ENV['PADDLEOCR_JOB_URL']}/{job_id}"
    while True:
        resp = request_with_retry("GET", url, headers=headers())
        resp.raise_for_status()
        d = resp.json()["data"]
        state = d["state"]
        if state == "done":
            p = d["extractProgress"]
            log.info("done: pages=%s, %s -> %s", p["extractedPages"], p["startTime"], p["endTime"])
            r = request_with_retry("GET", d["resultUrl"]["jsonUrl"])
            r.raise_for_status()
            with open(out, "w", encoding="utf-8") as f:
                f.write(r.text)
            return True
        if state == "failed":
            raise SystemExit(f"任务失败: {d.get('errorMsg')}")
        prog = d.get("extractProgress") or {}
        log.info("%s: %s/%s", state, prog.get("extractedPages", "?"), prog.get("totalPages", "?"))
        if not poll:
            return False
        time.sleep(5)


def main() -> None:
    cmd = sys.argv[1]
    if cmd == "submit":
        submit(sys.argv[2], sys.argv[3])
    elif cmd == "fetch":
        ok = fetch(sys.argv[2], poll="--nowait" not in sys.argv)
        sys.exit(0 if ok else 2)
    else:
        raise SystemExit(__doc__)


ENV = load_env()

if __name__ == "__main__":
    main()
