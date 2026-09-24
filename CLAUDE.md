# Contexte pour Claude Code

Dépôt d'automatisation du chauffage de la maison de Laurent (« Lolo »), sous
Home Assistant. Lire le README pour la logique complète. Ce fichier résume ce
qu'il faut savoir pour agir sur l'instance.

## Accès à Home Assistant

- Instance : `http://192.168.129.248:8123` (réseau local uniquement).
- Jeton d'accès longue durée dans `.env` (`HA_URL`, `HA_TOKEN`), ignoré par git.
  **Ne jamais afficher le jeton, ni le committer.**
- Charger les variables : `set -a && . ./.env && set +a`
- Lire un état :
  `curl -s -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/states/<entity_id>"`
- Appeler un service :
  `curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" -H "Content-Type: application/json" -d '{...}' "$HA_URL/api/services/<domaine>/<service>"`

## Déploiement

Le dépôt est cloné **dans** Home Assistant, sous `/config/claude-ha`, et
chargé par cette ligne placée en tête de `configuration.yaml` :

```yaml
homeassistant:
  packages: !include_dir_named claude-ha/packages
```

Le tableau de bord est lui aussi lu dans le dépôt, en mode YAML, par ce
bloc également placé en tête de `configuration.yaml` :

```yaml
lovelace:
  dashboards:
    chauffage-auto:
      mode: yaml
      title: Chauffage
      icon: mdi:radiator
      show_in_sidebar: true
      filename: claude-ha/tableau_de_bord/dashboard.yaml
```

Sauvegardes : `/config/configuration.yaml.avant-chauffage` (d'origine) et
`/config/configuration.yaml.avant-tableau` (avant l'ajout du tableau de bord).

Mettre à jour après un push : dans le terminal de HA (add-on Terminal & SSH),
`cd /config/claude-ha && git pull && ha core check && ha core restart`.
Depuis ce PC, on ne peut pas faire le `git pull` côté HA ; on peut en revanche
vérifier et recharger par l'API :

- vérifier la configuration : `POST /api/config/core/check_config`
- recharger sans redémarrer : services `template.reload`, `automation.reload`,
  `input_boolean.reload`, `input_number.reload`, `input_select.reload`,
  `schedule.reload`
- redémarrer : service `homeassistant.restart`

## Avant tout commit

`python3 outils/test_logique.py` doit passer. Il contrôle aussi la syntaxe de
tous les templates : une erreur Jinja laisse le YAML valide et rend seulement
le capteur « unavailable », sans autre signal.

## Règles

- Annoncer toute commande envoyée à un appareil physique (vannes, Lyric T6,
  clim) avant de l'envoyer, avec sa raison.
- **Ne jamais supprimer un appareil ZHA** pour le réappairer : les entités
  seraient recréées avec un suffixe `_2` et les automatisations cesseraient de
  fonctionner sans message d'erreur.
- La clim passe par Comfort Cloud, une API à quota : ne pas multiplier les
  commandes de test.
- Laurent écrit en français et préfère des instructions pas à pas, une étape
  à la fois.

## Points clés de l'installation

- `climate.thermostat_thermostat` : Lyric T6, **installé dans la cuisine**,
  détourné en relais de chaudière (24 °C = appel, 10 °C = repos). Il doit être
  en maintien permanent.
- `climate.clim_chambre` : clim Panasonic, chambre de Lolo, **pièce sans
  radiateur**. Déshumidifie en mode chaud (plus efficace que `dry` sur cet
  appareil).
- 8 vannes Sonoff TRVZB sous ZHA ; correspondance pièce par pièce dans le bloc
  `pieces` de `packages/chauffage.yaml`.
- Sondes d'ambiance : `t_hr` (Léo), `sonoff_t_hr_2` (Pablo), `sonoff_snzb_02d`
  (Lolo) ; la cuisine utilise la sonde du T6. Les autres pièces se rabattent
  sur les sondes internes de leurs vannes.
- `person.keppenne` = Laurent. Pas d'entité de présence pour Léo et Pablo :
  présence par parité de semaine (impaire = présents) et boutons manuels.

## État du déploiement

Package actif depuis le 24/09/2026 : tous les capteurs `sensor.chauffage_*`
ont une valeur, la sonde `t_hr` de Léo est revenue. Calendrier de garde
confirmé : semaine impaire = enfants présents.

## En suspens

- Lyric T6 à passer en maintien permanent.
- Interrupteurs à activer après le premier démarrage : présence Laurent,
  « Limiter l'humidité », « Maintenir une température minimale ».
- Add-on Tailscale qui ne redémarre plus ; statut d'un éventuel essai Nabu Casa.
