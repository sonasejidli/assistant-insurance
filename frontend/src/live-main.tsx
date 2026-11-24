import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Platform } from "./components/platform";
import "./styles.css";
import "./platform.css";

createRoot(document.getElementById("root")!).render(<StrictMode><Platform /></StrictMode>);
