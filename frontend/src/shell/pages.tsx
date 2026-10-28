// V1-058 R1: the simple notices of the new frame. Home is home/HomeScreen.tsx (step R6).

import type { Language } from "../signInText";
import { Icon } from "./icons";
import { hashForPage } from "./navigation";

const TEXT = {
  coming: [
    "This screen is being rebuilt to the new design. It comes in step {0}.",
    "អេក្រង់នេះកំពុងរៀបចំឡើងវិញតាមការរចនាថ្មី។ វានឹងមកនៅជំហាន {0}។",
  ],
  property_needed: [
    "This screen needs the Property. Open Settings, load the Property under Business configuration, and come back.",
    "អេក្រង់នេះត្រូវការអគារ។ បើកការកំណត់ ផ្ទុកអគារ នៅផ្នែកការកំណត់អាជីវកម្ម ហើយត្រឡប់មកវិញ។",
  ],
  open_settings: ["Open Settings", "បើកការកំណត់"],
  no_access: [
    "Your account cannot use this page. Ask the Owner if you need it.",
    "គណនីរបស់អ្នកមិនអាចប្រើទំព័រនេះទេ។ សូមសួរម្ចាស់ ប្រសិនបើអ្នកត្រូវការវា។",
  ],
  go_home: ["Go to Home", "ទៅទំព័រដើម"],
} as const;

type TextKey = keyof typeof TEXT;

function translate(language: Language, key: TextKey, argument?: string) {
  const template = TEXT[key][language === "en" ? 0 : 1];
  return argument === undefined
    ? template
    : template.replace("{0}", () => argument);
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
      <p>{translate(language, "coming", step)}</p>
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

export function NoAccess({ language }: { language: Language }) {
  return (
    <div className="shell-notice warn" role="note">
      <Icon name="info" />
      <p>
        {translate(language, "no_access")}{" "}
        <a href={hashForPage("home")}>{translate(language, "go_home")}</a>
      </p>
    </div>
  );
}
