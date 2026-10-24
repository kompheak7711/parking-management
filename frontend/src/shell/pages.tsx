// V1-058 R1: the simple pages of the new frame. Home here is a start page only; the eight
// cards and the "What to do" list (DESIGN.md "Home layout") come in step R6.

import type { Language } from "../signInText";
import { Icon } from "./icons";
import { MENU, hashForPage, menuItemName } from "./navigation";

const TEXT = {
  welcome: ["Welcome", "សូមស្វាគមន៍"],
  welcome_name: ["Welcome, {0}", "សូមស្វាគមន៍ {0}"],
  start: [
    "Choose where to start. The full Home page, with the eight cards and the To-do list, comes in a later step.",
    "ជ្រើសរើសកន្លែងចាប់ផ្តើម។ ទំព័រដើមពេញលេញ មានកាត ៨ និងបញ្ជីការងារ នឹងមកនៅជំហានក្រោយ។",
  ],
  coming: [
    "This screen is being rebuilt to the new design. It comes in step {0}.",
    "អេក្រង់នេះកំពុងរៀបចំឡើងវិញតាមការរចនាថ្មី។ វានឹងមកនៅជំហាន {0}។",
  ],
  coming_reports: [
    "Reports come with V1-057, after the screen rebuild.",
    "របាយការណ៍នឹងមកជាមួយ V1-057 ក្រោយការរៀបចំអេក្រង់ឡើងវិញ។",
  ],
  property_needed: [
    "This screen needs the Property. Open Settings, type the Property identifier under Business configuration, and come back.",
    "អេក្រង់នេះត្រូវការអគារ។ បើកការកំណត់ វាយលេខសម្គាល់អគារ នៅផ្នែកការកំណត់អាជីវកម្ម ហើយត្រឡប់មកវិញ។",
  ],
  open_settings: ["Open Settings", "បើកការកំណត់"],
} as const;

type TextKey = keyof typeof TEXT;

function translate(language: Language, key: TextKey, argument?: string) {
  const template = TEXT[key][language === "en" ? 0 : 1];
  return argument === undefined
    ? template
    : template.replace("{0}", () => argument);
}

export function HomePage({
  language,
  name,
}: {
  language: Language;
  name: string | null;
}) {
  const shown = name !== null && name.trim().length > 0 ? name.trim() : null;
  return (
    <section aria-labelledby="home-welcome" className="shell-card">
      <h2 id="home-welcome">
        {shown === null
          ? translate(language, "welcome")
          : translate(language, "welcome_name", shown)}
      </h2>
      <p className="shell-muted">{translate(language, "start")}</p>
      <ul className="shell-quick">
        {MENU.flatMap((group) => group.items)
          .filter((item) => item.page !== "home")
          .map((item) => (
            <li key={item.page}>
              <a className="shell-btn" href={hashForPage(item.page)}>
                <Icon name={item.icon} />
                <span>{menuItemName(item, language)}</span>
              </a>
            </li>
          ))}
      </ul>
    </section>
  );
}

export function ComingSoon({
  language,
  step,
}: {
  language: Language;
  step: string;
}) {
  return (
    <div className="shell-notice info" role="note">
      <Icon name="info" />
      <p>
        {step === "V1-057"
          ? translate(language, "coming_reports")
          : translate(language, "coming", step)}
      </p>
    </div>
  );
}

export function PropertyNeeded({ language }: { language: Language }) {
  return (
    <div className="shell-notice warn" role="note">
      <Icon name="info" />
      <p>
        {translate(language, "property_needed")}{" "}
        <a href={hashForPage("settings")}>
          {translate(language, "open_settings")}
        </a>
      </p>
    </div>
  );
}
