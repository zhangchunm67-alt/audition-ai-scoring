import { Button, Dropdown, Menu, Spin, Tabs } from "antd";
import { useState, type ReactNode } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "./auth";
import { ROLE_ZH } from "./components/hooks";
import { IconBook, IconChart, IconDown, IconKey, IconLogout, IconSettings, IconSliders, IconVideo } from "./components/icons";
import { BRAND, BrandMark, EmptyState } from "./components/ui";
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
import { ChangePasswordModal, ForcePasswordChange } from "./pages/ChangePassword";
import ProductDetail from "./pages/ProductDetail";
import ProductAuditionSettings from "./pages/ProductAuditionSettings";
import Products from "./pages/Products";
import ReadingScripts from "./pages/ReadingScripts";
import Redlines from "./pages/Redlines";
import RubricDetail from "./pages/RubricDetail";
import Rubrics from "./pages/Rubrics";
import SheetDetail from "./pages/SheetDetail";
import Sheets from "./pages/Sheets";
import Users from "./pages/Users";

type NavPage = { key: string; label: string; perm: string };
type NavSection = { key: string; label: string; icon: ReactNode; pages: NavPage[] };

const SECTIONS: NavSection[] = [
  {
    key: "auditions", label: "试镜管理", icon: <IconVideo />, pages: [
      { key: "/recordings", label: "试镜录像", perm: "report.read_all" },
      { key: "/candidates", label: "候选人", perm: "report.read_all" },
      { key: "/sheets", label: "试镜题单", perm: "sheet.read" },
    ],
  },
  {
    key: "reports", label: "评分报告", icon: <IconChart />, pages: [
      { key: "/reports", label: "报告与排名", perm: "report.read_all" },
      { key: "/reports", label: "我的试镜记录", perm: "report.read_own" },
      { key: "/dashboard", label: "看板", perm: "dashboard.read" },
    ],
  },
  {
    key: "materials", label: "培训资料", icon: <IconBook />, pages: [
      { key: "/rubrics", label: "评分标准", perm: "config.read" },
      { key: "/products", label: "产品资料", perm: "config.read" },
      { key: "/reading-scripts", label: "朗读稿", perm: "config.read" },
      { key: "/redlines", label: "红线词表", perm: "redline.read" },
    ],
  },
  {
    key: "calibration", label: "评分校准", icon: <IconSliders />, pages: [
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
  const [changingPassword, setChangingPassword] = useState(false);
  if (loading) return <div style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}><Spin size="large" /></div>;
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
  // 栏目内页签：所在栏目有多个页面时显示；系统管理的两个页面同理。
  const tabPages = activeSection ? activeSection.pages : activeSystemPage ? systemPages : [];
  const role = ROLE_ZH[me.role] ?? me.role;
  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand" aria-label={`${BRAND.name}首页`}>
            <BrandMark />
            <span className="brand-text">
              <div className="brand-name">{BRAND.name}</div>
              <div className="brand-sub">{BRAND.sub}</div>
            </span>
          </Link>
          <Menu
            aria-label="主要栏目"
            className="topnav"
            mode="horizontal"
            theme="dark"
            disabledOverflow
            selectedKeys={activeSection ? [activeSection.key] : []}
            items={sections.map(({ key, label, icon }) => ({ key, label, icon }))}
            onClick={({ key }) => {
              const section = sections.find((item) => item.key === key);
              if (section) nav(section.pages[0].key);
            }}
          />
          <div className="topbar-right">
            {systemPages.length > 0 && (
              <Dropdown trigger={["click"]} placement="bottomRight" menu={{
                items: systemPages,
                selectedKeys: activeSystemPage ? [activeSystemPage.key] : [],
                onClick: ({ key }) => nav(key),
              }}>
                <Button className={`topbar-btn${activeSystemPage ? " is-active" : ""}`} icon={<IconSettings />}>系统管理</Button>
              </Dropdown>
            )}
            <Dropdown trigger={["click"]} placement="bottomRight" menu={{
              items: [
                { key: "who", type: "group", label: `${me.display_name} · ${role}` },
                { key: "password", icon: <IconKey />, label: "改密码" },
                { type: "divider" },
                { key: "logout", icon: <IconLogout />, label: "退出登录" },
              ],
              onClick: ({ key }) => (key === "logout" ? void logout() : setChangingPassword(true)),
            }}>
              <Button className="user-chip" aria-label={`账号菜单：${me.display_name}（${role}）`}>
                <span className="user-avatar" aria-hidden>{me.display_name.trim().slice(0, 1)}</span>
                <span className="user-text" aria-hidden>
                  <div className="user-name">{me.display_name}</div>
                  <div className="user-role">{role}</div>
                </span>
                <IconDown />
              </Button>
            </Dropdown>
          </div>
        </div>
      </header>
      {tabPages.length > 1 && (
        <nav className="subnav" aria-label="栏目内页面">
          <div className="subnav-inner">
            <Tabs
              activeKey={(activePage ?? activeSystemPage)?.key}
              items={tabPages.map(({ key, label }) => ({ key, label }))}
              onTabClick={(key) => nav(key)}
            />
          </div>
        </nav>
      )}
      <main className="page">
        <Routes>
          <Route path="/" element={home ? <Navigate to={home} replace /> : <EmptyState title="暂无可访问的栏目"><p>请联系管理员为账号分配角色。</p></EmptyState>} />
          <Route path="/rubrics" element={<Rubrics />} />
          <Route path="/rubrics/:id" element={<RubricDetail />} />
          <Route path="/products" element={<Products />} />
          <Route path="/products/:id" element={<ProductDetail />} />
          <Route path="/sheets/products/:id/settings" element={<ProductAuditionSettings />} />
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
          <Route path="*" element={<EmptyState title="页面不存在"><p>地址可能已变更。</p><Button onClick={() => nav("/")}>回到首页</Button></EmptyState>} />
        </Routes>
      </main>
      <ChangePasswordModal open={changingPassword} onClose={() => setChangingPassword(false)} />
    </div>
  );
}
