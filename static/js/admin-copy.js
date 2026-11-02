/**
 * Copy-to-clipboard for the admin's temp-password screens (create_user.html,
 * reset_password_done.html) — Plan/09-Admin-Control-Center, dev-test finding 3.
 *
 * `navigator.clipboard` only exists in a "secure context" (HTTPS, or localhost/127.0.0.1).
 * This admin's documented self-hosted deployment target has no such guarantee — plain HTTP
 * over a Tailscale/LAN hostname is the expected case — so `navigator.clipboard` is `undefined`
 * there and a bare `writeText()` call throws silently. This falls back to the classic
 * `document.execCommand('copy')`-via-hidden-`<textarea>` path when the modern API is
 * unavailable, and always shows on-page feedback next to the button either way.
 *
 * Wired up via a `data-copy-target` attribute rather than an inline `onclick=` (10.4 — Content
 * Security Policy: `script-src 'self'` rejects an inline handler with no nonce/hash). See
 * `resolveCopyTarget` below for what the attribute means; `window.ptpCopyToClipboard` is no
 * longer exposed globally since nothing outside this file calls it any more.
 */
(function () {
  "use strict";

  function copyViaExecCommand(text) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    // Off-screen, but still selectable — execCommand('copy') requires a real selection.
    textarea.style.position = "fixed";
    textarea.style.top = "0";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);

    let succeeded = false;
    try {
      succeeded = document.execCommand("copy");
    } catch (err) {
      succeeded = false;
    }
    document.body.removeChild(textarea);
    return succeeded;
  }

  function feedbackElementFor(button) {
    const next = button.nextElementSibling;
    if (next && next.classList.contains("copy-feedback")) {
      return next;
    }
    const created = document.createElement("span");
    created.className = "copy-feedback";
    created.setAttribute("aria-live", "polite");
    button.insertAdjacentElement("afterend", created);
    return created;
  }

  function showFeedback(button, message, isError) {
    const feedback = feedbackElementFor(button);
    feedback.textContent = message;
    feedback.classList.toggle("copy-feedback-error", Boolean(isError));
    window.clearTimeout(feedback._ptpFeedbackTimeout);
    feedback._ptpFeedbackTimeout = window.setTimeout(function () {
      feedback.textContent = "";
    }, 4000);
  }

  /** Copy `text` to the clipboard, feeding back success/failure next to `button`. */
  function copyToClipboard(button, text) {
    const canUseModernApi =
      window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText;

    if (canUseModernApi) {
      navigator.clipboard.writeText(text).then(
        function () {
          showFeedback(button, "Copied.", false);
        },
        function () {
          const succeeded = copyViaExecCommand(text);
          showFeedback(
            button,
            succeeded ? "Copied." : "Could not copy automatically — select the text and copy it by hand.",
            !succeeded
          );
        }
      );
      return;
    }

    const succeeded = copyViaExecCommand(text);
    showFeedback(
      button,
      succeeded ? "Copied." : "Could not copy automatically — select the text and copy it by hand.",
      !succeeded
    );
  }

  /**
   * Resolves the element whose text a `data-copy-target` button should copy.
   *
   * `data-copy-target` is a CSS selector, resolved against the whole document by default
   * (`create_user.html`'s single, page-unique `#temp-password`). A button additionally
   * carrying `data-copy-target-closest` instead resolves the selector inside its nearest
   * matching ancestor — `reset_password_done.html`'s one-button-per-table-row case, where
   * each row's own `.temp-pw` cell must not be confused with another row's.
   */
  function resolveCopyTarget(button) {
    const selector = button.getAttribute("data-copy-target");
    if (!selector) {
      return null;
    }
    const closestSelector = button.getAttribute("data-copy-target-closest");
    if (closestSelector) {
      const scope = button.closest(closestSelector);
      return scope ? scope.querySelector(selector) : null;
    }
    return document.querySelector(selector);
  }

  document.addEventListener("click", function (event) {
    const button = event.target.closest ? event.target.closest("[data-copy-target]") : null;
    if (!button) {
      return;
    }
    const target = resolveCopyTarget(button);
    if (target) {
      copyToClipboard(button, target.textContent);
    }
  });
})();
