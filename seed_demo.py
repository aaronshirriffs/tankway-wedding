"""Seed demo data into wedding.db, tagged so it can be cleanly removed.

Everything inserted here is marked with a [DEMO] sentinel in a way the
clear script keys off, so real submissions are never touched.
"""
import sqlite3
from datetime import datetime, timezone, timedelta

DB = "/root/wedding/wedding.db"
DEMO_TAG = "::demo::"  # hidden marker stored in fields we can filter on

def ago(days=0, hours=0):
    return (datetime.now(timezone.utc) - timedelta(days=days, hours=hours)).isoformat()

wishes = [
    ("Aunty Mere", "Wishing you both a lifetime of laughter, love and sun-soaked mornings. So happy for you!", ago(0, 1)),
    ("Dave & Sarah", "From your first date to forever — we couldn't be happier. See you on the beach!", ago(0, 5)),
    ("The Wilson Family", "May your marriage be as warm and beautiful as a Fiji sunset.", ago(1)),
    ("Grandma Joan", "I've watched you grow into the kindest people. Tony, look after my Kate. Kate, you've found a good one.", ago(2)),
    ("Liam", "Can't wait to celebrate with you two legends. Get ready for some questionable dance moves.", ago(3)),
    ("Priya", "So much love for you both. Here's to the adventure of a lifetime!", ago(4)),
    ("Uncle Rob", "Marriage advice: she's always right. Congratulations you two!", ago(5)),
    ("Emma C", "Counting down the days! You two are the most beautiful couple. Love you both endlessly.", ago(6)),
    ("Josh & Mia", "To Tony & Kate — two of our favourite humans. Fiji won't know what hit it.", ago(8)),
    ("Nana", "My heart is so full. Wishing you every happiness, my darlings.", ago(11)),
    ("The Office Crew", "We'll hold the fort while you're away living your best life. Congrats!!", ago(14)),
    ("Tania", "Such joy seeing you find each other. Here's to white sand and forever.", ago(18)),
    ("Mark", "Best wishes to the happy couple — may your love story be as endless as the ocean.", ago(23)),
    ("Hannah & Pete", "We are SO excited for you. Bula! Bring on the celebrations.", ago(29)),
    ("Cousin Tom", "Congratulations you two! Save me a seat at the bar. Love always.", ago(40)),
]

# Real placeholder images at varying aspect ratios so the masonry looks natural.
photos_approved = [
    ("Sophie", "Golden hour on the beach", "https://picsum.photos/seed/wed1/700/900"),
    ("Dave", "The whole gang together", "https://picsum.photos/seed/wed2/900/600"),
    ("Aunty Mere", "Their engagement day", "https://picsum.photos/seed/wed3/700/700"),
    ("Liam", "Sunset toast", "https://picsum.photos/seed/wed4/700/1000"),
    ("Priya", "Palm trees and blue skies", "https://picsum.photos/seed/wed5/900/650"),
    ("Emma C", "Kate looking radiant", "https://picsum.photos/seed/wed6/700/850"),
    ("Josh", "Beach bonfire", "https://picsum.photos/seed/wed7/800/600"),
    ("Hannah", "First dance practice", "https://picsum.photos/seed/wed8/700/950"),
]
photos_pending = [
    ("Cousin Tom", "Blurry but happy!", "https://picsum.photos/seed/wed9/800/700"),
    ("Mark", "From the welcome dinner", "https://picsum.photos/seed/wed10/700/800"),
]

db = sqlite3.connect(DB)
for name, msg, ts in wishes:
    db.execute(
        "INSERT INTO wishes (name, message, submitted_at, approved) VALUES (?, ?, ?, 1)",
        (name, msg + " " + DEMO_TAG, ts),
    )
for name, cap, url in photos_approved:
    db.execute(
        "INSERT INTO photos (uploader_name, cloudinary_url, cloudinary_public_id, caption, submitted_at, approved) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (name, url, DEMO_TAG, cap, ago(1)),
    )
for name, cap, url in photos_pending:
    db.execute(
        "INSERT INTO photos (uploader_name, cloudinary_url, cloudinary_public_id, caption, submitted_at, approved) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        (name, url, DEMO_TAG, cap, ago(0, 2)),
    )
db.commit()
print("wishes:", db.execute("SELECT COUNT(*) FROM wishes").fetchone()[0])
print("approved photos:", db.execute("SELECT COUNT(*) FROM photos WHERE approved=1").fetchone()[0])
print("pending photos:", db.execute("SELECT COUNT(*) FROM photos WHERE approved=0").fetchone()[0])
db.close()
