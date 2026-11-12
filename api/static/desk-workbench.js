(function () {
  const root = document.getElementById("desk-live-root");
  if (!root || !root.dataset.runId || root.dataset.executionStatus === "TERMINAL") return;
  const note = document.getElementById("polling-note");
  async function poll() {
    try {
      const response = await fetch(`/ui/research/${encodeURIComponent(root.dataset.runId)}/status.json`);
      if (!response.ok) throw new Error("status");
      const payload = await response.json();
      if (payload.execution_status === "TERMINAL") {
        const detail = await fetch(`/ui/research/${encodeURIComponent(root.dataset.runId)}/detail.json`);
        // A terminal run may have no unambiguous product outcome. Reload its
        // honest server projection instead of polling indefinitely for success.
        if (detail.ok || detail.status === 409) { window.location.reload(); return; }
      }
    } catch (_) {
      if (note) note.textContent = "Не вдалося оновити стан. Повторна перевірка відбудеться автоматично.";
    }
  }
  window.setInterval(poll, 3000);
})();
