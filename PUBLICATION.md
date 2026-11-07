# Préparer la publication

Ce dossier est structuré pour un dépôt GitHub public contenant une seule intégration.

## Avant l’envoi sur GitHub

1. Créer le dépôt public [`Doudoulez/storcube-independent`](https://github.com/Doudoulez/storcube-independent) et y envoyer le contenu de ce dossier, sans ajouter un dossier parent autour. Les liens et le propriétaire du manifest sont déjà renseignés.
3. Dans les réglages GitHub, ajouter une description, activer Issues et choisir les sujets `home-assistant`, `home-assistant-integration`, `storcube`, `battery`.
4. Vérifier que les actions **Validate HACS** et **Validate Home Assistant** réussissent.
5. Créer une release GitHub dont le tag correspond exactement à `version` dans le manifest (actuellement `0.4.3`).
6. Pour demander l’ajout au catalogue public, suivre le guide officiel de soumission au Marketplace.

Le dépôt public et la release sont nécessaires : un fichier ZIP seul ne peut pas être installé depuis le catalogue. Ne publiez jamais de mot de passe, jeton ou identifiant personnel dans le dépôt ou dans un diagnostic.

## Installation

Sur Home Assistant 2026.11 et versions ultérieures, installer l’intégration depuis le Marketplace Home Assistant. Sur une version qui prend encore en charge les dépôts personnalisés HACS, ajouter l’URL du dépôt public comme dépôt personnalisé de type **Intégration**.
