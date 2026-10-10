import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate, NavLink, useNavigate } from "react-router-dom";
import { isAuthenticated, getUser, clearToken, restoreSession } from "./auth";
import Login from "./Login";
import { JobCacheProvider } from "./JobCache";
import { LoadingState, ToastHost } from "./ui";

const NewReel = React.lazy(() => import("./NewReel"));
const PlanReview = React.lazy(() => import("./PlanReview"));
const Render = React.lazy(() => import("./Render"));
const MyEffects = React.lazy(() => import("./MyEffects"));
const StyleLibrary = React.lazy(() => import("./StyleLibrary"));
const StyleLearner = React.lazy(() => import("./StyleLearner"));
const Library = React.lazy(() => import("./Library"));
const ContentCreator = React.lazy(() => import("./ContentCreator"));
const Landing = React.lazy(() => import("./Landing"));
const Signup = React.lazy(() => import("./Signup"));
const ForgotPassword = React.lazy(() => import("./ForgotPassword"));
const ResetPassword = React.lazy(() => import("./ResetPassword"));
const Jobs = React.lazy(() => import("./Jobs"));

const HermesLayout = React.lazy(() => import("./pages/hermes/HermesLayout.jsx"));
const HermesDashboard = React.lazy(() => import("./pages/hermes/HermesDashboard.jsx"));
const HermesConnect = React.lazy(() => import("./pages/hermes/HermesConnect.jsx"));
const HermesScheduler = React.lazy(() => import("./pages/hermes/HermesScheduler.jsx"));
const HermesPostEditor = React.lazy(() => import("./pages/hermes/HermesPostEditor.jsx"));
const HermesAnalytics = React.lazy(() => import("./pages/hermes/HermesAnalytics.jsx"));
const HermesAdvisor = React.lazy(() => import("./pages/hermes/HermesAdvisor.jsx"));
const HermesContentPlan = React.lazy(() => import("./pages/hermes/HermesContentPlan.jsx"));
const HermesSettings = React.lazy(() => import("./pages/hermes/HermesSettings"));

function LoadingSpinner() {
  return <LoadingState label="Loading page…" rows={2} />;
}

type ErrorBoundaryState = { hasError: boolean };

class AppErrorBoundary extends React.Component<React.PropsWithChildren, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("Unhandled React error", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="ui-state" role="alert">
          <h1>Something went wrong</h1>
          <p>Reload the page to try again.</p>
          <button onClick={() => window.location.reload()}>Reload</button>
        </main>
      );
    }
    return this.props.children;
  }
}

function SessionBootstrap({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = React.useState(isAuthenticated());
  React.useEffect(() => {
    if (!ready) void restoreSession().finally(() => setReady(true));
  }, [ready]);
  return ready ? <>{children}</> : <LoadingSpinner />;
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function UserNav() {
  const user = getUser();
  const navigate = useNavigate();
  const [loggingOut, setLoggingOut] = React.useState(false);
  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      const response = await fetch("/api/auth/logout", { method: "POST", credentials: "include", headers: { "content-type": "application/json" }, body: "{}" });
      if (!response.ok) console.warn("Server logout failed; refresh token revocation may not have completed.", response.status);
    } catch (error) {
      console.warn("Server logout request failed; refresh token revocation may not have completed.", error);
    }
    clearToken();
    navigate("/login");
  };
  return (
    <div className="nav-user">
      {user && <span className="nav-user-name">{user.name}</span>}
      <button className="nav-logout-btn" onClick={handleLogout} disabled={loggingOut} title={(loggingOut) ? "Wait for the current action to finish." : undefined}>{loggingOut ? "Logging out…" : "Log out"}</button>
    </div>
  );
}

function AuthenticatedApp() {
  return (
    <>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <nav className="app-nav" aria-label="Main navigation">
        <div className="nav-brand">
          <div className="nav-brand-icon">R</div>
          <span className="nav-brand-text">AI Render</span>
        </div>
        <div className="nav-links" aria-label="Sections">
          <NavLink to="/new">
            <span className="nav-icon">+</span>
            New Reel
          </NavLink>
          <NavLink to="/content">
            <span className="nav-icon">&#10024;</span>
            Content Creator
          </NavLink>
          <NavLink to="/jobs">
            <span className="nav-icon">&#9776;</span>
            Jobs
          </NavLink>
          <NavLink to="/my-effects">
            <span className="nav-icon">&#9733;</span>
            My Effects
          </NavLink>
          <NavLink to="/library">
            <span className="nav-icon">&#9776;</span>
            Library
          </NavLink>
          <NavLink to="/style-library">
            <span className="nav-icon">&#9998;</span>
            Styles & Fonts
          </NavLink>
          <NavLink to="/style-learner">
            <span className="nav-icon">&#9881;</span>
            Style Learner
          </NavLink>
          <NavLink to="/hermes">
            <span className="nav-icon">◎</span>
            Hermes
          </NavLink>
        </div>
        <UserNav />
        <div className="nav-footer">
          AI Render v0.1
        </div>
      </nav>
      <main id="main-content" tabIndex={-1}>
        <Routes>
          <Route path="/new" element={<NewReel />} />
          <Route path="/content" element={<ContentCreator />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:id" element={<PlanReview />} />
          <Route path="/jobs/:id/render" element={<Render />} />
          <Route path="/my-effects" element={<MyEffects />} />
          <Route path="/library" element={<Library />} />
          <Route path="/style-library" element={<StyleLibrary />} />
          <Route path="/style-learner" element={<StyleLearner />} />
          <Route path="/fonts" element={<Navigate to="/style-library#fonts" replace />} />
          <Route path="/hermes" element={<HermesLayout />}>
            <Route index element={<HermesDashboard />} />
            <Route path="connect" element={<HermesConnect />} />
            <Route path="scheduler" element={<HermesScheduler />} />
            <Route path="post/new" element={<HermesPostEditor />} />
            <Route path="post/:id" element={<HermesPostEditor />} />
            <Route path="analytics" element={<HermesAnalytics />} />
            <Route path="advisor" element={<HermesAdvisor />} />
            <Route path="content-plan" element={<HermesContentPlan />} />
            <Route path="settings" element={<HermesSettings />} />
          </Route>
          <Route path="*" element={<Navigate to="/new" replace />} />
        </Routes>
      </main>
      <ToastHost />
    </>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppErrorBoundary>
        <SessionBootstrap>
          <JobCacheProvider>
            <React.Suspense fallback={<LoadingSpinner />}>
              <Routes>
                <Route path="/" element={isAuthenticated() ? <Navigate to="/new" replace /> : <Landing />} />
                <Route path="/login" element={isAuthenticated() ? <Navigate to="/new" replace /> : <Login />} />
                <Route path="/signup" element={isAuthenticated() ? <Navigate to="/new" replace /> : <Signup />} />
                <Route path="/forgot-password" element={<ForgotPassword />} />
                <Route path="/reset-password" element={<ResetPassword />} />
                <Route path="/*" element={
                  <ProtectedRoute>
                    <AuthenticatedApp />
                  </ProtectedRoute>
                } />
              </Routes>
            </React.Suspense>
          </JobCacheProvider>
        </SessionBootstrap>
      </AppErrorBoundary>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
