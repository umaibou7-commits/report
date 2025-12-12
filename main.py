import os
import io
import csv
import json
from typing import Optional, List
from urllib.parse import urlparse

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI


# ======================
# 埋め込みHTML（フロントエンド）
# ======================

HTML_PAGE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8" />
  <title>Ahrefs CSV → SEOレポート自動生成</title>
  <style>
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      max-width: 960px;
      margin: 24px auto;
      padding: 0 16px 40px;
      background: #f5f7fb;
    }
    h1 {
      font-size: 1.6rem;
      margin-bottom: 0.5rem;
    }
    .card {
      background: #fff;
      border-radius: 12px;
      padding: 16px 20px;
      box-shadow: 0 4px 18px rgba(0,0,0,0.06);
      margin-bottom: 16px;
    }
    label {
      display: block;
      font-size: 0.9rem;
      margin: 8px 0 4px;
      font-weight: 600;
    }
    input[type="text"],
    input[type="month"],
    textarea {
      width: 100%;
      padding: 8px 10px;
      border-radius: 8px;
      border: 1px solid #cbd5e1;
      font-size: 0.9rem;
      box-sizing: border-box;
    }
    input[type="file"] {
      margin-top: 4px;
    }
    textarea {
      min-height: 260px;
      resize: vertical;
      font-family: SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      white-space: pre-wrap;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 8px 16px;
      border-radius: 999px;
      border: none;
      background: linear-gradient(135deg, #2563eb, #4f46e5);
      color: #fff;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      margin-top: 12px;
    }
    .btn:disabled {
      opacity: 0.6;
      cursor: default;
    }
    .btn-secondary {
      background: #0f172a;
      margin-left: 8px;
    }
    .status {
      font-size: 0.85rem;
      color: #475569;
      margin-top: 6px;
    }
    .error {
      color: #b91c1c;
    }
  </style>
</head>
<body>
  <h1>Ahrefs CSV → SEOレポート自動生成</h1>
  <p style="font-size:0.9rem;color:#475569;">
    1) Ahrefsから先月・今月のCSVを出す → 2) ここでアップロード → 3) レポート生成 → 4) Notionにコピペ
  </p>

  <div class="card">
    <form id="report-form">
      <label>対象サイトのURL</label>
      <input type="text" name="domain" placeholder="https://example-clinic.com" required />

      <label>先月</label>
      <input type="month" name="month_prev" required />

      <label>今月</label>
      <input type="month" name="month_current" required />

      <label>ブログ判定パス（カンマ区切り）</label>
      <input type="text" name="blog_paths" value="/blog,/column" />

      <label>先月のCSV（Top pages）</label>
      <input type="file" name="prev_csv" accept=".csv" required />

      <label>今月のCSV（Top pages）</label>
      <input type="file" name="curr_csv" accept=".csv" required />

      <button type="submit" class="btn" id="submit-btn">レポートを生成する</button>
      <span class="status" id="status"></span>
    </form>
  </div>

  <div class="card">
    <label>生成されたレポート（Markdown / このままNotionにコピペOK）</label>
    <textarea id="report-output" placeholder="ここにレポートが表示されます"></textarea>
    <button class="btn btn-secondary" id="download-btn" disabled>.mdとしてダウンロード</button>
  </div>

  <script>
    const BACKEND_URL = "/generate-report";

    const form = document.getElementById("report-form");
    const statusEl = document.getElementById("status");
    const submitBtn = document.getElementById("submit-btn");
    const output = document.getElementById("report-output");
    const dlBtn = document.getElementById("download-btn");

    let lastFilename = "report.md";

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      statusEl.textContent = "";
      statusEl.classList.remove("error");
      output.value = "";
      dlBtn.disabled = true;

      const fd = new FormData(form);

      submitBtn.disabled = true;
      submitBtn.textContent = "生成中...";
      statusEl.textContent = "OpenAIでレポート生成中です…";

      try {
        const res = await fetch(BACKEND_URL, {
          method: "POST",
          body: fd,
        });

        if (!res.ok) {
          const t = await res.text();
          throw new Error(`エラー: ${res.status} ${t}`);
        }

        const data = await res.json();
        output.value = data.report || "";
        lastFilename = data.filename || "report.md";
        dlBtn.disabled = !output.value;
        statusEl.textContent = "レポート生成が完了しました。Notionにコピペしてください。";
      } catch (err) {
        console.error(err);
        statusEl.textContent = "エラーが発生しました。コンソールログを確認してください。";
        statusEl.classList.add("error");
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "レポートを生成する";
      }
    });

    dlBtn.addEventListener("click", () => {
      const blob = new Blob([output.value], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = lastFilename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    });
  </script>
</body>
</html>
"""


# ======================
# CSV読み込みユーティリティ
# ======================

def guess_column(headers, kind: str):
    """
    AhrefsのCSVヘッダーから URL / Traffic / Keyword の列名を推測する
    """
    lowers = {h.lower(): h for h in headers}

    if kind == "url":
        candidates = ["url", "page url", "link url", "ページurl", "リンクurl"]
        contains = ["url", "ページ", "リンク"]
    elif kind == "traffic":
        candidates = ["traffic", "organic traffic", "search traffic", "トラフィック"]
        contains = ["traffic", "トラフィック"]
    elif kind == "keyword":
        candidates = ["top keyword", "top keywords", "keyword", "keywords", "キーワード"]
        contains = ["keyword", "キーワード"]
    else:
        return None

    # 完全一致
    for cand in candidates:
        if cand in lowers:
            return lowers[cand]

    # 部分一致
    for h in headers:
        h_low = h.lower()
        if any(ck in h_low for ck in contains):
            return h

    return None


def load_csv_pages_from_bytes(
    file_bytes: bytes,
    url_col_opt: Optional[str] = None,
    traffic_col_opt: Optional[str] = None,
    keyword_col_opt: Optional[str] = None,
):
    """
    アップロードされたCSV（バイト列）からページ情報を読み込む
    """
    # encoding推定（UTF-8 or Shift-JIS）
    for enc in ["utf-8-sig", "cp932"]:
        try:
            text = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(status_code=400, detail="CSVの文字コードが不明です（UTF-8 or Shift-JISで保存してください）")

    f = io.StringIO(text)
    reader = csv.DictReader(f)
    headers = reader.fieldnames or []

    url_col = url_col_opt or guess_column(headers, "url")
    traffic_col = traffic_col_opt or guess_column(headers, "traffic")
    keyword_col = keyword_col_opt or guess_column(headers, "keyword")

    missing = []
    if not url_col:
        missing.append("URL列")
    if not traffic_col:
        missing.append("Traffic列")
    if not keyword_col:
        missing.append("Keyword列")

    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"CSVヘッダーから必要な列が見つかりませんでした: {', '.join(missing)} / ヘッダー: {headers}",
        )

    pages = []
    for row in reader:
        url = row.get(url_col)
        traffic_raw = row.get(traffic_col)
        if not url or not traffic_raw:
            continue

        traffic_raw = traffic_raw.replace(",", "").strip()
        if traffic_raw == "":
            continue

        try:
            traffic = float(traffic_raw)
        except ValueError:
            continue

        keyword = row.get(keyword_col)
        pages.append(
            {
                "url": url,
                "traffic": traffic,
                "top_keyword": keyword,
            }
        )

    return pages


def summarize_pages(pages: List[dict]):
    """
    全体のトラフィック合計などを集計
    """
    if not pages:
        return {
            "total_traffic_prev": 0,
            "total_traffic_current": 0,
            "total_diff": 0,
            "total_diff_ratio": None,
            "page_count": 0,
        }
    total_prev = sum(p["prev_traffic"] for p in pages)
    total_current = sum(p["current_traffic"] for p in pages)
    diff = total_current - total_prev
    diff_ratio = None
    if total_prev > 0:
        diff_ratio = diff / total_prev * 100.0
    return {
        "total_traffic_prev": total_prev,
        "total_traffic_current": total_current,
        "total_diff": diff,
        "total_diff_ratio": diff_ratio,
        "page_count": len(pages),
    }


def merge_months(prev_pages, curr_pages, blog_paths=None):
    """
    先月 / 今月のページデータをマージし、差分とブログ判定を付与
    """
    if blog_paths is None:
        blog_paths = ["/blog", "/column"]

    merged = {}

    # 先月
    for p in prev_pages:
        url = p["url"]
        merged.setdefault(url, {})
        merged[url]["url"] = url
        merged[url]["prev_traffic"] = p["traffic"]
        merged[url]["top_keyword_prev"] = p.get("top_keyword")

    # 今月
    for p in curr_pages:
        url = p["url"]
        merged.setdefault(url, {})
        merged[url]["url"] = url
        merged[url]["current_traffic"] = p["traffic"]
        merged[url]["top_keyword_current"] = p.get("top_keyword")

    pages = []
    for url, data in merged.items():
        prev_tr = float(data.get("prev_traffic") or 0.0)
        curr_tr = float(data.get("current_traffic") or 0.0)
        diff = curr_tr - prev_tr
        diff_ratio = None
        if prev_tr > 0:
            diff_ratio = diff / prev_tr * 100.0

        is_blog = any(path in url for path in blog_paths)

        pages.append(
            {
                "url": url,
                "prev_traffic": prev_tr,
                "current_traffic": curr_tr,
                "diff": diff,
                "diff_ratio": diff_ratio,
                "top_keyword_prev": data.get("top_keyword_prev"),
                "top_keyword_current": data.get("top_keyword_current"),
                "is_blog": is_blog,
            }
        )

    summary = {
        "all": summarize_pages(pages),
        "blog_only": summarize_pages([p for p in pages if p["is_blog"]]),
    }

    return {"pages": pages, "summary": summary}


# ======================
# OpenAI でレポート生成
# ======================

def generate_report_with_openai(
    report_input: dict,
    domain: str,
    month_prev: str,
    month_current: str,
    openai_api_key: str,
) -> str:
    client = OpenAI(api_key=openai_api_key)

    instructions = f"""
あなたは、日本の医療・歯科クリニック向けのWebマーケティングコンサルタントです。
クライアントに提出する「月次SEOレポート」を日本語で作成してください。

【前提】
- 対象サイト: {domain}
- 比較期間: 前月（{month_prev}） と 今月（{month_current}）
- 入力データは URL ごとのオーガニックトラフィックとキーワードの情報です。
- `is_blog` が true のページはブログ記事（/blog や /column 等）として扱ってください。

【レポートの条件】
- 初心者のお客様にもわかる言葉で説明する
- 全体で 4,000〜6,000 文字程度
- コードブロック（```）は使わない
- Markdownライクな見出し・表は使用してよい

【レポート構成】

### 1. 今月のサマリー（重要ポイント3〜5個）

### 2. 全体のアクセス傾向（URL / Traffic / Top keyword 観点）

### 3. ブログ（/blog 等）のアクセス分析

### 4. 次月以降の具体的なアクション提案（3〜5個）

【トーン】
- 難しい専門用語は出来るだけ避ける
- 「結論 → 根拠 → 具体例」の順で書く
"""

    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(report_input, ensure_ascii=False)},
        ],
    )

    try:
        return resp.output[0].content[0].text
    except Exception:
        return str(resp)


# ======================
# FastAPI アプリ本体
# ======================

app = FastAPI()

# CORS（将来別ドメインのフロントから叩く場合も考えて一応許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReportResponse(BaseModel):
    report: str
    filename: str


@app.get("/", response_class=HTMLResponse)
async def root():
    """
    トップページ：埋め込みHTMLをそのまま返す
    """
    return HTMLResponse(HTML_PAGE)


@app.post("/generate-report", response_model=ReportResponse)
async def generate_report(
    domain: str = Form(...),
    month_prev: str = Form(...),
    month_current: str = Form(...),
    blog_paths: str = Form("/blog,/column"),
    prev_csv: UploadFile = File(...),
    curr_csv: UploadFile = File(...),
):
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY がサーバー側で設定されていません")

    prev_bytes = await prev_csv.read()
    curr_bytes = await curr_csv.read()

    prev_pages = load_csv_pages_from_bytes(prev_bytes)
    curr_pages = load_csv_pages_from_bytes(curr_bytes)

    if not prev_pages and not curr_pages:
        raise HTTPException(status_code=400, detail="CSVからデータを読み取れませんでした")

    blog_path_list = [p.strip() for p in blog_paths.split(",") if p.strip()]
    merged = merge_months(prev_pages, curr_pages, blog_paths=blog_path_list)

    parsed = urlparse(domain)
    dom = parsed.netloc or domain

    report_input = {
        "target": domain,
        "month_prev": month_prev,
        "month_current": month_current,
        "pages": merged["pages"],
        "summary": merged["summary"],
    }

    report_text = generate_report_with_openai(
        report_input, dom, month_prev, month_current, openai_api_key
    )

    safe_dom = dom.replace(":", "_")
    filename = f"report_{safe_dom}_{month_current}.md"

    return ReportResponse(report=report_text, filename=filename)
