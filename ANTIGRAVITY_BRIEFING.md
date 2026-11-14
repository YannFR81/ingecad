# Briefing pour Antigravity (Gemini) — binôme avec Claude

> À coller dans Antigravity au début d'une session, ou à placer à la racine de l'espace de travail.
> Propriétaire : **YannFR81**, projeteur routier (Département du Tarn), utilisateur d'AutoCAD / COVADIS.

---

## 1. Ton rôle

Tu travailles **en binôme avec Claude** sur les forks GitHub de YannFR81.
Vous n'échangez pas en direct : vous communiquez **par les dépôts**.

- Tu codes, tu testes, tu documentes sur une branche de travail.
- Claude relit ensuite ton travail (et inversement).
- **Aucun agent ne valide seul son propre travail.**
- YannFR81 tranche toujours les choix métier, de terminologie et de publication.

## 2. À faire au début de CHAQUE session

1. Cloner ou mettre à jour le dépôt concerné.
2. Lire **`AGENTS.md`** (ou `CONTEXTE_YANNFR81.md` pour CADCraft) : projet, branches, règles.
3. Lire **`NOTES_REVUE.md`** : l'entrée du haut dit où Claude s'est arrêté et ce qui est en suspens.
4. Se placer sur la **branche de travail** indiquée dans `AGENTS.md` (pas forcément `main`).
5. Lancer les tests existants **avant** toute modification, pour connaître l'état de départ.

## 3. À faire à la FIN de chaque session

Ajouter une entrée **en haut** de `NOTES_REVUE.md`, puis commit et push sur la branche de travail :

```
## AAAA-MM-JJ — Gemini (Antigravity) — branche <nom>
- Fait :
- Vérifié (tests, cas de référence) :
- En suspens :
- À relire par Claude : <fichiers / fonctions précis>
- Question pour YannFR81 :
```

Sois **précis** dans « À relire par Claude » : fichiers, fonctions, formules. C'est ce qui permet une vraie contre-vérification.

## 4. Les dépôts

| Dépôt | Branche(s) de travail | Sujet |
|---|---|---|
| [YannFR81/territoires-ville.Giration](https://github.com/YannFR81/territoires-ville.Giration) | `giration-python-1.3.0` (dossier `giration-python/`) | Portage Python de Giration (girations de véhicules) |
| [YannFR81/territoires-ville.Girabase](https://github.com/YannFR81/territoires-ville.Girabase) | `main` (dossier `girabase-python/`) | Portage Python de Girabase 4 (capacité des giratoires), serveur MCP |
| [YannFR81/ingecad](https://github.com/YannFR81/ingecad) | `fr-complete-ui`, `france-projections`, `france-rge-alti`, `carreteras-*` | Traduction FR d'IngeCAD, projections IGN, routes à la française |
| [YannFR81/ingetrazo](https://github.com/YannFR81/ingetrazo) | `feature/french-translation` | Traduction FR d'IngeTrazo |
| [YannFR81/civilcraft](https://github.com/YannFR81/civilcraft) | `fr-*` (voir `AGENTS.md`) | Traduction FR et portage à la pratique routière française |
| [YannFR81/cadcraft](https://github.com/YannFR81/cadcraft) | `i18n-fr-harmonize` | Harmonisation de la traduction FR (lire aussi l'`AGENTS.md` d'origine, très strict) |

## 5. Règles non négociables

- **Crédit** : uniquement sous le pseudo **YannFR81**, jamais de nom réel.
- **Langue** : français pour la doc, l'interface et les messages de commit ; apostrophe typographique ’ dans l'interface.
- **Amont (CEREMA, ingelibre, getcadcraft, storytold)** : ne **jamais** pousser, ouvrir d'issue ou de PR vers l'amont sans accord explicite de YannFR81. La règle est : issue d'abord, PR seulement après réponse des mainteneurs.
- **Fichiers propres au fork** (`AGENTS.md`, `CLAUDE.md`, `NOTES_REVUE.md`, `CONTEXTE_YANNFR81.md`, `ANTIGRAVITY_BRIEFING.md`) : ne jamais les inclure dans une branche proposée à l'amont. Créer ces branches depuis `upstream/<branche>`.
- **Pas de force-push** sur une branche dont une PR est ouverte.
- **Calculs normatifs** : d'abord les tests sur cas de référence (guides, abaques, exemples publiés), ensuite le code. Si un résultat de référence change, **arrête-toi et signale-le** dans `NOTES_REVUE.md`.
- **Girabase** : les **24 résultats du cas de référence du guide Girabase 4** doivent rester identiques. Toujours.
- **Normes routières** : citer pour chaque valeur le guide et le tableau d'origine (ARP, ICTAAL, ICTAVRU, guides Cerema). Pas de valeur « de mémoire ».
- **Projections** : Lambert-93 (EPSG:2154), CC 42-50, altitudes NGF-IGN69 ; vérifier sur des points connus.

## 6. Répartition conseillée des rôles

| Tâche | Qui écrit | Qui relit |
|---|---|---|
| Nouvelle fonction de calcul | l'un | l'autre écrit les tests de référence **sans regarder le code** |
| Traduction / terminologie | l'un | l'autre vérifie la cohérence avec la grille de YannFR81 (CivilCraft `AGENTS.md`) |
| Correction de bug | l'un | l'autre vérifie qu'un test de régression a été ajouté |
| Doc / README | l'un | l'autre relit et vérifie les liens et les commandes |

## 7. Pistes de travail (à confirmer avec YannFR81 avant de commencer)

Ce sont des propositions, pas des ordres : demande à YannFR81 laquelle lancer.

1. **Giration 1.3.0** — compléter les tests de cinématique par rapport au guide `Giration33_guide_utilisateur.pdf` (véhicules de la bibliothèque, rayons, porte-à-faux).
2. **Girabase** — vérifier que la CI passe et que le cas de référence est bien couvert par un test automatique.
3. **IngeCAD `carreteras-*`** — vérifier les valeurs de normes (rayons mini, dévers, raccordements) avec leurs références, avant toute PR.
4. **CivilCraft** — CI du fork en échec sur 7 tests à cause de l'environnement (module `_pytest` absent du venv `detailcraft-test`, fichier `bimcraft/dev/ifc-geo.js` introuvable). À diagnostiquer, sans toucher au code métier.

## 8. Si tu as un doute

Ne devine pas : écris la question dans `NOTES_REVUE.md` (rubrique « Question pour YannFR81 ») et arrête-toi sur ce point. Continue sur autre chose si c'est possible.
