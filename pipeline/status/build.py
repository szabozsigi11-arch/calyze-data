"""A nyilvános állapotoldal előállítása a napi lenyomatokból.

Az oldal adatot nem közöl — csak azt, hogy mi futott le, mikor, és mi a
becslés-csomag ujjlenyomata. Ez az, amit a licenc nélkül is szabad mutatni,
és pont ez az, ami a commit–reveal bizonyítékhoz kell: bárki láthatja, hogy
egy adott napi csomag lenyomata hónapokkal korábban rögzült.

Futtatás: `uv run python -m pipeline.status.build`
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path
from string import Template

REPO = Path(__file__).resolve().parents[2]
MANIFESTS = REPO / "manifests"
TEMPLATE = Path(__file__).with_name("template.html")
OUT = REPO / "site" / "index.html"

# Ennyi nap némaság után az oldal kimondja, hogy a futás elmaradt. Két
# kereskedési nap + hétvége belefér; ennél tovább már hiba.
STALE_AFTER_DAYS = 4

# Ez alatt a lefedettség alatt a nap „részleges": a forrás aznap az univerzum
# töredékére adott árat. Nem töröljük — amit mértünk, az marad —, de a
# táblázat megjelöli, különben egy 1 papíros nap ugyanúgy néz ki, mint a többi.
MIN_SESSION_COVERAGE = 0.8


@dataclass(frozen=True)
class Manifest:
    session: date
    made_at: str
    instruments: int
    universe: int
    forecasts: int
    sha256: str
    model: str
    status: str


def load_manifests() -> list[Manifest]:
    items: list[Manifest] = []
    for path in sorted(MANIFESTS.glob("*/*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        items.append(
            Manifest(
                session=date.fromisoformat(raw["session"]),
                made_at=raw.get("made_at", ""),
                instruments=int(raw.get("instruments", 0)),
                universe=int(raw.get("universe", 0)),
                forecasts=int(raw.get("forecasts", 0)),
                sha256=str(raw.get("sha256", "")),
                model=f"{raw.get('model_family', '?')} {raw.get('model_version', '')}".strip(),
                status=str(raw.get("status", "")),
            )
        )
    return sorted(items, key=lambda m: m.session, reverse=True)


def partial(m: Manifest) -> bool:
    """Részleges-e a nap: a forrás az univerzum töredékére adott csak árat."""
    if m.universe <= 0:
        return False
    return m.instruments < m.universe * MIN_SESSION_COVERAGE


def freshness(latest: Manifest | None, today: date) -> tuple[str, str]:
    """A fejléc állapotsora. Ha nincs adat vagy elavult, azt kimondja."""
    if latest is None:
        return ("no-runs", "No forecast package has been recorded yet.")
    age = (today - latest.session).days
    if age > STALE_AFTER_DAYS:
        return ("stale", f"The last recorded session is {latest.session.isoformat()}, {age} days ago.")
    return ("current", f"Last recorded session: {latest.session.isoformat()}.")


def render(manifests: list[Manifest], today: date) -> str:
    latest = manifests[0] if manifests else None
    state, sentence = freshness(latest, today)
    total_forecasts = sum(m.forecasts for m in manifests)

    rows = "\n".join(
        f"""        <tr{' class="partial"' if partial(m) else ""}>
          <td class="session">{escape(m.session.isoformat())}</td>
          <td class="num">{m.instruments}{
            '<span class="flag" title="The source covered only part of the universe '
            'that day; the estimates are kept as they were made.">partial</span>'
            if partial(m)
            else ""
        }</td>
          <td class="num">{m.forecasts}</td>
          <td class="model">{escape(m.model)}</td>
          <td class="hash" title="{escape(m.sha256)}">{escape(m.sha256[:16])}<span class="dim">…</span></td>
        </tr>"""
        for m in manifests
    )

    generated = datetime.now(UTC).replace(microsecond=0).isoformat()

    return Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        state=state,
        sentence=escape(sentence),
        sessions=len(manifests),
        forecasts=total_forecasts,
        instruments=latest.instruments if latest else 0,
        rows=rows,
        generated=escape(generated),
    )


def main() -> None:
    manifests = load_manifests()
    html = render(manifests, datetime.now(UTC).date())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"allapotoldal: {OUT.relative_to(REPO)} ({len(manifests)} lenyomat)")


if __name__ == "__main__":
    main()
