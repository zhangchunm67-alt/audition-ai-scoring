"""盲打分结果与人工金标准对比。

用法：.venv/bin/python scripts/compare_gold.py --results var/blind --gold gold.csv
gold.csv 列：视频,条目,人工分（视频名与说明文件里的 name 一致；模板见 docs/blind-test/gold.example.csv）。
输出：条目一致率（相差不超过满分 10%）、平均绝对误差、AI 未评条数、维度档位一致率（相差 ≤ 1 档）、全部分歧明细。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from app.pipeline.offline import compare_with_gold  # noqa: E402
from scoring import load_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="盲打分与金标准对比")
    ap.add_argument("--results", default="var/blind")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--rubric", default=str(ROOT / "config/rubric/rubric-v0.2.yaml"))
    ap.add_argument("--out", help="对比结果 JSON 输出路径")
    args = ap.parse_args()
    cfg = load_config(args.rubric)
    gold: dict[str, dict[str, float]] = {}
    with open(args.gold, encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row.get("人工分", "").strip():
                gold.setdefault(row["视频"].strip(), {})[row["条目"].strip()] = float(row["人工分"])
    results = [json.loads(p.read_text("utf-8")) for p in sorted(Path(args.results).glob("*/result.json"))]
    rep = compare_with_gold(results, gold, cfg)
    print("| 条目 | 样本数 | 一致率 | 平均绝对误差 | AI 未评 |\n|---|---|---|---|---|")
    for iid, st in rep["items"].items():
        print(f"| {iid} | {st['n']} | {st['agree_rate']} | {st['mae'] if st['mae'] is not None else '—'} | {st['ai_missing']} |")
    print(f"\n维度档位一致率（相差 ≤ 1 档）：{rep['dimension_agree_rate']}（只统计 AI 和人工都完整出分的维度）")
    print("\n分歧明细：")
    for r in rep["rows"]:
        if not r["agree"]:
            ai = "未评" if r["ai"] is None else f"{r['ai']:g}"
            print(f"- {r['video']} {r['item']}：人工 {r['gold']:g}，AI {ai}（满分 {r['max']}）")
    if args.out:
        Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
