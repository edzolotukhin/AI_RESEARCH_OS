(function () {
  const form = document.getElementById("research-brief-form");
  if (form) {
    form.addEventListener("submit", function () {
      const button = document.getElementById("start-research-btn");
      const hint = document.getElementById("form-state-hint");
      if (button) {
        button.disabled = true;
        button.textContent = "Submitting…";
      }
      if (hint) {
        hint.textContent = "Submitting research…";
      }
    });
  }

  const root = document.getElementById("research-root");
  if (!root) {
    return;
  }

  const researchId = root.dataset.researchId;
  let executionStatus = root.dataset.executionStatus;
  const phaseLabel = document.getElementById("current-phase-label");
  const stepper = document.getElementById("phase-stepper");
  const pollingNote = document.getElementById("polling-note");

  const phaseLabels = {
    QUEUED: "Research request queued",
    PLANNING: "Planning the research",
    RESEARCHING: "Finding and evaluating sources",
    EVALUATING: "Checking whether the evidence is sufficient",
    ANALYZING: "Analyzing supported evidence",
    WRITING: "Preparing the report",
    REVIEWING: "Reviewing research quality",
    COMPLETED: "Research process completed",
  };

  const phaseOrder = [
    "QUEUED",
    "PLANNING",
    "RESEARCHING",
    "EVALUATING",
    "ANALYZING",
    "WRITING",
    "REVIEWING",
    "COMPLETED",
  ];

  function updateStepper(phase) {
    const index = phaseOrder.indexOf(phase);
    if (!stepper || index < 0) {
      return;
    }
    stepper.querySelectorAll(".phase-step").forEach(function (item, itemIndex) {
      item.classList.toggle("is-complete", itemIndex < index);
      item.classList.toggle("is-current", itemIndex === index);
    });
    if (phaseLabel) {
      phaseLabel.textContent = phaseLabels[phase] || phase;
    }
  }

  async function fetchDetailWithRaceHandling() {
    const response = await fetch(`/ui/research/${researchId}/detail.json`);
    if (response.status === 409) {
      return false;
    }
    if (!response.ok) {
      throw new Error("detail_unavailable");
    }
    return true;
  }

  async function pollStatus() {
    try {
      const response = await fetch(`/ui/research/${researchId}/status.json`);
      if (!response.ok) {
        if (pollingNote) {
          pollingNote.textContent = "Unable to load research status.";
        }
        return;
      }
      const payload = await response.json();
      executionStatus = payload.execution_status;
      updateStepper(payload.phase);
      if (executionStatus === "TERMINAL") {
        const ready = await fetchDetailWithRaceHandling();
        if (ready) {
          window.location.reload();
          return;
        }
        if (pollingNote) {
          pollingNote.textContent = "Finalizing result…";
        }
      }
    } catch (_error) {
      if (pollingNote) {
        pollingNote.textContent = "Network error while checking progress.";
      }
    }
  }

  if (executionStatus && executionStatus !== "TERMINAL") {
    updateStepper(root.dataset.phase);
    window.setInterval(pollStatus, 3000);
  }

  document.querySelectorAll(".view-evidence-btn").forEach(function (button) {
    button.addEventListener("click", function () {
      const targetId = button.getAttribute("data-target");
      const drawer = targetId ? document.getElementById(targetId) : null;
      if (drawer) {
        drawer.hidden = !drawer.hidden;
      }
    });
  });
})();
