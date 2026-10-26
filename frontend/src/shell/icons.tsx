// V1-058 R1: the line icons of the mock-up (app.js IC), 24px grid, 1.7px stroke. Always shown
// beside a word, so they are hidden from screen readers.

import type { IconName } from "./navigation";

export type ShellIcon =
  | IconName
  | "menu"
  | "search"
  | "signout"
  | "info"
  | "x"
  | "door"
  | "wrench"
  | "plus"
  | "back"
  | "swap"
  | "alert"
  | "clock"
  | "zap"
  | "drop"
  | "upload"
  | "download"
  | "print"
  | "lock"
  | "forward";

const PATHS: Record<ShellIcon, string[]> = {
  home: ["M3 10.5 12 3l9 7.5", "M5 9.5V21h14V9.5", "M10 21v-6h4v6"],
  payments: [
    "M4.5 6h15a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z",
    "M12 9.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z",
    "M6 9.5v5M18 9.5v5",
  ],
  invoice: [
    "M14 2.5H6.5A1.5 1.5 0 0 0 5 4v16a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 20V7.5z",
    "M14 2.5v5h5",
    "M8.5 13h7M8.5 17h5",
  ],
  meter: ["M12 5a8 8 0 1 1 0 16 8 8 0 0 1 0-16z", "M12 13l3.5-3.5", "M8 18h8"],
  check: ["m5 12.5 4.5 4.5L19 7.5"],
  units: [
    "M6 21V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v17",
    "M3.5 21h17",
    "M9.5 7h1M13.5 7h1M9.5 11h1M13.5 11h1M10.5 21v-4h3v4",
  ],
  customers: [
    "M9 4.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7z",
    "M2.5 20a6.5 6.5 0 0 1 13 0",
    "M16 4.6a3.5 3.5 0 0 1 0 6.8M18 13.6a6.5 6.5 0 0 1 3.5 6.4",
  ],
  calendar: [
    "M5.5 5h13a2 2 0 0 1 2 2v11.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z",
    "M3.5 10h17M8 3v4M16 3v4",
  ],
  lease: ["M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17z", "M14 20h6"],
  list: ["M9 6.5h11M9 12h11M9 17.5h11", "M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01"],
  moveout: [
    "M14 4h4.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H14",
    "M9.5 16.5 5 12l4.5-4.5",
    "M5 12h10",
  ],
  reports: ["M4 20V4", "M4 20h16", "M8.5 16v-5M13 16V8M17.5 16v-3"],
  history: ["M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17z", "M12 7.5V12l3 2"],
  settings: [
    "M4 7h10M18 7h2M4 17h4M12 17h8",
    "M16 5a2 2 0 1 1 0 4 2 2 0 0 1 0-4zM10 15a2 2 0 1 1 0 4 2 2 0 0 1 0-4z",
  ],
  menu: ["M4 7h16M4 12h16M4 17h16"],
  search: ["M11 4.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13z", "m20 20-4.2-4.2"],
  signout: [
    "M10 4H5.5A1.5 1.5 0 0 0 4 5.5v13A1.5 1.5 0 0 0 5.5 20H10",
    "M14.5 16.5 19 12l-4.5-4.5",
    "M19 12H9",
  ],
  info: [
    "M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17z",
    "M12 11v5",
    "M12 8v.1",
  ],
  x: ["M6 6l12 12M18 6 6 18"],
  // V1-058 R2: icons of the Units screens.
  door: [
    "M6 21V4.5A1.5 1.5 0 0 1 7.5 3h9A1.5 1.5 0 0 1 18 4.5V21",
    "M3.5 21h17",
    "M14.5 12h.01",
  ],
  wrench: [
    "M14.7 6.3a4 4 0 0 0-5.4 5.2l-5.8 5.8a1.8 1.8 0 0 0 2.5 2.5l5.8-5.8a4 4 0 0 0 5.2-5.4l-2.6 2.6-2.3-.4-.4-2.3z",
  ],
  plus: ["M12 5v14M5 12h14"],
  back: ["M19 12H5M11 6l-6 6 6 6"],
  swap: ["M4 8h13l-3.5-3.5", "M20 16H7l3.5 3.5"],
  alert: ["M12 4 2.8 19.5h18.4z", "M12 10v4.5", "M12 17.2v.1"],
  clock: ["M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17z", "M12 7.5V12l3 2"],
  zap: ["M13 3 5 13.5h6L10 21l8-10.5h-6z"],
  drop: ["M12 3.5s6 6.6 6 10.5a6 6 0 0 1-12 0c0-3.9 6-10.5 6-10.5z"],
  upload: [
    "M12 15V4",
    "m7.5 8.5 4.5-4.5 4.5 4.5",
    "M4.5 15v3.5A1.5 1.5 0 0 0 6 20h12a1.5 1.5 0 0 0 1.5-1.5V15",
  ],
  download: [
    "M12 4v11",
    "m7.5 10.5 4.5 4.5 4.5-4.5",
    "M4.5 15v3.5A1.5 1.5 0 0 0 6 20h12a1.5 1.5 0 0 0 1.5-1.5V15",
  ],
  print: [
    "M7 9V3.5h10V9",
    "M5 9h14a1.5 1.5 0 0 1 1.5 1.5v5A1.5 1.5 0 0 1 19 17H5a1.5 1.5 0 0 1-1.5-1.5v-5A1.5 1.5 0 0 1 5 9z",
    "M7 14h10v6.5H7z",
  ],
  lock: ["M6 11h12v9.5H6z", "M8.5 11V8a3.5 3.5 0 0 1 7 0v3"],
  forward: ["M5 12h14M13 6l6 6-6 6"],
};

export function Icon({ name, small }: { name: ShellIcon; small?: boolean }) {
  return (
    <svg
      aria-hidden="true"
      className={small === true ? "shell-icon small" : "shell-icon"}
      focusable="false"
      viewBox="0 0 24 24"
    >
      {PATHS[name].map((d) => (
        <path d={d} key={d} />
      ))}
    </svg>
  );
}
