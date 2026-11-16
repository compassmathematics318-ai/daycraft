"""Portable calendar exports with UTC timestamps and escaped event text."""
import csv
from datetime import datetime, timezone
from io import StringIO


def escaped(value):
    return str(value or "").replace("\\", "\\\\").replace("\r\n", "\\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,").replace("\r", "")


def location_label(block, locations):
    mode = block.get("location_mode", "required" if block.get("location_id") else "unspecified")
    if mode == "remote":
        return "Remote / online"
    if mode == "unspecified":
        return "Location unspecified"
    key = block.get("resolved_location_id") or block.get("location_id")
    place = locations.get(key, {})
    substituted = bool(block.get("resolved_location_id") and key != block.get("location_id"))
    building = place.get("building") if substituted else block.get("building") or place.get("building")
    room = place.get("room") if substituted else block.get("room") or place.get("room")
    details = [place.get("name"), place.get("address"), building]
    if room:
        details.append(f"Room {room}")
    if place.get("floor"):
        details.append(f"Floor {place['floor']}")
    if place.get("entrance"):
        details.append(place["entrance"])
    label = ", ".join(dict.fromkeys(str(item) for item in details if item))
    return label + (" (preferred venue)" if mode == "preferred" and not block.get("resolved_location_id") else "")


def ics(schedule, locations):
    names = {item["id"]: item for item in locations}
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Schedule Builder//Daily Planner//EN", "CALSCALE:GREGORIAN"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for block in schedule["blocks"]:
        if block.get("status") == "skipped":
            continue
        start = datetime.fromisoformat(block["start"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        end = datetime.fromisoformat(block["end"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines.extend(["BEGIN:VEVENT", f"UID:{block['id']}@schedule-builder.local", f"DTSTAMP:{stamp}", f"DTSTART:{start}", f"DTEND:{end}", f"SUMMARY:{escaped(block['title'])}", f"DESCRIPTION:{escaped(block.get('rationale'))}", f"LOCATION:{escaped(location_label(block, names))}", "END:VEVENT"])
    lines.append("END:VCALENDAR")
    # RFC5545 folds by UTF-8 octets, preserving multibyte characters.
    folded = []
    for line in lines:
        current = ""
        for char in line:
            if len((current + char).encode("utf-8")) > 74:
                folded.append(current)
                current = " "
            current += char
        folded.append(current)
    return "\r\n".join(folded) + "\r\n"


def csv_export(schedule, locations):
    names = {item["id"]: item for item in locations}
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["Title", "Kind", "Start", "End", "Location", "Status", "Rationale"])
    for block in schedule["blocks"]:
        row = [block["title"], block["kind"], block["start"], block["end"], location_label(block, names), block.get("status", "todo"), block.get("rationale", "")]
        # Prevent spreadsheet formula execution when a user opens the CSV.
        writer.writerow(["'" + str(value) if str(value).startswith(("=", "+", "-", "@")) else value for value in row])
    return stream.getvalue()
