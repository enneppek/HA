# Automatisation Home Assistant — chauffage & présence

Dépôt de configuration pour l'automatisation du chauffage (chaudière mazout +
climatisation) piloté par la présence des occupants.

## Matériel en place

| Élément | Rôle |
|---|---|
| Honeywell Lyric T6 (API → HA) | Thermostat pilotant la chaudière mazout |
| Vannes thermostatiques Sonoff Zigbee (TRV) | Régulation par pièce |
| Clim Panasonic (Comfort Cloud) | Chaud/froid d'appoint |
| Capteurs température + humidité Zigbee | Mesure par pièce |

## Objectifs

1. Programmation horaire de la chaudière (confort / éco / hors-gel).
2. Consigne de température par pièce selon la présence de chacun
   (les enfants et le parent), pièce par pièce.

## Pourquoi le travail se fait en local

Une session Claude Code hébergée dans le cloud ne peut pas joindre
`192.168.129.248:8123` : elle tourne dans un conteneur isolé, sans route vers
un LAN privé ni vers un tailnet. Les automatisations se développent donc
depuis une machine du réseau local, qui elle a accès à l'instance.

### Mise en place sur une machine du LAN

Claude Code s'installe en ligne de commande. Choisir l'onglet correspondant
à son terminal.

**Windows — Invite de commandes (cmd)**

```bat
curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd
```

**Windows — PowerShell**

```powershell
irm https://claude.ai/install.ps1 | iex
```

Repère : l'invite affiche `PS C:\>` en PowerShell, et `C:\>` sans le `PS`
en cmd. Si `irm` renvoie « n'est pas reconnu », c'est qu'on est en cmd ;
si `&&` renvoie « n'est pas un séparateur d'instruction valide », c'est
qu'on est en PowerShell.

Sur Windows, installer aussi [Git pour Windows](https://git-scm.com/downloads/win) :
il fournit `git` et permet à Claude Code d'utiliser bash plutôt que PowerShell.

**macOS / Linux**

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Vérifier ensuite l'installation :

```bash
claude --version
```

**Puis, dans tous les cas :**

```bash
git clone https://github.com/enneppek/ha.git
cd ha
git checkout claude/home-assistant-automation-a404kg
claude
```

Au premier lancement, Claude Code demande de se connecter via le navigateur.

### Jeton d'accès Home Assistant

Ne jamais utiliser son mot de passe HA. Créer un jeton, qui se révoque d'un
clic sans toucher au compte :

Profil (en bas à gauche) > Sécurité > Jetons d'accès longue durée > Créer.
Le copier immédiatement, il n'est plus affiché ensuite.

```bash
cp .env.exemple .env
# puis éditer .env pour y coller l'URL et le jeton
```

`.env` est ignoré par git : le jeton ne doit jamais être committé.

### Vérifier la connexion depuis le LAN

```bash
set -a && . ./.env && set +a
curl -s -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/"
# Réponse attendue : {"message":"API running."}
```

Un **timeout** signale un problème de route réseau (mauvaise IP, mauvais
port, machine hors du LAN). Un **401** signale un jeton invalide : la
connexion, elle, fonctionne.

## Inventaire des entités

Avant d'écrire la moindre automatisation, il faut connaître les identifiants
réels des entités. Coller le contenu de `outils/export_entites.jinja` dans
Home Assistant : **Outils de développement > Modèle**, puis enregistrer le
résultat dans `inventaire.md`.

## Structure

```
packages/chauffage.yaml            Logique de chauffage (à déployer dans HA)
tableau_de_bord/carte_chauffage.yaml  Carte Lovelace
outils/export_entites.jinja        Modèle d'export des entités
outils/test_logique.py             Banc d'essai de la logique
```

Les fichiers de `packages/` se déploient via `packages:` dans
`configuration.yaml` :

```yaml
homeassistant:
  packages: !include_dir_named packages
```

## Logique de chauffage

### Règle de décision

Pour chaque pièce, la consigne est choisie par ordre de priorité décroissant :

| Priorité | Condition | Consigne |
|---|---|---|
| 1 | Bouton confort de la pièce pressé | Confort |
| 2 | Un occupant présent **et** horaire actif | Confort |
| 3 | Un occupant présent, hors horaire | Nuit |
| 4 | Aucun occupant présent | Absence (15 °C) |

La présence prime donc sur la parité de semaine : si Léo est là un mercredi
de semaine paire, il suffit d'appuyer sur son bouton pour que sa chambre et
la salle de bains enfants repassent en confort.

### Parité des semaines

| Semaine | Enfants | Chambres Léo, Pablo et SdB enfants |
|---|---|---|
| Paire | Absents | 15 °C |
| Impaire | Présents | Suivent l'horaire |

La bascule est automatique chaque nuit à 00h05. Les vacances scolaires ne
suivent pas la parité : `input_select.garde_enfants` permet de forcer
**Présents** ou **Absents** sans toucher au YAML.

### Commandes de la carte

- **Léo / Pablo / Laurent** — présence de chacun. Éteindre Léo ramène sa
  chambre à 15 °C ; la salle de bains enfants reste chaude tant que Pablo
  est présent, puisqu'elle a deux occupants.
- **Un bouton par pièce** — force la température de confort, puis se coupe
  seul au bout de la durée réglée (2 h par défaut).

## Déploiement

1. Activer les packages dans `configuration.yaml` :

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

2. Copier `packages/chauffage.yaml` dans le dossier `packages/` de Home Assistant.
3. **Remplacer les identifiants d'entités** du bloc `pieces` par les vrais
   (voir `outils/export_entites.jinja`). Ceux livrés sont des suppositions.
4. Outils de développement > Vérifier la configuration, puis redémarrer.
5. Ajouter la carte : tableau de bord > crayon > + Ajouter une carte >
   Manuel, et coller `tableau_de_bord/carte_chauffage.yaml`.

## Points de vigilance

### La sonde de Léo

Une vanne thermostatique mesure la température au ras du radiateur, donc
trop chaud : elle ferme avant que la pièce soit à température. La sonde
Sonoff de la chambre de Léo corrige ce biais, à condition que la vanne
accepte une mesure externe.

L'automatisation `chauffage_sonde_externe_leo` suppose une **TRVZB sous
Zigbee2MQTT**, qui expose `number.<vanne>_external_temperature_input`. Si
cette entité n'existe pas chez toi, deux solutions de repli :

- `number.<vanne>_local_temperature_calibration` — appliquer un décalage
  égal à `sonde_pièce - température_lue_par_la_vanne` ;
- un `generic_thermostat` qui régule sur la sonde et commande la vanne en
  tout ou rien.

Le choix dépend du firmware réel de tes vannes — d'où l'intérêt de l'export
d'entités.

### Le Lyric T6 coupe la chaudière

Le T6 est un thermostat d'ambiance : satisfait, il arrête le brûleur et les
vannes n'ont plus d'eau chaude, quelle que soit leur consigne. D'où
`chauffage_pilotage_chaudiere`, qui le pousse à 22 °C dès qu'une pièce
réclame et le laisse retomber à 15 °C sinon.

Deux vérifications sur place :

- Le T6 doit être en **maintien permanent**, sinon son programme interne
  reprendra la main sur la consigne envoyée par HA.
- La pièce où il est installé doit avoir un radiateur non robinetté, ou
  rester en demande, faute de quoi la régulation se mord la queue.

### Anti-cycles

`binary_sensor.chauffage_demande_chaudiere` déclenche à partir d'un déficit
de 0,3 °C et retombe avec 10 minutes de retard (`delay_off`), pour éviter
que la chaudière ne s'allume et s'éteigne en rafale. À ajuster selon
l'inertie réelle de l'installation.

## Tests

La logique de calcul des consignes est vérifiable hors instance :

```bash
python3 outils/test_logique.py
```

Le script simule le moteur de templates de Home Assistant et couvre les
semaines paires et impaires, les présences partielles, les boutons confort
et la demande chaudière. À relancer après toute modification du bloc
`pieces` ou des règles de priorité.

## Reste à faire

- Brancher les vrais identifiants d'entités (bloquant).
- Décider de la source de présence : app Companion (GPS) pour automatiser
  les boutons, ou pilotage manuel.
- Intégrer la clim Panasonic (Comfort Cloud), non traitée à ce stade :
  appoint en chauffage, ou rafraîchissement l'été.
