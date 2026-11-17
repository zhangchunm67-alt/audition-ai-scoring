import { Button, Progress, Tag } from "antd";
import type { ReportDetail } from "../api/report";
import AbilityRadar from "./AbilityRadar";
import CandidateIdentity from "./CandidateIdentity";
import { ABILITY_IDS, ABILITY_NAMES, weakestItems } from "./reportAbilities";

type Props = { report: ReportDetail; onInspect: (ids: string[]) => void };
export default function ReportOverview({ report: d, onInspect }: Props) {
  const dims = Object.fromEntries(d.result.dimensions.map(x => [x.id, x]));
  const grades = Object.fromEntries(d.result.dimensions.map(x => [x.id, x.grade]));
  return <section className="report-overview" aria-label="能力评估总览">
    <div className="report-profile">
      <CandidateIdentity name={d.candidate_name} phone={d.candidate_phone_masked} videoAssetId={d.candidate_video_asset_id} large />
      <div className="report-profile-meta"><span>{d.product_name}</span><span>第 {d.revision} 版 · {d.mode === "live" ? "录播" : "试镜"}评估</span></div>
    </div>
    <div className="report-composite">
      <div className="report-total">
        <span className="report-eyebrow">综合评分 / 总档位</span>
        <div className="report-grade"><strong>{d.result.total_grade ?? "—"}</strong><span>档</span></div>
        <div className="report-threshold">达标要求：总档位 &lt; {d.result.threshold}</div>
        <p>四类能力档位相加，越低越好。<br />本页展示第 {d.display_round} 轮评分结果。</p>
        <Tag color="blue">五维视图：总档位＋四类能力</Tag>
      </div>
      <AbilityRadar total={d.result.total_grade} grades={grades} />
    </div>
    <div className="report-ability-heading"><h2>四类能力与优先改进项</h2><span>按子项得分率比较，并列最弱全部标出</span></div>
    <div className="report-ability-grid">
      {ABILITY_IDS.map(id => {
        const dim = dims[id], weak = weakestItems(d.result.items, id);
        const comparable = d.result.items.filter(i => i.dimension === id && i.status === "scored" && i.score != null && i.max > 0);
        const missing = d.result.items.filter(i => i.dimension === id && i.status !== "scored" && i.status !== "not_applicable");
        return <article className={`report-ability-card ${weak.length ? "has-weakness" : ""}`} key={id}>
          <div className="ability-card-title"><h3>{dim?.name ?? ABILITY_NAMES[id]}</h3><span>{dim?.grade != null ? `${dim.grade} 档` : "未评分"}</span></div>
          <div className="ability-card-score"><strong>{dim?.score ?? "—"}</strong><span>/ 100 分</span></div>
          <Progress percent={dim?.score ?? 0} showInfo={false} strokeColor="#2454d9" size="small" />
          <div className="ability-weakness">
            {weak.length ? <><span className="weakness-label">优先改进{weak.length > 1 ? " · 并列最弱" : " · 最弱项"}</span>
              {weak.map(item => <Button type="link" key={item.item_id} onClick={() => onInspect([item.item_id])} className="weakness-link"><span>{item.name}</span><strong>{item.score} / {item.max}</strong></Button>)}
              {weak.some(i => i.low_confidence) && <span className="weakness-uncertain">含低置信结果，请核对证据</span>}
            </> : <span className="ability-no-weakness">{comparable.length ? "已评分子项均为满分" : "暂无已评分子项"}</span>}
            {missing.length > 0 && <span className="weakness-uncertain">另有 {missing.length} 项待评分或缺证据，未参与比较</span>}
          </div>
        </article>;
      })}
    </div>
  </section>;
}
