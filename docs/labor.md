# Labor (backtest) — definíció

**Rögzítve:** 2026-10-02. **Ez a dokumentum a mérés előtt készült.**

A labor azt mutatja meg, mi lett volna, ha valaki a modell becsléseit
szabályként követi (`spec/03`, 3.6). Ez **backtest**, nem bizonyíték: a
felületen minden futás mellett ott áll, hogy *„this is a backtest; the live
number is X”*, ahol X a modell élő találati aránya ugyanazon a horizonton.

Nem befektetési tanács, és nem ajánl stratégiát: azt méri, mennyit ért volna
egy egyszerű szabály a múltban, a teljes rács minden pontjával együtt — a
gyenge eredményekkel is.

---

## 1. Az adat

Az `lgbm-core` **mintán kívüli** becslései a purged walk-forward backtestből
(`modell-arena.md`, 3.): minden becslés olyan modelltől jön, ami a becslés
napja utáni adatot nem látott. A becslés valószínűsége (`prob_up`) és a
megvalósult `h` napos log teljes hozam.

## 2. A szabály

- **Átsúlyozás** minden `h`-adik kereskedési napon (nem átfedő időszakok).
- **Pozíció:** az univerzum minden papírja, amelyre a modell emelkedési
  valószínűsége legalább a küszöb; egyenlő súllyal. Csak long. Ha egy
  papír sem éri el, az időszak készpénzben telik (0 hozam).
- **Költség:** a beállított oda-vissza költség minden pozícióra, minden
  időszakban (konzervatív: mintha minden időszakban teljesen cserélődne).
- **Összevetés (buy & hold):** ugyanannak az univerzumnak minden papírja,
  egyenlő súllyal, ugyanazokra az időszakokra, költség nélkül.

## 3. A rács — a teljes, előre rögzített

| Paraméter | Értékek |
|---|---|
| Univerzum | `all` (mind), `sp500`, `midcap`, `etf` |
| Horizont (`h`) | 5, 20, 60 nap |
| Küszöb | 0,55 · 0,60 · 0,65 · 0,70 |
| Költség (oda-vissza) | 0 · 0,10% · 0,25% |

Ez **144** futás. A felület mindet elérhetővé teszi, és kiírja, hogy 144
közül a legjobbat kiválasztani maga is túlillesztés.

## 4. Mérés és verdikt

- Időszakonként a többlethozam: szabály − buy & hold.
- A verdikt a szokásos szabály (`spec/06`): 30 időszak alatt „Too early”;
  blokk-bootstrap p-érték; **Benjamini–Hochberg a teljes 144-es rácson**; a
  „Same” sáv ±0,5 pont időszakonként.
- Kiírva: évesített hozam és volatilitás mindkét oldalra, legnagyobb
  visszaesés, az időszakok hány százalékában volt jobb a szabály, átlagos
  pozíciószám, és hány időszak telt készpénzben.

## 5. Kötelező figyelmeztetések a felületen

- **Look-ahead:** a becslések mintán kívüliek (purged walk-forward); a
  költség és a végrehajtás ennek ellenére idealizált (záróáron, csúszás
  nélkül).
- **Túlélési torzítás:** az univerzum a mai papírokból áll; ami közben
  kiesett vagy csődbe ment, hiányzik — ez minden hosszú távú számot felfelé
  húz.
- **Túlillesztés:** 144 beállítás közül a legjobb kiválasztása önmagában
  hízelgő eredményt ad; a BH-korrekció ezt részben, nem teljesen kezeli.

## 6. Amit ez a változat szándékosan nem tud

**Szabadon választott paraméter (egyedi futás).** A felület a rács pontjai
közül választ, és mind a 144 előre ki van számolva. A spec egyedi, sorba
állított futást is említ; az a több felhasználós, korlátozott CPU-jú
helyzetre kell, és egy feladatsort, adatbázis-táblát és értesítést igényel.
A zárt futásban nem indokolt; ha lesz rá igény, ugyanerre a számításra épül.
