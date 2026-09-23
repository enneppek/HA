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
`192.168.129.248:8130` : elle tourne dans un conteneur isolé, sans route vers
un LAN privé ni vers un tailnet. Les automatisations se développent donc
depuis une machine du réseau local, qui elle a accès à l'instance.

### Mise en place sur une machine du LAN

```bash
# 1. Installer Claude Code (Linux / macOS)
curl -fsSL https://claude.ai/install.sh | bash
#    (alternative : npm install -g @anthropic-ai/claude-code)

# 2. Cloner ce dépôt
git clone https://github.com/enneppek/ha.git
cd ha
git checkout claude/home-assistant-automation-a404kg

# 3. Créer un jeton d'accès longue durée dans Home Assistant :
#    Profil (en bas à gauche) > Sécurité > Jetons d'accès longue durée
#    > Créer un jeton. Le copier immédiatement, il ne sera plus affiché.
cp .env.exemple .env
$EDITOR .env          # y coller l'URL et le jeton

# 4. Lancer Claude Code depuis le dépôt
claude
```

`.env` est ignoré par git : le jeton ne doit jamais être committé.

### Vérifier la connexion depuis le LAN

```bash
set -a && . ./.env && set +a
curl -s -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/" 
# Réponse attendue : {"message":"API running."}
```

## Inventaire des entités

Avant d'écrire la moindre automatisation, il faut connaître les identifiants
réels des entités. Coller le contenu de `outils/export_entites.jinja` dans
Home Assistant : **Outils de développement > Modèle**, puis enregistrer le
résultat dans `inventaire.md`.

## Structure

```
packages/    Automatisations HA, un fichier par domaine fonctionnel
outils/      Scripts et modèles utilitaires
inventaire.md  Liste des entités réelles (à générer)
```

Les fichiers de `packages/` se déploient via `packages:` dans
`configuration.yaml` :

```yaml
homeassistant:
  packages: !include_dir_named packages
```
