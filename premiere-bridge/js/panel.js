(function () {
  "use strict";

  // ── DOM refs ──────────────────────────────────────────────────────────────
  var dot        = document.getElementById("dot");
  var banner     = document.getElementById("banner");
  var jobCard    = document.getElementById("job-card");
  var jobName    = document.getElementById("job-name");
  var jobMeta    = document.getElementById("job-meta");
  var applyBtn   = document.getElementById("apply-btn");
  var manualCode = document.getElementById("code");
  var manualBtn  = document.getElementById("manual-btn");
  var portInput  = document.getElementById("port-input");

  // ── State ─────────────────────────────────────────────────────────────────
  var storedPort = localStorage.getItem("airender_port") || "8000";
  portInput.value = storedPort;
  var apiBase = "http://127.0.0.1:" + storedPort;
  var pollTimer = null;
  var pendingCode = null;   // code fetched via auto-poll
  var pairedSession = null; // Keep the one-time token for retries in this panel.
  var busy = false;

  portInput.addEventListener("change", function () {
    var p = portInput.value.trim();
    if (/^\d+$/.test(p)) {
      localStorage.setItem("airender_port", p);
      apiBase = "http://127.0.0.1:" + p;
      pendingCode = null;
      setBanner("Reconnecting…", "watching");
    }
  });

  // ── UI helpers ────────────────────────────────────────────────────────────
  function setDot(kind) {
    dot.className = "dot" + (kind ? " " + kind : "");
  }

  function setBanner(msg, kind) {
    banner.textContent = msg;
    banner.className = kind || "";
  }

  function showJob(name, meta) {
    jobName.textContent = name;
    jobMeta.textContent = meta;
    jobCard.className = "visible";
    applyBtn.className = "visible";
  }

  function hideJob() {
    jobCard.className = "";
    applyBtn.className = "";
    pendingCode = null;
  }

  // ── XHR wrapper ───────────────────────────────────────────────────────────
  function request(method, path, body, token, cb) {
    var xhr = new XMLHttpRequest();
    var settled = false;
    function done(err, value) {
      if (settled) return;
      settled = true;
      cb(err, value);
    }
    xhr.open(method, apiBase + path, true);
    xhr.setRequestHeader("Content-Type", "application/json");
    if (token) xhr.setRequestHeader("Authorization", "Bearer " + token);
    xhr.timeout = 15000;

    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      var parsed;
      try { parsed = JSON.parse(xhr.responseText || "{}"); }
      catch (_) { parsed = { detail: xhr.responseText || "Empty response" }; }
      if (xhr.status < 200 || xhr.status >= 300) {
        var error = new Error(parsed.detail || ("HTTP " + xhr.status));
        error.status = xhr.status;
        done(error);
      } else {
        done(null, parsed);
      }
    };

    xhr.onerror = function () {
      done(new Error("Cannot reach AI Render on " + apiBase + " — is the backend running?"));
    };
    xhr.ontimeout = function () { done(new Error("Request timed out")); };
    xhr.send(body != null ? JSON.stringify(body) : null);
  }

  // ── CEP bridge ────────────────────────────────────────────────────────────
  function hostInfo() {
    var env = {};
    try { env = JSON.parse(window.__adobe_cep__.getHostEnvironment()); } catch (_) {}
    return { kind: "CEP", version: "0.1.3", premiere_version: env.appVersion || null, app_name: env.appName || "PPRO" };
  }

  function jsxPath() {
    try {
      var base = window.__adobe_cep__.getSystemPath("extension");
      return (base || "").replace(/\\/g, "/") + "/jsx/bridge.jsx";
    } catch (_) { return ""; }
  }

  function loadJsx(cb) {
    var path = jsxPath();
    if (!path) return cb(new Error("Cannot resolve extension path."));
    var result;
    try { result = window.cep.fs.readFile(path); }
    catch (e) { return cb(new Error("cep.fs unavailable: " + e)); }
    if (result.err !== 0) return cb(new Error("Cannot read bridge.jsx (err " + result.err + "): " + path));
    window.__adobe_cep__.evalScript(result.data, function (r) {
      if (r === "EvalScript error.") return cb(new Error("bridge.jsx syntax error — check the file."));
      cb(null);
    });
  }

  function doExecute(command, cb) {
    var script;
    try { script = "AIRenderBridge.execute(" + JSON.stringify(JSON.stringify(command)) + ")"; }
    catch (e) { return cb(new Error("Failed to build script: " + e)); }
    window.__adobe_cep__.evalScript(script, function (raw) {
      if (!raw) return cb(new Error("Premiere returned no result."));
      if (raw === "EvalScript error.") return cb(new Error("JSX execution failed inside Premiere.\n\nMake sure a Premiere project is open, then try again."));
      try { cb(null, JSON.parse(raw)); }
      catch (_) { cb(new Error("Premiere returned invalid JSON: " + raw.substring(0, 120))); }
    });
  }

  function evalBridge(command, cb) {
    if (!window.__adobe_cep__ || !window.__adobe_cep__.evalScript) {
      return cb(new Error("CEP panel not initialized — restart Premiere."));
    }
    // Check if AIRenderBridge is loaded; if not (e.g. after project switch), reload the JSX first.
    window.__adobe_cep__.evalScript("typeof AIRenderBridge", function (typeResult) {
      if (typeResult === "undefined" || typeResult === "EvalScript error.") {
        setBanner("Reloading bridge script…", "watching");
        loadJsx(function (loadErr) {
          if (loadErr) return cb(loadErr);
          doExecute(command, cb);
        });
      } else {
        doExecute(command, cb);
      }
    });
  }

  // ── Core connect flow (shared by auto and manual) ─────────────────────────
  function doConnect(code, cb) {
    function execute(paired) {
      setBanner("Importing into Premiere…");
      function submit(receipt) {
        setBanner("Confirming with AI Render…");
        request("POST", "/jobs/" + encodeURIComponent(receipt.job_id) + "/premiere/bridge/receipt",
          receipt, paired.token, function (err3, accepted) {
            if (err3) return cb(err3);
            pairedSession = null;
            cb(null, accepted, receipt);
          });
      }
      if (pairedSession && pairedSession.receipt) return submit(pairedSession.receipt);
      evalBridge(paired.command, function (err2, receipt) {
        if (err2) return cb(err2);
        if (!receipt || receipt.job_id !== paired.command.job_id) return cb(new Error("Premiere returned an invalid receipt."));
        pairedSession.receipt = receipt;
        submit(receipt);
      });
    }
    if (pairedSession && pairedSession.code === code) return execute(pairedSession.paired);
    // Verify the JSX engine before consuming the one-time pairing code.
    loadJsx(function (loadErr) {
      if (loadErr) return cb(loadErr);
      window.__adobe_cep__.evalScript("typeof AIRenderBridge", function (probe) {
        if (probe !== "object") return cb(new Error("Premiere bridge script did not load (" + probe + ")."));
        request("POST", "/integrations/premiere/bridge/pair", { pairing_code: code, bridge: hostInfo() }, null, function (err, paired) {
          if (err) return cb(err);
          pairedSession = { code: code, paired: paired, receipt: null };
          execute(paired);
        });
      });
    });
  }

  function finish(accepted, receipt) {
    busy = false;
    applyBtn.disabled = false;
    manualBtn.disabled = false;
    hideJob();

    var state  = accepted.state || "unknown";
    var seq    = (receipt.sequence && receipt.sequence.imported) ? "Sequence ✓" : "Sequence ✗";
    var ren    = (receipt.render_reference && receipt.render_reference.imported) ? "Render ✓" : "Render ✗";
    var capOk  = receipt.captions && receipt.captions.imported;
    var capPl  = receipt.captions && receipt.captions.placed;
    var cap    = capOk ? (capPl ? "Captions ✓" : "Captions: needs placement") : "Captions ✗";
    var summary = seq + " · " + ren + " · " + cap;
    var extras = [].concat(receipt.errors || [], receipt.warnings || []).join("\n");
    var msg = state.charAt(0).toUpperCase() + state.slice(1) + "\n" + summary + (extras ? "\n\n" + extras : "");

    if (state === "completed") { setDot("ok"); setBanner(msg, "ok"); }
    else if (state === "partial") { setDot(""); setBanner(msg, "partial"); }
    else { setDot("error"); setBanner(msg, "error"); }

    // resume polling after a delay
    setTimeout(startPolling, 8000);
  }

  function handleError(err) {
    busy = false;
    applyBtn.disabled = false;
    manualBtn.disabled = false;
    setDot("error");
    if (pairedSession && (err.status === 401 || err.status === 409)) {
      pairedSession = null;
      pendingCode = null;
      hideJob();
      setBanner(err.message + "\nRequest a new pairing code in AI Render.", "error");
      setTimeout(startPolling, 6000);
      return;
    }
    if (pairedSession) {
      pendingCode = pairedSession.code;
      showJob(pairedSession.paired.command.sequence_name || "Sequence", "Retry the paired operation before its 15-minute expiry");
      setBanner(err.message + "\nClick Apply to retry this paired operation.", "error");
    } else {
      setBanner(err.message, "error");
    }
    setTimeout(startPolling, 6000);
  }

  // ── Apply button ──────────────────────────────────────────────────────────
  applyBtn.addEventListener("click", function () {
    if (busy || !pendingCode) return;
    busy = true;
    applyBtn.disabled = true;
    setDot("");
    setBanner("Pairing with AI Render…");
    doConnect(pendingCode, function (err, accepted, receipt) {
      if (err) return handleError(err);
      finish(accepted, receipt);
    });
  });

  // ── Manual connect ────────────────────────────────────────────────────────
  manualBtn.addEventListener("click", function () {
    var code = manualCode.value.trim().toUpperCase();
    if (!code) return;
    if (busy) return;
    busy = true;
    manualBtn.disabled = true;
    applyBtn.disabled = true;
    stopPolling();
    setBanner("Connecting…");
    doConnect(code, function (err, accepted, receipt) {
      if (err) return handleError(err);
      finish(accepted, receipt);
    });
  });

  // ── Auto-poll ─────────────────────────────────────────────────────────────
  function stopPolling() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }

  function poll() {
    if (busy) { pollTimer = setTimeout(poll, 3000); return; }

    request("GET", "/integrations/premiere/bridge/pending", null, null, function (err, data) {
      if (err) {
        setDot("idle");
        setBanner("AI Render not reachable — start the backend on port " + portInput.value + ".", "error");
        pollTimer = setTimeout(poll, 5000);
        return;
      }

      if (data.pending) {
        pendingCode = data.pairing_code;
        setDot("");
        setBanner("New job ready — click Apply to import into Premiere.", "watching");
        showJob(data.sequence_name || "Sequence", "Job " + data.job_id + " · expires in " + Math.round(data.expires_in_seconds / 60) + " min");
      } else if (pairedSession) {
        pendingCode = pairedSession.code;
        showJob(pairedSession.paired.command.sequence_name || "Sequence", "Paired operation ready to retry");
      } else {
        if (!busy) {
          setDot("");
          setBanner("Watching for jobs…", "watching");
          hideJob();
        }
      }

      pollTimer = setTimeout(poll, 3000);
    });
  }

  function startPolling() {
    stopPolling();
    pollTimer = setTimeout(poll, 0);
  }

  startPolling();

}());
