"""报告导出：单份 PDF（HTML 经无头 Chromium 打印）、按日期范围的 Excel（M5-2）。"""
from __future__ import annotations

import html
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

LABEL_ZH = {"recommend": "推荐", "pending": "待定", "not_recommend": "不推荐"}
AUDIENCE_ZH = {"veteran": "老主播", "month_1": "上播 1 个月", "new_trial": "新主播内部试播"}
DIM_ORDER = ["P", "S", "L", "O"]
DIM_ZH = {"P": "人设塑造", "S": "销售循环", "L": "表达逻辑", "O": "其他"}


class PdfError(RuntimeError):
    pass


def _ms(ms) -> str:
    if ms is None:
        return "—"
    s = int(ms) // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


def _cn(t) -> str:
    """按北京时间显示。"""
    from datetime import timedelta, timezone

    return t.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M") if t else "—"


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


def _item_row(i: dict) -> str:
    score = "—" if i["score"] is None else f"{i['score']:g}"
    flags = {"not_applicable": "不适用", "missing_evidence": "缺证据"}.get(i["status"], "") + ("低置信" if i["low_confidence"] else "")
    return (f"<tr><td>{_e(i['item_id'])}</td><td>{_e(i['name'])}</td><td>{score} / {i['max']}</td>"
            f"<td>{flags}</td><td>{_e('；'.join(i['notes'][:2]))}</td></tr>")


def _problem_row(s: dict) -> str:
    issues = "；".join(f"{h['item_id']} {h['reason'] or h['label'] or ''}" for h in s["hits"] if h["issue"])
    return f"<tr><td>{_ms(s['start_ms'])}</td><td>{_e(s['text'])}</td><td>{_e(issues)}</td><td>{_e(s['suggestion'] or '')}</td></tr>"


def report_html(d: dict) -> str:
    v, r = d["verdict"], d["result"]
    dims = {x["id"]: x for x in r["dimensions"]}
    banners = []
    if d["informal"]:
        banners.append("非正式报告：使用了草稿版的评分标准或检测配置，仅供试用")
    if d["critical"]:
        banners.append(f"临界样本：共 {len(v['rounds'])} 轮取多数，请谨慎使用")
    if r["low_confidence_items"]:
        banners.append("低置信条目：" + "、".join(r["low_confidence_items"]))
    rounds = "".join(f"<tr><td>第 {x['round_no']} 轮</td><td>{x['total_grade']}</td><td>{'达标' if x['grade_pass'] else '不达标'}</td></tr>" for x in v["rounds"])
    items = "".join(_item_row(i) for i in r["items"])
    problems = [s for seg in d["sentences"] for s in seg["sentences"] if s["issue"]][:40]
    prob = "".join(_problem_row(s) for s in problems)
    t = d["trace"]
    live = d.get("mode") == "live"
    kind = "录播" if live else "试镜"
    manifest = "；".join(f"{k}={v_}" for k, v_ in (t["model_manifest"] or {}).items())
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{kind}评分报告</title><style>
body {{ font-family: "WenQuanYi Zen Hei", "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", sans-serif; font-size: 12px; color: #000; margin: 24px; }}
h1 {{ font-size: 20px; margin: 0 0 4px; }} h2 {{ font-size: 14px; margin: 18px 0 6px; border-bottom: 1px solid #888; }}
table {{ width: 100%; border-collapse: collapse; }} td, th {{ border: 1px solid #aaa; padding: 3px 6px; text-align: left; vertical-align: top; }}
.label {{ display: inline-block; padding: 2px 10px; border: 2px solid #000; font-size: 16px; font-weight: bold; }}
.banner {{ background: #fff4e5; border: 1px solid #f0a020; padding: 4px 8px; margin: 4px 0; }} .meta {{ color: #444; }}
</style></head><body>
<h1>主播{kind}评分报告</h1>
<div class="meta">{_e(d['candidate_name'])} · {_e(d['product_name'])} · {'录播（无题单，整段视频评分）' if live else '题单'} {_e(d['sheet_code'])} · 提交 {_cn(d['submitted_at'])} · 第 {d['revision']} 版</div>
<p><span class="label">{LABEL_ZH[d['label']]}</span> {_e(v['reason'])}</p>
{''.join(f'<div class="banner">{_e(b)}</div>' for b in banners)}
<h2>总档位与维度</h2>
<table><tr><th>适用达标线</th><th>总档位</th>{''.join(f'<th>{_e(dims[k]["name"])}</th>' for k in DIM_ORDER)}</tr>
<tr><td>{AUDIENCE_ZH.get(d['audience'], d['audience'])}（&lt; {r['threshold']}）</td><td>{r['total_grade']}</td>
{''.join(f'<td>{dims[k]["score"]} 分 · {dims[k]["grade"]} 档</td>' for k in DIM_ORDER)}</tr></table>
{f'<h2>各轮结果</h2><table><tr><th>轮次</th><th>总档位</th><th>结论</th></tr>{rounds}</table>' if len(v['rounds']) > 1 else ''}
<h2>条目得分</h2><table><tr><th>编号</th><th>条目</th><th>得分</th><th>标记</th><th>说明</th></tr>{items}</table>
<h2>需要改进的句子（示范说法由 AI 生成，仅供参考）</h2>
<table><tr><th>时间</th><th>原句</th><th>问题</th><th>示范说法</th></tr>{prob or '<tr><td colspan="4">无</td></tr>'}</table>
<h2>追溯信息</h2>
<p>评分标准 {_e(t['rubric_version'])}（{_e(t['rubric_status'])}），配置哈希 {_e(t['config_hash'])}<br>
检测配置 {_e(t['detector_config_version'])}（{_e(t['detector_config_status'])}）<br>模型版本：{_e(manifest)}</p>
</body></html>"""


def chromium_path() -> str:
    """优先用无头专用版（chrome-headless-shell，启动快、不联网）；也可用 APP_CHROMIUM 指定。"""
    import glob

    cands = [os.environ.get("APP_CHROMIUM"), shutil.which("chrome-headless-shell"),
             *sorted(glob.glob("/opt/pw-browsers/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")),
             shutil.which("chromium"), shutil.which("chromium-browser"), "/opt/pw-browsers/chromium", shutil.which("google-chrome")]
    for c in cands:
        if c and Path(c).exists():
            return c
    raise PdfError("服务器没有安装 Chromium，无法导出 PDF（可设置 APP_CHROMIUM 指定路径）")


def html_to_pdf(doc: str) -> bytes:
    exe = chromium_path()
    with tempfile.TemporaryDirectory(prefix="audition-pdf-") as tmp:
        src, out = Path(tmp) / "r.html", Path(tmp) / "r.pdf"
        src.write_text(doc, "utf-8")
        args = [exe, "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={tmp}/profile",
                # 完整版 Chrome 启动时会联网（更新、同步等），在内网服务器上会卡住，一律关掉
                "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run",
                "--disable-default-apps", "--metrics-recording-only"]
        if "headless-shell" not in exe:
            args.append("--headless=new")
        try:
            r = subprocess.run([*args, f"--print-to-pdf={out}", src.as_uri()], capture_output=True, timeout=90)
        except subprocess.TimeoutExpired as exc:
            raise PdfError("PDF 生成超时") from exc
        if r.returncode != 0 or not out.exists():
            raise PdfError(f"PDF 生成失败：{r.stderr.decode(errors='ignore')[-300:]}")
        return out.read_bytes()


def _safe(v):
    """防 Excel 公式注入：以 = + - @ 或制表、回车开头的文字前面加单引号，按文本显示，不会被当成公式执行。"""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def ranking_xlsx(rows: list[dict], items_by_report: dict[str, list[dict]], date_desc: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "排名"
    head = ["排名", "候选人", "提交时间", "适用达标线", "结论", "原因", "总档位", "达标线（小于）", "临界", "非正式",
            "人设塑造", "销售循环", "表达逻辑", "其他", "低置信条目数", "报告版本", "报告编号"]
    ws.append([f"试镜排名（{date_desc}）"])
    ws.append(head)
    for c in ws[2]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDEBF7")
    for r in rows:
        ws.append([r["rank"], _safe(r["candidate_name"]), _cn(r["submitted_at"]) if r["submitted_at"] else "",
                   AUDIENCE_ZH.get(r["audience"], r["audience"]), LABEL_ZH[r["label"]], _safe(r["reason"]), r["total_grade"], r["threshold"],
                   "是" if r["critical"] else "", "是" if r["informal"] else "",
                   *[f"{r['dimension_scores'][k]} 分 / {r['dimension_grades'][k]} 档" for k in DIM_ORDER],
                   r["low_confidence_count"], r["revision"], str(r["id"])])
    for col, w in zip("ABCDEFGHIJKLMNOPQ", [6, 12, 17, 16, 8, 50, 8, 12, 6, 8, 16, 16, 16, 16, 12, 8, 38]):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=3):
        row[5].alignment = Alignment(wrap_text=True, vertical="top")
    ws2 = wb.create_sheet("条目明细")
    first = next(iter(items_by_report.values()), [])
    codes = [i["item_id"] for i in first]
    ws2.append(["排名", "候选人", *[DIM_ZH.get(i["dimension"], i["dimension"]) + "·" + i["name"] for i in first]])  # 按评分表位置称呼
    for c in ws2[1]:
        c.font = Font(bold=True)
    for r in rows:
        its = {i["item_id"]: i for i in items_by_report.get(str(r["id"]), [])}
        ws2.append([r["rank"], _safe(r["candidate_name"]), *[("不适用" if its[c]["status"] == "not_applicable" else its[c]["score"]) if c in its else "" for c in codes]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
