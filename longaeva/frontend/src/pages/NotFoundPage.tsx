import { Link } from "react-router-dom"

export function NotFoundPage() {
  return (
    <div>
      <h1 className="theme-page-title">Page not found</h1>
      <p className="theme-page-subtitle">
        That route is not in this shell.{" "}
        <Link to="/runs" className="text-link">
          Back to runs
        </Link>
        .
      </p>
    </div>
  )
}
