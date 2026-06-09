/* ===========================================================================
   Tony & Kate — vanilla JS: countdown, form handling, fade-in, admin panel.
   =========================================================================== */
(function () {
  "use strict";

  /* --- Countdown ---------------------------------------------------------- */
  function initCountdown() {
    const box = document.getElementById("countdown");
    if (!box) return;
    const married = document.getElementById("countdown-married");
    const festive = document.getElementById("countdown-festive");
    // All anchored to Fiji time (UTC+12).
    const ds = box.dataset.wedding;
    const ceremony = new Date(ds + "T16:00:00+12:00").getTime();   // counted down to
    const dayStart = new Date(ds + "T00:00:00+12:00").getTime();   // wedding date begins
    const dayEnd = dayStart + 86400000;                            // the day after begins
    const nums = {
      days: box.querySelector('[data-unit="days"]'),
      hours: box.querySelector('[data-unit="hours"]'),
      minutes: box.querySelector('[data-unit="minutes"]'),
      seconds: box.querySelector('[data-unit="seconds"]'),
    };
    const pad = (n) => String(n).padStart(2, "0");

    function tick() {
      const now = Date.now();

      // On the wedding date itself — a festive acknowledgement all day long.
      if (now >= dayStart && now < dayEnd) {
        box.hidden = true;
        married.hidden = true;
        festive.innerHTML =
          '<span class="festive-burst">🌺 🥂 🎉</span>' +
          '<span class="festive-headline">Today’s the day!</span>' +
          '<span class="festive-sub">Tony &amp; Kate are getting married in Fiji</span>';
        festive.hidden = false;
        clearInterval(timer);
        return;
      }

      // After the wedding day — count the days of marriage.
      if (now >= dayEnd) {
        box.hidden = true;
        festive.hidden = true;
        const daysMarried = Math.floor((now - dayStart) / 86400000);
        married.innerHTML =
          'Married in Fiji <strong>·</strong> ' +
          daysMarried + ' day' + (daysMarried === 1 ? '' : 's') + ' of happily ever after';
        married.hidden = false;
        clearInterval(timer);
        return;
      }

      // Before the wedding — live countdown to the ceremony.
      const diff = ceremony - now;
      const d = Math.floor(diff / 86400000);
      const h = Math.floor((diff % 86400000) / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      nums.days.textContent = d;
      nums.hours.textContent = pad(h);
      nums.minutes.textContent = pad(m);
      nums.seconds.textContent = pad(s);
    }
    tick();
    const timer = setInterval(tick, 1000);
  }

  /* --- Fade-in on scroll -------------------------------------------------- */
  function initFadeIn() {
    const items = document.querySelectorAll(".fade-in");
    if (!items.length) return;
    if (!("IntersectionObserver" in window)) {
      items.forEach((el) => el.classList.add("visible"));
      return;
    }
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("visible");
            obs.unobserve(e.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    items.forEach((el) => obs.observe(el));
  }

  function showMsg(el, text, ok) {
    el.textContent = text;
    el.className = "form-msg " + (ok ? "ok" : "error");
    el.hidden = false;
  }

  function escapeHtml(str) {
    const d = document.createElement("div");
    d.textContent = str == null ? "" : str;
    return d.innerHTML;
  }

  /* --- Photo upload form -------------------------------------------------- */
  function initPhotoForm() {
    const form = document.getElementById("photo-form");
    if (!form) return;
    const msg = document.getElementById("photo-msg");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = form.querySelector("button");
      btn.disabled = true;
      try {
        const res = await fetch(form.action || window.location.pathname, {
          method: "POST",
          body: new FormData(form),
          headers: { "X-Requested-With": "fetch" },
        });
        const data = await res.json();
        showMsg(msg, data.message, data.ok);
        if (data.ok) form.reset();
      } catch (_) {
        showMsg(msg, "Something went wrong. Please try again.", false);
      } finally {
        btn.disabled = false;
      }
    });
  }

  /* --- Wish form (auto-approved, prepend live) ---------------------------- */
  function initWishForm() {
    const form = document.getElementById("wish-form");
    if (!form) return;
    const msg = document.getElementById("wish-msg");
    const wall = document.getElementById("wish-wall");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = form.querySelector("button");
      btn.disabled = true;
      try {
        const res = await fetch(form.action || window.location.pathname, {
          method: "POST",
          body: new FormData(form),
          headers: { "X-Requested-With": "fetch" },
        });
        const data = await res.json();
        showMsg(msg, data.message, data.ok);
        if (data.ok && data.wish) {
          const empty = document.getElementById("wish-empty");
          if (empty) empty.remove();
          const card = document.createElement("article");
          card.className = "wish-card fade-in";
          card.innerHTML =
            '<p class="wish-text">' + escapeHtml(data.wish.message) + "</p>" +
            '<div class="wish-meta"><span class="wish-name">' +
            escapeHtml(data.wish.name) +
            '</span><span class="wish-time">' + escapeHtml(data.wish.timeago) +
            "</span></div>";
          wall.prepend(card);
          requestAnimationFrame(() => card.classList.add("visible"));
          form.reset();
        }
      } catch (_) {
        showMsg(msg, "Something went wrong. Please try again.", false);
      } finally {
        btn.disabled = false;
      }
    });
  }

  /* --- Vault form --------------------------------------------------------- */
  function initVaultForm() {
    const form = document.getElementById("vault-form");
    if (!form) return;
    const msg = document.getElementById("vault-msg");
    const count = document.getElementById("vault-count");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = form.querySelector("button");
      btn.disabled = true;
      try {
        const res = await fetch(form.action || window.location.pathname, {
          method: "POST",
          body: new FormData(form),
          headers: { "X-Requested-With": "fetch" },
        });
        const data = await res.json();
        showMsg(msg, data.message, data.ok);
        if (data.ok) {
          if (typeof data.sealed === "number" && count) count.textContent = data.sealed;
          form.reset();
        }
      } catch (_) {
        showMsg(msg, "Something went wrong. Please try again.", false);
      } finally {
        btn.disabled = false;
      }
    });
  }

  /* --- Admin panel -------------------------------------------------------- */
  function initAdmin() {
    if (!window.WEDDING) return;
    const base = window.WEDDING.base.replace(/\/$/, "");
    const api = (path) => base + "/api" + path;

    document.querySelectorAll(".admin-tabs .tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".admin-tabs .tab").forEach((t) => t.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
        tab.classList.add("active");
        document.getElementById("panel-" + tab.dataset.tab).classList.add("active");
      });
    });

    async function post(path) {
      await fetch(api(path), { method: "POST", headers: { "X-Requested-With": "fetch" } });
    }

    function photoCard(p, withApprove) {
      const card = document.createElement("div");
      card.className = "admin-card";
      card.innerHTML =
        '<img src="' + p.cloudinary_url + '" alt="">' +
        '<div class="meta"><b>' + escapeHtml(p.uploader_name) + "</b><small>" +
        escapeHtml(p.caption || "No caption") + "</small></div>" +
        '<div class="actions">' +
        (withApprove ? '<button class="mini approve">Approve</button>' : "") +
        '<button class="mini danger">Delete</button></div>';
      if (withApprove) {
        card.querySelector(".approve").onclick = async () => { await post("/photos/" + p.id + "/approve"); loadPhotos(); };
      }
      card.querySelector(".danger").onclick = async () => {
        if (confirm("Delete this photo permanently?")) { await post("/photos/" + p.id + "/delete"); loadPhotos(); }
      };
      return card;
    }

    async function loadPhotos() {
      const data = await (await fetch(api("/photos"))).json();
      const pending = data.filter((p) => !p.approved);
      const approved = data.filter((p) => p.approved);

      [document.getElementById("badge-photos"), document.getElementById("badge-photos-head")].forEach((b) => {
        if (!b) return;
        b.textContent = pending.length;
        b.classList.toggle("show", pending.length > 0);
      });

      const pendingList = document.getElementById("photos-pending");
      pendingList.innerHTML = "";
      if (!pending.length) {
        pendingList.innerHTML = '<p class="empty">Nothing awaiting approval.</p>';
      } else {
        pending.forEach((p) => pendingList.appendChild(photoCard(p, true)));
      }

      const approvedList = document.getElementById("photos-approved");
      approvedList.innerHTML = "";
      if (!approved.length) {
        approvedList.innerHTML = '<p class="empty">No approved photos yet.</p>';
      } else {
        approved.forEach((p) => approvedList.appendChild(photoCard(p, false)));
      }
    }

    async function loadWishes() {
      const list = document.getElementById("wishes-list");
      const data = await (await fetch(api("/wishes"))).json();
      if (!data.length) { list.innerHTML = '<p class="empty">No wishes yet.</p>'; return; }
      list.innerHTML = "";
      data.forEach((w) => {
        const row = document.createElement("div");
        row.className = "admin-row";
        row.innerHTML =
          '<div class="row-body"><p>' + escapeHtml(w.message) + "</p><small>— " +
          escapeHtml(w.name) + "</small></div>" +
          '<div class="row-actions"><button class="mini danger">Delete</button></div>';
        row.querySelector(".danger").onclick = async () => {
          if (confirm("Delete this wish?")) { await post("/wishes/" + w.id + "/delete"); loadWishes(); }
        };
        list.appendChild(row);
      });
    }

    async function loadEbook() {
      const box = document.getElementById("ebook-status");
      if (!box) return;
      try {
        const s = await (await fetch(api("/ebook"))).json();
        const auto = s.auto_sent
          ? '<span class="tag delivered">already auto-sent</span>'
          : '<span class="tag">scheduled for ' + escapeHtml(s.wedding_date) + '</span>';
        const smtp = s.smtp_ready
          ? ""
          : '<p class="ebook-warn">⚠ Email isn\'t configured yet — fill in SMTP settings in .env before the wedding day, or the auto-send won\'t work.</p>';
        box.innerHTML =
          "<p><strong>" + s.photos + "</strong> photo" + (s.photos === 1 ? "" : "s") +
          " &amp; <strong>" + s.wishes + "</strong> wish" + (s.wishes === 1 ? "" : "es") +
          " will be included.</p>" +
          "<p>Auto-delivery: " + auto +
          (s.couple_email ? " to <strong>" + escapeHtml(s.couple_email) + "</strong>" : "") + "</p>" +
          smtp;
        const sendBtn = document.getElementById("ebook-send");
        if (sendBtn) sendBtn.disabled = !s.smtp_ready;
      } catch (_) {
        box.textContent = "Could not load keepsake status.";
      }
    }

    const sendBtn = document.getElementById("ebook-send");
    if (sendBtn) {
      sendBtn.addEventListener("click", async () => {
        const msg = document.getElementById("ebook-msg");
        if (!confirm("Generate and email the keepsake e-book to the couple now?")) return;
        sendBtn.disabled = true;
        const original = sendBtn.textContent;
        sendBtn.textContent = "Sending…";
        try {
          const res = await fetch(base + "/ebook/send", { method: "POST", headers: { "X-Requested-With": "fetch" } });
          const data = await res.json();
          showMsg(msg, data.message, data.ok);
        } catch (_) {
          showMsg(msg, "Something went wrong sending the e-book.", false);
        } finally {
          sendBtn.disabled = false;
          sendBtn.textContent = original;
        }
      });
    }

    loadPhotos();
    loadWishes();
    loadEbook();
  }

  /* --- Boot --------------------------------------------------------------- */
  document.addEventListener("DOMContentLoaded", function () {
    initCountdown();
    initFadeIn();
    initPhotoForm();
    initWishForm();
    initVaultForm();
    initAdmin();
  });
})();
