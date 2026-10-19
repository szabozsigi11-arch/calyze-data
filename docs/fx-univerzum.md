# A deviza-univerzum és az adat — előre rögzítve

**Rögzítve:** 2026-10-02, **mielőtt egyetlen deviza-becslés vagy -mérés
készült volna.** Forrás: `docs/terv-6-fazis.md` (F1–F2).

---

## 1. Miért nem a Yahoo

A terv a Yahoo napi devizagyertyájával számolt, azzal a kikötéssel, hogy a
zárás időpontját előbb ellenőrizzük. Az ellenőrzés (2026-10-02) szerint a
Yahoo devizás „napi záró” **nem a nap végi ár**: a nyitó és a záró szinte
azonos, és a záró egy nap eleji pillanatfelvétel (az EURUSD 2026-09-29-i
„zárója” pontosan az előző esti 20:00 UTC-s órás záró; az USDJPY
2026-10-01-i „zárója” a 09-30 23:00 UTC-s árhoz áll legközelebb). Ha erre
építenénk, egy nap végén készült becslés ablakának nagy része már lezajlott
volna. **A Yahoo napi devizaadata ezért nem forrás.**

## 2. A forrás: az EKB referencia-árfolyama

- **Mi:** az Európai Központi Bank napi referencia-árfolyama (`EXR`,
  `SP00.A`), a jegybankok napi egyeztetéséből, **14:10 CET-kor rögzítve**,
  kb. 16:00 CET-kor közzétéve, 1999 óta.
- **Licenc:** az EKB statisztikai adata forrásmegjelöléssel szabadon
  felhasználható és terjeszthető; ha módosítjuk (pl. keresztárfolyamot
  számolunk belőle), azt ki kell mondani. A felület ezt kiírja: *„Source:
  ECB euro reference rates; cross rates computed by Calyze.”*
- **Ár:** naponta **egyetlen** árfolyam (fixálás), nincs nyitó, maximum,
  minimum és volumen. A tárban a négy ár ugyanaz, a volumen üres; a
  nyitó/maximum/minimum vagy volumen alapú szabályok és jelek devizán
  **kimaradnak** (az arénáknál a definíció ezt tételesen felsorolja).

## 3. Az univerzum: 28 pár

A nyolc fő deviza — **EUR, USD, JPY, GBP, CHF, AUD, CAD, NZD** — összes
párja: 8·7/2 = **28**. Az EKB a hét nem-euró devizát az euró ellen közli; a
többi pár keresztárfolyam: `A/B = (B per EUR) / (A per EUR)`.

**Elnevezés (piaci szokás):** az alap deviza a sorrendben előrébb álló:
EUR > GBP > AUD > NZD > USD > CAD > CHF > JPY (pl. `EURUSD`, `GBPJPY`,
`AUDNZD`, `USDJPY`). Az árfolyam: hány egység a második devizából egy
egység az elsőért.

**Azonosítók:** `CZ00671`-től, a fenti sorrendből képzett párok
lexikografikus rendjében (először az EUR-os párok, aztán a GBP-sek …).

## 4. A „nap” és a naptár

- **Egy nap = egy EKB-fixálás.** A záró a 14:10 CET-es referencia-árfolyam.
- **Kereskedési nap = TARGET-munkanap:** hétfőtől péntekig, kivéve
  újév, nagypéntek, húsvéthétfő, május 1., december 25. és 26. — ezeken
  az EKB nem közöl árfolyamot, és ez **nem hiány**.
- A horizont TARGET-munkanapban számít (5 / 20 / 60).
- **Hiány:** ha egy TARGET-munkanapra nincs közölt árfolyam, az hiányként
  jelölődik a futás jelentésében, és **nem pótoljuk**.

## 5. Az élő becslés ideje

A becslés a fixálás **közzététele után** készül. **Csak akkor számít élőnek,
ha a fixálás (14:10 CET) után legfeljebb 6 órán belül elkészül**; a
devizapiac közben is kereskedik, ezért a késői lenyomat utólagos
válogatásnak látszana (ugyanaz a szabály, mint kriptón,
`kripto-modell.md`, 6.). A kimaradt nap nem pótolható.

## 7. Bővítés: 128 pár (2026-10-19)

A tulajdonos kérése (2026-10-19): több deviza, köztük a forint. **Rögzítve az
új párok első letöltése előtt.**

- **Új devizák:** az EKB minden további, ma is közölt devizája, kivéve a
  rögzített árfolyamúakat (DKK, BGN, HKD: a jegybank sávban tartja, nincs mit
  előre jelezni) és a megszűnteket (euróra váltott devizák; a rubelt 2022
  óta nem közlik). Ez 20 deviza: CZK, HUF, PLN, RON, SEK, NOK, ISK, TRY, CNY,
  SGD, KRW, INR, IDR, MYR, PHP, THB, ILS, MXN, BRL, ZAR.
- **Párok:** mindegyik az euró, a dollár, a font, a frank és a jen ellen
  (20 × 5 = 100). Elnevezés: a fő deviza az alap (EUR/HUF), a jen a jegyzés
  oldalán (HUF/JPY), ahogy a piacon.
- **Azonosítók:** `CZ00706`–`CZ00805`, devizánként a fenti sorrendben. A régi
  28 azonosító változatlan.
- **Két mérési család.** Az euró és a dollár elleni pár (40) a fő
  deviza-rekordba tartozik. A font, a frank és a jen elleni pár (60,
  szegmens: `fx_cross`) **saját családot** kap (`scope = fx_cross`): becslés és
  verdikt van rá, de nagyrészt két másik pár különbsége, ezért a fő rekord,
  a fő backtest és az indikátor-, minta- és hír-aréna mintáját nem növeli.
- **Izlandi korona:** az EKB 2008-11 és 2018-02 között nem közölte. A múlt a
  szünet utáni első naptól (2018-02-01) él; különben a technikai mutatók egy
  kilencéves változást egyetlen napnak látnának.
- **Ellenőrizve (2026-10-19):** a 20 sor 1999-től (a BRL, CNY, ILS, INR
  2000-01-13-tól) hiány nélkül; a 2005-ös lej- és líra-átnevezés az EKB-soron
  nem okoz ugrást (az EKB visszamenőleg átszámolt).
- **A rezsim nem változik:** a hét dolláros fő párból számol, név szerint
  (`pipeline/fx/features.py`, `USD_PAIRS`).
