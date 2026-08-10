# Phase 1b — APRR gate snapping and test-pair verification

Snapped 209 APRR gates against OSRM `/nearest` (regional bfc-ara extract). 105 gates snapped further than 200 m from their `gare_master.csv` coordinates.

**Note on the 105-gate flag count:** the OSRM instance running against this report only serves the Bourgogne-Franche-Comte + Auvergne-Rhone-Alpes regional extract (Phase 1a); APRR's network extends well beyond that region (e.g. towards Paris, Tours, Reims, Verdun). Gates outside the loaded extract snap to the nearest in-extract road, tens to hundreds of km away — that is an extract-coverage artefact, not a geocoding error. The national OSRM build (Phase 3a) is required before this flag list is meaningful as a data-quality signal; until then, treat only the smaller in-region snap distances as informative.

## Gates flagged (>200 m snap distance)

| gare_id | name | snap distance (m) |
|---|---|---|
| 873 | TOURS-C/MONNAIE | 152048.3 |
| 911 | Péage de Veigné | 150398.6 |
| 912 | VEIGNE | 150398.6 |
| 292 | ESVRES | 145930.6 |
| 34 | AMBOISE CH.RENAULT | 139588.4 |
| 137 | BLERE | 133957.9 |
| 364 | Jarny | 131131.6 |
| 365 | JARNY | 130989.6 |
| 92 | Péage de Beaumont | 130803.3 |
| 93 | BEAUMONT | 130803.3 |
| 316 | Fresnes-en-Woevre | 127500.9 |
| 317 | FRESNES EN WOEVRE | 127241.8 |
| 915 | Verdun | 124280.1 |
| 916 | VERDUN | 124269.3 |
| 947 | VOIE SACRÉE | 119436.1 |
| 946 | VOIE SACREE | 119226.5 |
| 241 | Clermont-en-Argonne | 115949.8 |
| 242 | CLERMONT-EN-ARGONNE | 115649.3 |
| 834 | St-Romain-sur-Cher | 113966.7 |
| 138 | Blois | 112391.9 |
| 840 | STE MENEHOULD | 111751.2 |
| 228 | Chémery | 103002.5 |
| 672 | REIMS EST (TAISSY) | 102232.3 |
| 678 | REIMS OUEST (THILLOIS) | 101968.9 |
| 674 | REIMS NORD (ORMES) | 101820.2 |
| 516 | MER | 99784.3 |
| 679 | REIMS SUD | 99442.4 |
| 792 | St-Etienne-au-Temple | 99077.2 |
| 203 | CHALONS MOURMELON | 94567.0 |
| 202 | CHALONS - LA VEUVE | 93800.2 |
| 520 | Meung-sur-Loire | 88629.6 |
| 802 | St-Gibrien | 86763.1 |
| 272 | Dormans | 86454.7 |
| 931 | VILLEFRANCHE S/ CHER | 82981.0 |
| 533 | MONT-CHOISY | 81597.2 |
| 58 | Artenay | 79554.3 |
| 27 | ALLAINES | 79083.0 |
| 28 | Allainville | 78961.2 |
| 336 | GIDY | 77932.2 |
| 617 | Orléans nord | 77874.8 |
| 616 | ORLEANS-CENTRE | 76019.0 |
| 218 | CHÂTEAU-THIERRY | 74500.6 |
| 607 | OLIVET | 74041.9 |
| 393 | LA FOLIE-B/PARIS | 70983.3 |
| 351 | Péage de Gye | 68940.7 |
| 352 | GYE | 68940.7 |
| 561 | Péage de Montreuil-aux-Lions | 67896.1 |
| 562 | MONTREUIL AUX LIONS | 67870.4 |
| 560 | MONTREUIL (REIMS) | 67848.8 |
| 909 | VATRY | 67455.6 |
| 422 | LAMOTTE-BEUVRON | 63788.9 |
| 778 | Sommesous | 63731.6 |
| 740 | SALBRIS | 63725.3 |
| 923 | VIERZON NORD | 61604.4 |
| 246 | Colombey-les-Belles | 58521.2 |
| 922 | VIERZON EST | 58182.6 |
| 289 | Escrennes | 54101.4 |
| 290 | ESCRENNES | 53765.2 |
| 489 | LUSSE | 52528.0 |
| 906 | VALLÉE DE L'AUBE | 48341.8 |
| 799 | ST GERMAIN LES VERGNE | 43252.7 |
| 154 | BOURGES (LIM.CONC.) | 42898.0 |
| 463 | LES EPRUNES | 37910.2 |
| 302 | Péage de Fleury-en-Bière | 36606.3 |
| 303 | FLEURY-EN-BIERE | 36606.3 |
| 221 | CHATENOIS | 34944.2 |
| 71 | AUXY | 34873.8 |
| 70 | AUXY | 34603.5 |
| 889 | TULLE NORD | 34573.2 |
| 890 | TULLE NORD | 34573.2 |
| 798 | St-Germain-Laxis | 33884.4 |
| 853 | THENNELIERES | 31148.5 |
| 893 | URY | 27720.3 |
| 887 | TULLE EST | 27076.8 |
| 888 | TULLE EST | 27076.8 |
| 170 | BULGNEVILLE | 27035.9 |
| 223 | CHATILLON-LABORDE | 26686.2 |
| 689 | Robecourt | 24840.4 |
| 732 | SAINT THIBAULT | 24632.4 |
| 458 | LE TOURNEAU | 23539.8 |
| 283 | Egletons | 23447.2 |
| 284 | EGLETONS | 23447.2 |
| 549 | Montigny-le-Roi | 23016.4 |
| 425 | LANGRES NORD | 22549.5 |
| 338 | GONDREVILLE A77/N | 22139.5 |
| 339 | GONDREVILLE A77/S | 22139.5 |
| 863 | TORVILLIERS | 20648.4 |
| 305 | FONTAINEBLEAU | 18898.6 |
| 585 | NEMOURS | 16694.0 |
| 308 | FONTENAY /LOING | 16207.4 |
| 498 | Magnant | 15429.7 |
| 896 | USSEL OUEST | 13414.6 |
| 897 | USSEL OUEST | 13414.6 |
| 227 | CHAUMONT-SEMOUTIERS | 11194.8 |
| 900 | VAL DE LOING-SOUPPES | 11073.3 |
| 271 | DORDIVES | 11063.4 |
| 899 | Péage de Val de Loing barrière | 11016.3 |
| 785 | St-Amand-Montrond | 10734.1 |
| 312 | Forges | 9430.4 |
| 426 | Langres sud | 8672.8 |
| 925 | VILLE SOUS LAFERTE | 4604.2 |
| 803 | ST HILAIRE | 3080.1 |
| 894 | USSEL EST | 2474.9 |
| 895 | USSEL EST | 2474.9 |
| 507 | Marolles-sur-Seine | 2188.8 |

## 5 named test pairs (iterative-tumbling-lecun.md Phase 1b)

### 1. Dijon -> Lyon (A6 vs N6/N7)

DIJON SUD -> VILLEFRANCHE NORD: last APRR gate on A6 before the toll-free approach into Lyon.

- APRR fare: `DIJON SUD` -> `VILLEFRANCHE-NORD`, distance_km=149.15, class1=€14.1
- OSRM tolled route: distance=159850 m, duration=5685 s
- OSRM toll-free route: distance=158726 m, duration=9980 s
- Distinct toll-free alternative: YES

### 2. Paris -> Lyon (A6 vs N6)

LA FOLIE-B/PARIS -> VILLEFRANCHE NORD: the full A6 Paris-Lyon run.

- APRR fare: `LA FOLIE-B/PARIS` -> `VILLEFRANCHE-NORD`, distance_km=493.17, class1=€62.8
- OSRM tolled route: distance=372898 m, duration=13918 s
- OSRM toll-free route: distance=348908 m, duration=20631 s
- Distinct toll-free alternative: YES

### 4. Dijon -> Macon (medium-distance, parallel N6)

DIJON SUD -> MACON SUD: mid-length A6/N6 corridor segment.

- APRR fare: `DIJON SUD` -> `MACON SUD`, distance_km=118.93, class1=€11.1
- OSRM tolled route: distance=161893 m, duration=5761 s
- OSRM toll-free route: distance=129051 m, duration=8057 s
- Distinct toll-free alternative: YES

### 5. Beaune -> Macon (medium-distance, parallel N6)

BEAUNE SUD -> MACON NORD: shorter A6/N6 corridor segment.

- APRR fare: `BEAUNE SUD` -> `MACON NORD`, distance_km=74.1, class1=€6.6
- OSRM tolled route: distance=88837 m, duration=3208 s
- OSRM toll-free route: distance=88578 m, duration=5160 s
- Distinct toll-free alternative: YES

### 3. Clermont-Ferrand -> Montpellier (A75 free motorway - edge case)

No APRR gare exists south of Clermont-Ferrand: A75 is an untolled state motorway, so this pair is checked via OSRM city-centre coordinates only, not an od_pairs fare lookup. Expected result: no APRR price applies, and the tolled/toll-free routes should be near-identical (that is the point of the edge case).

- APRR fare: none (A75 carries no APRR toll gate south of Clermont-Ferrand)
- OSRM tolled route: distance=263511 m, duration=15370 s
- OSRM toll-free route: distance=263511 m, duration=15370 s
- Route changes under exclude=toll: NO (NO is expected/consistent with A75 being untolled end-to-end on this corridor; YES would mean a tolled alternative exists elsewhere on the route)

