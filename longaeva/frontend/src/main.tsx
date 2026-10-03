import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import App from "./App"
import "./styles/theme.css"

const root = document.getElementById("root")
if (!root) {
  throw new Error("Root element #root is missing")
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
