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

Aucun réglage ne porte de `initial:` : Home Assistant réimposerait sinon
cette valeur à chaque redémarrage, effaçant ce qui a été réglé depuis la
carte. Les valeurs de départ sont posées **une seule fois**, au premier
démarrage, par l'automatisation `chauffage_initialiser_reglages`. Elle active
aussi la présence de Laurent et « Maintenir une température minimale ».

Pour revenir aux valeurs d'usine : éteindre
`input_boolean.chauffage_reglages_initialises`, puis redémarrer.

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
tableau_de_bord/dashboard.yaml      Tableau de bord, lu par HA en mode YAML
tableau_de_bord/images/            Illustrations SVG animées
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

| Pièce | Vannes | Température lue sur | Occupants | Confort / Nuit / Absence |
|---|---|---|---|---|
| Chambre Léo | `vanne_thermo_leo` | sonde `t_hr` | Léo | 19,5 / 17 / 15 |
| Chambre Pablo | `vt` | sonde `sonoff_t_hr_2` | Pablo | 19,5 / 17 / 15 |
| Salle de bains enfants | `sonoff_trvzb` | **ses vannes** | Léo, Pablo | 21 / 18 / 15 |
| Chambre Lolo | **aucune** — clim seule | sonde `sonoff_snzb_02d` | Lolo | 19,5 / 17 / 15 |
| Boulangerie | `vt_boulangerie` (+ poêle) | **sa vanne** | Lolo | 19 / 16 / 15 |
| Cuisine | `vtherrmo_cuisine_1`, `vt_cuisine_couloir` | Lyric T6 | tous | 19 / 16,5 / 15 |
| Salon | `vt_salon_aquarium`, `vt_salon_canape` | **ses vannes** | tous | 20,5 / 17,5 / 15 |

### Trois sondes pour sept pièces

L'installation compte 8 vannes mais seulement 3 sondes d'ambiance, une par
chambre : Léo, Pablo, Lolo. La cuisine emprunte celle du Lyric T6, qui s'y
trouve. Les trois pièces restantes — salle de bains enfants, salon,
boulangerie — n'ont aucune mesure directe. Les pièces
qui n'en ont pas voient leur température reprise de la **moyenne des sondes
internes de leurs vannes**, exposée par `sensor.chauffage_temperatures`.

Ces sondes lisent au ras du radiateur, donc trop chaud : la pièce est en
réalité plus froide que la valeur affichée. C'est suffisant pour décider
d'appeler ou non la chaudière, mais moins juste qu'une vraie sonde. L'attribut
`origine` indique, pour chaque pièce, si la mesure vient d'une sonde ou d'un
repli — la carte le signale par la mention _(estimée par les vannes)_.

Le repli joue aussi quand une sonde tombe en panne ou s'épuise : la pièce
bascule seule sur ses vannes au lieu de disparaître du calcul. Ajouter une
sonde Sonoff dans une pièce améliore donc la régulation sans rien changer au
code — il suffit de renseigner sa clé `sonde`.

Une pièce sans sonde **ni** vanne ne serait pas mesurable : elle est alors
traitée comme n'ayant pas besoin de chaleur, plutôt que de faire tourner le
brûleur à l'aveugle.

### Compenser l'absence de sonde

Une vanne lit trop chaud, donc elle ferme trop tôt : la pièce se stabilise
en dessous de sa consigne. Sur une pièce sans sonde, l'écart se rattrape avec
le décalage de température locale de la vanne, exposé par ZHA :

```
number.<vanne>_decalage_de_temperature_locale
```

Méthode : poser un thermomètre au milieu de la pièce, comparer à ce
qu'affiche la vanne, et saisir la différence. Une vanne qui indique 21 °C
dans une pièce réellement à 19 °C prend un décalage de −2. Le réglage tient
jusqu'au remplacement de la pile.

C'est un correctif, pas un équivalent : le décalage est constant, alors que
l'écart réel varie avec la puissance du radiateur. Une vraie sonde d'ambiance
reste préférable — la pièce à équiper en priorité est la salle de bains
enfants, où la consigne de confort est la plus haute.

La boulangerie dispose en plus d'un **poêle à bois**. Aucun traitement
particulier n'est nécessaire : quand le poêle tourne, la pièce dépasse sa
consigne, cesse de réclamer, et sa vanne se ferme d'elle-même.

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

La bascule est automatique le lundi à 00h05, et seulement ce jour-là : un bouton Léo ou Pablo actionné à la main en cours de semaine tient jusqu'au lundi suivant. Les vacances scolaires ne
suivent pas la parité : `input_select.garde_enfants` permet de forcer
**Présents** ou **Absents** sans toucher au YAML.

### Le tableau de bord

Uniquement des cartes natives de Home Assistant, sans extension : vue en
sections, pastilles d'état en haut de page, cadrans de température colorés,
tuiles à boutons +/−, courbes sur 24 h. Deux illustrations animées suivent
l'état réel : la maison (fumée et fenêtres éclairées quand la chaudière
tourne) et la clim (souffle chaud, flocons ou gouttes aspirées selon son
rôle). Ce sont des SVG animés, rangés dans `tableau_de_bord/images/` et
copiés dans `/config/www/chauffage/` lors de chaque mise à jour :

```bash
cd /config/claude-ha && git pull
mkdir -p /config/www/chauffage && cp tableau_de_bord/images/*.svg /config/www/chauffage/
ha core check && ha core restart
```

- **Vue d'ensemble** — pour chaque pièce : mesure, consigne en cours, et
  horaire suivi (commun ou propre), avec son état.
- **Léo / Pablo / Laurent** — présence de chacun. Éteindre Léo ramène sa
  chambre à la température d'absence ; la salle de bains enfants reste
  chaude tant que Pablo est présent, puisqu'elle a deux occupants.
- **Une carte par pièce** — températures de confort et de nuit réglables, et
  un bouton qui force le confort immédiatement, puis se coupe seul au bout de
  la durée réglée (2 h par défaut).
- **Horaires** — voir ci-dessous.

### Réglages par pièce

Chaque pièce à radiateur a deux réglages, `input_number.chauffage_<pièce>_confort`
et `_nuit`. Les valeurs du bloc `pieces` ne servent plus que de repli, si un
réglage est indisponible. La température d'absence, elle, est commune à
toute la maison (`input_number.chauffage_absence`).

La chambre de Lolo n'a pas ces réglages : sa clim n'y chauffe pas, sauf à
activer l'appoint chauffage. Elle maintient une température minimale, et
n'assèche que sur demande (voir plus bas).

### Horaires

Une planification définie en YAML n'est pas modifiable dans l'interface. Les
horaires se créent donc dans Home Assistant (*Paramètres → Appareils et
services → Entrées → Créer une entrée → Planification*), où l'on dessine les
plages à la souris sur une grille hebdomadaire.

Chaque pièce cherche, dans l'ordre :

1. sa planification propre, `schedule.chauffage_<pièce>` ;
2. l'horaire commun, `schedule.chauffage_commun` ;
3. l'horaire par défaut, défini en YAML et non modifiable, qui n'est qu'un
   filet de sécurité.

L'identifiant est tiré du nom saisi à la création : il faut donc taper le
nom exact.

| Pour | Nom à saisir |
|---|---|
| Toute la maison | `Chauffage commun` |
| Chambre Léo | `Chauffage chambre leo` |
| Chambre Pablo | `Chauffage chambre pablo` |
| Salle de bains enfants | `Chauffage sdb enfants` |
| Chambre Lolo | `Chauffage chambre laurent` |
| Boulangerie | `Chauffage boulangerie` |
| Cuisine | `Chauffage cuisine` |
| Salon | `Chauffage salon` |

Une planification créée est prise en compte d'elle-même, sans redémarrage :
la vue d'ensemble indique « propre » en face de la pièce. Une fois créée, son
nom affiché peut être changé librement ; seul l'identifiant compte.

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
5. Déclarer le tableau de bord, lu directement dans le dépôt (aucun
   copier-coller dans l'interface, et un `git pull` le met à jour) :

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
| Une pièce au moins réclame | `chaudiere_consigne_marche` (24 °C) | Le T6 ne peut être satisfait, le brûleur tourne |
| Aucune pièce ne réclame | `chaudiere_consigne_arret` (10 °C) | Le T6 relâche, le brûleur s'arrête |

Ce sont les vannes, pièce par pièce, qui règlent réellement les températures.
Le T6 ne fait plus qu'ouvrir et fermer le robinet d'eau chaude.

**Pourquoi 24 °C et non le maximum.** Si Home Assistant tombe en panne, le
T6 reste figé sur sa dernière consigne, et cette valeur borne alors la
température de la cuisine : à 30 °C elle deviendrait invivable. C'est le
compromis entre « toujours appeler » et « échouer sans dégât ».

24 °C laisse environ 5 °C de marge au-dessus de la consigne de la cuisine.
Contrepartie à surveiller : une cuisson qui pousse la pièce au-delà de 24 °C
fera relâcher le brûleur le temps qu'elle redescende. Si cela arrive souvent
en hiver, relève la consigne d'appel — c'est exactement à quoi sert le
réglage.

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
chaleur. Elle fait deux choses, et rien d'autre :

| Rôle | Déclenchement | Action |
|---|---|---|
| Température minimale | automatique, si la sonde Sonoff passe sous le seuil | chaud, jusqu'à `input_number.clim_temp_min` (15 °C) |
| Assèchement | **uniquement sur demande**, bouton « Assécher la chambre » | chaud à **24 °C** pendant 1 h ou 2 h, au choix |

Le maintien du minimum se désactive par `input_boolean.clim_maintien_temp_min`.
Le rafraîchissement d'été et l'appoint chauffage existent, mais sont
**désactivés par défaut** : ce sont deux interrupteurs dans les Réglages.

### Assèchement à la demande

Aucun seuil d'humidité ne déclenche la clim : c'est un choix de Laurent. Un
appui sur **« Assécher la chambre »** (`input_boolean.clim_assechement`) la
passe en mode chaud à 24 °C pour la durée choisie dans
`input_select.clim_duree_assechement` (1 h ou 2 h), puis elle s'arrête seule.
Un second appui l'arrête avant. Pendant l'assèchement, la carte indique
l'heure de fin.

L'assèchement passe par le mode **chaud**, et non par le mode `dry` : sur
cette Panasonic, le mode chaud fait tomber l'humidité relative bien plus
efficacement. Il l'abaisse en réchauffant l'air plutôt qu'en extrayant de
l'eau — ce qui est justement l'effet recherché contre la condensation et les
moisissures sur les parois froides.

Appuyer sur le bouton est une demande explicite : cela désactive un éventuel
pilotage manuel en cours, sans quoi rien ne se passerait. La fin est vérifiée
chaque minute, et non par une minuterie, qu'un redémarrage de Home Assistant
annulerait.

### Priorités

| Priorité | Condition | Mode |
|---|---|---|
| 1 | Assèchement demandé | Chaud, 24 °C |
| 2 | Sous la température minimale | Chaud, jusqu'à ce minimum |
| 3 | Rafraîchissement activé, occupant présent, trop chaud | Froid |
| 4 | Appoint activé et pièce confiée à la clim | Chaud, consigne du moment |
| 5 | Sinon | Arrêt |

L'assèchement, demandé explicitement, passe devant tout le reste ; à 24 °C,
il couvre de toute façon le minimum. La température minimale passe avant tout le reste : une pièce sans radiateur
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
- Remettre en service la sonde `t_hr` de la chambre de Léo, qui remonte
  encore indisponible (pile, ou réappairage ZHA sans supprimer l'appareil).
- Racheter des sondes d'ambiance : salle de bains enfants d'abord, puis
  salon et boulangerie.
- En attendant, calibrer les vannes des pièces sans sonde (voir plus haut).
- Affiner `clim_seuil_pac` avec les prix réels de l'électricité et du mazout,
  si tu actives un jour l'appoint chauffage.
