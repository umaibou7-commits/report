import os
import sys
import csv
import json
import argparse
from urllib.parse import urlparse

from dotenv import load_dotenv
from openai import OpenAI


# ========= CSV 読み込みまわり =========

def try_open_csv(filepath: str):
    """
    CSVファイルをいい感じのエンコーディングで開く。
    - まず utf-8-sig
    - ダメなら cp932（Windows日本語）
    """
    encodings = ["utf-8-sig", "cp932"]
    last_error = None
    for enc in encodings:
        try:
            f = open(filepath, "r", encoding=enc, newline="")
            # 一度だけ読んでみて戻す（エラー確認）
            f.readline()
            f.seek(0)
            return f, enc
        except UnicodeDecodeError as e:
            last_error = e
            continue
    raise UnicodeDecodeError(
        "csv_error", b"", 0, 1,
        f"CSVの文字コードが想定外です。UTF-8 または Shift-JIS で保存されているか確認してください。最後のエラー: {last_error}"
    )


def guess_column(headers, kind: str):
    """
    ヘッダー行から、URL / Traffic / Keyword の列を推測する。
    kind: "url" | "traffic" | "keyword"
    戻り値: 見つかったヘッダー名 or None
    """
    lowers = {h.lower(): h for h in headers}

    # 候補（小文字でマッチ）
    if kind == "url":
        candidates = [
            "url",
            "page url",
            "link url",
            "リンクurl",
            "リンク url",
            "ページurl",
        ]
        # 部分一致させたいキーワード
        contains = ["url", "ページ", "リンク"]
    elif kind == "traffic":
        candidates = [
            "traffic",
            "organic traffic",
            "search traffic",
            "トラフィック",
            "オーガニックトラフィック",
        ]
        contains = ["traffic", "トラフィック"]
    elif kind == "keyword":
        candidates = [
            "top keyword",
            "top keywords",
            "keyword",
            "keywords",
            "キーワード",
            "トップキーワード",
        ]
        contains = ["keyword", "キーワード"]
    else:
        return None

    # 1. 完全一致（小文字）
    for cand in candidates:
        if cand in lowers:
            return lowers[cand]

    # 2. 部分一致
    for h in headers:
        h_low = h.lower()
        for ck in contains:
            if ck in h_low:
                return h

    return None


def load_csv_pages_auto(
    filepath: str,
    url_col_opt: str = None,
    traffic_col_opt: str = None,
    keyword_col_opt: str = None,
):
    """
    Ahrefs の CSV から URL / Traffic / Top keyword を取り出して list[dict] にする。
    - エンコーディング自動判定
    - 列名自動判定（指定がなければ）
    """
    f, encoding_used = try_open_csv(filepath)
    print(f"[INFO] CSVを開きました: {filepath} (encoding={encoding_used})", file=sys.stderr)

    reader = csv.DictReader(f)
    headers = reader.fieldnames or []
    print(f"[INFO] CSVヘッダー: {headers}", file=sys.stderr)

    # 列名が明示されていなければ自動推測
    url_col = url_col_opt or guess_column(headers, "url")
    traffic_col = traffic_col_opt or guess_column(headers, "traffic")
    keyword_col = keyword_col_opt or guess_column(headers, "keyword")

    missing = []
    if not url_col:
        missing.append("URL")
    if not traffic_col:
        missing.append("Traffic")
    if not keyword_col:
        missing.append("Top keyword")

    if missing:
        msg = (
            f"CSVから必要な列が自動判定できませんでした: {', '.join(missing)}\n"
            f"ヘッダー行: {headers}\n"
            "列名が日本語の場合は、--url-col / --traffic-col / --keyword-col で手動指定してください。\n"
        )
        raise ValueError(msg)

    print(f"[INFO] 使用する列: URL列='{url_col}', Traffic列='{traffic_col}', Keyword列='{keyword_col}'", file=sys.stderr)

    pages = []
    row_count = 0
    used_count = 0

    for row in reader:
        row_count += 1
        url = row.get(url_col)
        if not url:
            continue

        traffic_raw = row.get(traffic_col)
        if not traffic_raw:
            continue

        traffic_raw = traffic_raw.replace(",", "").strip()
        if traffic_raw == "":
            continue

        try:
            traffic = float(traffic_raw)
        except ValueError:
            # 変な文字列はスキップ（例: "-")
            continue

        keyword = row.get(keyword_col)
        pages.append(
            {
                "url": url,
                "traffic": traffic,
                "top_keyword": keyword,
            }
        )
        used_count += 1

    print(f"[INFO] 総行数: {row_count} 行, 読み取り成功: {used_count} 行", file=sys.stderr)
    f.close()
    return pages


# ========= 差分計算まわり =========

def merge_months(prev_pages, curr_pages, blog_paths=None):
    """
    先月・今月のリストをマージして差分などを計算する。

    prev_pages / curr_pages:
        list of {url, traffic, top_keyword}
    blog_paths:
        ブログURL判定に使うパス (例: ["/blog", "/column"])
    """
    if blog_paths is None:
        blog_paths = ["/blog", "/column"]

    merged = {}

    # 先月分
    for p in prev_pages:
        url = p["url"]
        merged.setdefault(url, {})
        merged[url]["url"] = url
        merged[url]["prev_traffic"] = p["traffic"]
        merged[url]["top_keyword_prev"] = p.get("top_keyword")

    # 今月分
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

        # /blog, /column などが URL に入っていたらブログ扱い
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
        "all": _summarize_pages(pages),
        "blog_only": _summarize_pages([p for p in pages if p["is_blog"]]),
    }

    return {"pages": pages, "summary": summary}


def _summarize_pages(pages):
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


# ========= OpenAI でレポート生成 =========

def generate_report_with_openai(
    report_input: dict,
    domain: str,
    month_prev: str,
    month_current: str,
    openai_api_key: str,
) -> str:
    """
    OpenAI Responses API を使ってレポート本文を生成。
    """
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
- Markdownライクな見出し・表は使用してよい（例：「### 見出し」, 「|列1|列2|」）

【レポート構成】

### 1. 今月のサマリー（重要ポイント3〜5個）
- 前月比での大きな変化（トラフィック増減）を箇条書きで簡潔にまとめる

### 2. 全体のアクセス傾向（URL / Traffic / Top keyword 観点）
1. 全体集計の比較表
2. トラフィックが増えたURLトップ5の表
3. トラフィックが減ったURLトップ5の表
4. キーワードの傾向（どんな検索ニーズが伸びているか・落ちているか）

### 3. ブログ（/blog 等）のアクセス分析
1. ブログ全体の集計表（全体との割合も含める）
2. 伸びたブログ記事トップ5 / 落ちたブログ記事トップ5 の表
3. 患者様目線での解釈（どんな悩み・ニーズの記事が読まれているか）
4. 今後増やすべきブログのテーマ例

### 4. 次月以降の具体的なアクション提案（3〜5個）
- 優先して改善・強化すべきURL
- 新規で作成すべきブログテーマ案
- タイトル・ディスクリプション、内部リンクの改善方向性 など

【書き方のトーン】
- 難しい専門用語はできるだけ避け、使う場合は簡単な説明を添える
- 「結論 → 根拠 → 具体例」の順で書く
- クライアントとの打ち合わせで、そのまま読み上げられるような自然な日本語
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(report_input, ensure_ascii=False)},
        ],
    )

    try:
        return response.output[0].content[0].text
    except Exception:
        # もし構造が変わっていた場合は、そのまま全文を返してデバッグ
        return str(response)


# ========= メイン処理 =========

def main():
    parser = argparse.ArgumentParser(
        description="Ahrefs の CSV から月次SEOレポートを自動生成するスクリプト"
    )
    parser.add_argument("--prev", required=True, help="先月のCSVファイルパス")
    parser.add_argument("--curr", required=True, help="今月のCSVファイルパス")
    parser.add_argument("--domain", required=True, help="対象サイトのURL（https://example.com）")
    parser.add_argument("--month-prev", required=True, help="先月（例: 2025-11）")
    parser.add_argument("--month-current", required=True, help="今月（例: 2025-12）")
    parser.add_argument(
        "--url-col",
        default=None,
        help="CSV内のURL列名（自動判定に失敗したとき用）",
    )
    parser.add_argument(
        "--traffic-col",
        default=None,
        help="CSV内のトラフィック列名（自動判定に失敗したとき用）",
    )
    parser.add_argument(
        "--keyword-col",
        default=None,
        help="CSV内のTop keyword列名（自動判定に失敗したとき用）",
    )
    parser.add_argument(
        "--blog-paths",
        default="/blog,/column",
        help="ブログURL判定に使うパス（カンマ区切り, 例: /blog,/column）",
    )
    args = parser.parse_args()

    # .env 読み込み
    load_dotenv()
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        print("環境変数 OPENAI_API_KEY が設定されていません。", file=sys.stderr)
        sys.exit(1)

    blog_paths = [p.strip() for p in args.blog_paths.split(",") if p.strip()]

    # CSV 読み込み（自動判定＋必要なら手動列指定）
    try:
        prev_pages = load_csv_pages_auto(
            args.prev, args.url_col, args.traffic_col, args.keyword_col
        )
        curr_pages = load_csv_pages_auto(
            args.curr, args.url_col, args.traffic_col, args.keyword_col
        )
    except Exception as e:
        print(f"[ERROR] CSV読み込みでエラー: {e}", file=sys.stderr)
        sys.exit(1)

    if not prev_pages and not curr_pages:
        print("CSVからデータが読み取れませんでした。列名や中身を確認してください。", file=sys.stderr)
        sys.exit(1)

    # 差分マージ
    merged = merge_months(prev_pages, curr_pages, blog_paths=blog_paths)

    report_input = {
        "target": args.domain,
        "month_prev": args.month_prev,
        "month_current": args.month_current,
        "pages": merged["pages"],
        "summary": merged["summary"],
    }

    parsed = urlparse(args.domain)
    domain = parsed.netloc or args.domain

    # レポート生成
    report_text = generate_report_with_openai(
        report_input, domain, args.month_prev, args.month_current, openai_api_key
    )

    # ファイル名: report_ドメイン_YYYY-MM.md
    safe_domain = domain.replace(":", "_")
    filename = f"report_{safe_domain}_{args.month_current}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report_text)

    print("\n===== 生成されたレポート =====\n")
    print(report_text)
    print(f"\nレポートを {filename} に保存しました。")


if __name__ == "__main__":
    main()
