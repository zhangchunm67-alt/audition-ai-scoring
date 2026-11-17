import type { ItemResult } from "../api/report";

export const ABILITY_IDS = ["P", "S", "L", "O"] as const;
export const ABILITY_NAMES: Record<string, string> = { P: "人设塑造", S: "销售循环", L: "表达逻辑", O: "其他能力" };

/** 比较得分率；缺证据、不适用和未计分均不冒充低分，所有并列项保留。 */
export function weakestItems(items: ItemResult[], dimension: string): ItemResult[] {
  const eligible = items.filter(i => i.dimension === dimension && i.status === "scored" && i.score != null && Number.isFinite(i.score) && i.max > 0);
  if (!eligible.length) return [];
  const rate = Math.min(...eligible.map(i => i.score! / i.max));
  // 全满分时没有短板，不能为了标记“最差”而制造问题。
  return rate >= 1 ? [] : eligible.filter(i => Math.abs(i.score! / i.max - rate) < 1e-9);
}

/** 档位 1–8，总档位 4–32。方向统一为越靠外越好；仅转换图形尺度，不产生新评分。 */
export function gradeRadius(grade: number | null | undefined, total = false): number | null {
  const min = total ? 4 : 1, max = total ? 32 : 8;
  if (grade == null || !Number.isFinite(grade) || grade < min || grade > max) return null;
  return (9 - (total ? grade / 4 : grade)) / 8;
}
