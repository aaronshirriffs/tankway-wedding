#!/usr/bin/env python3
"""Safely insert the /wedding/ location blocks into the live nginx default site.

Idempotent: does nothing if /wedding/ is already present. Inserts immediately
before the existing `location /suppliers/` block, which only exists inside the
tools.tankway.co.nz HTTPS server, so the blocks land in the right server.
"""
import sys

CONF = "/etc/nginx/sites-enabled/default"
ANCHOR = "location /suppliers/"

BLOCK = """\
        # --- Tony & Kate wedding site (Flask on :5005) ---
        location /wedding/ {
                proxy_pass http://127.0.0.1:5005/;
                proxy_set_header Host $host;
                proxy_set_header X-Real-IP $remote_addr;
        }

        location /wedding/static/ {
                proxy_pass http://127.0.0.1:5005/static/;
                proxy_set_header Host $host;
                proxy_set_header X-Real-IP $remote_addr;
        }

"""

with open(CONF) as f:
    content = f.read()

if "/wedding/" in content:
    print("ALREADY_PRESENT: /wedding/ block exists; no change made.")
    sys.exit(0)

idx = content.find(ANCHOR)
if idx == -1:
    print("ERROR: anchor '%s' not found; refusing to edit." % ANCHOR)
    sys.exit(2)

# Back up to the start of the anchor line (preserve its indentation).
line_start = content.rfind("\n", 0, idx) + 1
new_content = content[:line_start] + BLOCK + content[line_start:]

with open(CONF, "w") as f:
    f.write(new_content)
print("INSERTED: /wedding/ blocks added before the /suppliers/ block.")
