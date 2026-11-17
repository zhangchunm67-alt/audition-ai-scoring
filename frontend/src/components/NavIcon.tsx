type IconName = "auditions" | "reports" | "materials" | "calibration" | "plus" | "menu";

const paths: Record<IconName, string> = {
  auditions: "M4 5h11a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Zm13 5 5-3v10l-5-3M7 9l5 3-5 3V9Z",
  reports: "M5 3h10l4 4v14H5V3Zm9 0v5h5M9 17v-4m3 4v-6m3 6v-3",
  materials: "M3 4h7l2 2 2-2h7v16h-7l-2 1-2-1H3V4Zm9 2v15M6 8h3m-3 4h3m6-4h3m-3 4h3",
  calibration: "M4 7h16M4 17h16M9 4v6m6 4v6",
  plus: "M12 5v14M5 12h14",
  menu: "M4 6h16M4 12h16M4 18h16",
};

export default function NavIcon({ name }: { name: IconName }) {
  return <svg className="nav-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={paths[name]} /></svg>;
}
