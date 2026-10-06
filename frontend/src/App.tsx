import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/useAuth'
import { AppShell } from './components/AppShell'
import { AboutPage } from './pages/AboutPage'
import { DashboardPage } from './pages/DashboardPage'
import { DocumentDetailsPage } from './pages/DocumentDetailsPage'
import { DocumentsPage } from './pages/DocumentsPage'
import { LoginPage } from './pages/LoginPage'
import { OptimizationPage } from './pages/OptimizationPage'

function RequireAuth({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  return token ? children : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/documents/:id" element={<DocumentDetailsPage />} />
        <Route path="/optimization" element={<OptimizationPage />} />
        <Route path="/about" element={<AboutPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
