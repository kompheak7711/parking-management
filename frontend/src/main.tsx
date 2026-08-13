import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles.css";

const rootElement = document.getElementById("root");

if (rootElement === null) {
  throw new Error("Application root element is missing");
}

createRoot(rootElement).render(
  <StrictMode>
    <App
      environment={import.meta.env.VITE_APP_ENVIRONMENT ?? import.meta.env.MODE}
      buildId={import.meta.env.VITE_APP_BUILD_ID ?? "development"}
    />
  </StrictMode>,
);
