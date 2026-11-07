# StorCube Batteries (indépendant)

> Cette intégration communautaire est indépendante de StorCube. Elle n’est pas encore publiée : le dossier doit d’abord être envoyé dans un dépôt GitHub public et ses métadonnées finalisées. Voir [PUBLICATION.md](PUBLICATION.md).

À partir de Home Assistant 2026.11, l’installation d’intégrations via l’ancien HACS est bloquée ; utilise le Marketplace Home Assistant une fois le dépôt publié et accepté dans son catalogue. Sur les versions antérieures qui le permettent, le dépôt peut être ajouté comme dépôt personnalisé HACS.

Intégration Home Assistant autonome écrite spécialement pour connecter une ou plusieurs batteries StorCube via le cloud Baterway. Elle ne reprend pas le code d’une autre intégration Home Assistant. Le dépôt `fwPunsher/batteryMqtt` a uniquement servi de référence publique pour comprendre les messages de connexion MQTT/WebSocket de Baterway.

## Fonctionnement

- Connexion au compte de l’application StorCube.
- Connexion temps réel au WebSocket Baterway.
- Saisie de l’identifiant de chaque batterie à interroger, maître et esclave compris. Le maître seul peut ne transmettre que ses propres mesures; ajoute l’identifiant de l’esclave pour recevoir ses valeurs.
- Capteurs individuels pour chaque batterie reçue.
- Réglages modifiables depuis Home Assistant : puissance de sortie cible (W) et seuil de réserve (%), envoyés à l’API Baterway.
- Un appareil « Batterie virtuelle StorCube » regroupant les mesures reçues : charge moyenne, énergie restante totale, puissance solaire totale, puissance vers onduleur totale, puissance batterie estimée et nombre de modules.
- Diagnostic téléchargeable avec les trames brutes expurgées des identifiants du compte, des séries et des jetons.
- Seuls les paramètres identifiés sont créés en capteurs; les champs API inconnus restent masqués.
- Compteurs cumulés en kWh pour l’énergie chargée, l’énergie déchargée, le solaire (MPPT 1, MPPT 2, total) et l’énergie vers onduleur. Les compteurs sont restaurés après redémarrage.

La charge globale est la moyenne simple des modules découverts. L’énergie restante est la somme des champs `capacity`. La puissance solaire et la puissance vers onduleur utilisent les totaux de la pile lorsqu’ils sont fournis; sinon, les valeurs des modules sont additionnées. La puissance batterie utilise le champ direct s’il est présent; sinon elle est estimée comme le solaire moins la puissance vers onduleur. Les entités utilisent les icônes batterie, solaire et éclair appropriées.

## Installation manuelle

1. Copiez `custom_components/storcube_independent` dans `config/custom_components/`.
2. Redémarrez Home Assistant.
3. Ouvrez **Paramètres → Appareils et services → Ajouter une intégration**.
4. Recherchez **StorCube Batteries (indépendant)**.
5. Saisissez l’identifiant du maître, le compte et le mot de passe de l’application. Le code application par défaut est `Storcube`.
6. Ouvrez **Configurer** sur l’intégration et ajoutez l’identifiant de l’esclave dans **Identifiants de tous les modules**, séparé de celui du maître par une virgule. La batterie virtuelle regroupera les deux.

Dans **Paramètres → Tableaux de bord → Énergie → Batteries**, sélectionnez sur la batterie virtuelle **Énergie déchargée de la batterie** pour l’énergie fournie, puis **Énergie chargée dans la batterie** pour l’énergie reçue. Les deux compteurs sont des capteurs d’énergie cumulée en kWh; la charge (%) et l’énergie restante (Wh) apparaissent comme mesures de la batterie. Home Assistant attend des capteurs d’énergie avec `device_class: energy` et `state_class: total` ou `total_increasing` pour l’Energy Dashboard ([documentation](https://www.home-assistant.io/docs/energy/faq/)).

Après remplacement d’une version déjà installée, redémarrez Home Assistant. Les capteurs restent indisponibles jusqu’à la réception d’une première trame du cloud; laissez quelques minutes au WebSocket pour s’abonner et publier les mesures.

Les mesures changent au fil des trames WebSocket. Les deux commandes d’écriture connues dans batteryMqtt sont la puissance cible et le seuil de décharge/réserve (clé `reserved`/`threshold`). Leur prise en compte physique dépend de l’API et du modèle de batterie. Les champs qui ne sont que lus restent des capteurs.

## Limites

L’API Baterway est privée et non documentée. Les points d’accès observés utilisent HTTP et WebSocket non chiffrés; la connexion passe par le cloud et ne fonctionne donc pas hors ligne. Le format des trames peut changer. Cette première version n’a pas été validée avec une batterie physique dans cet environnement. Si les trames ne correspondent pas à votre micrologiciel, les journaux de `custom_components.storcube_independent` aideront à adapter le parseur.

Pour identifier les champs renvoyés par chaque batterie, télécharge les diagnostics après avoir renseigné les identifiants du maître et de l’esclave. Le fichier comprend les dernières trames brutes et leurs valeurs, avec les mots de passe, jetons et identifiants de batterie retirés. Ne partage jamais le mot de passe ni le jeton d’accès.

Cette intégration est un projet communautaire indépendant, sans affiliation avec StorCube.
