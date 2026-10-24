"""Export the parser lexicon as ``datasets/ruvr/lexicon.tsv`` (variant, category, canonical)."""

from __future__ import annotations

from pathlib import Path

from jikimi_server.search import lexicon as L


def main() -> None:
    rows = []
    for cat, table in (
        ("color", L.COLORS),
        ("vehicle", L.VEHICLES),
        ("place", L.PLACE_WORDS),
        ("alert_type", L.ALERT_TYPE_WORDS),
        ("day_part", L.DAY_PART_WORDS),
    ):
        for canon, words in table.items():
            rows += [(w, cat, canon) for w in words]
    rows += [(w, "person", "person") for w in L.PERSON_WORDS]
    rows += [(w, "number", str(n)) for w, n in L.NUMBERS.items()]
    rows += [(w, "day_ref", str(n)) for w, n in L.DAY_REFS.items()]
    rows += [(w, "weekday", str(n)) for w, n in L.WEEKDAYS.items()]
    out = Path("datasets/ruvr/lexicon.tsv")
    out.write_text(
        "variant\tcategory\tcanonical\n" + "\n".join("\t".join(r) for r in sorted(set(rows))) + "\n", encoding="utf-8"
    )
    print(f"wrote {out} ({len(set(rows))} variants)")


if __name__ == "__main__":
    main()
