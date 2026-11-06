import { Navigate, Outlet, useLocation } from "react-router-dom"
import { useAuth } from "@/contexts/AuthContext"
import { Layout } from "@/components/layout/Layout"

export function ProtectedRoute({ bootstrapping = false }: { bootstrapping?: boolean }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading || (bootstrapping && isAuthenticated)) {
    return <Layout bootstrapping />
  }

  return isAuthenticated ? <Outlet /> : <Navigate to="/login" state={{ returnTo: location.pathname + location.search }} replace />
}
