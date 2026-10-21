# The Rest Is History – serie-grupperer (prototype)

    pip install requests
    python build.py          # henter feed, grupperer -> out/series.json + out/feeds/<serie>.xml
    python render.py         # bygger out/index.html
    ANTHROPIC_API_KEY=... python build.py --llm   # lader Claude navngive serier uden fælles titel

- build.py: parse feed -> segmenter ("Part N"-kæder + fælles titelprefix) -> navngiv -> overrides -> output
- overrides.json: manuelle navne / opløsning af serier. Vinder altid.
- out/feeds/: ét RSS-feed pr. serie, peger på originale lydfiler.
