"""盲打分结果与人工金标准对比。

用法：.venv/bin/python scripts/compare_gold.py --results var/blind --gold gold.csv
gold.csv 列：视频,条目,人工分（视频名与说明文件里的 name 一致；模板见 docs/blind-test/gold.example.csv）。
可以直接用 Excel 另存的 CSV（UTF-8 或 GBK，逗号 / Tab / 分号分隔）；条目写编号（P3）或评分表名称（人设塑造·普通话标准）都行。
输出：条目一致率（相差不超过满分 10%）、平均绝对误差、AI 未评条数、维度档位一致率（相差 ≤ 1 档）、
结论一致率（上线门槛 ≥ 95%）、全部分歧明细。表格有问题时逐行报出，不出结果。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from app.pipeline.offline import compare_with_gold, load_gold_csv  # noqa: E402
from scoring import load_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="盲打分与金标准对比")
    ap.add_argument("--results", default="var/blind")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--rubric", default=str(ROOT / "config/rubric/rubric-v0.2.yaml"))
    ap.add_argument("--out", help="对比结果 JSON 输出路径")
    args = ap.parse_args()
    cfg = load_config(args.rubric)
    try:
        gold, _ = load_gold_csv(args.gold, cfg)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    results = [json.loads(p.read_text("utf-8")) for p in sorted(Path(args.results).glob("*/result.json"))]
    if not results:
        print(f"{args.results} 下没有盲打分结果（*/result.json）", file=sys.stderr)
        return 2
    rep = compare_with_gold(results, gold, cfg)
    for w in rep["warnings"]:
        print("注意：" + w, file=sys.stderr)
    if not rep["rows"]:
        print("金标准和盲打分结果没有对得上的视频，请检查视频名", file=sys.stderr)
        return 2
    names = {it.id: f"{d.name}·{it.name}" for d, it in cfg.items()}
    print("| 条目 | 样本数 | 一致率 | 平均绝对误差 | AI 未评 |\n|---|---|---|---|---|")
    for iid, st in rep["items"].items():
        print(f"| {names.get(iid, iid)} | {st['n']} | {st['agree_rate']} | {st['mae'] if st['mae'] is not None else '—'} | {st['ai_missing']} |")
    print(f"\n维度档位一致率（相差 ≤ 1 档）：{rep['dimension_agree_rate']}（只统计 AI 和人工都完整出分的维度）")
    print(f"结论一致率（是否达标）：{rep['conclusion_agree_rate']}（人工各条目齐全的视频；AI 没出总档位的记为不一致）")
    print("\n分歧明细：")
    for r in rep["rows"]:
        if not r["agree"]:
            ai = "未评" if r["ai"] is None else f"{r['ai']:g}"
            print(f"- {r['video']} {names.get(r['item'], r['item'])}：人工 {r['gold']:g}，AI {ai}（满分 {r['max']}）")
    if args.out:
        Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
