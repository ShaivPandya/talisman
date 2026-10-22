import { Component, Suspense, useEffect, type ErrorInfo, type ReactNode } from "react"
import { createBrowserRouter, RouterProvider, Route, Navigate, Outlet, useLocation, useRouteError, type RouteObject } from "react-router-dom"
import { QueryClientProvider } from "@tanstack/react-query"
import { queryClient } from "@/lib/queryClient"
import { LoginPage, PAGE_ROUTES, ROUTE_REDIRECTS, preloadRoute } from "@/lib/pageRoutes"
import { preloadRouteData } from "@/lib/routeData"
import { AuthProvider, useAuth } from "@/contexts/AuthContext"
import { ThemeProvider } from "@/contexts/ThemeContext"
import { PersonalizationProvider } from "@/contexts/PersonalizationContext"
import { ProtectedRoute } from "@/components/auth/ProtectedRoute"
import { Layout } from "@/components/layout/Layout"
import { isChunkLoadError, maybeReloadForChunkLoadError } from "@/lib/chunkRecovery"
import { captureRouteError, LoadObservabilityAfterRender, useRouteTracking } from "@/lib/observabilityShim"

class RouteErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: unknown }> {
  state = { error: null as unknown }

  static getDerivedStateFromError(error: unknown) {
    return { error }
  }

  componentDidUpdate(prevProps: { resetKey: string }) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    if (maybeReloadForChunkLoadError(error, "route-lazy")) return
    if (!isChunkLoadError(error)) {
      captureRouteError(error, {
        componentStack: info.componentStack,
        route: this.props.resetKey,
      })
    }
    console.error("Unhandled route render error", error, info)
  }

  render() {
    if (!this.state.error) return this.props.children

    return <RouteErrorScreen error={this.state.error} />
  }
}

function RouteErrorScreen({ error }: { error: unknown }) {
  const chunkLoadError = isChunkLoadError(error)
  return (
    <div className="flex min-h-screen items-center justify-center bg-app px-4 text-app">
      <section className="theme-surface max-w-md p-6 text-center">
        <h1 className="text-lg font-semibold text-app">
          {chunkLoadError ? "App Update Required" : "Page Failed To Load"}
        </h1>
        <p className="mt-2 text-sm leading-6 text-muted">
          {chunkLoadError
            ? "A deployed page module could not be loaded. Refresh to pull the current application bundle."
            : "This page hit an unexpected rendering error."}
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="theme-button-base theme-button-primary mt-5 min-h-10 px-4 text-sm"
        >
          Reload Application
        </button>
      </section>
    </div>
  )
}

function RouteLoadBoundary({ children }: { children: ReactNode }) {
  const location = useLocation()
  return <RouteErrorBoundary resetKey={location.pathname}>{children}</RouteErrorBoundary>
}

function LoginRoute() {
  const { isAuthenticated, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-app px-4 text-sm text-muted">
        Loading...
      </div>
    )
  }

  return isAuthenticated ? (
    <Navigate to="/" replace />
  ) : (
    <Suspense fallback={<RouteLoading />}>
      <LoginPage />
      <LoadObservabilityAfterRender />
    </Suspense>
  )
}

function RouteLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-app px-4 text-sm text-muted">
      Loading...
    </div>
  )
}

// Keep Sentry's deferred Routes tracker inside the router context. It only
// matches these paths; the actual route tree belongs to the data router.
const trackingRoutes = ["/login", ...PAGE_ROUTES.map(route => route.path), ...Object.keys(ROUTE_REDIRECTS)]
  .map(path => <Route key={path} path={path} />)

function RootRoute() {
  const RouteTracking = useRouteTracking()
  return (
    <RouteLoadBoundary>
      <Outlet />
      {/* eslint-disable-next-line react-hooks/static-components */}
      {RouteTracking && <RouteTracking>{trackingRoutes}</RouteTracking>}
    </RouteLoadBoundary>
  )
}

function StartupRoute() {
  const location = useLocation()
  return location.pathname === "/login" ? <RouteLoading /> : <ProtectedRoute bootstrapping />
}

function RouterFailure() {
  const error = useRouteError()
  const location = useLocation()
  useEffect(() => {
    if (maybeReloadForChunkLoadError(error, "route-lazy")) return
    if (!isChunkLoadError(error)) captureRouteError(error, { route: location.pathname })
    console.error("Unhandled route load error", error)
  }, [error, location.pathname])
  return <RouteErrorScreen error={error} />
}

let router: ReturnType<typeof createBrowserRouter> | undefined

function getRouter() {
  router ??= createBrowserRouter([{
    element: <RootRoute />,
    hydrateFallbackElement: <StartupRoute />,
    errorElement: <RouterFailure />,
    children: [
      { path: "/login", element: <LoginRoute />, loader: () => preloadRoute("/login").then(() => null) },
      {
        element: <ProtectedRoute />,
        children: [{
          element: <Layout />,
          children: [
            ...PAGE_ROUTES.map(({ path, page }): RouteObject => ({
              path,
              loader: ({ request }) => { preloadRouteData(request.url); return null },
              lazy: async () => ({ Component: (await page.preload()).default }),
            })),
            ...Object.entries(ROUTE_REDIRECTS).map(([path, to]) => ({ path, element: <Navigate to={to} replace /> })),
          ],
        }],
      },
    ],
  }])
  return router
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <PersonalizationProvider>
          <AuthProvider>
            <RouterProvider router={getRouter()} />
          </AuthProvider>
        </PersonalizationProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
