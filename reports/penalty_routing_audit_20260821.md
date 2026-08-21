# Penalty Routing Audit — 20260821

## Verdict: 🚫 BLOCKED

Option 3 uses `use_tolls: 0.0` (+ `toll_booth_cost: 9999` escalation) in place of the notoll Valhalla instance.

## Summary

| Status | All gates | Anchor gates (590) | Non-anchor gates |
|--------|-----------|----------------------------------|------------------|
| PASS | 90 | 35 | 55 |
| ESCALATED_PASS | 1 | 0 | 1 |
| FAIL_SHORT | 3 | 1 | 2 |
| FAIL_BLOCK | 238 | 194 | 44 |
| NO_ROUTE | 0 | 0 | 0 |
| NO_ORIGIN | 1616 | 950 | 666 |
| ERROR | 0 | 0 | 0 |
| **TOTAL** | **1948** | **1180** | **768** |

⚠️  238 FAIL_BLOCK entries require manual review before proceeding.

## Non-PASS Results

| gare_id | name | direction | status | toll_roads | toll_m | maps |
|---------|------|-----------|--------|------------|--------|------|
| 2 | ABBEVILLE EST | entry | FAIL_BLOCK | A 16 | 21789m | [map](https://www.google.com/maps/dir/50.105799,1.828902/50.102849,1.873087) |
| 2 | ABBEVILLE EST | exit | FAIL_BLOCK | A 16 | 18461m | [map](https://www.google.com/maps/dir/50.102849,1.873087/50.105799,1.828902) |
| 3 | ABBEVILLE NORD | entry | FAIL_BLOCK | A 16 | 7947m | [map](https://www.google.com/maps/dir/50.105799,1.828902/50.140078,1.808197) |
| 3 | ABBEVILLE NORD | exit | FAIL_BLOCK | A 16; E 402 | 15209m | [map](https://www.google.com/maps/dir/50.140078,1.808197/50.105799,1.828902) |
| 4 | Ablis | entry | FAIL_BLOCK | A 10; E 05; E 50; A 11; E 50 | 12370m | [map](https://www.google.com/maps/dir/48.535098,1.849400/48.526544,1.834914) |
| 4 | Ablis | exit | FAIL_BLOCK | A 11; E 50 | 19699m | [map](https://www.google.com/maps/dir/48.526544,1.834914/48.535098,1.849400) |
| 5 | ABLIS | entry | FAIL_BLOCK | A 10; E 05; E 50; A 11; E 50 | 12370m | [map](https://www.google.com/maps/dir/48.535098,1.849400/48.526544,1.834914) |
| 5 | ABLIS | exit | FAIL_BLOCK | A 11; E 50 | 19699m | [map](https://www.google.com/maps/dir/48.526544,1.834914/48.535098,1.849400) |
| 6 | Agde Pézenas | entry | FAIL_BLOCK | A 75; E 11; A 9; E 15; E 80 | 30243m | [map](https://www.google.com/maps/dir/43.456901,3.418941/43.376617,3.414270) |
| 6 | Agde Pézenas | exit | FAIL_BLOCK | A 9; E 15; E 80; D 600 | 26095m | [map](https://www.google.com/maps/dir/43.376617,3.414270/43.456901,3.418941) |
| 7 | Agen | exit | FAIL_BLOCK | A 62; E 72 | 25904m | [map](https://www.google.com/maps/dir/44.162390,0.602683/44.202304,0.631041) |
| 8 | Agen Ouest | entry | FAIL_BLOCK | A 62; E 72 | 31256m | [map](https://www.google.com/maps/dir/44.202304,0.631041/44.186283,0.540807) |
| 8 | Agen Ouest | exit | FAIL_BLOCK | A 62; E 72 | 25868m | [map](https://www.google.com/maps/dir/44.186283,0.540807/44.202304,0.631041) |
| 11 | Aiguillon | entry | FAIL_BLOCK | A 62; E 72 | 26173m | [map](https://www.google.com/maps/dir/44.297400,0.364287/44.281689,0.268855) |
| 11 | Aiguillon | exit | FAIL_BLOCK | A 62; E 72 | 22114m | [map](https://www.google.com/maps/dir/44.281689,0.268855/44.297400,0.364287) |
| 14 | AIRE-SUR-LA-LYS | entry | FAIL_BLOCK | A 26; E 15 | 8614m | [map](https://www.google.com/maps/dir/50.643784,2.403358/50.671247,2.250779) |
| 14 | AIRE-SUR-LA-LYS | exit | FAIL_BLOCK | A 26; E 15 | 22540m | [map](https://www.google.com/maps/dir/50.671247,2.250779/50.643784,2.403358) |
| 15 | AITON | exit | FAIL_BLOCK | A 43; E 70; A 430 | 11980m | [map](https://www.google.com/maps/dir/45.557904,6.242413/45.566974,6.254741) |
| 22 | Alençon | exit | FAIL_BLOCK | A 28; E 402; A 88 | 30190m | [map](https://www.google.com/maps/dir/48.397807,0.104804/48.429633,0.092012) |
| 23 | Alençon nord | entry | FAIL_BLOCK | A 28; E 402 | 18115m | [map](https://www.google.com/maps/dir/48.429633,0.092012/48.451606,0.132470) |
| 23 | Alençon nord | exit | FAIL_BLOCK | A 28; E 402; A 88 | 22484m | [map](https://www.google.com/maps/dir/48.451606,0.132470/48.429633,0.092012) |
| 24 | ALENCON NORD | entry | FAIL_BLOCK | A 28; E 402 | 18115m | [map](https://www.google.com/maps/dir/48.429633,0.092012/48.451606,0.132470) |
| 24 | ALENCON NORD | exit | FAIL_BLOCK | A 28; E 402; A 88 | 22484m | [map](https://www.google.com/maps/dir/48.451606,0.132470/48.429633,0.092012) |
| 25 | Alençon sud | exit | FAIL_BLOCK | A 28; E 402; A 88 | 29218m | [map](https://www.google.com/maps/dir/48.396606,0.111489/48.429633,0.092012) |
| 26 | ALENCON SUD | exit | FAIL_BLOCK | A 28; E 402; A 88 | 29218m | [map](https://www.google.com/maps/dir/48.396606,0.111489/48.429633,0.092012) |
| 28 | Allainville | entry | FAIL_BLOCK | A 10; E 05; E 50; A 10; E 05 | 16655m | [map](https://www.google.com/maps/dir/48.465354,1.897490/48.455294,1.911760) |
| 28 | Allainville | exit | FAIL_BLOCK | A 10; E 05 | 46292m | [map](https://www.google.com/maps/dir/48.455294,1.911760/48.465354,1.897490) |
| 29 | ALLONZIER | entry | FAIL_BLOCK | A 41; E 712; A 41 | 6800m | [map](https://www.google.com/maps/dir/45.994007,6.107365/45.990187,6.127813) |
| 29 | ALLONZIER | exit | FAIL_BLOCK | A 41; E 21; E 62 | 19550m | [map](https://www.google.com/maps/dir/45.990187,6.127813/45.994007,6.107365) |
| 31 | Ambérieu | entry | FAIL_BLOCK | A 40; E 21; E 62; A 42; E 611 | 21119m | [map](https://www.google.com/maps/dir/45.958414,5.368862/45.981506,5.311680) |
| 31 | Ambérieu | exit | FAIL_BLOCK | A 42; E 611 | 18483m | [map](https://www.google.com/maps/dir/45.981506,5.311680/45.958414,5.368862) |
| 32 | AMBERIEU EN BUGEY | entry | FAIL_BLOCK | A 40; E 21; E 62; A 42; E 611 | 21119m | [map](https://www.google.com/maps/dir/45.958414,5.368862/45.981506,5.311680) |
| 32 | AMBERIEU EN BUGEY | exit | FAIL_BLOCK | A 42; E 611 | 18483m | [map](https://www.google.com/maps/dir/45.981506,5.311680/45.958414,5.368862) |
| 35 | Amboise/Château-Renault | entry | FAIL_BLOCK | A 10; E 05; E 60 | 30678m | [map](https://www.google.com/maps/dir/47.594670,0.909328/47.546246,0.986234) |
| 35 | Amboise/Château-Renault | exit | FAIL_BLOCK | A 10; E 05; E 60 | 14179m | [map](https://www.google.com/maps/dir/47.546246,0.986234/47.594670,0.909328) |
| 37 | AMIENS NORD | entry | FAIL_BLOCK | A 16 | 18545m | [map](https://www.google.com/maps/dir/49.903041,2.292605/49.932004,2.245871) |
| 37 | AMIENS NORD | exit | FAIL_BLOCK | A 16; Avenue François Mitterrand | 6075m | [map](https://www.google.com/maps/dir/49.932004,2.245871/49.903041,2.292605) |
| 38 | AMIENS OUEST | entry | FAIL_BLOCK | Avenue François Mitterrand | 1787m | [map](https://www.google.com/maps/dir/49.903041,2.292605/49.890680,2.228691) |
| 38 | AMIENS OUEST | exit | FAIL_BLOCK | A 16 | 4091m | [map](https://www.google.com/maps/dir/49.890680,2.228691/49.903041,2.292605) |
| 40 | ANCENIS | entry | FAIL_BLOCK | A 11 | 25373m | [map](https://www.google.com/maps/dir/47.385541,-1.197594/47.400840,-1.194432) |
| 40 | ANCENIS | exit | FAIL_BLOCK | A 11; E 60 | 29301m | [map](https://www.google.com/maps/dir/47.400840,-1.194432/47.385541,-1.197594) |
| 41 | Andrézieux-Bouthéon nord | entry | FAIL_BLOCK | A 72 | 2510m | [map](https://www.google.com/maps/dir/45.532152,4.280670/45.547876,4.271073) |
| 42 | Andrézieux-Bouthéon sud | entry | FAIL_BLOCK | A 72 | 2510m | [map](https://www.google.com/maps/dir/45.532152,4.280670/45.547876,4.271073) |
| 46 | ANGERS | entry | FAIL_BLOCK | A 11; E 60 | 10499m | [map](https://www.google.com/maps/dir/47.467471,-0.561615/47.464765,-0.691621) |
| 46 | ANGERS | exit | FAIL_BLOCK | A 11; E 60 | 5920m | [map](https://www.google.com/maps/dir/47.464765,-0.691621/47.467471,-0.561615) |
| 48 | ANNECY CENTRE | entry | FAIL_BLOCK | A 41; E 712 | 2803m | [map](https://www.google.com/maps/dir/45.901584,6.125296/45.897950,6.092060) |
| 49 | ANNECY NORD | exit | FAIL_BLOCK | A 41; E 712; A 410; E 712 | 6945m | [map](https://www.google.com/maps/dir/45.938806,6.117104/45.901584,6.125296) |
| 52 | ARGENTAN OUEST | entry | FAIL_BLOCK | A 88 | 7780m | [map](https://www.google.com/maps/dir/48.729955,-0.013024/48.657152,0.087589) |
| 55 | ARLAY | entry | FAIL_BLOCK | A 39 | 44024m | [map](https://www.google.com/maps/dir/46.759650,5.542317/46.774605,5.518974) |
| 55 | ARLAY | exit | FAIL_BLOCK | A 39; A 36; E 60 | 47614m | [map](https://www.google.com/maps/dir/46.774605,5.518974/46.759650,5.542317) |
| 56 | ARRAS EST | entry | FAIL_BLOCK | A 1; E 15 | 19662m | [map](https://www.google.com/maps/dir/50.287896,2.768267/50.267933,2.867623) |
| 56 | ARRAS EST | exit | FAIL_BLOCK | A 1; E 15; E 15; A 26; E 17; E 19 | 55878m | [map](https://www.google.com/maps/dir/50.267933,2.867623/50.287896,2.768267) |
| 57 | ARRAS NORD | entry | FAIL_BLOCK | A 1; E 17; E 17; A 26; E 15 | 11314m | [map](https://www.google.com/maps/dir/50.287896,2.768267/50.349009,2.788544) |
| 57 | ARRAS NORD | exit | FAIL_BLOCK | A 26; E 15 | 12660m | [map](https://www.google.com/maps/dir/50.349009,2.788544/50.287896,2.768267) |
| 58 | Artenay | entry | FAIL_BLOCK | A 10; E 05 | 13705m | [map](https://www.google.com/maps/dir/48.076440,1.876771/48.084924,1.851642) |
| 58 | Artenay | exit | FAIL_BLOCK | A 10; E 05 | 4456m | [map](https://www.google.com/maps/dir/48.084924,1.851642/48.076440,1.876771) |
| 59 | Artix | entry | FAIL_BLOCK | E 07; A 64; E 80 | 13773m | [map](https://www.google.com/maps/dir/43.397719,-0.568770/43.397630,-0.549303) |
| 59 | Artix | exit | FAIL_BLOCK | A 64; E 80; La Pyrénéenne | 19101m | [map](https://www.google.com/maps/dir/43.397630,-0.549303/43.397719,-0.568770) |
| 61 | Aubagne | entry | FAIL_BLOCK | A 501 | 3060m | [map](https://www.google.com/maps/dir/43.301892,5.563888/43.324107,5.598551) |
| 61 | Aubagne | exit | FAIL_BLOCK | A 52 | 15002m | [map](https://www.google.com/maps/dir/43.324107,5.598551/43.301892,5.563888) |
| 63 | Aubignosc | entry | FAIL_BLOCK | Échangeur de Sisteron-Centre; A 51; E 712; Échangeur d'Aubignosc | 5932m | [map](https://www.google.com/maps/dir/44.126255,5.974309/44.127974,5.981238) |
| 63 | Aubignosc | exit | FAIL_BLOCK | Échangeur d'Aubignosc | 915m | [map](https://www.google.com/maps/dir/44.127974,5.981238/44.126255,5.974309) |
| 64 | AUMALE | entry | FAIL_BLOCK | A 29; E 44 | 43871m | [map](https://www.google.com/maps/dir/49.771602,1.747712/49.760394,1.702956) |
| 65 | Auriol | entry | FAIL_BLOCK | A 52; A 520 | 6764m | [map](https://www.google.com/maps/dir/43.360892,5.647170/43.366917,5.643613) |
| 68 | Auxerre nord | entry | FAIL_BLOCK | A 6; E 15; E 60 | 12394m | [map](https://www.google.com/maps/dir/47.790189,3.580299/47.855773,3.546657) |
| 68 | Auxerre nord | exit | FAIL_BLOCK | A 6; E 15; E 60; E 60; E 511; A 19; E 511 | 44728m | [map](https://www.google.com/maps/dir/47.855773,3.546657/47.790189,3.580299) |
| 69 | Auxerre sud | entry | FAIL_BLOCK | A 6; E 15; E 60 | 11848m | [map](https://www.google.com/maps/dir/47.790189,3.580299/47.799291,3.650191) |
| 69 | Auxerre sud | exit | FAIL_BLOCK | A 6; E 15; E 60 | 25462m | [map](https://www.google.com/maps/dir/47.799291,3.650191/47.790189,3.580299) |
| 70 | AUXY | exit | FAIL_BLOCK | Eco-Autoroute | 740m | [map](https://www.google.com/maps/dir/48.084840,2.468302/48.103199,2.476734) |
| 71 | AUXY | entry | FAIL_BLOCK | A 19; E 60 | 22066m | [map](https://www.google.com/maps/dir/48.103199,2.476734/48.082846,2.465321) |
| 71 | AUXY | exit | FAIL_BLOCK | A 19; E 60; A 19 | 53136m | [map](https://www.google.com/maps/dir/48.082846,2.465321/48.103199,2.476734) |
| 72 | Avallon | entry | FAIL_BLOCK | A 6; E 15; E 60 | 26408m | [map](https://www.google.com/maps/dir/47.484856,3.917279/47.515206,3.992451) |
| 72 | Avallon | exit | FAIL_BLOCK | A 6; E 15; E 60 | 19787m | [map](https://www.google.com/maps/dir/47.515206,3.992451/47.484856,3.917279) |
| 73 | Avignon nord | entry | FAIL_BLOCK | A 7; E 714 | 9028m | [map](https://www.google.com/maps/dir/43.936345,4.848861/43.979549,4.893091) |
| 73 | Avignon nord | exit | FAIL_BLOCK | A 7; E 714 | 6064m | [map](https://www.google.com/maps/dir/43.979549,4.893091/43.936345,4.848861) |
| 74 | Avignon sud | entry | FAIL_BLOCK | A 7; E 714 | 15560m | [map](https://www.google.com/maps/dir/43.936345,4.848861/43.896500,4.916602) |
| 74 | Avignon sud | exit | FAIL_BLOCK | A 7; E 714 | 10357m | [map](https://www.google.com/maps/dir/43.896500,4.916602/43.936345,4.848861) |
| 75 | Péage de Baillargues | entry | FAIL_BLOCK | A 9; E 15; E 80 | 16448m | [map](https://www.google.com/maps/dir/43.655493,4.011786/43.671556,4.013956) |
| 75 | Péage de Baillargues | exit | FAIL_BLOCK | A 9; E 15; E 80; D 600 | 36294m | [map](https://www.google.com/maps/dir/43.671556,4.013956/43.655493,4.011786) |
| 76 | Balan | exit | FAIL_BLOCK | A 42; E 611 | 5092m | [map](https://www.google.com/maps/dir/45.852784,5.096334/45.843199,5.110243) |
| 77 | Balbigny | entry | FAIL_BLOCK | A 89; E 70 | 2884m | [map](https://www.google.com/maps/dir/45.829367,4.192089/45.836526,4.165342) |
| 77 | Balbigny | exit | FAIL_BLOCK | A 89; E 70 | 13026m | [map](https://www.google.com/maps/dir/45.836526,4.165342/45.829367,4.192089) |
| 78 | Bandol | entry | FAIL_BLOCK | A 50 | 4917m | [map](https://www.google.com/maps/dir/43.148136,5.749756/43.146766,5.772669) |
| 79 | BAPAUME | entry | FAIL_BLOCK | A 1; E 15; E 19; A 1; E 15 | 10506m | [map](https://www.google.com/maps/dir/50.101426,2.853188/50.102811,2.871668) |
| 79 | BAPAUME | exit | FAIL_BLOCK | A 1; E 15 | 17562m | [map](https://www.google.com/maps/dir/50.102811,2.871668/50.101426,2.853188) |
| 80 | BARRIERE DE MONTREUIL AUX LIONS | entry | FAIL_BLOCK | A 4; E 50 | 11025m | [map](https://www.google.com/maps/dir/49.019955,3.192893/49.011517,3.150506) |
| 82 | BAUME-LES-DAMES | entry | FAIL_BLOCK | A 36; E 60 | 19532m | [map](https://www.google.com/maps/dir/47.349374,6.361718/47.374470,6.381279) |
| 82 | BAUME-LES-DAMES | exit | FAIL_BLOCK | A 36; E 60 | 24488m | [map](https://www.google.com/maps/dir/47.374470,6.381279/47.349374,6.361718) |
| 85 | Bayonne sud | entry | FAIL_BLOCK | A 63; E 05; E 70 | 6401m | [map](https://www.google.com/maps/dir/43.488544,-1.466564/43.461103,-1.501058) |
| 85 | Bayonne sud | exit | FAIL_BLOCK | A 63; E 05; E 70; E 80 | 5045m | [map](https://www.google.com/maps/dir/43.461103,-1.501058/43.488544,-1.466564) |
| 86 | Bazas | entry | FAIL_BLOCK | A 65; E 07 | 19827m | [map](https://www.google.com/maps/dir/44.437496,-0.217433/44.446257,-0.246073) |
| 86 | Bazas | exit | FAIL_BLOCK | A 65 | 17680m | [map](https://www.google.com/maps/dir/44.446257,-0.246073/44.437496,-0.217433) |
| 88 | Beaufort-en-Vallée | entry | FAIL_BLOCK | A 11; E 501; A 85; E 60 | 47717m | [map](https://www.google.com/maps/dir/47.441186,-0.213719/47.472003,-0.191706) |
| 88 | Beaufort-en-Vallée | exit | FAIL_BLOCK | A 85; E 60 | 7410m | [map](https://www.google.com/maps/dir/47.472003,-0.191706/47.441186,-0.213719) |
| 89 | BEAUFORT EN VALLEE | entry | FAIL_BLOCK | A 11; E 501; A 85; E 60 | 47717m | [map](https://www.google.com/maps/dir/47.441186,-0.213719/47.472003,-0.191706) |
| 89 | BEAUFORT EN VALLEE | exit | FAIL_BLOCK | A 85; E 60 | 7410m | [map](https://www.google.com/maps/dir/47.472003,-0.191706/47.441186,-0.213719) |
| 91 | Péage de Beaulieu-s.-Layon | entry | FAIL_BLOCK | A 87 | 740m | [map](https://www.google.com/maps/dir/47.314109,-0.610032/47.326504,-0.604256) |
| 91 | Péage de Beaulieu-s.-Layon | exit | FAIL_BLOCK | A 87 | 17972m | [map](https://www.google.com/maps/dir/47.326504,-0.604256/47.314109,-0.610032) |
| 94 | BEAUMONT SUR SARTHE | entry | FAIL_BLOCK | A 28; E 402 | 14495m | [map](https://www.google.com/maps/dir/48.223409,0.119925/48.193719,0.172052) |
| 94 | BEAUMONT SUR SARTHE | exit | FAIL_BLOCK | A 28; E 402; A 11; E 50; A 11 | 56068m | [map](https://www.google.com/maps/dir/48.193719,0.172052/48.223409,0.119925) |
| 95 | Beaune nord | entry | FAIL_BLOCK | A 6; E 15; E 60 | 66334m | [map](https://www.google.com/maps/dir/47.025352,4.840893/47.039877,4.851304) |
| 95 | Beaune nord | exit | FAIL_BLOCK | A 6; E 15; E 60; A 31; E 17; E 21; E 60; A 31; E 17; E 21 | 14740m | [map](https://www.google.com/maps/dir/47.039877,4.851304/47.025352,4.840893) |
| 96 | BEAUNE SUD | entry | FAIL_BLOCK | A 6; E 15 | 6123m | [map](https://www.google.com/maps/dir/47.025352,4.840893/46.999280,4.858992) |
| 96 | BEAUNE SUD | exit | FAIL_BLOCK | A 6; E 15; E 21; Péage - Chalon-Centre | 22892m | [map](https://www.google.com/maps/dir/46.999280,4.858992/47.025352,4.840893) |
| 97 | BEAUPONT | exit | FAIL_BLOCK | A 39 | 13790m | [map](https://www.google.com/maps/dir/46.442048,5.273805/46.422987,5.264577) |
| 101 | Beausoleil/Monaco Est | entry | FAIL_BLOCK | A 8; E 74; E 80 | 6761m | [map](https://www.google.com/maps/dir/43.744201,7.422903/43.758991,7.436200) |
| 101 | Beausoleil/Monaco Est | exit | FAIL_BLOCK | A 8; E 74; E 80 | 12339m | [map](https://www.google.com/maps/dir/43.758991,7.436200/43.744201,7.422903) |
| 102 | BEAUTOT | exit | FAIL_BLOCK | A 29; E 44 | 15178m | [map](https://www.google.com/maps/dir/49.635303,1.050659/49.640472,1.044687) |
| 103 | BEAUVAIS CENTRE | exit | FAIL_BLOCK | A 16 | 25478m | [map](https://www.google.com/maps/dir/49.399160,2.122917/49.439313,2.087881) |
| 104 | BEAUVAIS NORD | entry | FAIL_BLOCK | A 16; E 46; E 46 | 4262m | [map](https://www.google.com/maps/dir/49.439313,2.087881/49.430933,2.132300) |
| 104 | BEAUVAIS NORD | exit | FAIL_BLOCK | E 46 | 1245m | [map](https://www.google.com/maps/dir/49.430933,2.132300/49.439313,2.087881) |
| 105 | Belcodène | entry | FAIL_BLOCK | A 52 | 4734m | [map](https://www.google.com/maps/dir/43.425114,5.593386/43.419750,5.575717) |
| 113 | BERCK | entry | FAIL_BLOCK | A 16; E 402 | 19655m | [map](https://www.google.com/maps/dir/50.411178,1.581980/50.408465,1.693601) |
| 113 | BERCK | exit | FAIL_BLOCK | A 16; E 402 | 12806m | [map](https://www.google.com/maps/dir/50.408465,1.693601/50.411178,1.581980) |
| 115 | Bernay | exit | FAIL_BLOCK | A 28; E 402; A 88 | 67107m | [map](https://www.google.com/maps/dir/49.141157,0.580263/49.089387,0.594919) |
| 116 | BERNAY | exit | FAIL_BLOCK | A 28; E 402; A 88 | 67107m | [map](https://www.google.com/maps/dir/49.141157,0.580263/49.089387,0.594919) |
| 117 | Péage de Bersaillin | entry | FAIL_BLOCK | A 391 | 547m | [map](https://www.google.com/maps/dir/46.858338,5.596689/46.849296,5.574617) |
| 117 | Péage de Bersaillin | exit | FAIL_BLOCK | A 39; A 36; E 60 | 38293m | [map](https://www.google.com/maps/dir/46.849296,5.574617/46.858338,5.596689) |
| 118 | BERSAILLIN | entry | FAIL_BLOCK | A 391 | 547m | [map](https://www.google.com/maps/dir/46.858338,5.596689/46.849296,5.574617) |
| 118 | BERSAILLIN | exit | FAIL_BLOCK | A 39; A 36; E 60 | 38293m | [map](https://www.google.com/maps/dir/46.849296,5.574617/46.858338,5.596689) |
| 119 | Besançon est | entry | FAIL_BLOCK | A 36; A 36; E 60 | 15209m | [map](https://www.google.com/maps/dir/47.251938,6.001699/47.336051,6.154401) |
| 119 | Besançon est | exit | FAIL_BLOCK | A 36; E 60 | 43490m | [map](https://www.google.com/maps/dir/47.336051,6.154401/47.251938,6.001699) |
| 120 | Besançon nord | entry | FAIL_BLOCK | A 36; A 36; E 60 | 9776m | [map](https://www.google.com/maps/dir/47.251938,6.001699/47.278332,5.984474) |
| 120 | Besançon nord | exit | FAIL_BLOCK | A 36; E 60 | 58129m | [map](https://www.google.com/maps/dir/47.278332,5.984474/47.251938,6.001699) |
| 121 | BESANCON OUEST | entry | FAIL_BLOCK | A 36 | 577m | [map](https://www.google.com/maps/dir/47.251938,6.001699/47.236227,5.892400) |
| 121 | BESANCON OUEST | exit | FAIL_BLOCK | A 36; E 60; A 39 | 61213m | [map](https://www.google.com/maps/dir/47.236227,5.892400/47.251938,6.001699) |
| 122 | BÉTHUNE | entry | FAIL_BLOCK | A 26; E 15 | 7052m | [map](https://www.google.com/maps/dir/50.528207,2.646031/50.510432,2.613286) |
| 122 | BÉTHUNE | exit | FAIL_BLOCK | A 26; E 15 | 12755m | [map](https://www.google.com/maps/dir/50.510432,2.613286/50.528207,2.646031) |
| 124 | Péage de Beynost | entry | FAIL_BLOCK | A 42; E 611 | 1630m | [map](https://www.google.com/maps/dir/45.830607,4.980507/45.821955,4.996782) |
| 124 | Péage de Beynost | exit | FAIL_BLOCK | A 42; E 611 | 4766m | [map](https://www.google.com/maps/dir/45.821955,4.996782/45.830607,4.980507) |
| 125 | BEYNOST | entry | FAIL_BLOCK | A 42; E 611 | 1630m | [map](https://www.google.com/maps/dir/45.830672,4.999440/45.821955,4.996782) |
| 125 | BEYNOST | exit | FAIL_BLOCK | A 42; E 611 | 5949m | [map](https://www.google.com/maps/dir/45.821955,4.996782/45.830672,4.999440) |
| 127 | Béziers ouest | entry | FAIL_BLOCK | A 9; E 15; E 80 | 979m | [map](https://www.google.com/maps/dir/43.343264,3.233465/43.303488,3.222683) |
| 127 | Béziers ouest | exit | FAIL_BLOCK | A 9; E 15; E 80; A 75; E 11 | 8863m | [map](https://www.google.com/maps/dir/43.303488,3.222683/43.343264,3.233465) |
| 130 | Bierre-les-Semur | entry | FAIL_BLOCK | A 6; E 15; E 60 | 65873m | [map](https://www.google.com/maps/dir/47.512073,4.397479/47.435448,4.306822) |
| 130 | Bierre-les-Semur | exit | FAIL_BLOCK | A 6; E 15; E 60 | 26897m | [map](https://www.google.com/maps/dir/47.435448,4.306822/47.512073,4.397479) |
| 133 | Péage du Bignon | entry | FAIL_BLOCK | A 83; E 03 | 7358m | [map](https://www.google.com/maps/dir/47.100317,-1.503862/47.114846,-1.491783) |
| 133 | Péage du Bignon | exit | FAIL_BLOCK | A 83; E 03 | 1705m | [map](https://www.google.com/maps/dir/47.114846,-1.491783/47.100317,-1.503862) |
| 134 | Biriatou | entry | FAIL_BLOCK | A 63; E 05; E 70; E 80 | 7679m | [map](https://www.google.com/maps/dir/43.334883,-1.743402/43.340527,-1.750857) |
| 135 | Péage de Biriatou | entry | FAIL_BLOCK | A 63; E 05; E 70; E 80 | 7552m | [map](https://www.google.com/maps/dir/43.334883,-1.743402/43.341245,-1.749638) |
| 137 | BLERE | entry | FAIL_BLOCK | A 85; E 604 | 14790m | [map](https://www.google.com/maps/dir/47.301210,0.992188/47.288802,0.980887) |
| 137 | BLERE | exit | FAIL_BLOCK | A 85; E 604 | 30649m | [map](https://www.google.com/maps/dir/47.288802,0.980887/47.301210,0.992188) |
| 138 | Blois | exit | FAIL_BLOCK | A 10; E 05; E 60 | 30305m | [map](https://www.google.com/maps/dir/47.624887,1.346537/47.581406,1.316533) |
| 139 | BOLBEC | entry | FAIL_BLOCK | A 29; E 44 | 1098m | [map](https://www.google.com/maps/dir/49.575224,0.483302/49.581722,0.437219) |
| 139 | BOLBEC | exit | FAIL_BLOCK | A 29; E 44 | 9920m | [map](https://www.google.com/maps/dir/49.581722,0.437219/49.575224,0.483302) |
| 140 | Bollène | entry | FAIL_BLOCK | A7 S | 1073m | [map](https://www.google.com/maps/dir/44.291282,4.751420/44.294940,4.745490) |
| 140 | Bollène | exit | FAIL_BLOCK | A 7; E 15; A 7; E 714 | 26908m | [map](https://www.google.com/maps/dir/44.294940,4.745490/44.291282,4.751420) |
| 141 | Bonneville Est | entry | FAIL_BLOCK | A 40; E 25 | 4250m | [map](https://www.google.com/maps/dir/46.076863,6.408097/46.070130,6.424607) |
| 142 | Bonneville Ouest | entry | FAIL_BLOCK | A 40; E 25 | 3884m | [map](https://www.google.com/maps/dir/46.076863,6.408097/46.073228,6.382499) |
| 142 | Bonneville Ouest | exit | FAIL_BLOCK | A 40; E 25 | 8835m | [map](https://www.google.com/maps/dir/46.073228,6.382499/46.076863,6.408097) |
| 147 | BOULAY | entry | FAIL_BLOCK | A 314 | 17609m | [map](https://www.google.com/maps/dir/49.174790,6.494882/49.140892,6.470362) |
| 147 | BOULAY | exit | FAIL_BLOCK | A 4; E 25; E 50 | 3814m | [map](https://www.google.com/maps/dir/49.140892,6.470362/49.174790,6.494882) |
| 149 | BOULOGNE SUD | exit | FAIL_BLOCK | A 16; E 402 | 8400m | [map](https://www.google.com/maps/dir/50.676281,1.662265/50.726334,1.607492) |
| 150 | BOURG-ACHARD | entry | FAIL_BLOCK | A 13; E 05; E 46 | 616m | [map](https://www.google.com/maps/dir/49.347686,0.809686/49.364977,0.816482) |
| 150 | BOURG-ACHARD | exit | FAIL_BLOCK | A 13; E 05; E 46 | 13355m | [map](https://www.google.com/maps/dir/49.364977,0.816482/49.347686,0.809686) |
| 153 | Bourges | entry | FAIL_BLOCK | A 71; E 11 | 42101m | [map](https://www.google.com/maps/dir/47.082882,2.402294/47.043165,2.339047) |
| 153 | Bourges | exit | FAIL_BLOCK | A 71; E 11 | 26929m | [map](https://www.google.com/maps/dir/47.043165,2.339047/47.082882,2.402294) |
| 155 | BOURGOIN | exit | FAIL_BLOCK | A 43; E 70; E 711 | 1083m | [map](https://www.google.com/maps/dir/45.582177,5.300172/45.597957,5.266993) |
| 156 | Bourgueil | entry | FAIL_BLOCK | A 85; E 60 | 26118m | [map](https://www.google.com/maps/dir/47.295168,0.180986/47.256810,0.167914) |
| 156 | Bourgueil | exit | FAIL_BLOCK | A 85; E 60 | 18086m | [map](https://www.google.com/maps/dir/47.256810,0.167914/47.295168,0.180986) |
| 157 | BOURGUEIL | entry | FAIL_BLOCK | A 85; E 60 | 26118m | [map](https://www.google.com/maps/dir/47.295168,0.180986/47.256810,0.167914) |
| 157 | BOURGUEIL | exit | FAIL_BLOCK | A 85; E 60 | 18086m | [map](https://www.google.com/maps/dir/47.256810,0.167914/47.295168,0.180986) |
| 158 | BOURNEVILLE | entry | FAIL_BLOCK | A 13; E 05; E 46 | 13972m | [map](https://www.google.com/maps/dir/49.395952,0.616456/49.376588,0.633596) |
| 160 | Bram | entry | FAIL_BLOCK | A 61; E 80 | 14848m | [map](https://www.google.com/maps/dir/43.249204,2.102677/43.236668,2.096487) |
| 160 | Bram | exit | FAIL_BLOCK | A 61; E 80 | 18751m | [map](https://www.google.com/maps/dir/43.236668,2.096487/43.249204,2.102677) |
| 162 | Brignoles | exit | FAIL_BLOCK | A 8; E 80; A 57 | 25814m | [map](https://www.google.com/maps/dir/43.421348,6.067251/43.405995,6.073657) |
| 164 | Brionne | entry | FAIL_BLOCK | A 28; E 402 | 39503m | [map](https://www.google.com/maps/dir/49.188685,0.712970/49.245767,0.775772) |
| 164 | Brionne | exit | FAIL_BLOCK | A 28; E 402; A 13; E 05; E 46 | 16068m | [map](https://www.google.com/maps/dir/49.245767,0.775772/49.188685,0.712970) |
| 165 | BRIONNE | entry | FAIL_BLOCK | A 28; E 402 | 39503m | [map](https://www.google.com/maps/dir/49.188685,0.712970/49.245767,0.775772) |
| 165 | BRIONNE | exit | FAIL_BLOCK | A 28; E 402; A 13; E 05; E 46 | 16068m | [map](https://www.google.com/maps/dir/49.245767,0.775772/49.188685,0.712970) |
| 169 | BROU | entry | FAIL_BLOCK | A 11; E 50 | 50313m | [map](https://www.google.com/maps/dir/48.218538,1.160728/48.232218,1.032858) |
| 169 | BROU | exit | FAIL_BLOCK | A 11; E 50 | 28021m | [map](https://www.google.com/maps/dir/48.232218,1.032858/48.218538,1.160728) |
| 170 | BULGNEVILLE | entry | FAIL_BLOCK | A 31; E 21 | 10583m | [map](https://www.google.com/maps/dir/48.207210,5.834628/48.220443,5.837156) |
| 170 | BULGNEVILLE | exit | FAIL_BLOCK | A 31; E 21 | 14597m | [map](https://www.google.com/maps/dir/48.220443,5.837156/48.207210,5.834628) |
| 171 | Péage de Cabariot | entry | FAIL_BLOCK | A 837; E 602 | 1664m | [map](https://www.google.com/maps/dir/45.936655,-0.849707/45.943926,-0.849363) |
| 171 | Péage de Cabariot | exit | FAIL_BLOCK | A 837; E 602; D 137 | 29879m | [map](https://www.google.com/maps/dir/45.943926,-0.849363/45.936655,-0.849707) |
| 172 | CAEN | entry | FAIL_BLOCK | A 13; E 46 | 3954m | [map](https://www.google.com/maps/dir/49.184316,-0.371930/49.168114,-0.247100) |
| 172 | CAEN | exit | FAIL_BLOCK | A 13; E 46 | 3416m | [map](https://www.google.com/maps/dir/49.168114,-0.247100/49.184316,-0.371930) |
| 174 | CAGNY | entry | FAIL_BLOCK | A 13; E 46 | 4114m | [map](https://www.google.com/maps/dir/49.149155,-0.260845/49.168114,-0.247103) |
| 174 | CAGNY | exit | FAIL_BLOCK | A 13; E 46 | 3416m | [map](https://www.google.com/maps/dir/49.168114,-0.247103/49.149155,-0.260845) |
| 178 | CAMBRAI | entry | FAIL_BLOCK | A 2; E 19 | 1603m | [map](https://www.google.com/maps/dir/50.172628,3.240712/50.177474,3.185007) |
| 178 | CAMBRAI | exit | FAIL_BLOCK | E 19 | 29598m | [map](https://www.google.com/maps/dir/50.177474,3.185007/50.172628,3.240712) |
| 184 | Captieux | entry | FAIL_BLOCK | A 65; E 07 | 20314m | [map](https://www.google.com/maps/dir/44.261682,-0.256881/44.284935,-0.231637) |
| 184 | Captieux | exit | FAIL_BLOCK | A 65; E 07 | 29721m | [map](https://www.google.com/maps/dir/44.284935,-0.231637/44.261682,-0.256881) |
| 185 | Capvern | entry | FAIL_BLOCK | A 645; A 64; E 80 | 22829m | [map](https://www.google.com/maps/dir/43.108898,0.328743/43.102327,0.338640) |
| 185 | Capvern | exit | FAIL_BLOCK | A 64; E 80 | 14217m | [map](https://www.google.com/maps/dir/43.102327,0.338640/43.108898,0.328743) |
| 187 | Carcassonne est | exit | FAIL_BLOCK | A 61; E 80 | 35951m | [map](https://www.google.com/maps/dir/43.194357,2.419561/43.206781,2.349415) |
| 188 | Carcassonne ouest | entry | FAIL_BLOCK | A 61; E 80 | 32708m | [map](https://www.google.com/maps/dir/43.206781,2.349415/43.194939,2.303158) |
| 188 | Carcassonne ouest | exit | FAIL_BLOCK | A 61; E 80 | 45937m | [map](https://www.google.com/maps/dir/43.194939,2.303158/43.206781,2.349415) |
| 189 | Carnoules | entry | FAIL_BLOCK | A 57 | 10014m | [map](https://www.google.com/maps/dir/43.299794,6.192189/43.289740,6.194347) |
| 190 | Carros | entry | FAIL_BLOCK | A 8; E 80 | 2066m | [map](https://www.google.com/maps/dir/43.784043,7.191567/43.691601,7.189750) |
| 191 | Cassis | entry | FAIL_BLOCK | A 50 | 2375m | [map](https://www.google.com/maps/dir/43.223489,5.548832/43.224647,5.582277) |
| 191 | Cassis | exit | FAIL_BLOCK | A 50 | 3212m | [map](https://www.google.com/maps/dir/43.224647,5.582277/43.223489,5.548832) |
| 192 | Castelnaudary | entry | FAIL_BLOCK | A 61; E 80 | 32754m | [map](https://www.google.com/maps/dir/43.315108,1.959918/43.288796,1.944152) |
| 192 | Castelnaudary | exit | FAIL_BLOCK | A 61; E 80 | 862m | [map](https://www.google.com/maps/dir/43.288796,1.944152/43.315108,1.959918) |
| 193 | Castelsarrasin | entry | FAIL_BLOCK | A 62; E 72 | 20185m | [map](https://www.google.com/maps/dir/44.048086,1.131930/44.052651,1.095716) |
| 193 | Castelsarrasin | exit | FAIL_BLOCK | A 62; E 72; 10 | 24135m | [map](https://www.google.com/maps/dir/44.052651,1.095716/44.048086,1.131930) |
| 194 | Castets | entry | FAIL_BLOCK | A 63; E 05; E 70 | 5913m | [map](https://www.google.com/maps/dir/43.881800,-1.147983/43.835282,-1.180617) |
| 194 | Castets | exit | FAIL_BLOCK | A 63; E 05; E 70 | 6628m | [map](https://www.google.com/maps/dir/43.835282,-1.180617/43.881800,-1.147983) |
| 195 | Castets | entry | FAIL_BLOCK | A 63; E 05; E 70 | 5913m | [map](https://www.google.com/maps/dir/43.881800,-1.147983/43.835282,-1.180617) |
| 195 | Castets | exit | FAIL_BLOCK | A 63; E 05; E 70 | 6628m | [map](https://www.google.com/maps/dir/43.835282,-1.180617/43.881800,-1.147983) |
| 197 | Cavaillon | exit | FAIL_BLOCK | A 7; E 714 | 9855m | [map](https://www.google.com/maps/dir/43.814792,5.033922/43.848790,5.036175) |
| 201 | CHÂLONS-EN-CHAMPAGNE / LA VEUVE | entry | FAIL_BLOCK | A 4; E 50 | 9833m | [map](https://www.google.com/maps/dir/48.955254,4.368278/49.043479,4.320427) |
| 201 | CHÂLONS-EN-CHAMPAGNE / LA VEUVE | exit | FAIL_BLOCK | A 4; E 50 | 32987m | [map](https://www.google.com/maps/dir/49.043479,4.320427/48.955254,4.368278) |
| 204 | CHAMBERY NORD | exit | FAIL_BLOCK | A 43; E 70; E 712; A 41; E 712 | 23656m | [map](https://www.google.com/maps/dir/45.602732,5.887064/45.583223,5.909299) |
| 205 | PEAGE DE CHAMBOURCY | entry | FAIL_BLOCK | A 14 | 12371m | [map](https://www.google.com/maps/dir/48.902406,2.041587/48.912206,2.045723) |
| 205 | PEAGE DE CHAMBOURCY | exit | FAIL_BLOCK | A 14 | 1411m | [map](https://www.google.com/maps/dir/48.912206,2.045723/48.902406,2.041587) |
| 207 | Chanas | entry | FAIL_BLOCK | A 7; E 15 | 7688m | [map](https://www.google.com/maps/dir/45.322731,4.832401/45.322905,4.812056) |
| 207 | Chanas | exit | FAIL_BLOCK | A 7; E 15 | 1861m | [map](https://www.google.com/maps/dir/45.322905,4.812056/45.322731,4.832401) |
| 208 | Chantonnay | exit | FAIL_BLOCK | A 83; E 03 | 19971m | [map](https://www.google.com/maps/dir/46.627550,-1.147716/46.670663,-1.049215) |
| 211 | Charmont-sous-Barbuise | exit | FAIL_BLOCK | A 26; E 17 | 13306m | [map](https://www.google.com/maps/dir/48.412740,4.146532/48.409136,4.176287) |
| 214 | CHARTRES-THIVARS | entry | FAIL_BLOCK | A 11; E 50 | 16138m | [map](https://www.google.com/maps/dir/48.446525,1.502286/48.363346,1.444298) |
| 214 | CHARTRES-THIVARS | exit | FAIL_BLOCK | A 11; E 50 | 835m | [map](https://www.google.com/maps/dir/48.363346,1.444298/48.446525,1.502286) |
| 217 | CHATEAU-RENAULT | entry | FAIL_BLOCK | A 10; E 05; E 60 | 30678m | [map](https://www.google.com/maps/dir/47.594670,0.909328/47.546246,0.986234) |
| 217 | CHATEAU-RENAULT | exit | FAIL_BLOCK | A 10; E 05; E 60 | 14179m | [map](https://www.google.com/maps/dir/47.546246,0.986234/47.594670,0.909328) |
| 218 | CHÂTEAU-THIERRY | exit | FAIL_BLOCK | A 4; E 50 | 22468m | [map](https://www.google.com/maps/dir/49.081264,3.402355/49.050003,3.383835) |
| 219 | CHATELLERAULT NORD | exit | FAIL_BLOCK | A 10; E 05 | 8282m | [map](https://www.google.com/maps/dir/46.837926,0.524726/46.816200,0.551000) |
| 220 | CHATELLERAULT SUD | exit | FAIL_BLOCK | A 10; E 05 | 17579m | [map](https://www.google.com/maps/dir/46.781558,0.500526/46.816200,0.551000) |
| 223 | CHATILLON-LABORDE | exit | FAIL_BLOCK | A 5; E 54 | 18223m | [map](https://www.google.com/maps/dir/48.539508,2.794951/48.530369,2.831388) |
| 224 | CHATUZANGE BARRIERE | entry | FAIL_BLOCK | A 49; E 713 | 23041m | [map](https://www.google.com/maps/dir/45.005351,5.093124/45.026047,5.096592) |
| 224 | CHATUZANGE BARRIERE | exit | FAIL_BLOCK | A 49; E 713 | 994m | [map](https://www.google.com/maps/dir/45.026047,5.096592/45.005351,5.093124) |
| 227 | CHAUMONT-SEMOUTIERS | exit | FAIL_BLOCK | A 5; E 17; E 54; A 31; E 21 | 26248m | [map](https://www.google.com/maps/dir/48.039707,5.060420/48.061289,5.051148) |
| 228 | Chémery | entry | FAIL_BLOCK | A 85; E 604 | 12790m | [map](https://www.google.com/maps/dir/47.349003,1.485258/47.328378,1.500173) |
| 228 | Chémery | exit | FAIL_BLOCK | A 85; E 604 | 22232m | [map](https://www.google.com/maps/dir/47.328378,1.500173/47.349003,1.485258) |
| 229 | Chemillé | entry | FAIL_BLOCK | A 87 | 18048m | [map](https://www.google.com/maps/dir/47.216653,-0.689179/47.240102,-0.729159) |
| 229 | Chemillé | exit | FAIL_BLOCK | A 87 | 13788m | [map](https://www.google.com/maps/dir/47.240102,-0.729159/47.216653,-0.689179) |
| 232 | Chignin Barrière | entry | FAIL_BLOCK | A 43; E 70; E 712 | 3802m | [map](https://www.google.com/maps/dir/45.522213,6.007821/45.513883,5.999755) |
| 232 | Chignin Barrière | exit | FAIL_BLOCK | A 43; E 70; E 712; A 43; E 70 | 37705m | [map](https://www.google.com/maps/dir/45.513883,5.999755/45.522213,6.007821) |
| 233 | CHIGNIN BRETELLE | entry | FAIL_BLOCK | A 43; E 70; E 712 | 4060m | [map](https://www.google.com/maps/dir/45.522213,6.007821/45.512466,6.002351) |
| 233 | CHIGNIN BRETELLE | exit | FAIL_BLOCK | A 43; E 70; E 712; A 43; E 70 | 37448m | [map](https://www.google.com/maps/dir/45.512466,6.002351/45.522213,6.007821) |
| 235 | Choisey | exit | FAIL_BLOCK | A 39; A 391 | 28921m | [map](https://www.google.com/maps/dir/47.067801,5.438388/47.062176,5.453585) |
| 236 | Cholet nord | entry | FAIL_BLOCK | A 87 | 5360m | [map](https://www.google.com/maps/dir/47.036408,-0.875399/47.086301,-0.824181) |
| 236 | Cholet nord | exit | FAIL_BLOCK | A 87 | 63976m | [map](https://www.google.com/maps/dir/47.086301,-0.824181/47.036408,-0.875399) |
| 237 | CHOLET SUD | entry | FAIL_BLOCK | A 87 | 9903m | [map](https://www.google.com/maps/dir/47.036408,-0.875399/47.016113,-0.878200) |
| 237 | CHOLET SUD | exit | FAIL_BLOCK | A 87 | 54803m | [map](https://www.google.com/maps/dir/47.016113,-0.878200/47.036408,-0.875399) |
| 240 | CLERMONT-BARRIERE | entry | FAIL_BLOCK | A 71; A 89; E 11; E 70 | 7020m | [map](https://www.google.com/maps/dir/45.786671,3.107055/45.840494,3.160450) |
| 240 | CLERMONT-BARRIERE | exit | FAIL_BLOCK | A 71; E 11 | 3642m | [map](https://www.google.com/maps/dir/45.840494,3.160450/45.786671,3.107055) |
| 241 | Clermont-en-Argonne | exit | FAIL_BLOCK | A 4; E 50 | 14052m | [map](https://www.google.com/maps/dir/49.094442,5.101665/49.117503,5.099990) |
| 52 | ARGENTAN OUEST | exit | FAIL_SHORT | A 88 | 471m | [map](https://www.google.com/maps/dir/48.657152,0.087589/48.729955,-0.013024) |
| 65 | Auriol | exit | FAIL_SHORT | A 520 | 185m | [map](https://www.google.com/maps/dir/43.366917,5.643613/43.360892,5.647170) |
| 149 | BOULOGNE SUD | entry | FAIL_SHORT | A 16 | 386m | [map](https://www.google.com/maps/dir/50.726334,1.607492/50.676281,1.662265) |
| 134 | Biriatou | exit | ESCALATED_PASS |  | 0m | [map](https://www.google.com/maps/dir/43.340527,-1.750857/43.334883,-1.743402) |

## NO_ORIGIN (1616 legs)

Could not geocode an origin for these gates.

- gare_id=1 `A 20 limite de concession` entry
- gare_id=1 `A 20 limite de concession` exit
- gare_id=9 `Aigrefeuille` entry
- gare_id=9 `Aigrefeuille` exit
- gare_id=16 `Aix (A51)` entry
- gare_id=16 `Aix (A51)` exit
- gare_id=17 `Aix (A57,A50,A52,A8)` entry
- gare_id=17 `Aix (A57,A50,A52,A8)` exit
- gare_id=18 `AIX NORD` entry
- gare_id=18 `AIX NORD` exit
- gare_id=19 `Aix ouest` entry
- gare_id=19 `Aix ouest` exit
- gare_id=20 `AIX SUD` entry
- gare_id=20 `AIX SUD` exit
- gare_id=21 `ALBERT` entry
- gare_id=21 `ALBERT` exit
- gare_id=27 `ALLAINES` entry
- gare_id=27 `ALLAINES` exit
- gare_id=34 `AMBOISE CH.RENAULT` entry
- gare_id=34 `AMBOISE CH.RENAULT` exit
- ... and 1596 more (see CSV)

## Parameters

- DB: `/home/hugh/build/toll-1-exploration/tollroute/db/tollroute_national.sqlite`
- Valhalla: `http://localhost:8002`
- Base penalty: `use_tolls: 0.0`
- Escalated penalty: `use_tolls: 0.0, toll_booth_cost: 9999`
- FAIL_SHORT threshold: 500 m
- Geocoder: `https://api-adresse.data.gouv.fr`
- Gates tested: 974
- Total legs: 1948 (entry + exit for each gate)
