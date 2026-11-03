import { lazy, Suspense } from "react";
import { HashRouter, Route, Routes, useLocation } from "react-router-dom";
import { AppProvider, useApp } from "./lib/app-context";
import { Sidebar } from "./components/Sidebar";
import { ErrorBanner, Loading } from "./components/common";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { BrowserModeBanner, UpdateBanner } from "./components/AppBanners";
import NewSession from "./pages/NewSession";
import Settings from "./pages/Settings";
import History from "./pages/History";
import Welcome from "./pages/Welcome";
import Diagnostics from "./pages/Diagnostics";

const Quiz = lazy(() => import("./pages/Quiz"));
const Results = lazy(() => import("./pages/Results"));
const StudyGuide = lazy(() => import("./pages/StudyGuide"));
const Breakdown = lazy(() => import("./pages/Breakdown"));
const Playlist = lazy(() => import("./pages/Playlist"));

function Shell() {
  const { settings, settingsError, reloadSettings } = useApp();
  const location = useLocation();
  if (settings?.app.first_run) {
    return (
      <div className="app">
        <main className="main">
          <BrowserModeBanner />
          <Welcome />
        </main>
      </div>
    );
  }
  return (
    <div className="app">
      <Sidebar />
      <main className="main">
        <BrowserModeBanner />
        <UpdateBanner />
        {settingsError && (
          <div className="page"><ErrorBanner error={settingsError.toBody()} onRetry={() => void reloadSettings()} /></div>
        )}
        <ErrorBoundary resetKey={location.pathname}>
        <Suspense fallback={<Loading message="Loading…" rotate={false} />}>
          <Routes>
            <Route path="/" element={<NewSession />} />
            <Route path="/quiz/:id" element={<Quiz />} />
            <Route path="/results/:id" element={<Results />} />
            <Route path="/guide/:id" element={<StudyGuide />} />
            <Route path="/sets/:id" element={<Breakdown />} />
            <Route path="/study-guides/:gid" element={<StudyGuide />} />
            <Route path="/playlists/:id" element={<Playlist />} />
            <Route path="/history" element={<History />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/settings/diagnostics" element={<Diagnostics />} />
            <Route path="/welcome" element={<Welcome />} />
          </Routes>
        </Suspense>
        </ErrorBoundary>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <HashRouter>
      <AppProvider>
        <Shell />
      </AppProvider>
    </HashRouter>
  );
}
