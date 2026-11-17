import { useEffect, useRef } from "react";
import { ABILITY_IDS, ABILITY_NAMES, gradeRadius } from "./reportAbilities";

type Props = { total: number | null; grades: Record<string, number | null | undefined>; compact?: boolean };

/** 数据图形用 Canvas 绘制；原始档位通过文字和无障碍描述保留。 */
export default function AbilityRadar({ total, grades, compact = false }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const axes = [{ label: "总档位", grade: total, value: gradeRadius(total, true) }, ...ABILITY_IDS.map(id => ({ label: ABILITY_NAMES[id], grade: grades[id], value: gradeRadius(grades[id]) }))];
  const description = axes.map(a => `${a.label} ${a.grade ?? "未评分"}${a.grade != null ? " 档" : ""}`).join("，");
  const size = compact ? 96 : 300;
  const values = axes.map(a => a.value);
  useEffect(() => {
    const canvas = ref.current, ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = size * ratio; canvas.height = size * ratio;
    ctx.scale(ratio, ratio); ctx.clearRect(0, 0, size, size);
    const cx = size / 2, cy = compact ? size / 2 : size / 2 + 5, radius = compact ? 34 : 76;
    const point = (i: number, fraction: number): [number, number] => [cx + Math.cos(-Math.PI / 2 + i * 2 * Math.PI / 5) * radius * fraction, cy + Math.sin(-Math.PI / 2 + i * 2 * Math.PI / 5) * radius * fraction];
    const polygon = (fractions: number[]) => { ctx.beginPath(); fractions.forEach((v, i) => { const [x, y] = point(i, v); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); }); ctx.closePath(); };
    polygon(Array(5).fill(1)); ctx.fillStyle = "#f7f9ff"; ctx.fill();
    for (const f of [.25, .5, .75, 1]) { polygon(Array(5).fill(f)); ctx.strokeStyle = "#dde5f2"; ctx.lineWidth = 1; ctx.stroke(); }
    for (let i = 0; i < 5; i++) { const [x, y] = point(i, 1); ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.strokeStyle = "#e5ebf4"; ctx.stroke(); }
    // 缺轴时保留空网格，不将缺数据画成 0 分。
    if (values.every(v => v != null)) {
      polygon(values as number[]); ctx.fillStyle = "#2454d92b"; ctx.fill(); ctx.strokeStyle = "#2454d9"; ctx.lineWidth = compact ? 1.6 : 2; ctx.stroke();
      values.forEach((v, i) => { const [x, y] = point(i, v!); ctx.beginPath(); ctx.arc(x, y, compact ? 1.7 : 3, 0, 2 * Math.PI); ctx.fillStyle = "#2454d9"; ctx.fill(); });
    }
    if (!compact) axes.forEach((axis, i) => {
      const [x, y] = point(i, 1.32); ctx.textAlign = i === 0 ? "center" : i <= 2 ? "left" : "right";
      ctx.font = '12px -apple-system, "PingFang SC", sans-serif'; ctx.fillStyle = "#697790"; ctx.fillText(axis.label, x, y - 4);
      ctx.font = '600 13px -apple-system, "PingFang SC", sans-serif'; ctx.fillStyle = "#203352"; ctx.fillText(axis.grade != null ? `${axis.grade} 档` : "未评分", x, y + 15);
    });
  }, [size, compact, total, ...ABILITY_IDS.map(id => grades[id])]);
  return <figure className={`ability-radar ${compact ? "compact" : ""}`} title={`${description}。档位越低越好，图形越靠外越好。`}>
    <canvas ref={ref} style={{ width: size, height: size }} role="img" aria-label={`五维能力图：${description}。越靠外越好。缺少数据时不绘制能力区域。`} />
    {!compact && <figcaption>总档位 4–32 · 单类 1–8 档<br />档位越低越好，图形越靠外越好（总轴按总档位÷4换算）</figcaption>}
  </figure>;
}
