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
import json
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
TPL_BASES = capteur(chauffage, 'Chauffage consignes')['attributes']['consignes_base']
TPL_DEROGEES = capteur(chauffage, 'Chauffage consignes')['attributes']['derogations']
TPL_ETAT = capteur(chauffage, 'Chauffage consignes')['state']
TPL_TEXT = capteur(chauffage, 'Chauffage température extérieure')['state']
TPL_RELAIS = capteur(chauffage, 'Chauffage relais')['attributes']['relais']
TPL_DEMANDE = capteur(chauffage, 'Chauffage demande chaudière')['state']
TPL_CHAUDIERE = capteur(chauffage, 'Chauffage consigne chaudière')['state']
TPL_ORDRES = capteur(clim_pkg, 'Clim pilotage')['attributes']['ordres']
TPL_ROLE = capteur(clim_pkg, 'Clim rôle')['state']
TPL_GRILLES = capteur(chauffage, 'Chauffage horaires')['attributes']['grilles']


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
    # Équivalents des fonctions de date propres à Home Assistant.
    env.filters['timestamp_custom'] = (
        lambda ts, fmt: datetime.datetime.fromtimestamp(ts).strftime(fmt))
    env.globals['as_timestamp'] = lambda dt: dt.timestamp()
    env.filters['from_json'] = json.loads
    env.filters['to_json'] = json.dumps
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
        'input_select.clim_duree_assechement': '1 h',
        'input_number.clim_consigne_horaire': 19,
        'input_number.chauffage_nuit': 15,
        'input_number.clim_temp_min': 15,
        'input_number.chaudiere_consigne_marche': 24,
        'input_number.chaudiere_consigne_arret': 10,
    }

    def __init__(self, presents=(), horaire=True, boosts=(), temps=None,
                 humidites=None, semaine=41, exterieur=12.0,
                 clim_froid=False, clim_chaud=False, assechement=False,
                 temp_min=True, clim_etat='off', clim_consigne=24.0, dernier='',
                 sondes_indispo=(), reglages=None, horaires=None, depuis=None,
                 grilles=None, plages=None, derogations='', coupees=()):
        # Valeurs par défaut conformes à l'installation : maintien d'une
        # température minimale, assèchement seulement sur demande, froid et
        # appoint chauffage désactivés.
        self.presents = set(presents)
        self.horaire = horaire
        self.boosts = set(boosts)
        self.temps = temps or {}          # clé = nom de pièce
        self.humidites = humidites or {}  # clé = nom de pièce
        self.semaine = semaine
        self.exterieur = exterieur
        self.clim = {'froid': clim_froid, 'chaud': clim_chaud}
        self.assechement = assechement
        # {entité: minutes écoulées depuis son dernier changement d'état}
        self.depuis = depuis or {}
        # Contenu des planifications, tel que le range sensor.chauffage_horaires.
        self.grilles = grilles
        # Température portée par la plage en cours : {planification: °C}.
        self.plages = plages or {}
        # Contenu brut de input_text.chauffage_derogations.
        self.derogations = derogations
        # Pièces dont le bouton « Chauffer la pièce » est décoché.
        self.coupees = set(coupees)
        self.temp_min, self.clim_etat, self.clim_consigne = temp_min, clim_etat, clim_consigne
        # Mémoire du dernier ordre de HA (input_text.clim_dernier_ordre).
        self.dernier = dernier
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
        if eid == 'input_text.clim_dernier_ordre':
            return self.dernier
        if eid == 'input_text.chauffage_derogations':
            return self.derogations
        if eid == 'input_boolean.clim_assechement':
            return 'on' if self.assechement else 'off'
        if eid.startswith('input_boolean.clim_auto_'):
            return 'on' if self.clim[eid.rsplit('_', 1)[1]] else 'off'
        if eid.startswith('input_boolean.presence_'):
            return 'on' if eid.split('presence_')[1] in self.presents else 'off'
        if eid.startswith('input_boolean.chauffage_') and eid.endswith('_actif'):
            piece = eid[len('input_boolean.chauffage_'):-len('_actif')]
            return 'off' if piece in self.coupees else 'on'
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
        if eid in PIECE_PAR_CLIM and attr == 'temperature':
            return self.clim_consigne
        if eid.startswith('schedule.') and attr == 'temperature':
            return self.plages.get(eid)
        return {
            ('sensor.chauffage_configuration', 'pieces'): self.pieces,
            ('sensor.chauffage_temperatures', 'temperatures'): self.temperatures,
            ('sensor.chauffage_temperatures', 'origine'): self.origine,
            ('sensor.chauffage_consignes', 'consignes'): self.consignes,
            ('sensor.chauffage_consignes', 'horaires'): getattr(self, 'horaires_utilises', None),
            ('sensor.chauffage_consignes', 'consignes_base'): getattr(self, 'bases', None),
            ('sensor.chauffage_consignes', 'derogations'): getattr(self, 'derogees', None),
            ('sensor.chauffage_relais', 'relais'): self.relais,
            ('sensor.clim_pilotage', 'ordres'): self.ordres,
            ('sensor.chauffage_horaires', 'grilles'): self.grilles,
        }.get((eid, attr))

    def now(self):
        return datetime.datetime.fromisocalendar(2026, self.semaine, 1)

    def objet_etat(self, eid):
        """Équivalent de states['domaine.objet'] : état et date du changement."""
        class Etat:
            pass
        e = Etat()
        e.state = self.states(eid)
        e.last_changed = self.now() - datetime.timedelta(minutes=self.depuis.get(eid, 0))
        return e


class Etats:
    """Imite `states` de Home Assistant : appelable (states('x.y')), indexable
    (states['x.y']) et parcourable par attributs (states.x.y)."""

    def __init__(self, monde):
        self._m = monde

    def __call__(self, eid):
        return self._m.states(eid)

    def __getitem__(self, eid):
        return self._m.objet_etat(eid)

    def __getattr__(self, domaine):
        monde = self._m

        class Domaine:
            def __getattr__(self, objet):
                return monde.objet_etat(f"{domaine}.{objet}")
        return Domaine()


def rendre(tpl, m):
    return rendre_brut(tpl, {'states': Etats(m), 'is_state': m.is_state,
                             'state_attr': m.state_attr, 'now': m.now})


def evaluer(m):
    """Rejoue la chaîne de dépendances entre capteurs, dans l'ordre."""
    m.temperatures = eval(rendre(TPL_TEMPS, m))
    m.origine = eval(rendre(TPL_ORIGINE, m))
    m.consignes = eval(rendre(TPL_CONSIGNES, m))
    m.horaires_utilises = eval(rendre(TPL_HORAIRES, m))
    m.bases = eval(rendre(TPL_BASES, m))
    m.derogees = eval(rendre(TPL_DEROGEES, m))
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
    m_carte = Monde(presents=presents, clim_etat='heat', derogations='{"salon": [22.0, 20.5]}',
                    horaires={
        'schedule.chauffage_commun': 'on', 'schedule.chauffage_salon': 'off'}, grilles={
        'schedule.chauffage_commun': {'monday': [{'de': '06:00', 'a': '08:30', 't': 22}]},
        'schedule.chauffage_salon': {'monday': [{'de': '18:00', 'a': '24:00'}]},
        'schedule.chauffage': {'monday': [{'de': '06:00', 'a': '22:00'}]}})
    ok = True
    try:
        m_carte.temperatures = eval(rendre(TPL_TEMPS, m_carte))
        m_carte.origine = eval(rendre(TPL_ORIGINE, m_carte))
        m_carte.consignes = eval(rendre(TPL_CONSIGNES, m_carte))
        m_carte.horaires_utilises = eval(rendre(TPL_HORAIRES, m_carte))
        m_carte.bases = eval(rendre(TPL_BASES, m_carte))
        m_carte.derogees = eval(rendre(TPL_DEROGEES, m_carte))
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
    for domaine in ('input_boolean', 'input_number', 'input_select', 'input_text', 'schedule',
                    'script'):
        connues |= {f"{domaine}.{cle}" for cle in (paquet.get(domaine) or {})}
    for bloc in paquet.get('template', []):
        for domaine in ('sensor', 'binary_sensor'):
            connues |= {f"{domaine}.{slug(c['name'])}" for c in bloc.get(domaine, [])}
for c in PIECES.values():
    connues |= set(c['vannes']) | {c['sonde'], c['humidite'], c['clim']} - {None}
# Planifications créées dans l'interface par Laurent.
connues |= {'climate.thermostat_thermostat', 'schedule.chauffage_commun',
            'schedule.clim_chambre'} | {f"schedule.chauffage_{p}" for p in PIECES}
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
m = evaluer(Monde(presents=['laurent'], semaine=41, assechement=True,
                  temps={'chambre_laurent': 19.0}))
verifier("assèchement demandé -> « Assèchement » (et non Chauffage)",
         rendre(TPL_ROLE, m), 'Assèchement')
m = evaluer(Monde(presents=[], semaine=40, temps={'chambre_laurent': 9.0}))
verifier("pièce trop froide -> « Chauffage »", rendre(TPL_ROLE, m), 'Chauffage')
m = evaluer(Monde(presents=['laurent'], semaine=41, temps={'chambre_laurent': 19.0},
                  humidites={'chambre_laurent': 50.0}))
verifier("rien à faire -> « Arrêt »", rendre(TPL_ROLE, m), 'Arrêt')
m = evaluer(Monde(presents=['laurent'], semaine=41, clim_etat='heat',
                  temps={'chambre_laurent': 19.0}))
verifier("clim en marche sans raison pour HA -> « Manuel »", rendre(TPL_ROLE, m), 'Manuel')
m = evaluer(Monde(presents=['laurent'], semaine=41, temps={'chambre_laurent': 19.0},
                  horaires={'schedule.clim_chambre': 'on'}))
verifier("horaire de la clim actif -> « Chauffage »", rendre(TPL_ROLE, m), 'Chauffage')
roles = {k for k in cles_state_image(carte)} - {'on', 'off'}
verifier("chaque rôle possible a son image",
         {'Chauffage', 'Assèchement', 'Froid', 'Arrêt', 'Manuel'} <= roles, True)

titre("Automatisations : listes cohérentes, rien de perdu au redémarrage")
toutes = chauffage['automation'] + clim_pkg['automation']


def delais(noeud):
    if isinstance(noeud, dict):
        if 'delay' in noeud:
            yield noeud['delay']
        for valeur in noeud.values():
            yield from delais(valeur)
    elif isinstance(noeud, list):
        for valeur in noeud:
            yield from delais(valeur)


# Un `delay` est annulé par un redémarrage : seuls de courts délais de
# synchronisation sont admis, jamais une minuterie de plusieurs minutes.
longs = [(a['id'], d) for a in toutes for d in delais(a.get('action', []))
         if d != "00:00:05"]
verifier("aucune minuterie longue perdue au redémarrage", longs, [])

conforts = sorted(f"input_boolean.{c}" for c in chauffage['input_boolean']
                  if c.startswith('confort_'))
application = next(a for a in chauffage['automation'] if a['id'] == 'chauffage_application_consignes')
ids = [e for d in application['trigger'] for e in (d.get('entity_id') or [])
       if isinstance(d.get('entity_id'), list)]
verifier("aucun déclencheur en double", sorted(e for e in set(ids) if ids.count(e) > 1), [])
verifier("chaque bouton confort déclenche l'application",
         [c for c in conforts if c not in ids], [])
extinction = next(a for a in chauffage['automation'] if a['id'] == 'chauffage_extinction_confort')
verifier("chaque bouton confort s'éteint seul",
         [c for c in conforts if c not in extinction['variables']['a_eteindre']], [])


def a_eteindre(allumes_depuis):
    """allumes_depuis : {bouton: minutes écoulées depuis l'allumage}"""
    maintenant = datetime.datetime(2026, 10, 7, 12, 0)

    class Etat:
        def __init__(self, minutes):
            self.last_changed = maintenant - datetime.timedelta(minutes=minutes)

    etats = {f"input_boolean.confort_{b}": Etat(m) for b, m in allumes_depuis.items()}
    return rendre_brut(extinction['variables']['a_eteindre'], {
        'states': type('S', (), {
            '__getitem__': lambda s, e: etats[e],
            '__call__': lambda s, e: '120' if e == 'input_number.duree_confort' else 'off'})(),
        'is_state': lambda e, v: v == 'on' and e in etats,
        'now': lambda: maintenant})


verifier("confort allumé depuis 3 h : éteint",
         a_eteindre({'salon': 180}), "['input_boolean.confort_salon']")
verifier("confort allumé depuis 1 h : conservé", a_eteindre({'salon': 60}), "[]")

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

titre("Lecture du contenu des horaires")
# schedule.get_schedule renvoie des heures (objets time) ; une plage finissant
# à minuit vaut time.max. On accepte aussi des textes, par prudence.
reponse = {
    'schedule.chauffage_commun': {
        'monday': [{'from': datetime.time(6, 0), 'to': datetime.time(8, 30)},
                   {'from': datetime.time(16, 30), 'to': datetime.time(22, 0)}],
        'saturday': [{'from': datetime.time(8, 0), 'to': datetime.time.max}],
        'sunday': [{'from': '08:00:00', 'to': '22:00:00'}],
        'friday': [{'from': datetime.time(6, 0), 'to': datetime.time(8, 0),
                    'data': {'temperature': 24}}],
    },
}
grilles = eval(rendre_brut(TPL_GRILLES, {'reponse': reponse}))
commun = grilles['schedule.chauffage_commun']
verifier("plages converties en texte HH:MM",
         commun['monday'], [{'de': '06:00', 'a': '08:30', 't': None},
                            {'de': '16:30', 'a': '22:00', 't': None}])
verifier("fin à minuit affichée 24:00", commun['saturday'], [{'de': '08:00', 'a': '24:00', 't': None}])
verifier("heures déjà en texte : acceptées", commun['sunday'], [{'de': '08:00', 'a': '22:00', 't': None}])
verifier("température de la plage reprise", commun['friday'], [{'de': '06:00', 'a': '08:00', 't': 24}])
verifier("jour sans plage : liste vide", commun['tuesday'], [])
verifier("aucune réponse : aucun horaire", eval(rendre_brut(TPL_GRILLES, {'reponse': None})), {})

titre("Parité des semaines")
m = evaluer(Monde(presents=['laurent'], semaine=40))
verifier("semaine paire : chambre Léo à 15°", m.consignes['chambre_leo'], 15.0)
verifier("semaine paire : chambre Pablo à 15°", m.consignes['chambre_pablo'], 15.0)
verifier("semaine paire : SdB enfants à 15°", m.consignes['sdb_enfants'], 15.0)

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41))
verifier("semaine impaire : chambre Léo au confort", m.consignes['chambre_leo'], 19.5)
verifier("semaine impaire : SdB enfants au confort", m.consignes['sdb_enfants'], 21.0)

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], horaire=False, semaine=41))
verifier("hors horaire : nuit (15°, commune)", m.consignes['chambre_leo'], 15.0)

titre("Réglages par pièce")
m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  reglages={'input_number.chauffage_chambre_leo_confort': 21.0}))
verifier("confort de Léo réglé à 21° : pris en compte", m.consignes['chambre_leo'], 21.0)
verifier("  -> sans toucher à Pablo", m.consignes['chambre_pablo'], 19.5)

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41, horaire=False,
                  reglages={'input_number.chauffage_nuit': 16.0}))
verifier("nuit réglée à 16° : vaut pour toutes les pièces",
         {m.consignes[p] for p in ('salon', 'cuisine', 'chambre_leo', 'sdb_enfants')}, {16.0})

m = evaluer(Monde(presents=['laurent'], semaine=40,
                  reglages={'input_number.chauffage_nuit': 16.5}))
verifier("nuit réglée à 16,5° : appliquée aussi aux chambres vides",
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
verifier("  -> commun hors horaire : salon en nuit", m.consignes['salon'], 15.0)

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41, horaire=True,
                  horaires={'schedule.chauffage_commun': 'off',
                            'schedule.chauffage_salon': 'on'}))
verifier("horaire propre au salon : il prime sur le commun",
         m.horaires_utilises['salon'], 'schedule.chauffage_salon')
verifier("  -> salon au confort", m.consignes['salon'], 20.5)
verifier("  -> la cuisine reste sur le commun, en nuit", m.consignes['cuisine'], 15.0)

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  horaires={'schedule.chauffage_commun': 'unavailable'}))
verifier("horaire commun indisponible : retour à l'horaire par défaut",
         m.horaires_utilises['cuisine'], 'schedule.chauffage')

titre("Une température par plage")
tous = ['leo', 'pablo', 'laurent']
m = evaluer(Monde(presents=tous, horaires={'schedule.chauffage_sdb_enfants': 'on'},
                  plages={'schedule.chauffage_sdb_enfants': 24}))
verifier("SdB, plage 6-8 h à 24° : consigne 24°", m.consignes['sdb_enfants'], 24.0)
m = evaluer(Monde(presents=tous, horaires={'schedule.chauffage_sdb_enfants': 'on'},
                  plages={'schedule.chauffage_sdb_enfants': 15}))
verifier("SdB, plage 8-19 h à 15° : consigne 15°, même sous le confort",
         m.consignes['sdb_enfants'], 15.0)
m = evaluer(Monde(presents=tous, horaires={'schedule.chauffage_sdb_enfants': 'on'},
                  plages={'schedule.chauffage_sdb_enfants': 15}, boosts=['sdb_enfants']))
verifier("  -> confort immédiat pendant cette plage : confort (21°)",
         m.consignes['sdb_enfants'], 21.0)
m = evaluer(Monde(presents=tous, horaires={'schedule.chauffage_sdb_enfants': 'on'}))
verifier("plage sans température : curseur confort", m.consignes['sdb_enfants'], 21.0)
m = evaluer(Monde(presents=tous, horaires={'schedule.chauffage_sdb_enfants': 'off'}))
verifier("hors de toute plage : nuit", m.consignes['sdb_enfants'], 15.0)
m = evaluer(Monde(presents=['laurent'], horaires={'schedule.chauffage_sdb_enfants': 'on'},
                  plages={'schedule.chauffage_sdb_enfants': 24}))
verifier("plage à 24° mais enfants absents : absence (15°)", m.consignes['sdb_enfants'], 15.0)
m = evaluer(Monde(presents=tous, horaires={'schedule.chauffage_commun': 'on'},
                  plages={'schedule.chauffage_commun': 20}))
verifier("plage à 20° dans l'horaire commun : vaut pour les pièces qui le suivent",
         [m.consignes['cuisine'], m.consignes['chambre_leo']], [20.0, 20.0])
m = evaluer(Monde(presents=['laurent'], temps={'chambre_laurent': 18.0},
                  horaires={'schedule.clim_chambre': 'on'}, plages={'schedule.clim_chambre': 21}))
verifier("clim : plage à 21° de son horaire", m.ordres['chambre_laurent']['temp'], 21.0)

titre("Bouton « Chauffer la pièce »")
m = evaluer(Monde(presents=tous, coupees=['salon'], horaires={'schedule.chauffage_commun': 'on'}))
verifier("salon décoché, pendant l'horaire, tout le monde là : nuit (15°)",
         m.consignes['salon'], 15.0)
verifier("  -> les autres pièces suivent l'horaire", m.consignes['cuisine'], 19.0)
m = evaluer(Monde(presents=tous, coupees=['sdb_enfants'],
                  horaires={'schedule.chauffage_sdb_enfants': 'on'},
                  plages={'schedule.chauffage_sdb_enfants': 24}))
verifier("SdB décochée, plage à 24° : reste à la nuit", m.consignes['sdb_enfants'], 15.0)
m = evaluer(Monde(presents=tous, coupees=['salon'], boosts=['salon']))
verifier("salon décoché mais confort immédiat demandé : confort", m.consignes['salon'], 20.5)
m = evaluer(Monde(presents=tous, coupees=['salon'], derogations='{"salon": [21.0, 15.0]}'))
verifier("salon décoché mais vanne montée à 21° : la vanne l'emporte", m.consignes['salon'], 21.0)
m = evaluer(Monde(presents=tous, coupees=['salon'],
                  temps={**{p: 25.0 for p in PIECES}, 'salon': 17.0}))
verifier("salon décoché à 17° : ne réclame pas la chaudière", rendre(TPL_DEMANDE, m), 'False')
verifier("chaque pièce à vannes a son bouton",
         sorted(c[len('chauffage_'):-len('_actif')] for c in chauffage['input_boolean']
                if c.startswith('chauffage_') and c.endswith('_actif')),
         sorted(p for p, c in PIECES.items() if c['vannes']))

titre("Réglage fait sur une vanne")
m = evaluer(Monde(presents=tous, derogations='{"salon": [22.0, 20.5]}'))
verifier("salon réglé à 22° sur la vanne (base 20,5°) : consigne 22°", m.consignes['salon'], 22.0)
verifier("  -> signalé comme dérogation", m.derogees, ['salon'])
verifier("  -> la base reste connue", m.bases['salon'], 20.5)
verifier("  -> les autres pièces ne bougent pas", m.consignes['cuisine'], 19.0)
m = evaluer(Monde(presents=tous, horaire=False, derogations='{"salon": [22.0, 20.5]}'))
verifier("changement de plage (base passe à la nuit) : la dérogation tombe",
         (m.consignes['salon'], m.derogees), (15.0, []))
m = evaluer(Monde(presents=tous, derogations='', temps={p: 20.0 for p in PIECES}))
verifier("aucune dérogation : texte vide accepté", m.derogees, [])

m = evaluer(Monde(presents=tous, derogations='{"chambre_leo": [22.0, 19.5]}',
                  temps={**{p: 25.0 for p in PIECES}, 'chambre_leo': 20.0}))
verifier("chambre réglée à 22° sur la vanne, à 20° : la chaudière suit",
         rendre(TPL_DEMANDE, m), 'True')

detection = next(a for a in chauffage['automation'] if a['id'] == 'chauffage_derogation_vanne')
garde_detection = detection['action'][1]['value_template']
tpl_nouvelle = detection['action'][2]['data']['value']
tpl_piece = detection['action'][0]['variables']['piece']


def reglage_vanne(vanne, demandee, derogations=''):
    """Rejoue la détection : pièce trouvée, déclenchement, nouveau contenu."""
    m = evaluer(Monde(presents=tous, derogations=derogations))
    trig = {'entity_id': vanne}
    piece = rendre_brut(tpl_piece, {'state_attr': m.state_attr, 'trigger': trig})
    variables = {'piece': piece, 'demandee': demandee,
                 'voulue': m.consignes[piece], 'base': m.bases[piece],
                 'states': Etats(m), 'trigger': trig}
    return (piece, rendre_brut(garde_detection, variables),
            json.loads(rendre_brut(tpl_nouvelle, variables)))


verifier("vanne canapé montée à 22° : pièce salon, dérogation enregistrée",
         reglage_vanne('climate.vt_salon_canape_thermostat', 22.0),
         ('salon', 'True', {'salon': [22.0, 20.5]}))
verifier("valeur renvoyée par la vanne égale à la consigne (ordre de HA) : ignorée",
         reglage_vanne('climate.vt_salon_canape_thermostat', 20.5)[1], 'False')
verifier("arrondi au demi-degré de la vanne (0,2°) : ignoré",
         reglage_vanne('climate.vt_salon_canape_thermostat', 20.7)[1], 'False')
verifier("vanne remise à la base pendant une dérogation : dérogation retirée",
         reglage_vanne('climate.vt_salon_canape_thermostat', 20.5,
                       '{"salon": [22.0, 20.5]}')[1:],
         ('True', {}))
verifier("deuxième pièce réglée : les deux dérogations coexistent",
         reglage_vanne('climate.vanne_thermo_leo_thermostat', 21.0,
                       '{"salon": [22.0, 20.5]}')[2],
         {'salon': [22.0, 20.5], 'chambre_leo': [21.0, 19.5]})

menage = next(a for a in chauffage['automation'] if a['id'] == 'chauffage_derogation_fin')
m = evaluer(Monde(presents=tous, horaire=False,
                  derogations='{"salon": [22.0, 20.5], "chambre_leo": [18.0, 15.0]}'))
restantes = json.loads(rendre(menage['variables']['restantes'], m))
verifier("ménage : dérogation périmée retirée, celle encore valable gardée",
         restantes, {'chambre_leo': [18.0, 15.0]})

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

titre("Clim — assèchement uniquement à la demande")
m = evaluer(Monde(presents=['laurent'], semaine=41, temps={'chambre_laurent': 19.0},
                  humidites={'chambre_laurent': 85.0}))
verifier("85 % d'humidité sans appui sur le bouton : arrêt",
         m.ordres['chambre_laurent']['mode'], 'off')

m = evaluer(Monde(presents=['laurent'], semaine=41, assechement=True,
                  temps={'chambre_laurent': 19.0}))
verifier("bouton appuyé : mode chaud", m.ordres['chambre_laurent']['mode'], 'heat')
verifier("  -> à 24 °C", m.ordres['chambre_laurent']['temp'], 24)

m = evaluer(Monde(presents=['laurent'], semaine=41, assechement=True,
                  temps={'chambre_laurent': 23.0}))
verifier("pièce déjà à 23° : l'assèchement demandé a quand même lieu",
         m.ordres['chambre_laurent']['temp'], 24)

m = evaluer(Monde(presents=[], semaine=40, assechement=True,
                  temps={'chambre_laurent': 9.0}))
verifier("pièce à 9° : l'assèchement (24°) couvre aussi le minimum",
         m.ordres['chambre_laurent']['temp'], 24)

pilotage = next(a for a in clim_pkg['automation'] if a['id'] == 'clim_pilotage_automatique')
verifier("un appui pendant une exécution n'est pas ignoré (mode restart)",
         pilotage['mode'], 'restart')
TPL_DECISION = pilotage['action'][1]['repeat']['sequence'][0]['variables']['decision']


def decision(motif, etat, consigne, dernier='', declencheur='horloge',
             clim_depuis=30, ordre_depuis=30, temp=None):
    """Ce que fait l'automatisation pour un ordre voulu et un état de la clim."""
    voulu = {'arret': ('off', 0), 'assechement': ('heat', 24.0), 'horaire': ('heat', 19.0),
             'temp_min': ('heat', 15.0)}[motif]
    m = Monde(clim_etat=etat, clim_consigne=consigne, dernier=dernier,
              depuis={'climate.clim_chambre': clim_depuis,
                      'input_text.clim_dernier_ordre': ordre_depuis})
    return rendre_brut(TPL_DECISION, {
        'states': Etats(m), 'state_attr': m.state_attr, 'now': m.now,
        'clim': 'climate.clim_chambre', 'trigger': {'id': declencheur},
        'ordre': {'mode': voulu[0], 'temp': temp or voulu[1], 'motif': motif}})


titre("Clim — Laurent la pilote librement")
verifier("allumée par Laurent, HA sans raison d'agir : on n'y touche pas",
         decision('arret', 'heat', 21.0), 'rien')
verifier("éteinte, HA sans raison d'agir : rien", decision('arret', 'off', 24.0), 'rien')
verifier("allumée par HA, sa raison disparaît : il l'éteint",
         decision('arret', 'heat', 24.0, 'heat|24.0|assechement'), 'arreter')
verifier("allumée par HA puis modifiée par Laurent : HA l'oublie sans l'éteindre",
         decision('arret', 'heat', 21.0, 'heat|24.0|assechement'), 'liberer')
verifier("arrêt demandé juste après le lancement, clim pas encore à jour : éteinte quand même",
         decision('arret', 'off', 24.0, 'heat|24.0|assechement', 'commande', ordre_depuis=0.5),
         'arreter')
verifier("vérification périodique juste après un changement : attend",
         decision('arret', 'heat', 24.0, 'heat|24.0|horaire', 'horloge', clim_depuis=1), 'rien')
verifier("commande de Laurent juste après un changement : immédiate",
         decision('arret', 'heat', 24.0, 'heat|24.0|assechement', 'commande', clim_depuis=1),
         'arreter')

titre("Clim — HA intervient quand il a une raison")
verifier("assèchement demandé, clim éteinte : HA commande",
         decision('assechement', 'off', 22.0), 'commander')
verifier("début de l'horaire, clim éteinte : HA commande",
         decision('horaire', 'off', 22.0), 'commander')
verifier("horaire, clim déjà conforme : HA prend simplement la main",
         decision('horaire', 'heat', 19.0), 'commander')

titre("Clim — reprise en main pendant une période")
verifier("pendant l'horaire, Laurent passe à 21 : HA lui laisse la main",
         decision('horaire', 'heat', 21.0, 'heat|19.0|horaire'), 'ceder')
verifier("  -> et ne revient pas dessus jusqu'à la fin de la plage",
         decision('horaire', 'heat', 21.0, 'manuel|0|horaire'), 'rien')
verifier("  -> fin de la plage : HA oublie, sans éteindre ce que Laurent a réglé",
         decision('arret', 'heat', 21.0, 'manuel|0|horaire'), 'liberer')
verifier("reprise pendant l'horaire, puis assèchement demandé : l'assèchement l'emporte",
         decision('assechement', 'heat', 21.0, 'manuel|0|horaire'), 'commander')
verifier("minimum : Laurent chauffe déjà au-dessus, HA ne s'en mêle pas",
         decision('temp_min', 'heat', 20.0), 'rien')
verifier("minimum : Laurent coupe la clim sous 15 °C, HA la relance (gel)",
         decision('temp_min', 'off', 20.0, 'heat|15.0|temp_min'), 'commander')

titre("Clim — horaire et minimum dans la décision")
m = evaluer(Monde(presents=['laurent'], semaine=41, temps={'chambre_laurent': 18.0},
                  horaires={'schedule.clim_chambre': 'on'}))
verifier("horaire actif, Lolo là : chauffe à la consigne horaire",
         (m.ordres['chambre_laurent']['motif'], m.ordres['chambre_laurent']['temp']),
         ('horaire', 19.0))
m = evaluer(Monde(presents=[], semaine=41, temps={'chambre_laurent': 18.0},
                  horaires={'schedule.clim_chambre': 'on'}))
verifier("horaire actif, Lolo absent : pas de chauffe",
         m.ordres['chambre_laurent']['motif'], 'arret')
m = evaluer(Monde(presents=['laurent'], semaine=41, assechement=True,
                  temps={'chambre_laurent': 18.0}, horaires={'schedule.clim_chambre': 'on'}))
verifier("assèchement pendant l'horaire : l'assèchement l'emporte",
         m.ordres['chambre_laurent']['motif'], 'assechement')
m = evaluer(Monde(presents=[], semaine=40, temps={'chambre_laurent': 15.5},
                  dernier='heat|15.0|temp_min'))
verifier("minimum lancé par HA, pièce à 15,5° : continue (hystérésis)",
         m.ordres['chambre_laurent']['motif'], 'temp_min')
m = evaluer(Monde(presents=[], semaine=40, temps={'chambre_laurent': 15.5}))
verifier("pièce à 15,5° sans chauffe en cours : rien", m.ordres['chambre_laurent']['motif'], 'arret')
m = evaluer(Monde(presents=[], semaine=40, temps={'chambre_laurent': 16.2},
                  dernier='heat|15.0|temp_min'))
verifier("minimum lancé par HA, pièce à 16,2° : s'arrête", m.ordres['chambre_laurent']['motif'], 'arret')

fin_assechement = next(a for a in clim_pkg['automation'] if a['id'] == 'clim_assechement_fin')
garde_fin = fin_assechement['condition'][1]['value_template']


def fin_atteinte(duree, minutes):
    m = Monde(reglages={'input_select.clim_duree_assechement': duree},
              depuis={'input_boolean.clim_assechement': minutes})
    return rendre(garde_fin, m)


verifier("durée 1 h, lancé il y a 59 min : continue", fin_atteinte('1 h', 59), 'False')
verifier("durée 1 h, lancé il y a 60 min : s'arrête", fin_atteinte('1 h', 60), 'True')
verifier("durée 2 h, lancé il y a 90 min : continue", fin_atteinte('2 h', 90), 'False')
verifier("durée 2 h, lancé il y a 120 min : s'arrête", fin_atteinte('2 h', 120), 'True')

titre("Clim — température minimale")
m = evaluer(Monde(presents=[], semaine=40, temps={'chambre_laurent': 9.0}))
verifier("pièce vide à 9° : chauffe malgré l'absence",
         m.ordres['chambre_laurent']['mode'], 'heat')
verifier("  -> au minimum réglé, pas au confort",
         m.ordres['chambre_laurent']['temp'], 15.0)

m = evaluer(Monde(presents=[], semaine=40, temp_min=False,
                  temps={'chambre_laurent': 9.0}))
verifier("maintien désactivé : plus rien ne chauffe",
         m.ordres['chambre_laurent']['mode'], 'off')

titre("Clim — température minimale paramétrable")
m = evaluer(Monde(presents=[], semaine=40,
                  reglages={'input_number.clim_temp_min': 17},
                  temps={'chambre_laurent': 16.0}))
verifier("minimum porté à 17° : 16° déclenche la chauffe",
         m.ordres['chambre_laurent']['mode'], 'heat')
verifier("  -> jusqu'à 17°", m.ordres['chambre_laurent']['temp'], 17.0)

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
          and m.consignes.get(p, 0) > 15.0
          and PIECES[p]['vannes']]
verifier("aucune pièce chauffée par les deux sources à la fois", double, [])
verifier("état du capteur = consigne maximale", rendre(TPL_ETAT, m), '21.0')

# =============================================================================
print()
if echecs:
    print(f"{ROUGE}{len(echecs)} test(s) en échec{RAZ} : " + ", ".join(echecs))
    raise SystemExit(1)
print(f"{VERT}Tous les tests passent.{RAZ}")
