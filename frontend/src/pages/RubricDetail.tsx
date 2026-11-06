import { Alert, Button, Descriptions, List, Popconfirm, Space, Table, Tabs, Tag, Typography } from "antd";
import { useParams } from "react-router-dom";
import { post, type S } from "../api/client";
import { useAuth } from "../auth";
import { AUDIENCE_ZH, STATUS_ZH, useAction, useFetch } from "../components/hooks";

export default function RubricDetail() {
  const { id } = useParams();
  const { data, reload } = useFetch<S<"RubricDetail">>(`/rubrics/${id}`);
  const { can } = useAuth();
  const act = useAction();
  if (!data) return null;
  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          {data.version}
        </Typography.Title>
        <Tag>{STATUS_ZH[data.status]}</Tag>
        {can("config.write") && data.status === "draft" && (
          <Button type="primary" disabled={data.blockers.length > 0} onClick={async () => (await act(() => post(`/rubrics/${id}/publish`), "已发布")) && reload()}>
            发布
          </Button>
        )}
        {can("config.write") && data.status !== "retired" && (
          <Popconfirm title="停用后不能再用于新题单，确定？" onConfirm={async () => (await act(() => post(`/rubrics/${id}/retire`), "已停用")) && reload()}>
            <Button danger>停用</Button>
          </Popconfirm>
        )}
      </Space>
      <Descriptions size="small" column={2} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="配置哈希">
          <Typography.Text code copyable>
            {data.config_hash}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="产品讲解计分">{data.checklist_max == null ? "按固定话术完成准确度（0–50）" : `旧版：卖点卡要点满分 ${data.checklist_max} + 结构`}</Descriptions.Item>
        <Descriptions.Item label="达标线">
          {Object.entries(data.thresholds).map(([k, v]) => (
            <Tag key={k}>
              {AUDIENCE_ZH[k] ?? k} &lt; {v}
            </Tag>
          ))}
        </Descriptions.Item>
      </Descriptions>
      {data.blockers.length > 0 && (
        <Alert
          type="warning"
          style={{ marginBottom: 16 }}
          message={`有 ${data.blockers.length} 项待确认规则或测试占位值，不能发布`}
          description={<List size="small" dataSource={data.blockers} renderItem={(b) => <List.Item style={{ padding: "2px 0" }}>{b}</List.Item>} />}
        />
      )}
      <Tabs
        items={[
          {
            key: "items",
            label: "条目（23 条）",
            children: (
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={data.items}
                columns={[
                  { title: "维度", dataIndex: "dimension" },
                  { title: "编号", dataIndex: "id" },
                  { title: "条目", dataIndex: "name" },
                  { title: "计分类型", dataIndex: "type" },
                  { title: "满分", dataIndex: "max" },
                ]}
              />
            ),
          },
          { key: "yaml", label: "YAML 原文", children: <pre style={{ background: "#fafafa", padding: 16, maxHeight: 600, overflow: "auto" }}>{data.yaml_text}</pre> },
        ]}
      />
    </>
  );
}
