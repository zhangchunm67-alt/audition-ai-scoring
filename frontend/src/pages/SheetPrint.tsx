import { useParams, useSearchParams } from "react-router-dom";
import type { S } from "../api/client";
import { msToClock, useFetch } from "../components/hooks";

type Rules = { version: string; title: string; intro: string; flow: { name: string; time: string; what: string }[]; requirements: string[]; compliance: string[]; privacy: string[] };

const css = `
  .sheet-print { max-width: 760px; margin: 24px auto; padding: 0 16px; font-size: 14px; line-height: 1.7; color: #000; background: #fff; }
  .sheet-print h1 { font-size: 22px; margin: 0 0 4px; } .sheet-print h2 { font-size: 16px; margin: 20px 0 6px; border-bottom: 1px solid #999; }
  .sheet-print table { width: 100%; border-collapse: collapse; } .sheet-print td, .sheet-print th { border: 1px solid #999; padding: 4px 8px; text-align: left; vertical-align: top; }
  .sheet-print .meta { color: #444; } .sheet-print .no-print { margin-bottom: 16px; }
  @media print { .sheet-print .no-print { display: none; } .sheet-print { margin: 0; } }
`;

/** 可打印题单。工作人员联含异议、时间点和知识题；候选人联不含（不提前透露题目），不含任何分值。 */
export default function SheetPrint() {
  const { id } = useParams();
  const [qs, setQs] = useSearchParams();
  const copy = qs.get("copy") === "candidate" ? "candidate" : "staff";
  const { data: s } = useFetch<S<"SheetOut">>(`/sheets/${id}`);
  const { data: rules } = useFetch<Rules>(s ? `/recording-rules/${s.recording_rules_version}` : null);
  const { data: cards } = useFetch<S<"CardOut">[]>(s ? `/products/${s.product_id}/cards` : null);
  if (!s || !rules) return null;
  const card = cards?.find((c) => c.id === s.product_card_id);
  const r = s.draw_rule as Record<string, number>;
  const fill = (t: string) =>
    t.replace("{prep_minutes}", String(Math.round(r.prep_seconds / 60))).replace("{main_end}", msToClock(r.main_seconds * 1000))
      .replace("{question_count}", String(r.question_count)).replace("{question_seconds}", String(r.question_seconds));
  return (
    <div className="sheet-print">
      <style>{css}</style>
      <div className="no-print">
        <button onClick={() => setQs({ copy: "staff" })} disabled={copy === "staff"}>工作人员联</button>{" "}
        <button onClick={() => setQs({ copy: "candidate" })} disabled={copy === "candidate"}>候选人联</button>{" "}
        <button onClick={() => window.print()}>打印</button>
      </div>
      <h1>{rules.title}（{copy === "staff" ? "工作人员联" : "候选人联"}）</h1>
      <div className="meta">题单编号 {s.code} · 产品 {s.product_name} · 录制规则 {rules.version}</div>
      <p>{rules.intro}</p>

      <h2>录制流程</h2>
      <table><tbody>
        {rules.flow.map((f) => <tr key={f.name}><td style={{ width: 150 }}>{f.name}</td><td style={{ width: 170 }}>{fill(f.time)}</td><td>{f.what}</td></tr>)}
      </tbody></table>

      {copy === "staff" ? (
        <>
          <h2>主体段异议（到时间点时提出）</h2>
          <table><tbody>
            {s.objections.map((o, i) => <tr key={o.objection_id}><td style={{ width: 60 }}>{i + 1}</td><td style={{ width: 80 }}>{msToClock(o.at_ms)}</td><td>{o.text}</td></tr>)}
          </tbody></table>
          <h2>知识问答（每题 {r.question_seconds} 秒，逐题提出）</h2>
          <table><tbody>
            {s.questions.map((q, i) => <tr key={q.question_id}><td style={{ width: 60 }}>{i + 1}</td><td>{q.text}</td></tr>)}
          </tbody></table>
        </>
      ) : (
        <p><b>主体段中的观众异议和知识问答题目，录制时逐条给出，不提前提供。</b></p>
      )}

      <h2>朗读稿</h2>
      <p>{s.reading_text}</p>

      {card && (
        <>
          <h2>产品卖点卡（准备时阅读）</h2>
          <p><b>必讲要点：</b>{card.content.checklist.map((p) => p.name + (p.compliance_required ? "（合规必讲）" : "")).join("、")}</p>
          {!!card.content.targeted_points?.length && <p><b>针对性卖点：</b>{card.content.targeted_points.join("；")}</p>}
          {!!card.content.scenarios?.length && <p><b>使用场景：</b>{card.content.scenarios.join("；")}</p>}
          {!!card.content.glossary?.length && <p><b>术语白话：</b>{card.content.glossary.map((g) => `${g.term}——${g.plain}`).join("；")}</p>}
          {!!card.content.key_numbers?.length && <p><b>关键数字：</b>{card.content.key_numbers.map((k) => `${k.name} ${k.value}`).join("；")}</p>}
          {!!card.content.banned_phrases?.length && <p><b>禁用说法：</b>{card.content.banned_phrases.join("；")}</p>}
        </>
      )}

      <h2>录制要求</h2>
      <ul>{rules.requirements.map((x) => <li key={x}>{x}</li>)}</ul>
      <h2>合规要求</h2>
      <ul>{rules.compliance.map((x) => <li key={x}>{x}</li>)}</ul>
      <h2>个人信息与授权</h2>
      <ul>{rules.privacy.map((x) => <li key={x}>{x}</li>)}</ul>
    </div>
  );
}
