import { lazy, Suspense } from "react";
import { HashRouter, Route, Routes } from "react-router-dom";
import { AppProvider, useApp } from "./lib/app-context";
import { Sidebar } from "./components/Sidebar";
import { ErrorBanner, Loading } from "./components/common";
import NewSession from "./pages/NewSession";
import Settings from "./pages/Settings";
import History from "./pages/History";

const Quiz = lazy(() => import("./pages/Quiz"));
const Results = lazy(() => import("./pages/Results"));
const StudyGuide = lazy(() => import("./pages/StudyGuide"));

function Shell() {
  const { settingsError, reloadSettings } = useApp();
  return (
    <div className="app">
      <Sidebar />
      <main className="main">
        {settingsError && (
          <div className="page"><ErrorBanner error={settingsError.toBody()} onRetry={() => void reloadSettings()} /></div>
        )}
        <Suspense fallback={<Loading message="Loading…" rotate={false} />}>
          <Routes>
            <Route path="/" element={<NewSession />} />
            <Route path="/quiz/:id" element={<Quiz />} />
            <Route path="/results/:id" element={<Results />} />
            <Route path="/guide/:id" element={<StudyGuide />} />
            <Route path="/history" element={<History />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Suspense>
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
