---
type: Project Rules
title: Règles de palo-bug-tracker
description: Règles communes aux bug trackers et particularités de PAN-OS.
resource: https://github.com/frc-fr/palo-bug-tracker
tags: [rules, pan-os, palo-alto-networks, bug-tracker]
timestamp: 2026-11-09T18:30:00+01:00
product: PAN-OS
site: https://frc-fr.github.io/palo-bug-tracker/
---

# Critères communs

Section identique dans forti-, juni-, palo-, cisco- et f5-bug-tracker. Toute modification se reporte dans les cinq.

## Architecture

- Site statique : pas de serveur, pas de base de données.
- Python côté collecte, JavaScript sans framework côté navigateur.
- Paquet Python `<fournisseur>bugs`, une commande par étape :
  - `collect` : met à jour l'état des sources et télécharge ce qui a changé.
  - `extract` : lit les documents en cache ; échoue au moindre avertissement.
  - `build` : croise les données et génère `dist/`.
- Modules : `collect`, `parser`, `extract`, `normalize` (matériel), `lifecycle` (dates de support), `build`, `feed`, `cli`.

### Répertoires

- `sources/` : état des sources (adresses, ETag, lastmod, dates de support). Commité.
- `.cache/` : documents bruts. Non versionné, gardé par le cache de la CI.
- `data/extracted/` : un JSON par document, une ligne par bug pour des diffs lisibles. Commité.
- `data/changes.json` : journal des nouveautés. Absent au départ : la première extraction sert de référence.
- `site/` : `index.html`, `app.js` (affichage), `logic.js` (règles de statut, testables), `i18n.js`, `theme.js`, `style.css`, mentions légales FR/EN.
- `dist/` : site généré, avec `data/*.json` compacts et `feed.xml`. Non versionné.

### Modèle de données

- Un bug = identifiant, description, contournement, matériel cité, événements.
- Un événement = version, statut (`r` corrigé, `k` connu, `l` limitation…), page officielle.
- Les statuts par version sont calculés dans le navigateur, à partir des notes de la branche.

### Tests

- `pytest` : tests unitaires, plus tests sur les vrais documents en cache.
- `node --test tests/site/logic.test.js` : règles de statut et de comparaison.
- Test des clés de traduction et de la CSP.

## Sources et collecte

- Sources officielles et publiques du fournisseur en priorité.
- Source communautaire (ex. endoflife.date) seulement à défaut d'équivalent officiel, citée comme telle dans les mentions légales.
- robots.txt respecté : un chemin interdit n'est jamais interrogé.
- 2 secondes minimum entre deux requêtes, User-Agent du projet.
- Ne recharger que ce qui a changé (ETag, Last-Modified, lastmod du sitemap).
- Résultats d'extraction commités dans `data/` : vider le cache CI ne relance pas tout.
- Un avertissement d'extraction arrête la mise à jour : le site garde ses dernières données valides.
- Une source annexe (dates de support…) en échec garde ses dernières valeurs.
- Le navigateur ne contacte jamais de service tiers.

## Contenu

- Objet : bugs connus et bugs corrigés. Jamais la sécurité.
- Entrées de sécurité écartées, références CVE retirées des descriptions.
- Chaque fait renvoie à la page officielle exacte qui le porte.
- Textes des bugs laissés en anglais, tels que publiés.
- Statuts déduits des notes, jamais inventés ; « Inconnu » expliqué et masqué par défaut.
- Un modèle cité ne veut pas dire « seul ce modèle est touché ». Filtre matériel inclusif.
- Un bug à la fois correction et changement de comportement n'est compté qu'une fois.
- Une version annoncée mais pas encore publiée est marquée « non publiée ».
- Toutes les branches restent consultables ; les branches supportées sont mises en avant.
- Pas d'affirmation générale ou trop assurée dans les textes.

## Interface

- Français et anglais, sans page /en/ séparée.
- Bandeau visible : « vos sélections ne sont ni enregistrées ni transmises ».
- Onglets : Rechercher, Comparer, Matériel, puis Quoi de neuf à droite de Matériel.
- Comparaison : pastilles triées par ordre alphabétique, « Tous » en premier.
- Libellé court « Correction » ; risques (nouveaux, toujours présents) mis en valeur.
- Panneau « À lire » replié par défaut, il ne s'ouvre que si l'utilisateur le déplie.
- Listes déroulantes filtrables à la frappe ; bouton Réinitialiser.
- Tableau sélectionnable en entier et bouton « Copier le tableau ».
- Bouton de retour en haut de page.
- Logos RSS puis GitHub, minimalistes et presque transparents, à gauche de « EN ».
- Thème clair et sombre ; pas de noir trop profond.
- Textes longs justifiés, sur toute la largeur.
- Cron et date de dernière mise à jour affichés.
- Placeholders neutres : ne jamais révéler le matériel de l'utilisateur.
- Même forme dans tous les sites, quelle que soit la façon de présenter du fournisseur : on cherche au même endroit.
- Données uniformes entre fournisseurs : pas d'information propre à un seul fournisseur si elle n'aide pas l'exploitation (ex. date de mise en vente).
- Plusieurs systèmes : sélecteur de logiciel, libellé visible « Logiciel », jamais un choix de matériel.

## Matériel et nouveautés

- Onglet Matériel : pastilles de statut (« Tous » en premier, puis « Plus dans la dernière branche » ou son équivalent).
- Colonnes : Modèle, Première version, Dernière version, Statut <logiciel>, Version recommandée, Fin de support.
- Statut tiré d'une source officielle du fournisseur : il dit, sans le deviner, si le matériel est encore maintenu.
- Fin de vie annoncée par référence : variantes affichées séparément, pièces détachées et modules écartés.
- Pas de source : « Aucune fin annoncée », jamais « supporté ».
- Version recommandée seulement si le fournisseur la publie sans compte ; sinon la colonne est absente, et la note dit pourquoi.
- Rechercher : un modèle choisi affiche ce que le fournisseur dit de lui (statut, version recommandée, fin de support).
- Quoi de neuf : cartes « Dernière version publiée », « Dernier document mis à jour », puis « Recommandée par <fournisseur> » si elle existe.

## Design

- Même structure et mêmes jetons de couleur dans les trois sites.
- Couleur du fournisseur en touche seulement : bordure haute et nom du produit.
- Contraste professionnel, rien qui « pique les yeux ».
- Cohérence entre pages : mêmes pastilles partout, pas de tuiles géantes.

## Publication

- Cron du lundi au vendredi : 9 h 15, 14 h 15, 19 h 00, Europe/Paris.
- Horaire décrit dans `sources/schedule.yml` et affiché sur le site, qui le lit au build.
- Workflow GitHub sans déclencheur `schedule` (retardé ou oublié par GitHub) : lancé par `workflow_dispatch`.
- Ordre : tests, collecte, extraction, tests sur le corpus réel, commit des données, build, GitHub Pages.
- Flux RSS/Atom des nouveautés.
- CSP stricte : aucun script, style ou service tiers.

## Mentions et licence

- Outil créé et maintenu par FR Consulting ; contact@fr-consulting.fr ; lien vers fr-consulting.fr.
- Site indépendant, non affilié au fournisseur. Jamais « approuvé par ».
- Mentions légales FR et EN, avec la liste des services et composants tiers.
- Code sous AGPL 3.0 ou ultérieure ; contenus du fournisseur exclus.
- README générique : rien de sensible ni de personnel.

# Particularités PAN-OS

## Versions

- Version de maintenance : `11.2.13`. Hotfix : `11.2.13-h3`.
- Hotfix -h : même logique que les -S de Junos.
- Une correction en `11.2.13-h3` vaut pour `11.2.13-h4`, pas pour `11.2.12-h9` ni pour `11.2.14`.
- Une correction dans une version de maintenance vaut pour les suivantes de la branche.
- Pas de Known Issues par hotfix : il reprend celles de sa version de maintenance, statut « Affecté ».
- Pas de date de publication dans les notes : version datée du jour où l'outil la découvre.
- Branches couvertes depuis 8.1.

## Sources

- Pages HTML de docs.paloaltonetworks.com, une par version et par hotfix.
- PDF jamais téléchargés : robots.txt interdit `/content/dam/techdocs/en_US/*.pdf`.
- Pages découvertes par le sitemap ; téléchargées seulement si nouvelles ou si le lastmod change.
- Encodage : le serveur n'annonce pas de charset, lire en UTF-8.
- 9.0 et 10.0 absentes du sitemap : parcourues une fois par leurs liens, plus jamais interrogées.
- Dates de support : page End-of-Life Summary, tableau « PAN-OS & Panorama ».
- Support standard pour « supportée » ; support étendu affiché à part.

## Extraction

- Pages lues : Addressed Issues, Known Issues, Limitations, Changes to Default Behavior, et pages CN-Series.
- Ligne sans identifiant listant des CVE : écartée.
- « This issue is now resolved. See PAN-OS x Addressed Issues » : correction en x si absente ailleurs.
- Limitations et Known Issues de branche : valent pour chaque version jusqu'à la correction.
- Ne pas doubler un bug déjà dans les Known Issues d'une version précise.
- Coquilles tolérées : identifiant collé au texte, `PAN- 155147`, `RLP—146384`, `254927` seul, titre `9-1-16-h3`.

## CN-Series

- Une page Known Issues et une page Addressed Issues par génération : « CN-Series 10.x », « 11.x ».
- Seules les pages sous `cn-series-<n>-x-release-notes/` sont lues ; les copies à la racine sont anciennes.
- Known Issues : valent pour chaque version de maintenance des branches de la génération, jusqu'à la correction.
- Addressed Issues : pas de version ; affichées « CN-Series 10.x (version non précisée) », sans événement.
- Bugs de ces pages rattachés d'office à la famille CN-Series.

## Matériel

- Aucun chapitre par plateforme : modèle et famille connus seulement par le texte.
- Familles : PA-400, PA-1400, PA-3400, PA-5400… ; PA-5450 et PA-7500 à part ; M-Series, VM-Series, CN-Series, WF-500.
- « Panorama » seul n'est pas une famille : il désigne aussi le logiciel.
- Fin de vie : page Hardware End-of-Life Dates, colonnes End-of-Life Date et Last Supported OS.
- Lignes gardées : pare-feu et appliances (SKU `-SYS`, `-ZTP` compris). Cartes, disques, optiques, K2, ION, LightCyber écartés.
- « Arrêt après » : dernière version de PAN-OS avant la dernière branche publiée, ou fin de vie passée.
- M-100 : deux versions selon la mémoire, la plus récente est retenue.
- Pas de colonne ni de carte « version recommandée » : la page des versions préférées demande un compte client.

## Affichage

- Identifiants complets : `PAN-338608`, `WF500-6271`. Recherche aussi par numéro seul.
- Bugs PAN- en premier, du plus récent au plus ancien.
- Détail : description du problème, puis texte du correctif.
- Comparaison : Changes to Default Behavior rattachés à la version qu'ils citent, sinon à la première de la branche.
- Panneau « À lire : Changes to Default Behavior / Limitations », pages des branches traversées.
- Couleur de marque : orange Palo Alto, nettement orange pour ne pas se confondre avec le rouge de FortiOS.

# Citations

[1] [robots.txt de docs.paloaltonetworks.com](https://docs.paloaltonetworks.com/robots.txt)
[2] [End-of-Life Summary](https://www.paloaltonetworks.com/services/support/end-of-life-announcements/end-of-life-summary)
[3] [Where to find the current preferred software versions?](https://knowledgebase.paloaltonetworks.com/KCSArticleDetail?id=kA10g000000PMViCAO)
