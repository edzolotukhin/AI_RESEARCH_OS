(function () {
  const root = document.getElementById("project-desk-live-root");
  if (!root || !root.dataset.runId || root.dataset.executionStatus === "TERMINAL") return;

  let stopped = false;
  let reloadRequested = false;
  const interval = 3000;

  async function poll() {
    if (stopped || document.visibilityState === "hidden") return;
    try {
      const response = await fetch(`/ui/research/${encodeURIComponent(root.dataset.runId)}/status.json`);
      if (!response.ok) throw new Error("status");
      const payload = await response.json();
      if (payload.execution_status === "TERMINAL") {
        stopped = true;
        if (!reloadRequested) {
          reloadRequested = true;
          window.location.reload();
        }
      }
    } catch (_) {
      // Keep the normal interval: transient failures must not disable refresh.
    }
  }

  window.setInterval(poll, interval);
})();
