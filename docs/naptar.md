# R1 naptár: ütemezett események a becslés ablakában — előre rögzített definíció

**Rögzítve:** 2026-09-27, az első jelölt becslés előtt.
**Forrás:** `spec/07` (hírrendszer, R1), `spec/06` (új modellverzió szabálya).

## 1. Mi kerül a naptárba

Csak **hivatalos, ingyenes forrásból**, a kiadó saját oldaláról vett, előre
bejelentett időpont:

| Esemény | Forrás | Időpont (New York) |
|---|---|---|
| FOMC kamatdöntés (az ülés 2. napja) | federalreserve.gov, FOMC calendars | 14:00 |
| CPI | bls.gov, CPI release schedule | 08:30 |
| Foglalkoztatási jelentés (NFP) | bls.gov, Employment Situation schedule | 08:30 |
| EKB kamatdöntés | ecb.europa.eu, Governing Council calendar | 08:15 (14:15 CET) |

Az első változat 2026-01-01 és 2027-12-31 között **50 eseményt** tartalmaz
(`pipeline/events/calendar.py`). A BLS a 2027-es CPI- és NFP-dátumokat még
nem tette közzé; amikor közzéteszi, új sorokként kerülnek be, a meglévők
nem változnak.

**Gyorsjelentések (papíronként) még nincsenek benne.** Hivatalos, ingyenes,
620 papírra kiterjedő forrást még nem választottunk; addig a felület nem
állítja, hogy az ablakban nincs gyorsjelentés — azt mondja, hogy ezt nem
figyeljük.

## 2. Mikor kap egy becslés jelölést

A becslés az `S` nap zárása után készül, és az `E` célnap zárásáig szól. Egy
`D` napra bejelentett esemény akkor esik az ablakba, ha

> `S < D' ≤ E`, ahol `D'` az első kereskedési nap `D`-n vagy utána.

Az `S` napon, zárás előtt közölt esemény már benne van az árban, ezért nem
számít. A jelölés (`calendar_flag`) a becslés-csomagba kerül az események
azonosítóival, a becsléssel együtt, a napi lenyomat alá.

## 3. Mit NEM csinálunk most

**A sáv nem szélesedik.** Az a modell megváltoztatása lenne, ezért csak új
modellverzióként jöhet, előre rögzített szabállyal, és a régi verzió
eredményei külön megmaradnak (`spec/06`).

## 4. Mit mérünk később (feltáró, nem verdikt)

Amikor mindkét csoportban legalább 30 lezárt becslés van horizontonként:
a jelölt és a nem jelölt becslések találati aránya, Brier-pontszáma és
sáv-lefedettsége, a szokásos baseline-nal. Ebből dől el, kell-e az új
modellverzió. Ez feltáró összevetés: FDR-korrekcióval, és nem kerül a
főverdiktbe.
