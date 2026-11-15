"""sonzaix/_tokens.py — Token default buat provider bundled.

Token ini dipakai sebagai FALLBACK kalau env var (MELOLO_TOKEN, dll) tidak diset.
Kenapa di-bundle: biar Fi-x-Zam jalan langsung di lokal Windows / VPS
tanpa perlu setup token manual.

NOTE: Token ini sensitif. Kalau repo public, pertimbangkan:
  - Jadikan repo private, ATAU
  - Rotasi token secara berkala, ATAU
  - Override via env var MELOLO_TOKEN (diutamakan di atas nilai di sini).
"""

# Token Melolo / proxy sonzaix (dipakai cashdrama, rapidtv, melolo, dll)
MELOLO_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2YWY3ZjQxMzVmNTRmM2NmMGFjYzQ3ZjUiLCJlbWFpbCI6InN4LmVtYmVkLjQ0NDIxNUBtYWlsaW5hdG9yLmNvbSIsIm5hbWUiOiJFbWJlZCIsInNjb3BlIjoidXNlciIsImlhdCI6MTc5NDYzNDc3MSwiZXhwIjoxNzk3MjI2NzcxLCJlcG9jaCI6MCwiZGV2IjoiZW1iZWRkZWQtZGV2In0.COSE7XVrSdJsaVIVWrJfPUHiFmDwXCNRDjfdq1DqZoM"
