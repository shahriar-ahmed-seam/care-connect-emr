# Backend assets

Place `clinic-logo.png` here (PNG, ~600×200, on a white/transparent background).
It is embedded at the top of generated prescription PDFs.

When present, wire it by passing its path to the PDF generator
(`clinic_logo_path`) in `app/api/prescriptions.py`; the renderer already handles
a missing logo gracefully, so the PDF works with or without it.
