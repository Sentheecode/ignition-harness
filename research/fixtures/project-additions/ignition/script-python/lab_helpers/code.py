def status_text(value):
    return "Script V2 OK: %.1f" % float(value)

def db_rows():
    rows = system.db.runPrepQuery("SELECT id, label, reading FROM samples ORDER BY id", [], "HarnessLabDB")
    return [{"id": int(row["id"]), "label": str(row["label"]), "reading": float(row["reading"])} for row in rows]
