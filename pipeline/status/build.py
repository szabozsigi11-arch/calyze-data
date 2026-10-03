"""A nyilvános állapotoldal előállítása a napi lenyomatokból.

Az oldal adatot nem közöl — csak azt, hogy mi futott le, mikor, és mi a
becslés-csomag ujjlenyomata. Ez az, amit a licenc nélkül is szabad mutatni,
és pont ez az, ami a commit–reveal bizonyítékhoz kell: bárki láthatja, hogy
egy adott napi csomag lenyomata hónapokkal korábban rögzült.

Futtatás: `uv run python -m pipeline.status.build`
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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


def load_manifests(root: Path = MANIFESTS) -> list[Manifest]:
    items: list[Manifest] = []
    for path in sorted(root.glob("*/*.json")):
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


@dataclass(frozen=True)
class Asset:
    """Egy eszközosztály az oldalon: saját lenyomat-mappa, naptár és határidő."""

    key: str
    title: str
    note: str
    root: Path
    #: az első nap, amelyre élő becslést vártunk (előtte nincs „kiesett” nap)
    live_from: date
    #: a várt napok `start`-tól `end`-ig, a saját naptár szerint
    days: Callable[[date, date], list[date]]
    #: eddig kellett a lenyomatnak elkészülnie (utána a nap kiesett vagy késett)
    deadline: Callable[[date], datetime]


def _equity_deadline(day: date) -> datetime:
    """A következő tőzsdenap nyitása (docs/elo-futas.md)."""
    import pandas as pd

    from pipeline.calendar import calendar

    cal = calendar()
    return cal.session_open(cal.next_session(pd.Timestamp(day))).to_pydatetime()


def _crypto_deadline(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1, hours=6)


def _fx_deadline(day: date) -> datetime:
    from pipeline.fx.calendar import fixing_at

    return fixing_at(day) + timedelta(hours=6)


def _bonds_deadline(day: date) -> datetime:
    from pipeline.bonds.calendar import snapshot_at

    return snapshot_at(day) + timedelta(hours=6)


def _equity_days(start: date, end: date) -> list[date]:
    from pipeline.calendar import sessions

    return sessions(start, end)


def _every_day(start: date, end: date) -> list[date]:
    return [start + timedelta(days=k) for k in range((end - start).days + 1)]


def _fx_days(start: date, end: date) -> list[date]:
    from pipeline.fx.calendar import target_days

    return target_days(start, end)


def _bond_days(start: date, end: date) -> list[date]:
    from pipeline.bonds.calendar import bond_days

    return bond_days(start, end)


ASSETS = (
    Asset(
        "equity",
        "Stocks and ETFs",
        "One row per NYSE session. The fingerprint must be committed before the next session opens.",
        MANIFESTS,
        date(2026, 9, 18),
        _equity_days,
        _equity_deadline,
    ),
    Asset(
        "crypto",
        "Crypto",
        "One row per UTC day. Live only if fingerprinted within six hours of 00:00 UTC.",
        REPO / "manifests-crypto",
        date(2026, 10, 2),
        _every_day,
        _crypto_deadline,
    ),
    Asset(
        "fx",
        "Currencies",
        "One row per ECB fixing (TARGET business days). Live only within six hours of the 14:10 CET fixing.",
        REPO / "manifests-fx",
        date(2026, 10, 5),
        _fx_days,
        _fx_deadline,
    ),
    Asset(
        "bonds",
        "Treasury yields",
        "One row per Treasury business day. Live only within six hours of the 3:30 pm ET snapshot.",
        REPO / "manifests-bonds",
        date(2026, 10, 5),
        _bond_days,
        _bonds_deadline,
    ),
)


def missed_days(asset: Asset, manifests: list[Manifest], now: datetime) -> list[date]:
    """Az élő kezdet óta várt napok, amelyek határideje lejárt, és nincs lenyomatuk."""
    seen = {m.session for m in manifests}
    today = now.astimezone(UTC).date()
    if asset.live_from > today:
        return []
    return [
        d
        for d in asset.days(asset.live_from, today)
        if d not in seen and asset.deadline(d) <= now.astimezone(UTC)
    ]


def late(m: Manifest, deadline: Callable[[date], datetime] | None) -> bool:
    """A lenyomat a határidő után készült (docs/elo-futas.md, 2.)."""
    if deadline is None or not m.made_at:
        return False
    return datetime.fromisoformat(m.made_at) > deadline(m.session)


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


@dataclass(frozen=True)
class Section:
    asset: Asset | None
    title: str
    note: str
    manifests: list[Manifest]
    missed: list[date]


FLAG_PARTIAL = (
    '<span class="flag" title="The source covered only part of the universe that day; '
    'the estimates are kept as they were made.">partial</span>'
)
FLAG_LATE = (
    '<span class="flag" title="Fingerprinted after the deadline; kept in the record and '
    'listed in docs/elo-futas.md.">late</span>'
)
FLAG_MISSED = (
    '<span class="flag" title="No fingerprint was committed before the deadline. '
    'Missed days are not filled in later.">missed</span>'
)


def _rows(section: Section) -> str:
    deadline = section.asset.deadline if section.asset is not None else None
    items: list[tuple[date, str]] = []
    for m in section.manifests:
        flags = (FLAG_PARTIAL if partial(m) else "") + (FLAG_LATE if late(m, deadline) else "")
        items.append(
            (
                m.session,
                f"""        <tr{' class="partial"' if partial(m) else ""}>
          <td class="session">{escape(m.session.isoformat())}{flags}</td>
          <td class="num">{m.instruments}</td>
          <td class="num">{m.forecasts}</td>
          <td class="model">{escape(m.model)}</td>
          <td class="hash" title="{escape(m.sha256)}">{escape(m.sha256[:16])}<span class="dim">…</span></td>
        </tr>""",
            )
        )
    for d in section.missed:
        items.append(
            (
                d,
                f"""        <tr class="missed">
          <td class="session">{escape(d.isoformat())}{FLAG_MISSED}</td>
          <td class="num dim">–</td>
          <td class="num dim">–</td>
          <td class="model dim">–</td>
          <td class="hash dim">no fingerprint</td>
        </tr>""",
            )
        )
    if not items:
        return '        <tr><td colspan="5" class="dim">No session yet.</td></tr>'
    return "\n".join(row for _, row in sorted(items, key=lambda x: x[0], reverse=True))


HEADER = (
    '<tr><th>Session</th><th class="num">Instruments</th><th class="num">Forecasts</th>'
    "<th>Model</th><th>SHA-256</th></tr>"
)


def _section_html(section: Section) -> str:
    recorded = len(section.manifests)
    summary = f"{recorded} recorded · {len(section.missed)} missed"
    return f"""  <section>
    <h2>{escape(section.title)}</h2>
    <p class="note">{escape(section.note)} <span class="dim">{escape(summary)}</span></p>
    <div class="wrap"><table>
      <thead>
        {HEADER}
      </thead>
      <tbody>
{_rows(section)}
      </tbody>
    </table></div>
  </section>"""


def render(manifests: list[Manifest], today: date, sections: list[Section] | None = None) -> str:
    """Az oldal. `manifests` a részvényes lenyomatok (a fejléc frissessége ebből);
    `sections` mind a négy eszközosztály — ha nincs megadva, csak a részvényes."""
    latest = manifests[0] if manifests else None
    state, sentence = freshness(latest, today)
    if sections is None:
        sections = [Section(None, "Stocks and ETFs", ASSETS[0].note, manifests, [])]
    every = [m for sec in sections for m in sec.manifests]
    generated = datetime.now(UTC).replace(microsecond=0).isoformat()
    return Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        state=state,
        sentence=escape(sentence),
        sessions=len(every),
        forecasts=sum(m.forecasts for m in every),
        missed=sum(len(sec.missed) for sec in sections),
        sections="\n".join(_section_html(sec) for sec in sections),
        generated=escape(generated),
    )


def build_sections(now: datetime) -> list[Section]:
    out = []
    for asset in ASSETS:
        manifests = load_manifests(asset.root)
        out.append(Section(asset, asset.title, asset.note, manifests, missed_days(asset, manifests, now)))
    return out


def main() -> None:
    now = datetime.now(UTC)
    sections = build_sections(now)
    manifests = sections[0].manifests
    html = render(manifests, now.date(), sections)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"allapotoldal: {OUT.relative_to(REPO)} ({sum(len(x.manifests) for x in sections)} lenyomat)")


if __name__ == "__main__":
    main()
