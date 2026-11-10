import { Button, Dropdown, Layout, Menu, Space, Spin, Tabs, Typography } from "antd";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "./auth";
import { ROLE_ZH } from "./components/hooks";
import AuditLogs from "./pages/AuditLogs";
import Calibration, { CalibrationSet } from "./pages/Calibration";
import CalibrationTask, { MyTasks } from "./pages/CalibrationTask";
import Candidates from "./pages/Candidates";
import Dashboard from "./pages/Dashboard";
import NewRecording from "./pages/NewRecording";
import RecordingDetail from "./pages/RecordingDetail";
import ReportDetail from "./pages/ReportDetail";
import Reports from "./pages/Reports";
import Recordings from "./pages/Recordings";
import SheetPrint from "./pages/SheetPrint";
import Login from "./pages/Login";
import { ChangePasswordButton, ForcePasswordChange } from "./pages/ChangePassword";
import ProductDetail from "./pages/ProductDetail";
import Products from "./pages/Products";
import ReadingScripts from "./pages/ReadingScripts";
import Redlines from "./pages/Redlines";
import RubricDetail from "./pages/RubricDetail";
import Rubrics from "./pages/Rubrics";
import SheetDetail from "./pages/SheetDetail";
import Sheets from "./pages/Sheets";
import Users from "./pages/Users";

type NavPage = { key: string; label: string; perm: string };
type NavSection = { key: string; label: string; pages: NavPage[] };

const SECTIONS: NavSection[] = [
  {
    key: "auditions", label: "试镜管理", pages: [
      { key: "/recordings", label: "试镜录像", perm: "report.read_all" },
      { key: "/candidates", label: "候选人", perm: "report.read_all" },
      { key: "/sheets", label: "试镜题单", perm: "sheet.read" },
    ],
  },
  {
    key: "reports", label: "评分报告", pages: [
      { key: "/reports", label: "报告与排名", perm: "report.read_all" },
      { key: "/reports", label: "我的试镜记录", perm: "report.read_own" },
      { key: "/dashboard", label: "看板", perm: "dashboard.read" },
    ],
  },
  {
    key: "materials", label: "培训资料", pages: [
      { key: "/rubrics", label: "评分标准", perm: "config.read" },
      { key: "/products", label: "产品与题库", perm: "config.read" },
      { key: "/reading-scripts", label: "朗读稿", perm: "config.read" },
      { key: "/redlines", label: "红线词表", perm: "redline.read" },
    ],
  },
  {
    key: "calibration", label: "评分校准", pages: [
      { key: "/calibration/sets", label: "金标准与校准", perm: "calibration.manage" },
      { key: "/calibration/tasks", label: "我的校准任务", perm: "calibration.score" },
    ],
  },
];

const SYSTEM_PAGES: NavPage[] = [
  { key: "/users", label: "账号管理", perm: "users.manage" },
  { key: "/audit", label: "审计日志", perm: "audit.read" },
];

const matchesPage = (pathname: string, key: string) => pathname === key || pathname.startsWith(`${key}/`);

export default function App() {
  const { me, loading, logout, can } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  if (loading) return <Spin style={{ margin: 80 }} />;
  if (!me) return <Login />;
  if (me.must_change_password) return <ForcePasswordChange />;
  if (/^\/sheets\/[^/]+\/print$/.test(loc.pathname)) {
    return (
      <Routes>
        <Route path="/sheets/:id/print" element={<SheetPrint />} />
      </Routes>
    );
  }
  const sections = SECTIONS.map((section) => ({
    ...section,
    label: section.key === "reports" && can("report.read_own") && !can("report.read_all")
      ? "我的试镜记录" : section.label,
    pages: section.pages.filter((page) => can(page.perm)),
  })).filter((section) => section.pages.length > 0);
  const systemPages = SYSTEM_PAGES.filter((page) => can(page.perm));
  const activeSection = sections.find((section) => section.pages.some((page) => matchesPage(loc.pathname, page.key)));
  const activePage = activeSection?.pages.find((page) => matchesPage(loc.pathname, page.key));
  const activeSystemPage = systemPages.find((page) => matchesPage(loc.pathname, page.key));
  const home = can("calibration.score") ? "/calibration/tasks" : sections[0]?.pages[0].key;
  const items = sections.map(({ key, label }) => ({ key, label }));
  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Sider width={200} theme="light">
        <Typography.Title level={5} style={{ padding: "16px 20px", margin: 0 }}>
          试镜评分后台
        </Typography.Title>
        <Menu
          aria-label="主要栏目"
          mode="inline"
          selectedKeys={activeSection ? [activeSection.key] : []}
          items={items}
          onClick={({ key }) => {
            const section = sections.find((item) => item.key === key);
            if (section) nav(section.pages[0].key);
          }}
        />
      </Layout.Sider>
      <Layout>
        <Layout.Header style={{ background: "#fff", display: "flex", alignItems: "center", justifyContent: "space-between", paddingInline: 24 }}>
          <Typography.Text strong>{activeSection?.label ?? activeSystemPage?.label}</Typography.Text>
          <Space size="middle">
            {systemPages.length > 0 && (
              <Dropdown trigger={["click"]} menu={{
                items: systemPages,
                selectedKeys: activeSystemPage ? [activeSystemPage.key] : [],
                onClick: ({ key }) => nav(key),
              }}>
                <Button type={activeSystemPage ? "primary" : "text"}>系统管理</Button>
              </Dropdown>
            )}
            <span>
              {me.display_name}（{ROLE_ZH[me.role] ?? me.role}）
            </span>
            <ChangePasswordButton />
            <Button onClick={logout}>退出</Button>
          </Space>
        </Layout.Header>
        <Layout.Content style={{ padding: 24 }}>
          {activeSection && activeSection.pages.length > 1 && (
            <Tabs
              activeKey={activePage?.key}
              items={activeSection.pages.map(({ key, label }) => ({ key, label }))}
              onTabClick={(key) => nav(key)}
            />
          )}
          <Routes>
            <Route path="/" element={home ? <Navigate to={home} replace /> : <Typography.Text>暂无可访问的栏目</Typography.Text>} />
            <Route path="/rubrics" element={<Rubrics />} />
            <Route path="/rubrics/:id" element={<RubricDetail />} />
            <Route path="/products" element={<Products />} />
            <Route path="/products/:id" element={<ProductDetail />} />
            <Route path="/reading-scripts" element={<ReadingScripts />} />
            <Route path="/redlines" element={<Redlines />} />
            <Route path="/sheets" element={<Sheets />} />
            <Route path="/sheets/:id" element={<SheetDetail />} />
            <Route path="/candidates" element={<Candidates />} />
            <Route path="/recordings" element={<Recordings />} />
            <Route path="/recordings/new" element={<NewRecording />} />
            <Route path="/recordings/:id" element={<RecordingDetail />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/reports/:id" element={<ReportDetail />} />
            <Route path="/calibration/sets" element={<Calibration />} />
            <Route path="/calibration/sets/:id" element={<CalibrationSet />} />
            <Route path="/calibration/tasks" element={<MyTasks />} />
            <Route path="/calibration/tasks/:id" element={<CalibrationTask />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/users" element={<Users />} />
            <Route path="/audit" element={<AuditLogs />} />
            <Route path="*" element={<Typography.Text>页面不存在</Typography.Text>} />
          </Routes>
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
