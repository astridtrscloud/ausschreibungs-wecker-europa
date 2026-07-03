"""Quellen-Registry – Plug-in-System für neue Quellen.

Neue Quelle hinzufügen:
1. Modul in sources/ erstellen (z.B. sources/france_boamp.py)
2. Hier importieren und in SOURCES-Liste eintragen
"""
from app.sources.ted import TEDSource
from app.sources.simap_ch import SIMAPSource
from app.sources.bund_de import BundDeSource

SOURCES = [
    TEDSource(),
    SIMAPSource(),
    BundDeSource(),
]
