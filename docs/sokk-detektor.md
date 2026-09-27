# R2 sokk-detektor, R3 besorolás, visszatartás — előre rögzített definíció

**Rögzítve:** 2026-09-27, az első jelzés előtt.
**Forrás:** `spec/07` (2–4. és 7. fejezet); a tulajdonos döntése
(2026-09-26): **napi, zárás utáni** futás, napközbeni adat nélkül.

A küszöbök innentől nem hangolhatók utólag. Ha változnak, új változatként
jönnek, dátummal, és a régi szerint mért eredmények külön megmaradnak.

## 1. Jelek (az `S` nap zárása után, napvégi adatból)

Jelölés: `r_t` a napi log-hozam a teljes hozamú sorból; `σ60`, `σ20` a
napi log-hozam szórása az `S` ELŐTTI 60 ill. 20 kereskedési napon (a mai
nap nincs benne).

**Papíronként**

| Jel | Mérés | Küszöb |
|---|---|---|
| `volume` | `(V_S − átlag60(V)) / szórás60(V)` | > 3 |
| `gap` | `|ln(open_S / close_{S−1})| / σ60` | > 2 |
| `move` | `|r_S| / σ20` | > 2,5 |

A `gap` jelet felosztás napján nem számoljuk (a nyers ár ott ugrik, a
papír nem).

**Piaci szinten**

| Jel | Mérés | Küszöb |
|---|---|---|
| `vix` | a VIX napi változása (a FRED-ből, **egy nap késéssel** — a sor másnap jelenik meg) | > +20% |
| `cross_market` | öt eszközosztály ETF-je — SPY (részvény), TLT (kötvény), GLD (arany), USO (olaj), UUP (dollár) — közül hánynál `|r_S| / σ60 > 2,5` | legalább 3 |

**Eltérés a spectől.** A spec a keresztpiaci jelet korreláció-mátrix
távolságaként írja le. Itt ugyanazt a kérdést egyszerűbben mérjük: *több
eszközosztály egyszerre mozdult-e ki szokatlanul*. Ez nem igényel becsült
mátrixot és távolság-küszöböt, és a felületen egy mondatban elmondható.

## 2. Besorolás (R3)

**Hatókör** (`scope`), a legszélesebb teljesülő:

| Érték | Feltétel |
|---|---|
| `global_macro` | `cross_market` vagy `vix` jelzett |
| `country` | a részvény-univerzum legalább 30%-a jelzett papíronként |
| `sector` | egy szektor (legalább 5 papír) legalább 30%-a jelzett — a szektor papírjaira |
| `instrument` | csak az adott papír jelzett |

**Tartósság** (`persistence`), előrejelzésként: `days`, ha a papíron
legalább két jel szól, vagy piaci szintű jel van; különben `intraday_noise`.
`regime_change`-et az első napon nem mondunk.

**Kezelhetőség** (`tractability`): `unknowable`, ha `vix` ÉS
`cross_market` is jelzett; különben `priceable`.

## 3. Visszatartás (spec/07, 7.)

Ha `tractability = unknowable` és `scope ∈ {country, global_macro}`, az
aznapi becslés **minden papírra visszatartva** jelenik meg: a felület nem
mutat számot, hanem kiírja, miért. **A becslés ettől még elkészül, és a
lenyomat alá kerül** — különben nem lehetne utólag megmérni, jogos volt-e a
visszatartás. Az időgép ugyanúgy visszatartva mutatja, ahogy aznap látszott.

A spec másik feltételét (a rezsim túl messze van a tanító időszaktól) még nem
vezetjük be; ahhoz előbb egy távolság-mértéket kell rögzíteni.

## 4. Mérés (a hír-aréna alapja)

Minden jelzés előrejelzés arra, hogy a következő napokban nagyobb lesz a
mozgás.

- **Találat:** a következő 5 kereskedési nap realizált volatilitása
  (napi log-hozamok szórása) nagyobb a jelzés előtti `σ20`-nál.
- **Baseline:** ugyanez az arány a jelzés nélküli papír-napokon, ugyanabban
  az időszakban.
- **Visszatartás jogos**, ha a SPY következő 5 napi realizált volatilitása
  legalább 1,5-szerese a jelzés előtti `σ20`-nak.
- A verdikt a szokásos szabály szerint (30 alatt Not enough data, ±0,5 pont,
  FDR). A tartósság-előrejelzést ugyanezzel a mércével mérjük.

## 5. Amit nem csinál

Nem jósol irányt, nem mond „vegyél” vagy „adj el” jelet, és nem olvas híreket
a jelzéshez. A hírek (H8) csak utána, címkézni jönnek.
