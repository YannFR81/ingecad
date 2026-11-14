# IngeCAD — traduction et adaptation française (fork YannFR81)

Instructions pour les agents d'IA travaillant sur ce dépôt.
Lu par Gemini / Antigravity (`AGENTS.md`) et par Claude (via `CLAUDE.md`).

Amont : ingelibre/ingecad (DAO 2D).

## Le projet

Traduction française d'**IngeCAD** et adaptation à la pratique routière et topographique française.

## Branches du fork
- `fr-complete-ui` : traduction complète de l'interface (PR #137 sur l'amont).
- `add-french-translation` : premier pack de traduction (cœur, terreno, topografia).
- `france-projections` : projections françaises de l'IGN et fonds IGN (BD ORTHO HR) pour l'extension Terrain.
- `france-rge-alti` : altitudes RGE ALTI (NGF) pour l'extension Terrain.
- `carreteras-fr`, `carreteras-france`, `carreteras-profil` : adaptation de l'extension Routes (`plugins/carreteras`)
  — clothoïdes, grades, recommandations Cerema (ARP, ICTAAL, ICTAVRU).
- `puente-ia-mcp` : MCP intégré à IngeCAD.
- `main` suit l'amont.

## Points de vigilance pour la relecture
- Normes routières : citer le guide et le tableau d'où vient chaque valeur (rayons mini, devers, raccordements).
- Projections : Lambert-93 (EPSG:2154) et CC 42-50 ; altitudes NGF-IGN69. Vérifier les transformations sur des points connus.

## Règles communes à tous les agents (Claude, Gemini / Antigravity, autres)

- **Propriétaire du fork :** YannFR81, projeteur routier (conception routière, AutoCAD / COVADIS).
  C'est lui qui tranche les choix métier et de terminologie.
- **Crédit :** uniquement sous le pseudo **YannFR81**, jamais de nom réel (commits, README, feuilles de route, PR).
- **Langue :** français pour la documentation, les messages de commit et les échanges ; apostrophe typographique ’ dans les textes d'interface.
- **Relations avec le dépôt d'origine (amont) :** proposer d'abord par une *issue* ; n'ouvrir une PR qu'après
  réponse des mainteneurs. Ne jamais pousser ni ouvrir de PR vers l'amont sans accord explicite de YannFR81.
- **Fichiers propres au fork :** `AGENTS.md`, `CLAUDE.md`, `NOTES_REVUE.md` (et `CONTEXTE_YANNFR81.md` le cas échéant)
  ne doivent **jamais** figurer dans une branche proposée à l'amont. Créer les branches destinées à l'amont
  à partir de la branche de l'amont (`upstream/<branche>`), ou retirer ces fichiers avant la PR.
- **Pas de force-push** sur une branche dont une PR est ouverte.

## Travail en binôme

1. Un agent écrit, **l'autre relit** : aucun agent ne valide seul son propre travail.
2. Calculs normatifs ou moteur de calcul : écrire ou compléter d'abord les **tests sur cas de référence**
   (guides, abaques, exemples publiés), puis modifier le code. Un résultat de référence qui change = arrêt et signalement.
3. À la fin de chaque session, ajouter une entrée en tête de `NOTES_REVUE.md`
   (date, agent, branche, fait / vérifié / en suspens / question pour YannFR81).
4. Avant de commencer, lire `NOTES_REVUE.md` pour reprendre là où l'autre agent s'est arrêté.
