<!DOCTYPE html>
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
    // 同じドメイン上の /generate-report にPOSTする
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
