import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RuntimeApp } from "./runtime";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RuntimeApp />
  </StrictMode>,
);
