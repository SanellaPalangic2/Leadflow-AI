// Small progressive enhancements. Every feature also works without JavaScript
// except "Fill with sample data" and "Copy email".
document.addEventListener("DOMContentLoaded", () => {
  // Clickable table rows on the dashboard
  document.querySelectorAll("tr[data-href]").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (!e.target.closest("a")) window.location = row.dataset.href;
    });
  });

  // Loading state while the lead is analyzed (a live LLM call takes a few seconds)
  const leadForm = document.getElementById("lead-form");
  if (leadForm) {
    const btn = leadForm.querySelector("[data-loading-text]");
    const idleLabel = btn.innerHTML;
    leadForm.addEventListener("submit", () => {
      btn.disabled = true; // also prevents double submissions
      btn.innerHTML = '<span class="spinner"></span>' + btn.dataset.loadingText;
    });
    // If the user navigates Back to this page, the browser may restore it from
    // cache with the button still disabled. Reset it.
    window.addEventListener("pageshow", () => {
      btn.disabled = false;
      btn.innerHTML = idleLabel;
    });
  }

  // Demo helper: fill the form with a realistic lead
  const fill = document.getElementById("fill-sample");
  if (fill && leadForm) {
    const samples = [
      { first_name: "Maria", last_name: "Delgado", email: "maria.delgado@example.com", phone: "(512) 555-0147",
        address: "4821 Juniper Ridge Dr, Austin, TX 78745", monthly_bill: "410", service_interest: "Solar + Roofing",
        message: "Our roof is about 18 years old and we'd like to replace it before adding solar. Bills are brutal in summer and we just bought an EV. We own the home and want to get started this month if the numbers make sense. Is financing available?" },
      { first_name: "Derek", last_name: "Owens", email: "", phone: "(737) 555-0192",
        address: "", monthly_bill: "", service_interest: "Roofing",
        message: "Water is leaking into the upstairs bedroom after last night's storm. Need someone out ASAP." },
      { first_name: "Priya", last_name: "Nair", email: "priya.nair@example.com", phone: "",
        address: "77 Cedar Hollow Ln, Round Rock, TX 78664", monthly_bill: "145", service_interest: "Solar",
        message: "Just researching for now. Curious about the tax credit and whether our trees would be a problem." },
    ];
    let i = 0;
    fill.addEventListener("click", () => {
      const s = samples[i++ % samples.length];
      Object.entries(s).forEach(([name, value]) => {
        const el = leadForm.elements[name];
        if (el instanceof RadioNodeList) {
          el.forEach((r) => (r.checked = r.value === value));
        } else if (el) {
          el.value = value;
        }
      });
    });
  }

  // Auto-submit the status dropdown
  document.querySelectorAll("select[data-autosubmit]").forEach((sel) => {
    sel.addEventListener("change", () => sel.form.submit());
  });

  // Toggle the email edit form
  const editForm = document.getElementById("email-edit");
  const preview = document.getElementById("email-preview");
  const actions = document.getElementById("email-actions");
  document.querySelectorAll("[data-toggle-edit]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const editing = editForm.hidden;
      editForm.hidden = !editing;
      preview.hidden = editing;
      actions.hidden = editing;
      if (editing) editForm.querySelector("textarea").focus();
    });
  });

  // Copy an approved email to the clipboard
  const copyBtn = document.querySelector("[data-copy-email]");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const text = `Subject: ${document.getElementById("email-subject").textContent}\n\n${document.getElementById("email-body").textContent}`;
      try {
        await navigator.clipboard.writeText(text);
        copyBtn.textContent = "Copied ✓";
      } catch {
        copyBtn.textContent = "Copy failed. Select the text manually.";
      }
      setTimeout(() => (copyBtn.textContent = "Copy email"), 2500);
    });
  }
});
