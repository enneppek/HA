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

### Première mise en service

Aucun `initial:` n'est posé sur les interrupteurs, afin qu'un redémarrage
n'écrase pas tes choix. Après la première installation, pense donc à activer
**Limiter l'humidité** et **Maintenir une température minimale** sur la carte.

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
packages/chauffage.yaml            Chauffage : consignes, arbitrage, chaudière
packages/clim.yaml                 Climatisation Panasonic
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

## Pièces

| Pièce | Vannes | Occupants | Confort / Nuit / Absence |
|---|---|---|---|
| Chambre Léo | 1 | Léo | 19,5 / 17 / 15 |
| Chambre Pablo | 1 | Pablo | 19,5 / 17 / 15 |
| Salle de bains enfants | 1 | Léo, Pablo | 21 / 18 / 15 |
| Chambre Lolo | **aucune** — clim seule | Lolo | 19,5 / 17 / 15 |
| Boulangerie | 1 | Lolo | 19 / 16 / 15 |
| Cuisine | 2 | tous | 19 / 16,5 / 15 |
| Salon | 2 | tous | 20,5 / 17,5 / 15 |

Une pièce peut porter plusieurs vannes : elles reçoivent toutes la même
consigne. Les pièces communes se déclenchent dès qu'une personne est
présente, quelle qu'elle soit.

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

### Zigbee : ZHA

L'installation tourne sous **ZHA**.

**Ne jamais supprimer un appareil pour le réappairer.** ZHA recrée alors des
entités suffixées `_2` (`climate.vanne_salon_1_2`), et toute automatisation
qui référence les anciennes cesse de fonctionner en silence. Un appareil
réappairé sans suppression rejoint avec la même adresse IEEE et **conserve
ses identifiants**.

Dans l'ordre, pour une vanne qui a décroché :

1. **Reconfigurer l'appareil** (fiche de l'appareil > Reconfigurer). Cela
   relit les clusters et rétablit les liaisons, et suffit souvent.
2. Si elle a réellement quitté le réseau : ZHA en mode ajout, puis appui long
   sur le bouton de la vanne jusqu'au clignotement du symbole réseau.
3. Réveiller l'appareil pendant l'opération — une vanne sur pile dort, et ZHA
   ne peut lui parler que fenêtre ouverte.

**Chercher la cause, sinon le problème reviendra.** Deux vannes voisines
perdues simultanément ne relèvent pas du hasard :

- **piles faibles** — une TRVZB sous tension basse décroche sans prévenir ;
- **routeur Zigbee disparu** — les vannes sont des terminaux sur pile et
  dépendent d'un appareil sur secteur à proximité. Une prise Zigbee
  débranchée ou déplacée fait décrocher tout ce qui transitait par elle.

**Point à vérifier sous ZHA :** l'entrée de température externe des TRVZB
n'est pas exposée de la même façon que sous Zigbee2MQTT. Si
`number.<vanne>_external_temperature_input` n'existe pas, se rabattre sur
`number.<vanne>_local_temperature_calibration` (voir ci-dessous).

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

### Le Lyric T6 détourné en relais

**Le T6 est installé dans la cuisine.** Laissé en thermostat, il confie le
chauffage de toute la maison à la température d'une seule pièce — celle qui
monte le plus vite, cuisson comprise. Le symptôme observé : les vannes de la
cuisine ouvertes à 30 °C, la cuisine satisfaite, **le brûleur coupé pendant
qu'une chambre est à 16 °C**. Aucune consigne de vanne ne rattrape cela :
sans eau chaude, une vanne ouverte ne chauffe rien.

Le T6 n'est donc plus un thermostat, mais un interrupteur :

| Demande de Home Assistant | Consigne envoyée au T6 | Effet |
|---|---|---|
| Une pièce au moins réclame | `chaudiere_consigne_marche` (26 °C) | Le T6 ne peut être satisfait, le brûleur tourne |
| Aucune pièce ne réclame | `chaudiere_consigne_arret` (10 °C) | Le T6 relâche, le brûleur s'arrête |

Ce sont les vannes, pièce par pièce, qui règlent réellement les températures.
Le T6 ne fait plus qu'ouvrir et fermer le robinet d'eau chaude.

**Pourquoi 26 °C et non 30 °C.** Si Home Assistant tombe en panne, le T6
reste figé sur sa dernière consigne. Cette valeur borne alors la température
de la cuisine : à 30 °C elle deviendrait invivable, à 26 °C elle est
seulement chaude. C'est le compromis entre « toujours appeler » et « échouer
sans dégât ». Si ta cuisine dépasse régulièrement 26 °C en cuisinant, relève
la consigne d'appel — c'est exactement à quoi sert le réglage.

**À corriger sur place :** remets les vannes de la cuisine en régulation
normale. Leur réglage à 30 °C était un contournement du problème ; une fois
le T6 en relais, il devient nuisible — la cuisine surchaufferait et le T6 ne
réclamerait plus. Le package s'en charge automatiquement dès qu'il tourne.

**Deux vérifications sur place :**

- Le T6 doit être en **maintien permanent**, sinon son programme interne
  reprendra la main sur la consigne envoyée par HA.
- L'installation a besoin d'un **débit minimal** : si toutes les vannes se
  ferment pendant que le brûleur tourne, la chaudière cycle court. La
  temporisation de 10 minutes y aide, mais un radiateur non robinetté ou une
  soupape différentielle reste la vraie réponse hydraulique.

### Ancienne note — le T6 coupe la chaudière

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

## Climatisation Panasonic — chambre de Lolo

Cette pièce **n'a aucun radiateur**. La clim y est l'unique source de
chaleur, ce qui lui donne deux garanties à tenir, toutes deux réglables
depuis la carte, et mesurées sur la sonde d'ambiance Sonoff de la pièce :

| Garantie | Réglage | Défaut |
|---|---|---|
| Température minimale | `input_number.clim_temp_min` | 15 °C |
| Humidité relative maximale | `input_number.clim_seuil_humidite` | 65 % |

Chacune se désactive : `input_boolean.clim_maintien_temp_min` et
`input_boolean.clim_auto_deshu`.

En dehors de ces deux garanties, la clim ne fait rien. Le rafraîchissement
d'été et l'appoint chauffage existent, mais sont **désactivés par défaut** :
ce sont deux interrupteurs à activer si le besoin s'en fait sentir.

### Assèchement par le mode chaud

L'assèchement passe par le mode **chaud**, et non par le mode `dry` : sur
cette Panasonic, le mode chaud fait tomber l'humidité relative bien plus
efficacement. Il l'abaisse en réchauffant l'air plutôt qu'en extrayant de
l'eau — ce qui est justement l'effet recherché contre la condensation et les
moisissures sur les parois froides.

La consigne visée vaut `température ambiante + clim_deshu_delta` (1,5 °C par
défaut), bornée par `clim_deshu_temp_max` (22 °C) : il s'agit d'assécher, pas
de cuire la pièce. Au-delà de cette limite, l'assèchement s'interrompt.

Une hystérésis de 5 points évite le battement : l'assèchement démarre
au-dessus du seuil et ne s'arrête que 5 points en dessous.

### Priorités

| Priorité | Condition | Mode |
|---|---|---|
| 1 | Sous la température minimale | Chaud, jusqu'à ce minimum |
| 2 | Rafraîchissement activé, occupant présent, trop chaud | Froid |
| 3 | Appoint activé et pièce confiée à la clim | Chaud, consigne du moment |
| 4 | Humidité au-dessus du seuil | Chaud (assèchement) |
| 5 | Sinon | Arrêt |

La température minimale passe avant tout le reste : une pièce sans radiateur
qui se refroidit n'a aucun recours.

### Pilotage manuel

Dès qu'une consigne est posée **à la main depuis Home Assistant**,
`input_boolean.clim_pilotage_manuel` s'active et l'automatisation se tait
pendant `clim_duree_manuel` (3 h par défaut), puis reprend d'elle-même.

La détection repose sur `context.user_id`, renseigné uniquement quand un
humain agit depuis Home Assistant : une commande émise par une automatisation
en est dépourvue, ce qui évite que le pilotage ne se prenne lui-même pour toi.

**Limite connue :** un réglage fait depuis la télécommande infrarouge ou
l'application Comfort Cloud n'a pas davantage de `user_id` et passera donc
inaperçu. Dans ce cas, active l'interrupteur de pilotage manuel toi-même.

### Arbitrage avec la chaudière

`sensor.chauffage_relais` désigne, pour chaque pièce, qui délivre la chaleur.
Sans cet arbitrage, la chaudière et la clim chaufferaient la même pièce
simultanément.

| Situation | Relais |
|---|---|
| Pièce sans radiateur | Clim, en toute saison |
| Pièce avec radiateur et clim, appoint activé, extérieur ≥ seuil PAC, demande en cours | Clim |
| Tous les autres cas | Radiateur |

Une pièce confiée à la clim voit sa vanne retomber à la consigne d'absence et
cesse de compter dans la demande chaudière.

### Quota Comfort Cloud

Comfort Cloud est une API distante, lente et limitée en nombre d'appels. Une
automatisation bavarde peut saturer le quota et faire tomber l'intégration en
erreur. Deux garde-fous : aucun ordre n'est envoyé si l'appareil est déjà
dans l'état voulu, et au maximum une commande toutes les 5 minutes par
appareil.

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
- Affiner `clim_seuil_pac` avec les prix réels de l'électricité et du mazout,
  si tu actives un jour l'appoint chauffage.
