"""Banc d'essai de la logique de chauffage et de climatisation.

Simule le moteur de templates de Home Assistant pour vérifier les décisions
hors instance réelle. À relancer après toute modification du bloc `pieces`
ou des règles de priorité :

    python3 outils/test_logique.py

Les scénarios désignent les pièces par leur nom court ('chambre_leo'), jamais
par un identifiant d'entité : la correspondance est lue dans le bloc `pieces`,
si bien qu'un renommage d'entité ne casse aucun test.
"""
import datetime
import yaml
from jinja2 import Environment

RACINE = __file__.rsplit('/outils/', 1)[0]
chauffage = yaml.safe_load(open(RACINE + '/packages/chauffage.yaml', encoding='utf-8'))
clim_pkg = yaml.safe_load(open(RACINE + '/packages/clim.yaml', encoding='utf-8'))
carte = yaml.safe_load(open(RACINE + '/tableau_de_bord/dashboard.yaml', encoding='utf-8'))


def capteur(paquet, nom):
    for bloc in paquet['template']:
        for cle in ('sensor', 'binary_sensor'):
            for c in bloc.get(cle, []):
                if c['name'] == nom:
                    return c
    raise KeyError(nom)


TPL_CFG = capteur(chauffage, 'Chauffage configuration')['attributes']['pieces']
TPL_TEMPS = capteur(chauffage, 'Chauffage températures')['attributes']['temperatures']
TPL_ORIGINE = capteur(chauffage, 'Chauffage températures')['attributes']['origine']
TPL_CONSIGNES = capteur(chauffage, 'Chauffage consignes')['attributes']['consignes']
TPL_HORAIRES = capteur(chauffage, 'Chauffage consignes')['attributes']['horaires']
TPL_ETAT = capteur(chauffage, 'Chauffage consignes')['state']
TPL_TEXT = capteur(chauffage, 'Chauffage température extérieure')['state']
TPL_RELAIS = capteur(chauffage, 'Chauffage relais')['attributes']['relais']
TPL_DEMANDE = capteur(chauffage, 'Chauffage demande chaudière')['state']
TPL_CHAUDIERE = capteur(chauffage, 'Chauffage consigne chaudière')['state']
TPL_ORDRES = capteur(clim_pkg, 'Clim pilotage')['attributes']['ordres']
TPL_ROLE = capteur(clim_pkg, 'Clim rôle')['state']


def rendre_brut(tpl, globals_=None):
    def flottant(v, default=None):
        try:
            return float(v)
        except (TypeError, ValueError):
            if default is None and default is not False:
                return None
            return default

    env = Environment()
    env.filters['float'] = flottant
    env.globals.update(globals_ or {})
    return env.from_string(tpl).render().strip()


# Le bloc `pieces` est un littéral : il se rend sans état simulé.
PIECES = eval(rendre_brut(TPL_CFG, {'states': lambda e: 'unknown',
                                    'state_attr': lambda e, a: None}))

# Correspondances inverses, pour désigner les pièces par leur nom.
PIECE_PAR_SONDE = {c['sonde']: p for p, c in PIECES.items() if c['sonde']}
PIECE_PAR_HUMIDITE = {c['humidite']: p for p, c in PIECES.items() if c['humidite']}
PIECE_PAR_VANNE = {v: p for p, c in PIECES.items() for v in c['vannes']}
PIECE_PAR_CLIM = {c['clim']: p for p, c in PIECES.items() if c['clim']}


class Monde:
    """État simulé de l'instance Home Assistant."""

    REGLAGES = {
        'input_number.clim_seuil_pac': 5,
        'input_number.clim_seuil_froid': 26,
        'input_number.clim_consigne_ete': 25,
        'input_number.clim_seuil_humidite': 65,
        'input_number.clim_deshu_delta': 1.5,
        'input_number.clim_deshu_temp_max': 22,
        'input_number.clim_temp_min': 15,
        'input_number.chaudiere_consigne_marche': 24,
        'input_number.chaudiere_consigne_arret': 10,
    }

    def __init__(self, presents=(), horaire=True, boosts=(), temps=None,
                 humidites=None, semaine=41, exterieur=12.0,
                 clim_froid=False, clim_chaud=False, clim_deshu=True,
                 temp_min=True, manuel=False, clim_etat='off',
                 sondes_indispo=(), reglages=None, horaires=None):
        # Valeurs par défaut conformes à l'installation : déshumidification
        # seule, froid et appoint chauffage désactivés.
        self.presents = set(presents)
        self.horaire = horaire
        self.boosts = set(boosts)
        self.temps = temps or {}          # clé = nom de pièce
        self.humidites = humidites or {}  # clé = nom de pièce
        self.semaine = semaine
        self.exterieur = exterieur
        self.clim = {'froid': clim_froid, 'chaud': clim_chaud, 'deshu': clim_deshu}
        self.temp_min, self.manuel, self.clim_etat = temp_min, manuel, clim_etat
        self.sondes_indispo = set(sondes_indispo)
        self.reglages = {**self.REGLAGES, **(reglages or {})}
        # Planifications créées dans l'interface : {entité: 'on' | 'off'}.
        # Absentes du dictionnaire, elles n'existent pas.
        self.horaires = horaires or {}
        self.pieces = PIECES
        self.temperatures = self.origine = None
        self.consignes = self.relais = self.ordres = None
        self.text = None
        self.demande = False

    def temp_piece(self, piece):
        return self.temps.get(piece, 18.0)

    def states(self, eid):
        if eid is None or '.' not in str(eid):
            raise TypeError(f"identifiant d'entité invalide : {eid!r} "
                            "(Home Assistant lève ici une erreur)")
        if eid in self.reglages:
            return str(self.reglages[eid])
        if eid in PIECE_PAR_SONDE:
            piece = PIECE_PAR_SONDE[eid]
            if piece in self.sondes_indispo:
                return 'unavailable'
            return str(self.temp_piece(piece))
        if eid in PIECE_PAR_HUMIDITE:
            return str(self.humidites.get(PIECE_PAR_HUMIDITE[eid], 50.0))
        if eid in PIECE_PAR_CLIM:
            return self.clim_etat
        if eid == 'sensor.thermostat_thermostat_outdoor_temperature':
            return str(self.exterieur)
        if eid == 'sensor.chauffage_temperature_exterieure':
            return str(self.text)
        if eid == 'binary_sensor.chauffage_demande_chaudiere':
            return 'on' if self.demande else 'off'
        if eid == 'schedule.chauffage':
            return 'on' if self.horaire else 'off'
        if eid.startswith('schedule.'):
            return self.horaires.get(eid, 'unknown')
        if eid == 'input_boolean.clim_maintien_temp_min':
            return 'on' if self.temp_min else 'off'
        if eid == 'input_boolean.clim_pilotage_manuel':
            return 'on' if self.manuel else 'off'
        if eid.startswith('input_boolean.clim_auto_'):
            return 'on' if self.clim[eid.rsplit('_', 1)[1]] else 'off'
        if eid.startswith('input_boolean.presence_'):
            return 'on' if eid.split('presence_')[1] in self.presents else 'off'
        if eid.startswith('input_boolean.confort_'):
            return 'on' if eid.split('confort_')[1] in self.boosts else 'off'
        return 'unknown'

    def is_state(self, eid, val):
        return self.states(eid) == val

    def state_attr(self, eid, attr):
        # Sonde interne d'une vanne : sert de repli quand la pièce n'a pas
        # de sonde d'ambiance.
        if eid in PIECE_PAR_VANNE and attr == 'current_temperature':
            return self.temp_piece(PIECE_PAR_VANNE[eid])
        return {
            ('sensor.chauffage_configuration', 'pieces'): self.pieces,
            ('sensor.chauffage_temperatures', 'temperatures'): self.temperatures,
            ('sensor.chauffage_temperatures', 'origine'): self.origine,
            ('sensor.chauffage_consignes', 'consignes'): self.consignes,
            ('sensor.chauffage_consignes', 'horaires'): getattr(self, 'horaires_utilises', None),
            ('sensor.chauffage_relais', 'relais'): self.relais,
            ('sensor.clim_pilotage', 'ordres'): self.ordres,
        }.get((eid, attr))

    def now(self):
        return datetime.datetime.fromisocalendar(2026, self.semaine, 1)


def rendre(tpl, m):
    return rendre_brut(tpl, {'states': m.states, 'is_state': m.is_state,
                             'state_attr': m.state_attr, 'now': m.now})


def evaluer(m):
    """Rejoue la chaîne de dépendances entre capteurs, dans l'ordre."""
    m.temperatures = eval(rendre(TPL_TEMPS, m))
    m.origine = eval(rendre(TPL_ORIGINE, m))
    m.consignes = eval(rendre(TPL_CONSIGNES, m))
    m.horaires_utilises = eval(rendre(TPL_HORAIRES, m))
    m.text = float(rendre(TPL_TEXT, m))
    m.relais = eval(rendre(TPL_RELAIS, m))
    m.demande = rendre(TPL_DEMANDE, m) == 'True'
    m.ordres = eval(rendre(TPL_ORDRES, m))
    return m


VERT, ROUGE, RAZ = '\033[32m', '\033[31m', '\033[0m'
echecs = []


def verifier(libelle, obtenu, attendu):
    ok = obtenu == attendu
    if not ok:
        echecs.append(libelle)
    print(f"  {VERT + 'OK   ' if ok else ROUGE + 'ÉCHEC'}{RAZ} {libelle}")
    if not ok:
        print(f"         attendu : {attendu!r}")
        print(f"         obtenu  : {obtenu!r}")


def titre(t):
    print(f"\n\033[1m{t}\033[0m")


# =============================================================================
titre("Syntaxe de tous les templates")
# Une erreur de syntaxe Jinja laisse le YAML valide : seul le rendu échoue, et
# Home Assistant se contente alors d'un capteur « unavailable », sans rien
# signaler. Ce contrôle compile chaque template des deux packages, y compris
# ceux qu'aucun scénario ci-dessous n'exerce.


def templates(noeud, chemin=""):
    if isinstance(noeud, dict):
        for cle, valeur in noeud.items():
            yield from templates(valeur, f"{chemin}.{cle}")
    elif isinstance(noeud, list):
        for i, valeur in enumerate(noeud):
            yield from templates(valeur, f"{chemin}[{i}]")
    elif isinstance(noeud, str) and ('{{' in noeud or '{%' in noeud):
        yield chemin, noeud


erreurs = 0
for nom, paquet in (('chauffage', chauffage), ('clim', clim_pkg), ('carte', carte)):
    for chemin, tpl in templates(paquet, nom):
        try:
            Environment().parse(tpl)
        except Exception as e:
            erreurs += 1
            echecs.append(chemin)
            print(f"  {ROUGE}ÉCHEC{RAZ} {chemin}\n         {e}")
verifier("tous les templates compilent", erreurs, 0)

titre("Rendu de la carte du tableau de bord")
# La carte n'est pas chargée par Home Assistant au démarrage : une erreur
# n'y apparaît qu'à l'affichage, sous forme de carte vide ou bloquée.


def contenus_markdown(noeud):
    if isinstance(noeud, dict):
        if noeud.get('type') == 'markdown':
            yield noeud['content']
        for valeur in noeud.values():
            yield from contenus_markdown(valeur)
    elif isinstance(noeud, list):
        for valeur in noeud:
            yield from contenus_markdown(valeur)


for scenario in ('maison pleine', 'maison vide'):
    presents = ['leo', 'pablo', 'laurent'] if scenario == 'maison pleine' else []
    m_carte = Monde(presents=presents, clim_etat='heat')
    ok = True
    try:
        m_carte.temperatures = eval(rendre(TPL_TEMPS, m_carte))
        m_carte.origine = eval(rendre(TPL_ORIGINE, m_carte))
        m_carte.consignes = eval(rendre(TPL_CONSIGNES, m_carte))
        m_carte.horaires_utilises = eval(rendre(TPL_HORAIRES, m_carte))
        m_carte.text = float(rendre(TPL_TEXT, m_carte))
        m_carte.relais = eval(rendre(TPL_RELAIS, m_carte))
        m_carte.ordres = eval(rendre(TPL_ORDRES, m_carte))
        for contenu in contenus_markdown(carte):
            rendre(contenu, m_carte)
    except Exception as e:
        ok = False
        print(f"         {e}")
    verifier(f"toutes les sections se rendent ({scenario})", ok, True)

import unicodedata


def slug(texte):
    texte = unicodedata.normalize('NFKD', texte).encode('ascii', 'ignore').decode()
    return ''.join(ch if ch.isalnum() else '_' for ch in texte.lower()).strip('_').replace('__', '_')


def entites_referencees(noeud):
    if isinstance(noeud, dict):
        if isinstance(noeud.get('entity'), str):
            yield noeud['entity']
        for valeur in noeud.values():
            yield from entites_referencees(valeur)
    elif isinstance(noeud, list):
        for valeur in noeud:
            yield from entites_referencees(valeur)


connues = set()
for paquet in (chauffage, clim_pkg):
    for domaine in ('input_boolean', 'input_number', 'input_select', 'schedule'):
        connues |= {f"{domaine}.{cle}" for cle in (paquet.get(domaine) or {})}
    for bloc in paquet.get('template', []):
        for domaine in ('sensor', 'binary_sensor'):
            connues |= {f"{domaine}.{slug(c['name'])}" for c in bloc.get(domaine, [])}
for c in PIECES.values():
    connues |= set(c['vannes']) | {c['sonde'], c['humidite'], c['clim']} - {None}
connues |= {'climate.thermostat_thermostat', 'schedule.chauffage_commun'}
inconnues = sorted(set(entites_referencees(carte)) - connues)
verifier("toutes les entités de la carte existent", inconnues, [])

import os
import re

images = set(re.findall(r"/local/chauffage/([\w.-]+\.svg)", open(
    RACINE + '/tableau_de_bord/dashboard.yaml', encoding='utf-8').read()))
manquantes = sorted(i for i in images
                    if not os.path.exists(f"{RACINE}/tableau_de_bord/images/{i}"))
verifier("chaque image citée existe dans tableau_de_bord/images", manquantes, [])


def cles_state_image(noeud):
    if isinstance(noeud, dict):
        if isinstance(noeud.get('state_image'), dict):
            yield from noeud['state_image'].keys()
        for valeur in noeud.values():
            yield from cles_state_image(valeur)
    elif isinstance(noeud, list):
        for valeur in noeud:
            yield from cles_state_image(valeur)


# Sans guillemets, `on:` et `off:` sont lus comme des booléens par le YAML de
# Home Assistant, et l'image ne change jamais.
verifier("toutes les clés de state_image sont des textes",
         [k for k in cles_state_image(carte) if not isinstance(k, str)], [])

titre("Clim : rôle affiché sur le tableau de bord")
m = evaluer(Monde(presents=['laurent'], semaine=41, temps={'chambre_laurent': 19.0},
                  humidites={'chambre_laurent': 72.0}))
verifier("humidité trop haute -> « Assèchement » (et non Chauffage)",
         rendre(TPL_ROLE, m), 'Assèchement')
m = evaluer(Monde(presents=[], semaine=40, temps={'chambre_laurent': 9.0}))
verifier("pièce trop froide -> « Chauffage »", rendre(TPL_ROLE, m), 'Chauffage')
m = evaluer(Monde(presents=['laurent'], semaine=41, temps={'chambre_laurent': 19.0},
                  humidites={'chambre_laurent': 50.0}))
verifier("rien à faire -> « Arrêt »", rendre(TPL_ROLE, m), 'Arrêt')
m = evaluer(Monde(presents=['laurent'], semaine=41, manuel=True))
verifier("pilotage manuel -> « Manuel »", rendre(TPL_ROLE, m), 'Manuel')
roles = {k for k in cles_state_image(carte)} - {'on', 'off'}
verifier("chaque rôle possible a son image",
         {'Chauffage', 'Assèchement', 'Froid', 'Arrêt', 'Manuel'} <= roles, True)

titre("Cohérence du bloc `pieces`")
verifier("sept pièces déclarées", len(PIECES), 7)
verifier("huit vannes au total",
         sum(len(c['vannes']) for c in PIECES.values()), 8)
verifier("une entrée externe par vanne",
         all(len(c['entrees_externes']) == len(c['vannes']) for c in PIECES.values()),
         True)
verifier("la chambre de Lolo n'a pas de vanne", PIECES['chambre_laurent']['vannes'], [])
verifier("la clim n'est que dans la chambre de Lolo",
         [p for p, c in PIECES.items() if c['clim']], ['chambre_laurent'])
verifier("salon et cuisine portent deux vannes",
         [len(PIECES['salon']['vannes']), len(PIECES['cuisine']['vannes'])], [2, 2])

titre("Origine de la température de chaque pièce")
m = evaluer(Monde(presents=['laurent']))
verifier("chambre Pablo : sonde d'ambiance", m.origine['chambre_pablo'], 'sonde')
verifier("chambre Lolo : sonde d'ambiance", m.origine['chambre_laurent'], 'sonde')
verifier("cuisine : sonde du Lyric T6", m.origine['cuisine'], 'sonde')
verifier("chambre Léo : sonde d'ambiance", m.origine['chambre_leo'], 'sonde')
verifier("salon : repli sur ses vannes", m.origine['salon'], 'vannes')
verifier("SdB enfants : repli sur sa vanne", m.origine['sdb_enfants'], 'vannes')
verifier("boulangerie : repli sur sa vanne", m.origine['boulangerie'], 'vannes')

m = evaluer(Monde(presents=['laurent'], sondes_indispo=['chambre_pablo'],
                  temps={'chambre_pablo': 16.0}))
verifier("sonde en panne : bascule sur les vannes",
         m.origine['chambre_pablo'], 'vannes')
verifier("  -> et la mesure reste exploitable",
         m.temperatures['chambre_pablo'], 16.0)

verifier("une sonde d'ambiance par chambre",
         sorted(p for p, c in PIECES.items() if c['sonde'] and 'thermostat' not in c['sonde']),
         ['chambre_laurent', 'chambre_leo', 'chambre_pablo'])

# La sonde de Léo, retrouvée, remonte encore « unavailable » tant qu'elle
# n'a pas rejoint le réseau : la chambre doit tenir sur sa vanne entre-temps.
m = evaluer(Monde(presents=['leo'], sondes_indispo=['chambre_leo'],
                  temps={'chambre_leo': 17.0}))
verifier("sonde de Léo pas encore revenue : repli sur sa vanne",
         m.origine['chambre_leo'], 'vannes')
verifier("  -> la chambre reste pilotable", m.temperatures['chambre_leo'], 17.0)

titre("Parité des semaines")
m = evaluer(Monde(presents=['laurent'], semaine=40))
verifier("semaine paire : chambre Léo à 15°", m.consignes['chambre_leo'], 15.0)
verifier("semaine paire : chambre Pablo à 15°", m.consignes['chambre_pablo'], 15.0)
verifier("semaine paire : SdB enfants à 15°", m.consignes['sdb_enfants'], 15.0)

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41))
verifier("semaine impaire : chambre Léo au confort", m.consignes['chambre_leo'], 19.5)
verifier("semaine impaire : SdB enfants au confort", m.consignes['sdb_enfants'], 21.0)

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], horaire=False, semaine=41))
verifier("hors horaire : repli de nuit", m.consignes['chambre_leo'], 17.0)

titre("Réglages par pièce")
m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  reglages={'input_number.chauffage_chambre_leo_confort': 21.0}))
verifier("confort de Léo réglé à 21° : pris en compte", m.consignes['chambre_leo'], 21.0)
verifier("  -> sans toucher à Pablo", m.consignes['chambre_pablo'], 19.5)

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41, horaire=False,
                  reglages={'input_number.chauffage_salon_nuit': 16.0}))
verifier("nuit du salon réglée à 16° : prise en compte", m.consignes['salon'], 16.0)

m = evaluer(Monde(presents=['laurent'], semaine=40,
                  reglages={'input_number.chauffage_absence': 16.5}))
verifier("absence réglée à 16,5° : appliquée aux chambres vides",
         m.consignes['chambre_leo'], 16.5)

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41))
verifier("réglage jamais posé : repli sur la valeur du bloc `pieces`",
         m.consignes['cuisine'], 19.0)

titre("Horaires modifiables")
m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41, horaire=True))
verifier("aucune planification créée : horaire par défaut",
         m.horaires_utilises['salon'], 'schedule.chauffage')

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41, horaire=True,
                  horaires={'schedule.chauffage_commun': 'off'}))
verifier("horaire commun créé : il remplace celui par défaut",
         m.horaires_utilises['salon'], 'schedule.chauffage_commun')
verifier("  -> commun hors horaire : salon en nuit", m.consignes['salon'], 17.5)

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41, horaire=True,
                  horaires={'schedule.chauffage_commun': 'off',
                            'schedule.chauffage_salon': 'on'}))
verifier("horaire propre au salon : il prime sur le commun",
         m.horaires_utilises['salon'], 'schedule.chauffage_salon')
verifier("  -> salon au confort", m.consignes['salon'], 20.5)
verifier("  -> la cuisine reste sur le commun, en nuit", m.consignes['cuisine'], 16.5)

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  horaires={'schedule.chauffage_commun': 'unavailable'}))
verifier("horaire commun indisponible : retour à l'horaire par défaut",
         m.horaires_utilises['cuisine'], 'schedule.chauffage')

titre("Pièces communes")
m = evaluer(Monde(presents=['leo'], semaine=41))
verifier("cuisine chauffée dès qu'une personne est là", m.consignes['cuisine'], 19.0)
verifier("salon de même", m.consignes['salon'], 20.5)
m = evaluer(Monde(presents=[], semaine=41))
verifier("maison vide : cuisine à 15°", m.consignes['cuisine'], 15.0)
verifier("maison vide : salon à 15°", m.consignes['salon'], 15.0)
m = evaluer(Monde(presents=['leo'], semaine=41))
verifier("boulangerie : Lolo absent, elle reste à 15°",
         m.consignes['boulangerie'], 15.0)
m = evaluer(Monde(presents=['laurent'], semaine=41))
verifier("boulangerie : Lolo présent, elle chauffe", m.consignes['boulangerie'], 19.0)

titre("Présences partielles")
m = evaluer(Monde(presents=['leo', 'laurent'], semaine=41))
verifier("Léo présent : sa chambre chauffe", m.consignes['chambre_leo'], 19.5)
verifier("Pablo absent : sa chambre à 15°", m.consignes['chambre_pablo'], 15.0)
verifier("SdB commune : chauffée par le seul Léo", m.consignes['sdb_enfants'], 21.0)

m = evaluer(Monde(presents=['pablo', 'laurent'], semaine=41))
verifier("Pablo présent : sa chambre chauffe", m.consignes['chambre_pablo'], 19.5)
verifier("Léo absent : sa chambre à 15°", m.consignes['chambre_leo'], 15.0)
verifier("SdB commune : chauffée par le seul Pablo", m.consignes['sdb_enfants'], 21.0)

m = evaluer(Monde(presents=['laurent'], semaine=41))
verifier("aucun enfant : les trois pièces à l'absence",
         [m.consignes[p] for p in ('chambre_leo', 'chambre_pablo', 'sdb_enfants')],
         [15.0, 15.0, 15.0])

titre("Bascule de semaine : les boutons tiennent jusqu'au lundi")
bascule = next(a for a in chauffage['automation'] if a['id'] == 'chauffage_bascule_garde')
verifier("pas de déclenchement au redémarrage",
         any(d.get('platform') == 'homeassistant' for d in bascule['trigger']), False)
garde = bascule['condition'][0]['value_template']


def bascule_autorisee(declencheur, jour):
    lundi = datetime.datetime.fromisocalendar(2026, 41, 1)
    return rendre_brut(garde, {'trigger': {'id': declencheur},
                               'now': lambda: lundi + datetime.timedelta(days=jour)})


verifier("00h05 un lundi : bascule", bascule_autorisee('nuit', 0), 'True')
verifier("00h05 un mercredi : bouton manuel préservé", bascule_autorisee('nuit', 2), 'False')
verifier("sélecteur de garde changé un mercredi : bascule",
         bascule_autorisee('selecteur', 2), 'True')

titre("Bouton confort")
m = evaluer(Monde(presents=['laurent'], horaire=False, semaine=40,
                  boosts=['chambre_pablo']))
verifier("forçage malgré l'absence", m.consignes['chambre_pablo'], 19.5)
verifier("les autres pièces ne bougent pas", m.consignes['chambre_leo'], 15.0)

titre("Arbitrage radiateur / clim")
froid = {p: 16.0 for p in PIECES}
m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  temps=froid, exterieur=12.0, clim_chaud=True))
verifier("chambre Lolo (sans vanne) revient à la clim",
         m.relais['chambre_laurent'], 'clim')
verifier("les pièces avec vanne restent au radiateur",
         m.relais['chambre_leo'], 'radiateur')
verifier("salon au radiateur", m.relais['salon'], 'radiateur')

m = evaluer(Monde(presents=['laurent'], semaine=41, temps=froid,
                  exterieur=-5.0, clim_chaud=True))
verifier("par -5 °C, la chambre sans vanne reste à la clim",
         m.relais['chambre_laurent'], 'clim')
verifier("  -> et la clim chauffe effectivement",
         m.ordres['chambre_laurent']['mode'], 'heat')

titre("Chaudière — le T6 n'est plus qu'un relais")
# Le scénario qui cassait l'installation : le T6 est dans la cuisine ; celle-ci
# à bonne température, une chambre glaciale. Le brûleur doit tourner.
chaud_partout = {p: 21.0 for p in PIECES}
m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  temps={**chaud_partout, 'cuisine': 22.0,
                         'chambre_leo': 16.0, 'chambre_pablo': 16.0}))
verifier("cuisine à 22° mais chambres froides -> demande maintenue",
         rendre(TPL_DEMANDE, m), 'True')
verifier("  -> consigne d'appel envoyée au T6", rendre(TPL_CHAUDIERE, m), '24.0')

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  temps={**chaud_partout, 'sdb_enfants': 22.0}))
verifier("toutes les pièces à température -> pas de demande",
         rendre(TPL_DEMANDE, m), 'False')
verifier("  -> consigne de repos, le brûleur relâche",
         rendre(TPL_CHAUDIERE, m), '10.0')

m = evaluer(Monde(presents=['laurent'], semaine=40,
                  temps={**chaud_partout, 'chambre_leo': 16.0,
                         'chambre_pablo': 16.0, 'sdb_enfants': 16.0}))
verifier("chambres vides à 16° (>15) -> pas de demande",
         rendre(TPL_DEMANDE, m), 'False')

m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={**chaud_partout, 'chambre_laurent': 12.0}))
verifier("chambre Lolo froide mais servie par la clim -> pas de chaudière",
         rendre(TPL_DEMANDE, m), 'False')

m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={**chaud_partout, 'boulangerie': 16.0}))
verifier("boulangerie froide (mesurée par sa vanne) -> demande",
         rendre(TPL_DEMANDE, m), 'True')

titre("Clim — déshumidification (comportement par défaut)")
m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={'chambre_laurent': 19.0},
                  humidites={'chambre_laurent': 72.0}))
verifier("72 % d'humidité -> mode chaud, pas dry",
         m.ordres['chambre_laurent']['mode'], 'heat')
verifier("  -> consigne = ambiante + delta", m.ordres['chambre_laurent']['temp'], 20.5)

m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={'chambre_laurent': 19.0},
                  humidites={'chambre_laurent': 55.0}))
verifier("air sec : arrêt", m.ordres['chambre_laurent']['mode'], 'off')

m = evaluer(Monde(presents=['laurent'], semaine=41, clim_deshu=False,
                  temps={'chambre_laurent': 19.0},
                  humidites={'chambre_laurent': 72.0}))
verifier("déshumidification désactivée : arrêt",
         m.ordres['chambre_laurent']['mode'], 'off')

titre("Clim — hystérésis d'humidité")
m = evaluer(Monde(presents=['laurent'], semaine=41, clim_etat='heat',
                  temps={'chambre_laurent': 19.0},
                  humidites={'chambre_laurent': 62.0}))
verifier("déjà en marche à 62 % : poursuit",
         m.ordres['chambre_laurent']['mode'], 'heat')

m = evaluer(Monde(presents=['laurent'], semaine=41, clim_etat='off',
                  temps={'chambre_laurent': 19.0},
                  humidites={'chambre_laurent': 62.0}))
verifier("à l'arrêt à 62 % : ne redémarre pas",
         m.ordres['chambre_laurent']['mode'], 'off')

titre("Clim — limite haute d'assèchement")
m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={'chambre_laurent': 21.5},
                  humidites={'chambre_laurent': 72.0}))
verifier("ambiante + delta dépasse la limite : bridé à 22°",
         m.ordres['chambre_laurent']['temp'], 22.0)

m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={'chambre_laurent': 23.0},
                  humidites={'chambre_laurent': 72.0}))
verifier("déjà au-dessus de la limite : on n'insiste pas",
         m.ordres['chambre_laurent']['mode'], 'off')

titre("Clim — température minimale, prioritaire sur tout")
m = evaluer(Monde(presents=[], semaine=40, temps={'chambre_laurent': 9.0}))
verifier("pièce vide à 9° : chauffe malgré l'absence",
         m.ordres['chambre_laurent']['mode'], 'heat')
verifier("  -> au minimum réglé, pas au confort",
         m.ordres['chambre_laurent']['temp'], 15.0)

m = evaluer(Monde(presents=[], semaine=40, temp_min=False,
                  temps={'chambre_laurent': 9.0}))
verifier("maintien désactivé : plus rien ne chauffe",
         m.ordres['chambre_laurent']['mode'], 'off')

titre("Clim — les deux garanties sont paramétrables")
m = evaluer(Monde(presents=[], semaine=40,
                  reglages={'input_number.clim_temp_min': 17},
                  temps={'chambre_laurent': 16.0}))
verifier("minimum porté à 17° : 16° déclenche la chauffe",
         m.ordres['chambre_laurent']['mode'], 'heat')
verifier("  -> jusqu'à 17°", m.ordres['chambre_laurent']['temp'], 17.0)

m = evaluer(Monde(presents=['laurent'], semaine=41,
                  reglages={'input_number.clim_seuil_humidite': 55},
                  temps={'chambre_laurent': 19.0},
                  humidites={'chambre_laurent': 60.0}))
verifier("seuil d'humidité abaissé à 55 % : 60 % déclenche l'assèchement",
         m.ordres['chambre_laurent']['mode'], 'heat')

titre("Clim — rôles désactivés par défaut")
m = evaluer(Monde(presents=['laurent'], semaine=41, exterieur=30.0,
                  temps={'chambre_laurent': 28.0}))
verifier("28° mais rafraîchissement désactivé : arrêt",
         m.ordres['chambre_laurent']['mode'], 'off')

m = evaluer(Monde(presents=['laurent'], semaine=41, exterieur=30.0,
                  clim_froid=True, temps={'chambre_laurent': 28.0}))
verifier("rafraîchissement activé : froid",
         m.ordres['chambre_laurent']['mode'], 'cool')

m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={'chambre_laurent': 17.0}))
verifier("17° mais appoint désactivé : pas de chauffe",
         m.ordres['chambre_laurent']['mode'], 'off')

m = evaluer(Monde(presents=['laurent'], semaine=41, clim_chaud=True,
                  temps={'chambre_laurent': 17.0}))
verifier("appoint activé : chauffe à la consigne du moment",
         m.ordres['chambre_laurent']['temp'], 19.5)

titre("Cohérence d'ensemble")
m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  temps=froid, clim_chaud=True))
double = [p for p in PIECES
          if m.relais.get(p) == 'clim'
          and m.consignes.get(p, 0) > PIECES[p]['absence']
          and PIECES[p]['vannes']]
verifier("aucune pièce chauffée par les deux sources à la fois", double, [])
verifier("état du capteur = consigne maximale", rendre(TPL_ETAT, m), '21.0')

# =============================================================================
print()
if echecs:
    print(f"{ROUGE}{len(echecs)} test(s) en échec{RAZ} : " + ", ".join(echecs))
    raise SystemExit(1)
print(f"{VERT}Tous les tests passent.{RAZ}")
