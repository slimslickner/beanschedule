// Fava extension JS module for the Schedules report.
//
// Fava only executes an extension's JS module on navigation to its report
// (injected inline <script> tags are not run for client-side navigation), so
// the report's interactivity lives here and is (re)wired in
// `onExtensionPageLoad`. The module is a plain ES module loaded from
// /extension_js_module/Schedules.js and must export a default object.

/** Compose the RRULE from the builder fields and write it to the preview. */
function compose(form) {
  const freq = form.querySelector("[name=freq]");
  if (!freq) {
    return;
  }
  const parts = ["FREQ=" + freq.value];
  const interval = form.querySelector("[name=interval]");
  if (interval && interval.value && interval.value !== "1") {
    parts.push("INTERVAL=" + interval.value);
  }
  const days = Array.prototype.slice
    .call(form.querySelectorAll("[name=byday]:checked"))
    .map((el) => el.value);
  if (freq.value === "WEEKLY" && days.length) {
    parts.push("BYDAY=" + days.join(","));
  }
  const day = form.querySelector("[name=bymonthday]");
  if (freq.value === "MONTHLY" && day && day.value) {
    parts.push("BYMONTHDAY=" + day.value);
  }
  const month = form.querySelector("[name=bymonth]");
  if (freq.value === "YEARLY" && month && month.value) {
    parts.push("BYMONTH=" + month.value);
  }
  const out = form.querySelector(".schedule-rrule-preview");
  if (out) {
    out.textContent = parts.join(";");
  }
}

/** Show the builder controls that apply to the chosen frequency. */
function syncFreq(form) {
  const freq = form.querySelector("[name=freq]");
  if (!freq) {
    return;
  }
  form.querySelectorAll("[data-when]").forEach((el) => {
    el.style.display = el.getAttribute("data-when") === freq.value ? "" : "none";
  });
  compose(form);
}

/** Show and enable the amortization fields only for an amortization schedule. */
function syncType(form) {
  const type = form.querySelector("[name=schedule_type]");
  if (!type) {
    return;
  }
  const amortized = type.value === "amortization";
  form
    .querySelectorAll(".schedule-amort, .schedule-leg-field")
    .forEach((el) => {
      el.style.display = amortized ? "" : "none";
    });
  form
    .querySelectorAll(
      ".schedule-amort input, .schedule-amort select, .schedule-leg-field select",
    )
    .forEach((el) => {
      el.disabled = !amortized;
    });
}

/** Wire one structured form: preview, frequency/type toggles, Enter guard. */
function wire(form) {
  if (form.dataset.scheduleWired) {
    return;
  }
  form.dataset.scheduleWired = "1";
  syncFreq(form);
  syncType(form);
  form.addEventListener("input", () => {
    syncFreq(form);
  });
  form.addEventListener("change", () => {
    syncFreq(form);
    syncType(form);
  });
  // Enter should never submit the schedule; only the button does.
  form.addEventListener("keydown", (event) => {
    if (
      event.key === "Enter" &&
      event.target.tagName !== "TEXTAREA" &&
      event.target.type !== "submit"
    ) {
      event.preventDefault();
    }
  });
  const add = form.querySelector(".schedule-add-posting");
  if (add) {
    add.addEventListener("click", () => {
      const row = form.querySelector(".schedule-posting-row").cloneNode(true);
      row.querySelectorAll("input").forEach((input) => {
        input.value = "";
      });
      row.querySelectorAll("select").forEach((select) => {
        select.selectedIndex = 0;
      });
      add.parentNode.insertBefore(row, add);
      syncFreq(form);
      syncType(form);
    });
  }
}

export default {
  /** Called whenever the Schedules report is loaded, by navigation or reload. */
  onExtensionPageLoad() {
    document.querySelectorAll(".schedule-structured").forEach(wire);
  },
};
