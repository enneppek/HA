"""Banc d'essai de la logique de chauffage et de climatisation.

Simule le moteur de templates de Home Assistant pour vérifier les décisions
hors instance réelle. À relancer après toute modification du bloc `pieces`
ou des règles de priorité :

    python3 outils/test_logique.py
"""
import datetime
import yaml
from jinja2 import Environment

RACINE = __file__.rsplit('/outils/', 1)[0]
chauffage = yaml.safe_load(open(RACINE + '/packages/chauffage.yaml', encoding='utf-8'))
clim_pkg = yaml.safe_load(open(RACINE + '/packages/clim.yaml', encoding='utf-8'))


def capteur(paquet, nom):
    """Retrouve un capteur template par son nom, quel que soit son bloc."""
    for bloc in paquet['template']:
        for cle in ('sensor', 'binary_sensor'):
            for c in bloc.get(cle, []):
                if c['name'] == nom:
                    return c
    raise KeyError(nom)


TPL_CFG = capteur(chauffage, 'Chauffage configuration')['attributes']['pieces']
TPL_CONSIGNES = capteur(chauffage, 'Chauffage consignes')['attributes']['consignes']
TPL_ETAT = capteur(chauffage, 'Chauffage consignes')['state']
TPL_TEXT = capteur(chauffage, 'Chauffage température extérieure')['state']
TPL_RELAIS = capteur(chauffage, 'Chauffage relais')['attributes']['relais']
TPL_DEMANDE = capteur(chauffage, 'Chauffage demande chaudière')['state']
TPL_ORDRES = capteur(clim_pkg, 'Clim pilotage')['attributes']['ordres']


class Monde:
    """État simulé de l'instance Home Assistant."""

    REGLAGES = {
        'input_number.clim_seuil_pac': 5,
        'input_number.clim_seuil_froid': 26,
        'input_number.clim_consigne_ete': 25,
        'input_number.clim_seuil_humidite': 65,
    }

    def __init__(self, presents=(), horaire=True, boosts=(), temps=None,
                 humidites=None, semaine=41, exterieur=12.0,
                 clim_froid=True, clim_chaud=True, clim_deshu=True):
        self.presents = set(presents)
        self.horaire = horaire
        self.boosts = set(boosts)
        self.temps = temps or {}
        self.humidites = humidites or {}
        self.semaine = semaine
        self.exterieur = exterieur
        self.clim = {'froid': clim_froid, 'chaud': clim_chaud, 'deshu': clim_deshu}
        self.pieces = self.consignes = self.relais = self.ordres = None
        self.text = None

    def states(self, eid):
        if eid is None:
            return 'unknown'
        if eid in self.REGLAGES:
            return str(self.REGLAGES[eid])
        if eid == 'schedule.chauffage':
            return 'on' if self.horaire else 'off'
        if eid == 'sensor.temperature_exterieure':
            return str(self.exterieur)
        if eid == 'sensor.chauffage_temperature_exterieure':
            return str(self.text)
        if eid.startswith('input_boolean.clim_auto_'):
            role = eid.rsplit('_', 1)[1]
            return 'on' if self.clim[role] else 'off'
        if eid.startswith('input_boolean.presence_'):
            return 'on' if eid.split('presence_')[1] in self.presents else 'off'
        if eid.startswith('input_boolean.confort_'):
            return 'on' if eid.split('confort_')[1] in self.boosts else 'off'
        if eid.startswith('sensor.temperature_'):
            return str(self.temps.get(eid, 18.0))
        if eid.startswith('sensor.humidite_'):
            return str(self.humidites.get(eid, 50.0))
        return 'unknown'

    def is_state(self, eid, val):
        return self.states(eid) == val

    def state_attr(self, eid, attr):
        return {
            ('sensor.chauffage_configuration', 'pieces'): self.pieces,
            ('sensor.chauffage_consignes', 'consignes'): self.consignes,
            ('sensor.chauffage_relais', 'relais'): self.relais,
            ('sensor.clim_pilotage', 'ordres'): self.ordres,
        }.get((eid, attr))

    def now(self):
        return datetime.datetime.fromisocalendar(2026, self.semaine, 1)


def rendre(tpl, m):
    def flottant(v, default=None):
        try:
            return float(v)
        except (TypeError, ValueError):
            if default is None:
                raise
            return default

    env = Environment()
    env.filters['float'] = flottant
    env.globals.update(states=m.states, is_state=m.is_state,
                       state_attr=m.state_attr, now=m.now)
    return env.from_string(tpl).render().strip()


def evaluer(m):
    """Rejoue la chaîne de dépendances entre capteurs, dans l'ordre."""
    m.pieces = eval(rendre(TPL_CFG, m))
    m.consignes = eval(rendre(TPL_CONSIGNES, m))
    m.text = float(rendre(TPL_TEXT, m))
    m.relais = eval(rendre(TPL_RELAIS, m))
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

titre("Présences partielles")
m = evaluer(Monde(presents=['leo', 'laurent'], semaine=41))
verifier("Léo présent : sa chambre chauffe", m.consignes['chambre_leo'], 19.5)
verifier("Pablo absent : sa chambre à 15°", m.consignes['chambre_pablo'], 15.0)
verifier("SdB commune : chauffée par le seul Léo", m.consignes['sdb_enfants'], 21.0)

titre("Bouton confort")
m = evaluer(Monde(presents=['laurent'], horaire=False, semaine=40,
                  boosts=['chambre_pablo']))
verifier("forçage malgré l'absence", m.consignes['chambre_pablo'], 19.5)
verifier("les autres pièces ne bougent pas", m.consignes['chambre_leo'], 15.0)

# =============================================================================
titre("Arbitrage radiateur / clim")
froid_partout = {f'sensor.temperature_{p}': 16.0 for p in
                 ['chambre_leo', 'chambre_pablo', 'sdb_enfants',
                  'chambre_laurent', 'sejour']}

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  temps=froid_partout, exterieur=12.0))
verifier("chambre Lolo (sans radiateur) revient à la clim",
         m.relais['chambre_laurent'], 'clim')
verifier("les pièces avec radiateur restent au radiateur",
         m.relais['chambre_leo'], 'radiateur')
verifier("séjour (radiateur, pas de clim) au radiateur",
         m.relais['sejour'], 'radiateur')

m = evaluer(Monde(presents=['laurent'], semaine=41, temps=froid_partout,
                  exterieur=-5.0))
verifier("par -5 °C, la chambre sans radiateur reste à la clim",
         m.relais['chambre_laurent'], 'clim')
verifier("  -> et la clim chauffe effectivement",
         m.ordres['chambre_laurent']['mode'], 'heat')

m = evaluer(Monde(presents=['laurent'], semaine=41, temps=froid_partout,
                  exterieur=12.0, clim_chaud=False))
verifier("appoint désactivé : la pièce sans radiateur garde la clim",
         m.relais['chambre_laurent'], 'clim')

titre("Chaudière")
m = evaluer(Monde(presents=['leo', 'laurent'], semaine=41,
                  temps={**froid_partout,
                         'sensor.temperature_sdb_enfants': 22.0,
                         'sensor.temperature_sejour': 21.0}))
verifier("déficit chez Léo -> demande", rendre(TPL_DEMANDE, m), 'True')

m = evaluer(Monde(presents=['laurent'], semaine=40,
                  temps={**froid_partout, 'sensor.temperature_sejour': 21.0}))
verifier("chambres vides à 16° (>15) -> pas de demande",
         rendre(TPL_DEMANDE, m), 'False')

m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={**froid_partout, 'sensor.temperature_sejour': 21.0}))
verifier("chambre Lolo froide mais servie par la clim -> pas de chaudière",
         rendre(TPL_DEMANDE, m), 'False')

# =============================================================================
titre("Clim — hors-gel d'une pièce sans radiateur")
m = evaluer(Monde(presents=[], semaine=40,
                  temps={'sensor.temperature_chambre_laurent': 9.0}))
verifier("personne présent : la clim maintient quand même",
         m.ordres['chambre_laurent']['mode'], 'heat')
verifier("  -> à la consigne d'absence, pas au confort",
         m.ordres['chambre_laurent']['temp'], 15.0)

m = evaluer(Monde(presents=[], semaine=40,
                  temps={'sensor.temperature_chambre_laurent': 17.0}))
verifier("pièce vide déjà au-dessus de 15° : arrêt",
         m.ordres['chambre_laurent']['mode'], 'off')

titre("Clim — rafraîchissement")
m = evaluer(Monde(presents=['laurent'], semaine=41, exterieur=30.0,
                  temps={'sensor.temperature_chambre_laurent': 28.0}))
verifier("28° et occupant présent -> froid",
         m.ordres['chambre_laurent']['mode'], 'cool')
verifier("  -> à la consigne d'été", m.ordres['chambre_laurent']['temp'], 25.0)

m = evaluer(Monde(presents=[], semaine=41, exterieur=30.0,
                  temps={'sensor.temperature_chambre_laurent': 28.0}))
verifier("pièce vide : on ne rafraîchit pas",
         m.ordres['chambre_laurent']['mode'], 'off')

m = evaluer(Monde(presents=['laurent'], semaine=41, exterieur=30.0,
                  clim_froid=False,
                  temps={'sensor.temperature_chambre_laurent': 28.0}))
verifier("rafraîchissement désactivé : arrêt",
         m.ordres['chambre_laurent']['mode'], 'off')

titre("Clim — déshumidification")
m = evaluer(Monde(presents=['laurent'], semaine=41, exterieur=18.0,
                  temps={'sensor.temperature_chambre_laurent': 20.0},
                  humidites={'sensor.humidite_chambre_laurent': 72.0}))
verifier("72 % d'humidité, température correcte -> déshu",
         m.ordres['chambre_laurent']['mode'], 'dry')

m = evaluer(Monde(presents=['laurent'], semaine=41, exterieur=18.0,
                  temps={'sensor.temperature_chambre_laurent': 16.0},
                  humidites={'sensor.humidite_chambre_laurent': 72.0}))
verifier("humide ET froid : le chauffage passe devant",
         m.ordres['chambre_laurent']['mode'], 'heat')

m = evaluer(Monde(presents=['laurent'], semaine=41, exterieur=18.0,
                  clim_deshu=False,
                  temps={'sensor.temperature_chambre_laurent': 20.0},
                  humidites={'sensor.humidite_chambre_laurent': 72.0}))
verifier("déshumidification désactivée : arrêt",
         m.ordres['chambre_laurent']['mode'], 'off')

titre("Cohérence d'ensemble")
m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  temps=froid_partout))
double = [p for p in m.pieces
          if m.relais.get(p) == 'clim'
          and m.consignes.get(p, 0) > m.pieces[p]['absence']
          and m.pieces[p]['vanne']]
verifier("aucune pièce chauffée par les deux sources à la fois", double, [])
verifier("état du capteur = consigne maximale", rendre(TPL_ETAT, m), '21.0')

# =============================================================================
print()
if echecs:
    print(f"{ROUGE}{len(echecs)} test(s) en échec{RAZ} : " + ", ".join(echecs))
    raise SystemExit(1)
print(f"{VERT}Tous les tests passent.{RAZ}")
