import { Alert, Button, List, Popconfirm, Table, Tabs, Tag, Typography } from "antd";
import { useParams } from "react-router-dom";
import { post, type S } from "../api/client";
import { useAuth } from "../auth";
import { AUDIENCE_ZH, useAction, useFetch } from "../components/hooks";
import { ConfigStatus, MetaGrid, PageHeader } from "../components/ui";

export default function RubricDetail() {
  const { id } = useParams();
  const { data, reload } = useFetch<S<"RubricDetail">>(`/rubrics/${id}`);
  const { can } = useAuth();
  const act = useAction();
  if (!data) return null;
  return (
    <>
      <PageHeader
        back={{ to: "/rubrics", label: "评分标准" }}
        title={<span className="mono">{data.version}</span>}
        tags={<ConfigStatus status={data.status} />}
        actions={<>
          {can("config.write") && data.status !== "retired" && (
            <Popconfirm title="停用后不能再用于新题单，确定？" onConfirm={async () => (await act(() => post(`/rubrics/${id}/retire`), "已停用")) && reload()}>
              <Button danger>停用</Button>
            </Popconfirm>
          )}
          {can("config.write") && data.status === "draft" && (
            <Button type="primary" disabled={data.blockers.length > 0} onClick={async () => (await act(() => post(`/rubrics/${id}/publish`), "已发布")) && reload()}>
              发布
            </Button>
          )}
        </>}
      />
      <MetaGrid columns={3} style={{ marginBottom: 16 }} items={[
        { label: "产品讲解计分", value: data.checklist_max == null ? "按固定话术完成准确度（0–50）" : `旧版：卖点卡要点满分 ${data.checklist_max} + 结构` },
        { label: "达标线", value: Object.entries(data.thresholds).map(([k, v]) => (
          <Tag key={k}>
            {AUDIENCE_ZH[k] ?? k} &lt; {v}
          </Tag>
        )) },
        { label: "配置哈希", value: <Typography.Text copyable className="mono" style={{ fontSize: 12.5 }}>{data.config_hash}</Typography.Text> },
      ]} />
      <div className="stack-sm" style={{ marginBottom: 16 }}>
        {!data.processing_supported && (
          <Alert type="warning" showIcon message="此版本与当前检测器不兼容，仅供历史追溯。新评分请导入并选择现行配置。"
            description={data.processing_blockers.join("、")} />
        )}
        {data.blockers.length > 0 && (
          <Alert
            type="warning"
            showIcon
            message={`有 ${data.blockers.length} 项待确认规则或测试占位值，不能发布`}
            description={<List size="small" split={false} dataSource={data.blockers} renderItem={(b) => <List.Item style={{ padding: "2px 0" }}>{b}</List.Item>} />}
          />
        )}
      </div>
      <Tabs
        items={[
          {
            key: "items",
            label: `条目（${data.items.length} 条）`,
            children: (
              <Table
                className="table-card"
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={data.items}
                scroll={{ x: "max-content" }}
                columns={[
                  { title: "维度", dataIndex: "dimension", render: (v) => <span className="muted">{v}</span> },
                  { title: "编号", dataIndex: "id", render: (v) => <span className="item-code">{v}</span> },
                  { title: "条目", dataIndex: "name", render: (v) => <span className="cell-main">{v}</span> },
                  { title: "计分类型", dataIndex: "type", render: (v) => <span className="mono muted">{v}</span> },
                  { title: "满分", dataIndex: "max", align: "right", render: (v) => <span className="num">{v}</span> },
                ]}
              />
            ),
          },
          { key: "yaml", label: "YAML 原文", children: <pre className="code-block">{data.yaml_text}</pre> },
        ]}
      />
    </>
  );
}
