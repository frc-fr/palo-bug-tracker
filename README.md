# palo-bug-tracker

Site statique de suivi des bugs de PAN-OS et de leurs corrections, construit à partir des Release Notes
publiques de Palo Alto Networks.

Ce projet est indépendant. Il n'est pas affilié à Palo Alto Networks.
Les informations sont fournies à titre indicatif : vérifiez toujours la documentation officielle.

## Fonctionnalités

- Recherche par identifiant (PAN-338608, ou son numéro seul) ou mots-clés, par version, hotfix et matériel
- Toutes les branches publiées depuis PAN-OS 8.1, avec mise en avant des branches supportées, sans masquer les autres
- Comparaison de deux versions : bugs corrigés, nouveaux problèmes connus, problèmes toujours présents,
  changements de comportement par défaut (« Changes to Default Behavior ») et pages à lire avant la mise à niveau
- Liste des modèles cités dans les bugs
- Suivi des nouveautés, avec un flux RSS/Atom
- Interface en français et en anglais

Vos recherches et vos filtres restent dans votre navigateur : ils ne sont ni enregistrés ni transmis.

## Ce que disent les notes, et ce qu'elles ne disent pas

- Palo Alto Networks publie une page de corrections (« Addressed Issues ») par version de maintenance
  (11.2.13) et par hotfix (11.2.13-h3), et une page de problèmes connus (« Known Issues ») par version de
  maintenance. Un hotfix ne suit que sa propre version : une correction en 11.2.13-h3 vaut pour
  11.2.13-h4, pas pour 11.2.12-h9.
- Un problème connu corrigé depuis l'indique sous son identifiant (« This issue is now resolved. See PAN-OS
  11.2.15 Addressed Issues »). Les Limitations et les changements de comportement sont publiés pour toute
  une branche.
- Les notes ne rangent pas les bugs par plateforme. Le modèle n'est connu que lorsque le texte le cite,
  comme « (PA-5420 firewalls only) ». Le filtre matériel est donc inclusif : avec un modèle choisi, il garde
  les bugs qui le citent, ceux qui ne citent que sa famille et ceux qui ne citent aucun matériel.
- CN-Series publie une page de problèmes connus et une page de corrections par génération (« CN-Series
  10.x », « 11.x »), sans version précise. Un problème connu vaut pour toutes les versions des branches de
  cette génération, jusqu'à sa correction. Une correction est indiquée sans être placée sur une version.
- Les notes ne donnent pas de date de publication : une version est datée du jour où l'outil la découvre.
- Les correctifs de sécurité sont écartés et les références CVE retirées des descriptions.

## Sources

- Release Notes de PAN-OS et de CN-Series sur `docs.paloaltonetworks.com`. Le robots.txt de ce site interdit aux robots les copies
  PDF (`/content/dam/techdocs/en_US/*.pdf`) : elles ne sont jamais téléchargées. Les pages HTML, autorisées
  et rendues par le serveur, sont lues à la place, et chaque bug renvoie vers la page exacte qui le cite.
- Les pages sont découvertes par le sitemap du site, avec leur date de modification. Une page n'est
  téléchargée que si elle est nouvelle ou si cette date a changé. Deux secondes séparent deux requêtes.
- Les branches 9.0 et 10.0, absentes du sitemap et terminées, ont été parcourues une fois en suivant
  les liens de leur livre, et ne sont plus jamais interrogées.
- Le résultat de la lecture est commité dans `data/` : vider le cache de la CI ne relance pas la lecture
  de toutes les pages.
- Dates de support : page [End-of-Life Summary](https://www.paloaltonetworks.com/services/support/end-of-life-announcements/end-of-life-summary)
  de Palo Alto Networks, tableau « PAN-OS & Panorama » (support standard et support étendu).
- Matériel : page [Hardware End-of-Life Dates](https://www.paloaltonetworks.com/services/support/end-of-life-announcements/hardware-end-of-life-dates),
  avec la date de fin de vie et la dernière version de PAN-OS de chaque produit. Seules les lignes qui
  citent un pare-feu ou une appliance sont gardées : une carte, un disque ou un transceiver ne dit rien du
  modèle. Résultat dans `sources/hardware.json` ; une page illisible garde les dernières valeurs.
- La version préférée de Palo Alto Networks est sur une page réservée aux clients : elle n'est pas reprise.

## Mise à jour

Un traitement GitHub Actions s'exécute du lundi au vendredi à 9 h 15, 14 h 15 et 19 h 00, heure de
Paris, et sur lancement manuel. Il collecte, extrait, contrôle, puis publie le site sur GitHub Pages. Si
un contrôle échoue, le site garde ses dernières données valides.

À chaque passage, seul le sitemap est relu en entier ; seules les pages nouvelles ou modifiées depuis le
dernier passage sont téléchargées et relues.

## Liens utiles chez Palo Alto Networks

- [Where to find the current preferred software versions?](https://knowledgebase.paloaltonetworks.com/KCSArticleDetail?id=kA10g000000PMViCAO) :
  versions préférées de PAN-OS, accès client requis pour la page de LIVEcommunity
- [Best Practices for PAN-OS Upgrade](https://knowledgebase.paloaltonetworks.com/KCSArticleDetail?id=kA10g000000ClRrCAK)
- [Compatibility Matrix](https://docs.paloaltonetworks.com/compatibility-matrix) : matériel et versions supportées
- [Hardware End-of-Life Dates](https://www.paloaltonetworks.com/services/support/end-of-life-announcements/hardware-end-of-life-dates)
- [Customer Support Portal](https://support.paloaltonetworks.com/) : compte requis

## Développement

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
node --test tests/site/logic.test.js
```

Pour récupérer les pages puis prévisualiser le site :

```sh
.venv/bin/palobugs collect
.venv/bin/palobugs extract
.venv/bin/palobugs --base-url http://localhost:8020/ build
python3 -m http.server 8020 --directory dist
```

## Licence

Le code est distribué sous licence [GNU AGPL 3.0 ou ultérieure](LICENSE).

Cette licence ne couvre pas les contenus de tiers, notamment les textes issus de la documentation
Palo Alto Networks. Palo Alto Networks et PAN-OS sont des marques de Palo Alto Networks, Inc.

## Contact

Outil créé et maintenu par [FR Consulting](https://fr-consulting.fr).
Pour toute demande : contact@fr-consulting.fr
