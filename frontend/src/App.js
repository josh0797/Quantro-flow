import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from './components/ui/sonner';
import { AuthProvider } from './contexts/AuthContext';
import { BusinessProfileProvider } from './contexts/BusinessProfileContext';
import { LanguageProvider } from './context/LanguageContext';
import ProtectedRoute from './components/ProtectedRoute';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import SmartInbox from './pages/SmartInbox';
import Schedule from './pages/Schedule';
import CRM from './pages/CRM';
import Onboarding from './pages/Onboarding';
import ContentEngine from './pages/ContentEngine';
import AutomationPolicies from './pages/AutomationPolicies';
import Settings from './pages/Settings';
import PlanAndUsage from './pages/PlanAndUsage';
import LoginPage from './pages/LoginPage';
import AuthCallback from './pages/AuthCallback';
import OnboardingShell from './pages/welcome/OnboardingShell';
import StartChoice from './pages/welcome/StartChoice';
import Checkout from './pages/welcome/Checkout';
import StepInbox from './pages/welcome/StepInbox';
import StepCalendar from './pages/welcome/StepCalendar';
import StepCRM from './pages/welcome/StepCRM';
import StepAutomations from './pages/welcome/StepAutomations';
import StepReady from './pages/welcome/StepReady';
import Members from './pages/Members';
import JoinPage from './pages/JoinPage';
import './App.css';

/**
 * AppShell — the authenticated layout (sidebar + content). Wrapped by
 * ProtectedRoute at the route level. We mount BusinessProfileProvider
 * INSIDE the authenticated shell so it only fires API calls once a user
 * is signed in and a workspace is active.
 */
function AppShell() {
  return (
    <BusinessProfileProvider>
      <div className="app-shell dark">
        <div className="gradient-wash" />
        <Sidebar />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/inbox" element={<SmartInbox />} />
            <Route path="/schedule" element={<Schedule />} />
            <Route path="/crm" element={<CRM />} />
            <Route path="/onboarding" element={<Onboarding />} />
            <Route path="/content" element={<ContentEngine />} />
            <Route path="/automation" element={<AutomationPolicies />} />
            <Route path="/automation-policies" element={<AutomationPolicies />} />
            <Route path="/plan" element={<PlanAndUsage />} />
            <Route path="/members" element={<Members />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </BusinessProfileProvider>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      {/* Public-ish invite acceptance page. Still requires auth — the
          page itself redirects unauthenticated users to /login?next=… */}
      <Route
        path="/join/:token"
        element={
          <ProtectedRoute bypassOnboarding>
            <JoinPage />
          </ProtectedRoute>
        }
      />
      {/* Welcome flow (Phase 7d) — multi-step activation experience for
          new signups. Lives OUTSIDE the AppShell so each step gets a
          full-screen Apple-style canvas. bypassOnboarding prevents the
          ProtectedRoute from looping back here once the flow is done. */}
      <Route
        path="/welcome"
        element={
          <ProtectedRoute bypassOnboarding>
            <OnboardingShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<StartChoice />} />
        <Route path="checkout" element={<Checkout />} />
        <Route path="inbox" element={<StepInbox />} />
        <Route path="calendar" element={<StepCalendar />} />
        <Route path="crm" element={<StepCRM />} />
        <Route path="automations" element={<StepAutomations />} />
        <Route path="ready" element={<StepReady />} />
      </Route>
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}

function App() {
  return (
    <LanguageProvider>
      <AuthProvider>
        <Router>
          <AppRoutes />
          <Toaster position="bottom-right" theme="dark" />
        </Router>
      </AuthProvider>
    </LanguageProvider>
  );
}

export default App;
