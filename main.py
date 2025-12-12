import os
import io
import csv
import json
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI


# ======================
# トークン認証（必須化）
# ======================

def require_access_token(x_access_token: Optional[str]) -> None:
    expected = os.getenv("ACCESS_TOKEN")
    if not expected:
        raise HTTPException(status_code=500, detail="ACCESS_TOKEN がサーバー側で設定されていません")
    if not x_access_token or x_access_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


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
      max-width: 980px;
      margin: 24px auto;
      padding: 0 16px 40px;
      background: #f5f7fb;
    }
    h1 { font-size: 1.6rem; margin-bottom: 0.5rem; }

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
    input[type="password"],
    textarea {
      width: 100%;
      padding: 8px 10px;
      border-radius: 8px;
      border: 1px solid #cbd5e1;
      font-size: 0.9rem;
      box-sizing: border-box;
    }

    textarea {
      min-height: 280px;
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
    }
    .btn:disabled { opacity: 0.6; cursor: default; }
    .btn-secondary { background: #0f172a; }
    .btn-ghost { background: #e2e8f0; color: #0f172a; }

    .status {
      font-size: 0.85rem;
      color: #475569;
      margin-left: 8px;
      word-break: break-word;
    }
    .status.error { color: #b91c1c; }

    .button-row {
      margin-top: 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }

    .drop-area {
      margin-top: 4px;
      padding: 16px;
      border: 2px dashed #cbd5e1;
      border-radius: 10px;
      text-align: center;
      font-size: 0.85rem;
      color: #64748b;
      background: #f8fafc;
      cursor: pointer;
      user-select: none;
    }
    .drop-area.highlight {
      border-color: #2563eb;
      background: #eff6ff;
      color: #1d4ed8;
    }

    .subtext {
      font-size: 0.8rem;
      color: #64748b;
      margin-top: 4px;
      display: block;
    }

    /* Dashboard */
    .dash-title {
      font-size: 1rem;
      font-weight: 700;
      margin-bottom: 8px;
    }
    #dash-wrap {
      border: 1px solid #e2e8f0;
      background: #ffffff;
      border-radius: 12px;
      padding: 12px;
    }
    .dash-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .dash-box {
      background: #f8fafc;
      border-radius: 10px;
      padding: 10px 10px;
      border: 1px solid #e2e8f0;
    }
    .dash-label { color: #64748b; font-size: 0.78rem; }
    .dash-value { font-size: 1.05rem; font-weight: 800; margin-top: 2px; }
    .dash-mini { color: #64748b; font-size: 0.75rem; margin-top: 2px; }

    .bar-outer {
      margin-top: 8px;
      height: 8px;
      width: 100%;
      border-radius: 999px;
      background: #e2e8f0;
      overflow: hidden;
    }
    .bar-inner {
      height: 100%;
      width: 0%;
      border-radius: 999px;
      background: linear-gradient(90deg, #2563eb, #4f46e5);
      transition: width 0.3s ease;
    }

    @media (max-width: 720px) {
      .dash-grid { grid-template-columns: 1fr; }
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
      <label>アクセス用トークン（共通パスワード）</label>
      <input type="password" id="access_token" placeholder="チーム共有のトークンを入力" required />

      <div class="button-row" style="margin-top:8px;">
        <label style="display:flex;gap:8px;align-items:center;font-weight:600;margin:0;">
          <input type="checkbox" id="remember_token" />
          この端末にトークンを保存
        </label>
        <button type="button" class="btn btn-ghost" id="forget_token_btn">保存トークンを削除</button>
      </div>
      <span class="subtext">※ 共有PCの場合は保存しないでください（保存するとそのPCのブラウザに残ります）</span>

      <label>クリニック名（タイトル用）</label>
      <input type="text" name="clinic_name" id="clinic_name" placeholder="例：長尾歯科医院" />
      <span class="subtext">未入力の場合はドメイン名で代用します</span>

      <label>対象サイトのURL</label>
      <input type="text" name="domain" id="domain" placeholder="https://example-clinic.com" required />

      <label>先月（ここを選ぶと今月が自動反映されます）</label>
      <input type="month" name="month_prev" id="month_prev" required />

      <label>今月</label>
      <input type="month" name="month_current" id="month_current" required />

      <label>ブログ判定パス（カンマ区切り）</label>
      <input type="text" name="blog_paths" value="/blog,/column" />
      <span class="subtext">例: /blog,/column,/news/column など（URL内に含まれていればブログ扱い）</span>

      <label>レポートタイトル（自動生成）</label>
      <input type="text" id="title-field" readonly />
      <div class="button-row" style="margin-top:8px;">
        <button type="button" class="btn btn-ghost" id="copy-title-btn">タイトルをコピー</button>
      </div>

      <label>先月のCSV（Top pages）</label>
      <div class="drop-area" id="drop-prev">
        <span id="prev-file-label">ここにファイルをドロップするか、クリックして選択</span>
      </div>
      <input type="file" name="prev_csv" id="prev_csv" accept=".csv" style="display:none" required />

      <label>今月のCSV（Top pages）</label>
      <div class="drop-area" id="drop-curr">
        <span id="curr-file-label">ここにファイルをドロップするか、クリックして選択</span>
      </div>
      <input type="file" name="curr_csv" id="curr_csv" accept=".csv" style="display:none" required />

      <div class="button-row">
        <button type="submit" class="btn" id="submit-btn">レポートを生成する</button>
        <button type="button" class="btn btn-secondary" id="clear-btn">一括クリア</button>
        <span class="status" id="status"></span>
      </div>
    </form>
  </div>

  <div class="card" id="dash-card" style="display:none;">
    <div class="dash-title">📊 全体トラフィック（先月⇄今月）</div>

    <div id="dash-wrap">
      <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-end;flex-wrap:wrap;">
        <div style="font-weight:800;" id="dash-headline">—</div>
        <div style="color:#64748b;font-size:0.8rem;" id="dash-sub">—</div>
      </div>

      <div class="dash-grid" style="margin-top:10px;">
        <div class="dash-box">
          <div class="dash-label">先月 合計トラフィック</div>
          <div class="dash-value" id="dash-prev">-</div>
          <div class="bar-outer"><div class="bar-inner" id="bar-prev"></div></div>
        </div>
        <div class="dash-box">
          <div class="dash-label">今月 合計トラフィック</div>
          <div class="dash-value" id="dash-current">-</div>
          <div class="bar-outer"><div class="bar-inner" id="bar-current"></div></div>
        </div>
        <div class="dash-box">
          <div class="dash-label">差分 / 変化率</div>
          <div class="dash-value" id="dash-diff">-</div>
          <div class="dash-mini" id="dash-diff-note">—</div>
          <div class="bar-outer"><div class="bar-inner" id="bar-diff"></div></div>
        </div>
      </div>
    </div>

    <span class="subtext">この枠ごとスクショしてレポート冒頭に貼ると分かりやすいです。</span>
  </div>

  <div class="card">
    <label>生成されたレポート（Markdown / NotionにそのままコピペOK）</label>
    <textarea id="report-output" placeholder="ここにレポートが表示されます"></textarea>
    <span class="subtext" id="char-count">文字数: 0</span>
    <div class="button-row" style="margin-top:8px;">
      <button class="btn btn-ghost" id="copy-btn" disabled>レポートをコピー</button>
      <button class="btn btn-secondary" id="download-btn" disabled>.mdとしてダウンロード</button>
    </div>
  </div>

  <script>
    const BACKEND_URL = "/generate-report";

    const form = document.getElementById("report-form");
    const statusEl = document.getElementById("status");
    const submitBtn = document.getElementById("submit-btn");
    const clearBtn = document.getElementById("clear-btn");

    const output = document.getElementById("report-output");
    const dlBtn = document.getElementById("download-btn");
    const copyBtn = document.getElementById("copy-btn");
    const charCountEl = document.getElementById("char-count");

    const accessTokenInput = document.getElementById("access_token");
    const rememberTokenCheckbox = document.getElementById("remember_token");
    const forgetTokenBtn = document.getElementById("forget_token_btn");
    const TOKEN_KEY = "report_access_token_v1";

    const clinicNameInput = document.getElementById("clinic_name");
    const domainInput = document.getElementById("domain");
    const monthPrevInput = document.getElementById("month_prev");
    const monthCurrentInput = document.getElementById("month_current");
    const titleField = document.getElementById("title-field");
    const copyTitleBtn = document.getElementById("copy-title-btn");

    const prevInput = document.getElementById("prev_csv");
    const currInput = document.getElementById("curr_csv");
    const prevDrop = document.getElementById("drop-prev");
    const currDrop = document.getElementById("drop-curr");
    const prevLabel = document.getElementById("prev-file-label");
    const currLabel = document.getElementById("curr-file-label");

    const dashCard = document.getElementById("dash-card");
    const dashHeadline = document.getElementById("dash-headline");
    const dashSub = document.getElementById("dash-sub");
    const dashPrev = document.getElementById("dash-prev");
    const dashCurrent = document.getElementById("dash-current");
    const dashDiff = document.getElementById("dash-diff");
    const dashDiffNote = document.getElementById("dash-diff-note");
    const barPrev = document.getElementById("bar-prev");
    const barCurrent = document.getElementById("bar-current");
    const barDiff = document.getElementById("bar-diff");

    let lastFilename = "report.md";

    function preventDefaults(e) { e.preventDefault(); e.stopPropagation(); }

    function setupDropArea(dropEl, inputEl, labelEl) {
      ["dragenter", "dragover", "dragleave", "drop"].forEach(ev => {
        dropEl.addEventListener(ev, preventDefaults, false);
      });
      ["dragenter", "dragover"].forEach(ev => {
        dropEl.addEventListener(ev, () => dropEl.classList.add("highlight"), false);
      });
      ["dragleave", "drop"].forEach(ev => {
        dropEl.addEventListener(ev, () => dropEl.classList.remove("highlight"), false);
      });

      dropEl.addEventListener("click", () => inputEl.click());

      dropEl.addEventListener("drop", (e) => {
        const file = e.dataTransfer.files[0];
        if (!file) return;
        const dt = new DataTransfer();
        dt.items.add(file);
        inputEl.files = dt.files;
        labelEl.textContent = file.name;
      });

      inputEl.addEventListener("change", () => {
        if (inputEl.files && inputEl.files[0]) {
          labelEl.textContent = inputEl.files[0].name;
        } else {
          labelEl.textContent = "ここにファイルをドロップするか、クリックして選択";
        }
      });
    }

    function updateCharCount() {
      charCountEl.textContent = "文字数: " + (output.value.length).toString();
    }

    function monthToJP(ym) {
      if (!ym) return "";
      const [y, m] = ym.split("-");
      if (!y || !m) return ym;
      return `${y}年${parseInt(m, 10)}月`;
    }

    function parseHostname(url) {
      try { return new URL(url).host; } catch(e) { return url || ""; }
    }

    function addOneMonth(ym) {
      if (!ym) return "";
      const parts = ym.split("-");
      if (parts.length !== 2) return "";
      let y = parseInt(parts[0], 10);
      let m = parseInt(parts[1], 10);
      if (isNaN(y) || isNaN(m)) return "";
      m += 1;
      if (m > 12) { m = 1; y += 1; }
      return `${y}-${String(m).padStart(2, "0")}`;
    }

    function updateTitleField() {
      const prev = monthPrevInput.value;
      const curr = monthCurrentInput.value;
      const clinic = (clinicNameInput.value || "").trim();
      const dom = parseHostname(domainInput.value || "");
      if (!prev || !curr) { titleField.value = ""; return; }
      const name = clinic ? clinic : dom;
      titleField.value = `${monthToJP(prev)}と${monthToJP(curr)}のアクセス比較分析（${name}）`;
    }

    function formatNum(n) {
      if (n === null || n === undefined) return "-";
      return Math.round(n).toLocaleString("ja-JP");
    }
    function formatPct(p) {
      if (p === null || p === undefined) return "-";
      return (Math.round(p * 10) / 10).toString() + "%";
    }

    function updateDashboard(summary, titleText) {
      if (!summary || !summary.all) { dashCard.style.display = "none"; return; }
      const all = summary.all;
      const prev = all.total_traffic_prev || 0;
      const curr = all.total_traffic_current || 0;
      const diff = all.total_diff || 0;
      const ratio = all.total_diff_ratio;

      dashHeadline.textContent = titleText || "全体トラフィックの推移";
      dashSub.textContent = "※ Ahrefs Top pages（CSV）集計";

      dashPrev.textContent = formatNum(prev);
      dashCurrent.textContent = formatNum(curr);

      const sign = diff >= 0 ? "+" : "";
      dashDiff.textContent = `${sign}${formatNum(diff)} / ${formatPct(ratio)}`;

      let note = "";
      if (prev === 0 && curr > 0) note = "先月が0のため変化率は参考値です";
      if (prev > 0 && Math.abs(diff) < (prev * 0.05)) note = "変化は小さめ（±5%以内）";
      if (prev > 0 && diff > (prev * 0.1)) note = "増加傾向（+10%超）";
      if (prev > 0 && diff < -(prev * 0.1)) note = "減少傾向（-10%超）";
      dashDiffNote.textContent = note;

      const maxVal = Math.max(prev, curr, Math.abs(diff), 1);
      barPrev.style.width = Math.round((prev / maxVal) * 100) + "%";
      barCurrent.style.width = Math.round((curr / maxVal) * 100) + "%";
      barDiff.style.width = Math.round((Math.abs(diff) / maxVal) * 100) + "%";

      dashCard.style.display = "block";
    }

    setupDropArea(prevDrop, prevInput, prevLabel);
    setupDropArea(currDrop, currInput, currLabel);

    output.addEventListener("input", updateCharCount);

    clinicNameInput.addEventListener("input", updateTitleField);
    domainInput.addEventListener("input", updateTitleField);

    monthPrevInput.addEventListener("change", () => {
      monthCurrentInput.value = addOneMonth(monthPrevInput.value);
      updateTitleField();
    });
    monthCurrentInput.addEventListener("change", updateTitleField);

    copyTitleBtn.addEventListener("click", async () => {
      try {
        if (!titleField.value) updateTitleField();
        await navigator.clipboard.writeText(titleField.value || "");
        statusEl.textContent = "タイトルをコピーしました。";
        statusEl.classList.remove("error");
      } catch(e) {
        statusEl.textContent = "タイトルのコピーに失敗しました。";
        statusEl.classList.add("error");
      }
    });

    // 起動時に保存トークンがあれば復元
    window.addEventListener("DOMContentLoaded", () => {
      const saved = localStorage.getItem(TOKEN_KEY);
      if (saved) {
        accessTokenInput.value = saved;
        rememberTokenCheckbox.checked = true;
      }
    });

    // 保存トークンを削除（ログアウト的に使う）
    forgetTokenBtn.addEventListener("click", () => {
      localStorage.removeItem(TOKEN_KEY);
      accessTokenInput.value = "";
      rememberTokenCheckbox.checked = false;
      statusEl.textContent = "保存トークンを削除しました。";
      statusEl.classList.remove("error");
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      statusEl.textContent = "";
      statusEl.classList.remove("error");
      output.value = "";
      updateCharCount();
      dlBtn.disabled = true;
      copyBtn.disabled = true;
      dashCard.style.display = "none";

      updateTitleField();

      const token = (accessTokenInput.value || "").trim();
      if (!token) {
        statusEl.textContent = "アクセス用トークンを入力してください。";
        statusEl.classList.add("error");
        return;
      }

      // トークン保存（チェックONのときだけ）
      if (rememberTokenCheckbox.checked) {
        localStorage.setItem(TOKEN_KEY, token);
      } else {
        localStorage.removeItem(TOKEN_KEY);
      }

      const fd = new FormData(form);

      submitBtn.disabled = true;
      submitBtn.textContent = "生成中...";
      statusEl.textContent = "OpenAIでレポート生成中です…";

      try {
        const res = await fetch(BACKEND_URL, {
          method: "POST",
          headers: { "X-Access-Token": token },
          body: fd
        });

        if (!res.ok) {
          let serverMessage = "";
          try {
            const ct = res.headers.get("content-type") || "";
            if (ct.includes("application/json")) {
              const j = await res.json();
              serverMessage = j.detail || JSON.stringify(j);
            } else {
              serverMessage = await res.text();
            }
          } catch (e) {
            serverMessage = "(サーバーメッセージの解析に失敗しました)";
          }
          throw new Error(`サーバーエラー: ${res.status} ${serverMessage}`);
        }

        const data = await res.json();
        output.value = data.report || "";
        lastFilename = data.filename || "report.md";
        if (data.title) titleField.value = data.title;

        updateCharCount();
        const hasText = !!output.value;
        dlBtn.disabled = !hasText;
        copyBtn.disabled = !hasText;

        if (data.summary) updateDashboard(data.summary, titleField.value || "全体トラフィックの推移");

        statusEl.textContent = "完了！Notionに貼り付けてください。";
      } catch (err) {
        console.error(err);
        statusEl.textContent = err.message || "エラーが発生しました。";
        statusEl.classList.add("error");
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "レポートを生成する";
      }
    });

    // 一括クリア：トークンは消さない（デフォ）
    clearBtn.addEventListener("click", () => {
      // フォームリセットで token も消えるので、保存されているなら復元しておく
      form.reset();

      // ファイル表示リセット
      prevLabel.textContent = "ここにファイルをドロップするか、クリックして選択";
      currLabel.textContent = "ここにファイルをドロップするか、クリックして選択";

      // 出力リセット
      output.value = "";
      updateCharCount();
      dlBtn.disabled = true;
      copyBtn.disabled = true;
      lastFilename = "report.md";
      titleField.value = "";
      dashCard.style.display = "none";

      // ステータスクリア
      statusEl.textContent = "";
      statusEl.classList.remove("error");

      // トークンは消さない（保存があれば復元 / なければ空）
      const saved = localStorage.getItem(TOKEN_KEY);
      if (saved) {
        accessTokenInput.value = saved;
        rememberTokenCheckbox.checked = true;
      } else {
        // もともと保存してない人は空でOK（毎回入力運用）
        accessTokenInput.value = "";
        rememberTokenCheckbox.checked = false;
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

    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(output.value || "");
        statusEl.textContent = "レポートをコピーしました。";
        statusEl.classList.remove("error");
      } catch(e) {
        statusEl.textContent = "レポートのコピーに失敗しました。";
        statusEl.classList.add("error");
      }
    });

    updateCharCount();
  </script>
</body>
</html>
"""


# ======================
# CSV 読み込みユーティリティ
# ======================

def guess_column(headers, kind: str):
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

    for cand in candidates:
        if cand in lowers:
            return lowers[cand]

    for h in headers:
        hl = h.lower()
        if any(s in hl for s in contains):
            return h
    return None


def load_csv_pages_from_bytes(
    file_bytes: bytes,
    url_col_opt: Optional[str] = None,
    traffic_col_opt: Optional[str] = None,
    keyword_col_opt: Optional[str] = None,
):
    for enc in ["utf-8-sig", "cp932", "utf-16", "utf-16-le", "utf-16-be"]:
        try:
            text = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(
            status_code=400,
            detail="CSVの文字コードが不明です（UTF-8 / Shift-JIS / UTF-16 で保存してください）",
        )

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
        if not url or traffic_raw is None:
            continue

        traffic_raw = str(traffic_raw).replace(",", "").strip()
        if traffic_raw == "":
            continue

        try:
            traffic = float(traffic_raw)
        except ValueError:
            continue

        keyword = row.get(keyword_col)
        pages.append({"url": url, "traffic": traffic, "top_keyword": keyword})

    return pages


def summarize_pages(pages: List[dict]):
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
    diff_ratio = (diff / total_prev * 100.0) if total_prev > 0 else None
    return {
        "total_traffic_prev": total_prev,
        "total_traffic_current": total_current,
        "total_diff": diff,
        "total_diff_ratio": diff_ratio,
        "page_count": len(pages),
    }


def merge_months(prev_pages, curr_pages, blog_paths=None):
    if blog_paths is None:
        blog_paths = ["/blog", "/column"]

    merged: Dict[str, Dict[str, Any]] = {}

    for p in prev_pages:
        url = p["url"]
        merged.setdefault(url, {})
        merged[url]["url"] = url
        merged[url]["prev_traffic"] = p["traffic"]
        merged[url]["top_keyword_prev"] = p.get("top_keyword")

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
        diff_ratio = (diff / prev_tr * 100.0) if prev_tr > 0 else None
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


def ym_to_japanese(ym: str) -> str:
    try:
        y, m = ym.split("-")
        return f"{y}年{int(m)}月"
    except Exception:
        return ym


def normalize_domain(domain: str) -> str:
    parsed = urlparse(domain)
    return parsed.netloc or domain


# ======================
# OpenAI でレポート生成
# ======================

def generate_report_with_openai(
    report_input: dict,
    domain: str,
    month_prev: str,
    month_current: str,
    title: str,
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
- summary.all / summary.blog_only に「先月・今月の合計トラフィック」「差分」「変化率」が入っています。

【出力フォーマット（Notionにそのまま貼る想定）】
- レポート1行目に必ずタイトル（H1）：
  # {title}
- 見出しは H2（##）中心。各H2タイトルの先頭に絵文字（📊📈📝✅💡）を付ける
- コードブロック（```）は絶対に使わない
- 冒頭に以下を必ず入れる：
  1) 「全体サマリー表」(summary.all)
  2) 「ブログサマリー表」(summary.blog_only)
  それぞれ列は「指標 / 前月 / 今月 / 差分 / 変化率」
  ※表の数値は summary の実数を使い、推測しない

【レポート構成】
## 📌 1. 今月のサマリー（重要ポイント3〜5個）
## 📈 2. 全体のアクセス傾向（URL / Traffic / Top keyword）
## ✍️ 3. ブログ（/blog等）のアクセス分析（blog_onlyの合計変化も言及）
## ✅ 4. 次月にやるべき具体アクション（3〜5個）

【トーン】
- 初心者でも分かる言葉
- 「結論 → 根拠 → 具体例」
- 4,000〜6,000文字程度
"""

    resp = client.responses.create(
        model="gpt-4.1",
        input=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(report_input, ensure_ascii=False)},
        ],
    )
    return resp.output[0].content[0].text


# ======================
# FastAPI アプリ本体
# ======================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 後で絞るのがおすすめ
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReportResponse(BaseModel):
    report: str
    filename: str
    title: str
    summary: Dict[str, Any]


@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(HTML_PAGE)


@app.post("/generate-report", response_model=ReportResponse)
async def generate_report(
    x_access_token: Optional[str] = Header(default=None, alias="X-Access-Token"),

    clinic_name: str = Form(""),
    domain: str = Form(...),
    month_prev: str = Form(...),
    month_current: str = Form(...),
    blog_paths: str = Form("/blog,/column"),
    prev_csv: UploadFile = File(...),
    curr_csv: UploadFile = File(...),
):
    require_access_token(x_access_token)

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

    dom = normalize_domain(domain)
    jp_prev = ym_to_japanese(month_prev)
    jp_curr = ym_to_japanese(month_current)
    name_for_title = clinic_name.strip() if clinic_name.strip() else dom
    title = f"{jp_prev}と{jp_curr}のアクセス比較分析（{name_for_title}）"

    report_input = {
        "target": domain,
        "clinic_name": clinic_name,
        "month_prev": month_prev,
        "month_current": month_current,
        "pages": merged["pages"],
        "summary": merged["summary"],
    }

    report_text = generate_report_with_openai(
        report_input, dom, month_prev, month_current, title, openai_api_key
    )

    safe_dom = dom.replace(":", "_").replace("/", "_")
    filename = f"report_{safe_dom}_{month_current}.md"

    return ReportResponse(
        report=report_text,
        filename=filename,
        title=title,
        summary=merged["summary"],
    )
