import { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

/** Catches render errors (and failed lazy-chunk loads) so the window never goes blank. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    const chunk = /dynamically imported module|Loading chunk/i.test(this.state.error.message);
    return (
      <div className="page">
        <div className="banner error" role="alert">
          <AlertTriangle size={20} />
          <div className="banner-body">
            <div className="banner-title">{chunk ? "The app was updated" : "This screen hit a problem"}</div>
            <div>{chunk ? "Reload to pick up the latest version." : "Your progress is saved. Reloading usually fixes it."}</div>
            {!chunk && <div className="banner-detail">{this.state.error.message}</div>}
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn sm primary" onClick={() => window.location.reload()}><RefreshCw size={14} /> Reload</button>
            </div>
          </div>
        </div>
      </div>
    );
  }
}
