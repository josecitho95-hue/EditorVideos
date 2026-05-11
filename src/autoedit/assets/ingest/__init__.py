"""Asset ingestors — download and index assets from external sources.

Available ingestors
-------------------
- :mod:`~autoedit.assets.ingest.twitch_emotes`  BTTV + 7TV + FFZ (no auth)
- :mod:`~autoedit.assets.ingest.freesound`       Freesound SFX  (FREESOUND_API_KEY)
- :mod:`~autoedit.assets.ingest.pixabay`         Pixabay images (PIXABAY_API_KEY)

Each module exposes a ``run(dest_dir, retrieval, **kwargs) -> int`` function
that downloads, registers, and indexes new assets and returns the count of
newly added items (already-known assets are skipped via source_url dedup).
"""
