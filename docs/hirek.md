# Hírek: címkézés hivatalos közleményekből (H8, első változat)

**Rögzítve:** 2026-09-27.

- **Mikor:** csak ha az `S` napon piaci sokk-jel volt (`docs/sokk-detektor.md`),
  vagy ütemezett esemény esett rá (`docs/naptar.md`). Máskor nem kérünk le
  semmit.
- **Mire:** címkézni, nem jelezni. A közlemény nem változtat a becslésen, és
  nem kerül a mérésbe.
- **Honnan:** a kiadók saját, nyilvános hírcsatornái: Federal Reserve (összes
  sajtóközlemény), Európai Központi Bank. A BLS csatornája gépi lekérést tilt;
  nem kerüljük meg, ezért kimarad.
- **Mit tárolunk:** cím (legfeljebb 200 karakter), forrás, időpont, link — a
  link csak a kiadó saját domainjére mutathat. A közlemény szövegét nem.
- **Ablak:** az `S` napot megelőző nap 00:00 UTC-től `S` utáni nap 06:00
  UTC-ig közzétett tételek, legfeljebb 10.

**Még nincs:** papíronkénti (vállalati) hír. Ahhoz forrást kell választani
(pl. SEC EDGAR, GDELT), aminek licenc- és adatkezelési kérdései vannak — ez a
tulajdonos döntése.
