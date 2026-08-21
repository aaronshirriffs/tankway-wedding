# Deployment notes

## Live deployment

As of 21 August 2026:

| | |
|---|---|
| Live domain | **kateandtony.co.nz** |
| Host | DigitalOcean droplet `tankway-server` (Ubuntu 24.04 LTS) |
| App directory | `/root/wedding` |
| Process | `gunicorn -w 2 -b 127.0.0.1:5005 app:app` via `wedding.service` |
| Deploy method | manual `git pull` on the server |

One thing in this repo is **out of date**: `app.py` and `nginx-wedding.conf`
both describe the site as living at `tools.tankway.co.nz/wedding/`. The live
domain is `kateandtony.co.nz`.

`main` was reconciled with the deployed code on 21 August 2026. The server's
four unpushed commits — the Big Reveal home page, the admin bulk actions, and
the removal of the e-book concept — were merged in and are now the basis of
`main`. A copy of the server's state as pushed that day is preserved on the
`server-live` branch.

The server itself has **not** pulled since. It is one `git pull` behind `main`,
and still carries a hand-appended `.fade-in{opacity:1!important}` line in its
working copy from the recovery described below.

## 21 August 2026 — album and wishes rendered invisible

**Symptom.** Photos and wishes occupied their full layout height but were
invisible, stuck at `opacity: 0`. Safari Reader Mode showed the content
normally, confirming it was in the DOM and hidden by CSS. It began on the
wedding date and had not worked since.

**Cause.** Two defects compounding:

1. `initCountdown()` in `static/main.js` called `tick()` synchronously *before*
   `const timer` was initialised. Both post-wedding branches of `tick()` call
   `clearInterval(timer)`, so from the wedding date onward the first call hit
   the temporal dead zone and threw `Cannot access 'timer' before
   initialization`. That throw escaped the `DOMContentLoaded` handler and
   aborted every init registered after it — the fade-in reveal, the photo
   upload form and the wish form all silently stopped running. Before the
   wedding date `tick()` took the countdown branch, never touched `timer`, and
   nothing broke; this is why the failure appeared to start on the day.
2. The reveal had no fallback. `.fade-in` set `opacity: 0` in CSS, and the only
   thing that ever restored it was a `.visible` class added by an
   IntersectionObserver callback. With the script dead, the content stayed
   hidden permanently.

Reproduced in Chromium against the real assets: with a past wedding date the
page threw and every `.fade-in` measured `opacity: 0`; with a future date there
was no error and they measured `opacity: 1`.

**Fix** (commit `2be4549`, on `main`):

* Declare the interval handle before the first tick and stop the clock through
  a guarded helper, so the countdown can end without throwing.
* Make `.fade-in` visible at rest and perform the entrance with a
  self-completing CSS keyframe animation. Final opacity no longer depends on
  JavaScript, scroll position or an observer; the observer was removed.
* Honour `prefers-reduced-motion`.
* Boot each init independently so one failure cannot take down the rest.

Verified with the script blocked outright, under reduced motion, and for items
far below the fold.

## What was actually run on the server

`git pull` failed with divergent branches, so the fixed assets were applied
directly instead:

```sh
cd /root/wedding
git checkout origin/main -- static
```

That overwrote the server's own `static/style.css` with this repo's version.
Because this repo's CSS only targets `.masonry-item` markup, nothing then
constrained the photo widths in the server's own reveal-list template, and
since `app.py` stores Cloudinary's untransformed `secure_url`, the photos
rendered at their full multi-thousand-pixel natural size.

Recovered by restoring the server's own stylesheet and forcing the reveal
visible over the top of it:

```sh
git checkout HEAD -- static/style.css
echo '.fade-in{opacity:1!important;transform:none!important}' >> static/style.css
```

The site was confirmed working after this. Note that the override is an
uncommitted local edit on the server; it is not represented anywhere in this
repository.

## Outstanding

* **Deploy `main` to the server.** Once `git pull` succeeds there, the
  hand-appended `!important` override at the end of `static/style.css` can be
  deleted — commit `93cf217` supersedes it properly.
* **Correct the stale domain references** in `app.py` and `nginx-wedding.conf`.
* **Serve resized images.** `app.py` stores Cloudinary's `secure_url`, the
  untouched original, so every reveal view downloads full-resolution camera
  files — several megabytes each. Requesting a width-limited `f_auto,q_auto`
  derivative instead would cut page weight dramatically. This is the single
  biggest improvement left.
* **Automate deployment**, so changes reach the server without hand-editing
  files over a console.
