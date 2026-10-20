# Forgatókönyv: becslés „ha nem jön váratlan hír”

**Rögzítve:** 2026-10-20, az első mérés előtt. Forrás: a tulajdonos kérése és
válaszai (2026-10-19, a privát repó `docs/terv-forgatokonyv.md`).

## 1. Mit jelent a „hír”

**Váratlan hír = a sokk-detektor jelzése** (`docs/sokk-detektor.md`, 1.) az
ablak bármelyik napján: papír-jel (forgalom, rés, mozgás) vagy piaci jel
(VIX-ugrás, keresztpiaci sokk). A múltra ugyanazok a vektoros jelek, mint a
hír-arénában (`pipeline/newsarena/signals.py`, illetve az eszközosztályok
`*_frames` függvényei). **A naptári esemény nem hír:** a CPI havonta jön, így
egy hónapnál hosszabb ablakot szinte mind kizárná; a felület felsorolja őket.

Az ablak a becslés napja **utáni** h saját nap (a becslés napjának hírét a
becslés már látta). Ahol az ablak még nem zárult le, nincs ítélet.

## 2. A feltételes becslés

A modell pontbecslése (`expected_return`) és skálája (`scale`, a 20 napos
volatilitás a horizont hosszára) a napi csomagból jön, változatlanul. Csak a
normalizált hibák `(y − pont) / skála` eloszlása szűkül a hírmentes ablakokra:

- 90%-os sáv: `pont ± q · skála`, ahol `q` a hírmentes |hibák| 90%-os
  kvantilise;
- emelkedési esély: `1 − F(−pont / skála)`, ahol `F` a hírmentes hibák
  empirikus eloszlásfüggvénye (199 kvantilisből, lineárisan).

A kettő ugyanabból az eloszlásból jön, ezért nem mondhat ellent egymásnak
(2026-09-19-i döntés). Izotón kalibráció itt nincs; ezért mérjük külön.

**Feltételezett piaci állapot:** a hibák csak a választott állapotú (nyugodt /
normál / feszült) napok hírmentes ablakaiból. A pontbecslés ekkor is a mai: a
modellt nem futtatjuk újra egy kitalált állapottal.

## 3. Mérés

Foldonként előre: a korábbi foldok hírmentes ablakaiból kalibrálunk (legalább
300 ablak), és a következő fold hírmentes ablakain pontozunk.

- irány-találat a naiv baseline ellen (`compare`, blokk-bootstrap a horizonnal);
- a sáv lefedettsége a névleges 90%-hoz (`coverage_verdict`);
- **saját FDR-család** eszközosztályonként (`scope = scenario-<osztály>`), a
  fő rekordot nem érinti; azon belül a bővített időtávok (1, 120 nap) külön.
- 30 hírmentes ablak alatt nincs eloszlás és nincs százalék.

Deviza: csak a fő (euró és dollár elleni) párokon, mint a fő rekord.

## 4. Mit közlünk

`<osztály>/scenario.json` (a kapu mögött): horizontonként és állapotonként a
kvantilisek, a hírmentes ablakok hányada (`calm_share`), papíronként a saját
hányad (30 lezárt ablak alatt üres), és a mérés. A felület mindig mellé teszi
a feltétel nélküli becslést és a baseline-t, és kiírja, hogy az ilyen ablak a
múltban milyen gyakori volt.

## 5. Ami még hátravan

A rögzítés (időbélyeg, módosíthatatlan) és az élő pontozás: lezáráskor, ha a
feltétel teljesült, a baseline ellen; ha nem, „feltétel nem teljesült”
jelöléssel, darabszámként.
