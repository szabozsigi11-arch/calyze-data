# Időtávok: 1, 5, 20, 60 és 120 kereskedési nap

Bevezetve: 2026-10-19. A korábbi dokumentumok 5/20/60 napot írnak; ahol ez a
lap mást mond, ez az újabb.

## 1. Mi változott

| Időtáv | Felületi címke | Mérési család |
|---|---|---|
| 1 nap | 1 day | bővített |
| 5 nap | 1 week | régi (core) |
| 20 nap | 1 month | régi (core) |
| 60 nap | 3 months | régi (core) |
| 120 nap | 6 months | bővített |

Kripton a nap naptári nap, devizán EKB-fixálás, kötvényen kötvénynap; a
számolás minden eszközosztályon ugyanaz (`pipeline/model/config.py`, `HORIZONS`).

## 2. Külön FDR-család

Az `apply_fdr` az összevetéseket a horizontjuk szerint két családra bontja
(`fdr_family`), és családonként korrigál. Így az 1 és a 120 napos időtáv
bevétele a meglévő 5/20/60 verdikteket nem szigorítja utólag (teszt:
`test_the_extended_horizons_do_not_change_the_core_family`). Minden összevetés
viszi, hány tesztre korrigáltunk a saját családjában (`n_tests`).

## 3. Ami a régi három időtávon marad

- **Konfluencia-motor:** a tesztelt családja a mérés előtt rögzült
  (`docs/konfluencia.md`); új időtáv új keresés lenne.

Az indikátor- és minta-aréna, a modell-aréna kihívói, a laborok és a négy
eszközosztály modellje mind az öt időtávon fut.

## 4. Bevezetés

A napi becslés a régi három időtáv modelljét követeli meg; a bővített
időtáv modellje az első heti tanításig hiányozhat, addig kimarad
(`pipeline/model/loading.py`, figyelmeztetés a naplóban:
`model_missing_extended_horizon`). Az első 120 napos élő verdikt legkorábban
kb. 7 hónap múlva jön (120 nap a lezárásig + 30 lezárt becslés); addig a
felület „Not enough data”-t ír.

## 5. Mire számíts

Az 1 napos becslés várhatóan alig jobb a pénzfeldobásnál: a napi mozgás
túlnyomórészt zaj. A felület ezt kimondja, nem tompítja.
