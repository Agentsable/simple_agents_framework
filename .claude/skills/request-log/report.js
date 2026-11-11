/* Request report renderer (source: .claude/skills/request-log/report.js; build_artifact.py copies it to
   requests_and_response/assets/report.js with the diff2html stylesheet inlined as D2H_CSS).
   Reads window.REPORT_DERIVED (the request's derived.js, written by metrics.py) and the report's own
   sections, and draws: the review box and meta line in the header, the KPI strip, the timeline
   (Mermaid gantt) and the diff (diff2html, loaded when the section is opened). The page stays
   readable without this script: every written section is static HTML. */
(function () {
  "use strict";
  var D = window.REPORT_DERIVED || null;
  var $ = function (s) { return document.querySelector(s); };
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  var CDN = {
    mermaid: "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js",
    d2h: "https://cdn.jsdelivr.net/npm/diff2html@3.4.48/bundles/js/diff2html-ui.min.js"
  };
  function load(src) {
    return new Promise(function (ok, fail) {
      var s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = fail; document.head.appendChild(s);
    });
  }
  function fmtTokens(n) {
    if (!n && n !== 0) return "—";
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M";
    if (n >= 1e3) return Math.round(n / 1e3) + "k";
    return String(n);
  }
  function fmtMinutes(m) {
    if (m == null) return "—";
    if (m < 60) return m + "<small> min</small>";
    return Math.floor(m / 60) + "<small> h </small>" + (m % 60) + "<small> min</small>";
  }
  function hhmm(iso) { return iso ? iso.slice(11, 16) : ""; }
  function dark() {
    var t = document.documentElement.getAttribute("data-theme");
    return t ? t === "dark" : window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
  }

  /* ---- header: review box ---- */
  var review = $("#review");
  var verdict = review ? (review.getAttribute("data-verdict") || "") : "";
  var box = $("#verdict-box");
  if (box) {
    var problems = 0, reviewed = "";
    if (review) {
      var heads = review.querySelectorAll("h3");
      for (var i = 0; i < heads.length; i++) {
        if (/problems/i.test(heads[i].textContent) && heads[i].nextElementSibling) {
          var lis = heads[i].nextElementSibling.querySelectorAll("li");
          for (var j = 0; j < lis.length; j++) if (!/^\s*none\b/i.test(lis[j].textContent)) problems++;
        }
      }
      var m = review.textContent.match(/reviewed\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})/i);
      reviewed = m ? m[1] : "";
    }
    var label = verdict || "not reviewed";
    var cls = verdict === "PASS" ? "pass" : verdict === "FAIL" ? "fail" : verdict === "PENDING" ? "pending" : "";
    var sub = verdict === "PASS" || verdict === "FAIL" ? problems + " problem" + (problems === 1 ? "" : "s") : verdict === "PENDING" ? "review running" : "";
    if (D && D.review_rounds) sub += (sub ? " · " : "") + D.review_rounds + " round" + (D.review_rounds === 1 ? "" : "s");
    box.innerHTML = '<div class="lbl">Evidence review</div><div><span class="vpill ' + cls + '">' + esc(label) + "</span></div>" +
      '<div class="vsub">' + esc(sub) + (reviewed ? "<br>" + esc(reviewed) + " · evidence-reviewer" : "") + "</div>";
  }

  if (!D) return;
  var c = D.counts || {}, k = D.commit || {}, t = D.tokens || {};

  /* ---- header: meta line ---- */
  var meta = $("#metaline");
  if (meta) {
    var parts = ["<span>Started <b>" + esc((D.started || "").slice(0, 16).replace("T", " ")) + "</b></span>"];
    if (D.ended && !D.in_progress) parts.push("<span>Finished <b>" + esc(hhmm(D.ended)) + "</b></span>");
    if (D.in_progress) parts.push("<span><b>In progress</b></span>");
    if (k.sha) parts.push('<span>Commit <b class="mono">' + esc(k.sha) + '</b> on <b class="mono">' + esc(D.branch) + "</b></span>");
    meta.innerHTML = parts.join("");
  }

  /* ---- log summary: totals of the covered requests, and the list of them ---- */
  var S = D.kind === "summary" ? (D.summary || {}) : null;
  if (S) {
    var sk = $("#kpis");
    if (sk) {
      var p = S.period || {}, sc = [];
      var put = function (key, val, detail) { sc.push('<div class="kpi"><div class="k">' + key + '</div><div class="v">' + val + '</div><div class="d">' + (detail || "") + "</div></div>"); };
      put("Requests covered", String(S.requests || 0), esc((p.from || "").slice(0, 10) + " – " + (p.to || "").slice(0, 10)));
      put("Time", fmtMinutes(S.minutes), "covered requests, overlaps counted once");
      put("Tokens", S.tokens ? esc(fmtTokens(S.tokens)) : "—", S.tokens ? "covered requests" : "no transcript data");
      put("Files changed", String(S.files || 0), "distinct files across their commits");
      put("Errors", String(S.errors || 0), (S.open_preventions || 0) + " preventions carried over");
      put("Review rounds", String(S.review_rounds || 0), "");
      sk.innerHTML = sc.join("");
    }
    var anchor = $("#tasks");
    if (anchor && S.covers && S.covers.length) {
      var cbox = document.createElement("div"); cbox.className = "derived"; cbox.id = "covers";
      cbox.innerHTML = "<h2>Covered requests</h2><p class=\"note\">Removed from the folder by this cleanup; every full report is kept under Past tasks.</p><ol>" +
        S.covers.map(function (x) { return '<li><a href="../past.html#' + esc(x.slug) + '">' + esc(x.title) + "</a> <small>" + esc(x.started) + " · " + esc(x.slug) + "</small></li>"; }).join("") + "</ol>";
      anchor.parentNode.insertBefore(cbox, anchor);
    }
  }

  /* ---- KPI strip ---- */
  var kpis = S ? null : $("#kpis");
  if (kpis) {
    var cards = [];
    var add = function (key, val, detail) { cards.push('<div class="kpi"><div class="k">' + key + '</div><div class="v">' + val + '</div><div class="d">' + (detail || "") + "</div></div>"); };
    add("Duration", fmtMinutes(D.minutes), D.in_progress ? "so far" : "started to commit");
    add("Tokens", esc(fmtTokens(t.total)), t.total ? fmtTokens(t.output) + " output · " + (t.messages || 0) + " messages" + (t.cost_usd != null && t.cost_usd !== undefined ? " · $" + t.cost_usd : "") : "no transcript data");
    add("Tasks", String(c.tasks || 0), c.tasks ? "in the plan" : "");
    add("Errors", String(c.errors || 0), c.errors ? '<span class="ok">' + (c.applied || 0) + " applied</span> · <span class=\"warn\">" + (c.suggested || 0) + " suggested</span>" : "none logged");
    add("Files changed", String(k.files || 0), k.files ? (k.added || 0) + " added · " + (k.modified || 0) + " modified" + (k.deleted ? " · " + k.deleted + " deleted" : "") : (D.in_progress ? "not committed" : ""));
    add("Review rounds", String(D.review_rounds || 0), D.review_rounds > 1 ? (D.review_rounds - 1) + " FAIL before the PASS" : "");
    var sizes = c.sizes || {}, sz = Object.keys(sizes).map(function (s) { return sizes[s] + " " + s; }).join(" · ");
    add("Follow-ups", String(c.follow_ups || 0), sz);
    kpis.innerHTML = cards.join("");
  }

  /* ---- timeline ---- */
  var tl = $("#timeline");
  if (tl) {
    var bars = D.timeline || [];
    if (!bars.length) {
      tl.innerHTML = "<h2>Timeline</h2><p class=\"note\">No timeline recorded: this request predates timeline logging, or has no step marks yet.</p>";
    } else {
      var lines = ["gantt", "  dateFormat X", "  axisFormat %H:%M", "  todayMarker off"];
      bars.forEach(function (b, n) {
        var s = Math.floor(Date.parse(b.start) / 1000), e = Math.max(Math.floor(Date.parse(b.end) / 1000), s + 30);
        var tag = b.kind === "fail" ? "crit, " : b.kind === "review" ? "done, " : b.kind === "ship" ? "milestone, " : "";
        if (b.kind === "ship") tag = "active, ";
        var label = String(b.label).replace(/[:#;]/g, " ").slice(0, 60) + " (" + b.minutes + " min)";
        lines.push("  " + label + " :" + tag + "b" + n + ", " + s + ", " + e);
      });
      tl.innerHTML = "<h2>Timeline</h2><p class=\"note\">Plan, logged steps, review rounds (red = FAIL) and shipping. " + (D.timeline_events || 0) + " recorded events.</p>" +
        '<div class="scroll"><pre class="mermaid"></pre></div>';
      tl.querySelector("pre").textContent = lines.join("\n");
      load(CDN.mermaid).then(function () {
        window.mermaid.initialize({ startOnLoad: false, theme: dark() ? "dark" : "default", gantt: { barHeight: 22, fontSize: 13, leftPadding: 220 } });
        return window.mermaid.run({ nodes: tl.querySelectorAll("pre.mermaid") });
      }).catch(function () {
        var p = document.createElement("p"); p.className = "note";
        p.textContent = "The timeline library could not load; the bars are listed instead: " + bars.map(function (b) { return b.label + " " + hhmm(b.start) + "–" + hhmm(b.end); }).join(", ");
        tl.appendChild(p);
      });
    }
  }

  /* ---- diff ---- */
  var df = $("#diff");
  if (df) {
    if (!D.diff) {
      df.innerHTML = "<h2>Diff</h2><p class=\"note\">" + (k.sha ? "Commit " + esc(k.sha) + " changed only the request log itself (reports and evidence), which this view leaves out." : "No code changes recorded yet.") + "</p>";
    } else {
      df.innerHTML = "<h2>Diff</h2><details class=\"diff\"><summary>Show the " + esc(k.diff_label || "diff") + " · " + (k.files || "") + " files, request log excluded" +
        (k.diff_truncated ? " (truncated)" : "") + '</summary><div class="d2h-host"><p class="note">Loading…</p></div></details>';
      var det = df.querySelector("details"), drawn = false;
      det.addEventListener("toggle", function () {
        if (!det.open || drawn) return;
        drawn = true;
        if (window.D2H_CSS && !document.getElementById("d2h-css")) {
          var st = document.createElement("style"); st.id = "d2h-css"; st.textContent = window.D2H_CSS; document.head.appendChild(st);
        }
        var host = df.querySelector(".d2h-host");
        load(CDN.d2h).then(function () {
          host.innerHTML = "";
          var ui = new window.Diff2HtmlUI(host, D.diff, { drawFileList: true, matching: "lines", outputFormat: window.innerWidth < 900 ? "line-by-line" : "side-by-side", highlight: false, colorScheme: dark() ? "dark" : "light" });
          ui.draw();
        }).catch(function () {
          host.innerHTML = "";
          var pre = document.createElement("pre"); pre.textContent = D.diff; host.appendChild(pre);
        });
      });
    }
  }
})();
