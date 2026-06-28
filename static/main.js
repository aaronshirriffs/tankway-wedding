/* ===========================================================================
   Kate & Tony — vanilla JS: countdown, form handling, fade-in, admin panel.
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
          '<span class="festive-sub">Kate &amp; Tony are getting married in Fiji</span>';
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

    function photoCard(p) {
      const card = document.createElement("div");
      card.className = "admin-card" + (p.approved ? "" : " is-hidden");
      const toggle = p.approved
        ? '<button class="mini neutral">Hide</button>'
        : '<button class="mini approve">Show</button>';
      card.innerHTML =
        '<img src="' + p.cloudinary_url + '" alt="">' +
        '<div class="meta"><b>' + escapeHtml(p.uploader_name) + "</b><small>" +
        escapeHtml(p.caption || "No caption") + "</small></div>" +
        '<div class="actions">' + toggle +
        '<button class="mini danger">Delete</button></div>';
      card.querySelector(".neutral, .approve").onclick = async () => {
        await post("/photos/" + p.id + (p.approved ? "/hide" : "/approve"));
        loadPhotos();
      };
      card.querySelector(".danger").onclick = async () => {
        if (confirm("Delete this photo permanently?")) { await post("/photos/" + p.id + "/delete"); loadPhotos(); }
      };
      return card;
    }

    async function loadPhotos() {
      const data = await (await fetch(api("/photos"))).json();
      const inAlbum = data.filter((p) => p.approved);
      const hidden = data.filter((p) => !p.approved);

      const tabBadge = document.getElementById("badge-photos");
      if (tabBadge) { tabBadge.textContent = hidden.length; tabBadge.classList.toggle("show", hidden.length > 0); }
      const headBadge = document.getElementById("badge-photos-head");
      if (headBadge) { headBadge.textContent = inAlbum.length; headBadge.classList.toggle("show", inAlbum.length > 0); }

      const approvedList = document.getElementById("photos-approved");
      approvedList.innerHTML = inAlbum.length ? "" : '<p class="empty">No photos in the album yet.</p>';
      inAlbum.forEach((p) => approvedList.appendChild(photoCard(p)));

      const pendingList = document.getElementById("photos-pending");
      pendingList.innerHTML = hidden.length ? "" : '<p class="empty">Nothing hidden.</p>';
      hidden.forEach((p) => pendingList.appendChild(photoCard(p)));
    }

    async function loadWishes() {
      const list = document.getElementById("wishes-list");
      const data = await (await fetch(api("/wishes"))).json();
      if (!data.length) { list.innerHTML = '<p class="empty">No wishes yet.</p>'; return; }
      list.innerHTML = "";
      data.forEach((w) => {
        const row = document.createElement("div");
        row.className = "admin-row" + (w.approved ? "" : " is-hidden");
        const toggle = w.approved
          ? '<button class="mini neutral">Hide</button>'
          : '<button class="mini approve">Show</button>';
        row.innerHTML =
          '<div class="row-body"><p>' + escapeHtml(w.message) + "</p><small>— " +
          escapeHtml(w.name) + (w.approved ? "" : " · hidden") + "</small></div>" +
          '<div class="row-actions">' + toggle +
          '<button class="mini danger">Delete</button></div>';
        row.querySelector(".neutral, .approve").onclick = async () => {
          await post("/wishes/" + w.id + (w.approved ? "/hide" : "/show"));
          loadWishes();
        };
        row.querySelector(".danger").onclick = async () => {
          if (confirm("Delete this wish?")) { await post("/wishes/" + w.id + "/delete"); loadWishes(); }
        };
        list.appendChild(row);
      });
    }

    async function loadCloudUsage() {
      const box = document.getElementById("cloud-usage");
      if (!box) return;
      try {
        const s = await (await fetch(api("/cloudinary"))).json();
        if (!s.ready) { box.innerHTML = '<span class="cu-label">Cloudinary isn\'t configured yet.</span>'; return; }
        if (s.error) { box.innerHTML = '<span class="cu-label">Couldn\'t load Cloudinary usage right now.</span>'; return; }
        const pct = Math.max(0, Math.min(100, Number(s.used_percent) || 0));
        const tone = pct >= 90 ? "red" : pct >= 70 ? "amber" : "green";
        const gb = (b) => (b ? (b / 1073741824).toFixed(2) : "0.00");
        const used = (Number(s.credits_used) || 0).toFixed(2);
        const limit = s.credits_limit != null ? s.credits_limit : 25;
        box.innerHTML =
          '<div class="cu-top"><span class="cu-label">Cloudinary — storage &amp; bandwidth</span>' +
          '<span class="cu-pct ' + tone + '">' + pct.toFixed(1) + '% of free plan</span></div>' +
          '<div class="cu-bar"><span class="cu-fill ' + tone + '" style="width:' + pct + '%"></span></div>' +
          '<div class="cu-meta">' + used + ' / ' + limit + ' credits used · ' +
          gb(s.storage_bytes) + ' GB stored · ' + (s.objects || 0) + ' file' + ((s.objects === 1) ? '' : 's') +
          (pct >= 70 ? ' · <strong>nearing the free limit</strong>' : '') + '</div>';
      } catch (_) {
        box.innerHTML = '<span class="cu-label">Couldn\'t load Cloudinary usage right now.</span>';
      }
    }

    loadPhotos();
    loadWishes();
    loadCloudUsage();
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
