"""Simule le moteur de templates de Home Assistant pour valider la logique
de calcul des consignes, hors instance réelle."""
import yaml, datetime
from jinja2 import Environment

paquet = yaml.safe_load(open('/home/user/HA/packages/chauffage.yaml', encoding='utf-8'))
capteurs = paquet['template'][0]['sensor'][0], paquet['template'][1]['sensor'][0]
cfg_tpl = capteurs[0]['attributes']['pieces']
consignes_tpl = capteurs[1]['attributes']['consignes']
etat_tpl = capteurs[1]['state']
bs = paquet['template'][2]['binary_sensor'][0]

env = Environment()

class Monde:
    """État simulé de l'instance."""
    def __init__(self, presents, horaire, boosts=(), temps=None, semaine=40):
        self.presents, self.horaire = presents, horaire
        self.boosts, self.temps = set(boosts), temps or {}
        self.semaine = semaine
        self.pieces = None

    def states(self, eid):
        if eid == 'schedule.chauffage':
            return 'on' if self.horaire else 'off'
        if eid.startswith('input_boolean.presence_'):
            return 'on' if eid.split('presence_')[1] in self.presents else 'off'
        if eid.startswith('input_boolean.confort_'):
            return 'on' if eid.split('confort_')[1] in self.boosts else 'off'
        if eid.startswith('sensor.temperature_'):
            return str(self.temps.get(eid, 18.0))
        return 'unknown'

    def is_state(self, eid, val):
        return self.states(eid) == val

    def state_attr(self, eid, attr):
        if eid == 'sensor.chauffage_configuration' and attr == 'pieces':
            return self.pieces
        if eid == 'sensor.chauffage_consignes' and attr == 'consignes':
            return self.consignes
        return None

    def now(self):
        # lundi d'une semaine ISO donnée
        return datetime.datetime.fromisocalendar(2026, self.semaine, 1)

def rendre(tpl, m):
    def f(v, default=None):
        try: return float(v)
        except (TypeError, ValueError):
            if default is None: raise
            return default
    e = Environment()
    e.filters['float'] = f
    e.globals.update(states=m.states, is_state=m.is_state,
                     state_attr=m.state_attr, now=m.now)
    return e.from_string(tpl).render().strip()

def evaluer(m):
    m.pieces = eval(rendre(cfg_tpl, m))
    m.consignes = eval(rendre(consignes_tpl, m))
    return m.consignes

def demande(m):
    return rendre(bs['state'], m)

ROUGE, VERT, RAZ = '\033[31m', '\033[32m', '\033[0m'
echecs = 0
def verifier(libelle, obtenu, attendu):
    global echecs
    ok = obtenu == attendu
    if not ok: echecs += 1
    print(f"  {VERT+'OK  ' if ok else ROUGE+'ÉCHEC'}{RAZ} {libelle}")
    if not ok:
        print(f"        attendu : {attendu}")
        print(f"        obtenu  : {obtenu}")

print("\n=== Semaine PAIRE : enfants absents ===")
m = Monde(presents=['laurent'], horaire=True, semaine=40)
c = evaluer(m)
verifier("chambre Léo à 15°",        c['chambre_leo'], 15.0)
verifier("chambre Pablo à 15°",      c['chambre_pablo'], 15.0)
verifier("SdB enfants à 15°",        c['sdb_enfants'], 15.0)
verifier("séjour au confort",        c['sejour'], 20.5)

print("\n=== Semaine IMPAIRE, horaire actif : enfants présents ===")
m = Monde(presents=['leo', 'pablo', 'laurent'], horaire=True, semaine=41)
c = evaluer(m)
verifier("chambre Léo au confort",   c['chambre_leo'], 19.5)
verifier("SdB enfants au confort",   c['sdb_enfants'], 21.0)

print("\n=== Semaine IMPAIRE, hors horaire : repli de nuit ===")
m = Monde(presents=['leo', 'pablo', 'laurent'], horaire=False, semaine=41)
c = evaluer(m)
verifier("chambre Léo en nuit",      c['chambre_leo'], 17.0)
verifier("SdB enfants en nuit",      c['sdb_enfants'], 18.0)

print("\n=== Léo seul présent (Pablo absent) ===")
m = Monde(presents=['leo', 'laurent'], horaire=True, semaine=40)
c = evaluer(m)
verifier("chambre Léo chauffée",     c['chambre_leo'], 19.5)
verifier("chambre Pablo à 15°",      c['chambre_pablo'], 15.0)
verifier("SdB enfants chauffée",     c['sdb_enfants'], 21.0)

print("\n=== Bouton confort : forçage même en l'absence de l'occupant ===")
m = Monde(presents=['laurent'], horaire=False, semaine=40,
          boosts=['chambre_pablo'])
c = evaluer(m)
verifier("chambre Pablo forcée",     c['chambre_pablo'], 19.5)
verifier("chambre Léo reste à 15°",  c['chambre_leo'], 15.0)

print("\n=== Demande chaudière ===")
m = Monde(presents=['leo', 'laurent'], horaire=True, semaine=41,
          temps={'sensor.temperature_chambre_leo': 16.0,
                 'sensor.temperature_chambre_pablo': 16.0,
                 'sensor.temperature_sdb_enfants': 22.0,
                 'sensor.temperature_chambre_laurent': 20.0,
                 'sensor.temperature_sejour': 21.0})
evaluer(m)
verifier("déficit chez Léo -> demande", demande(m), 'True')

m = Monde(presents=['laurent'], horaire=True, semaine=40,
          temps={'sensor.temperature_chambre_leo': 16.0,
                 'sensor.temperature_chambre_pablo': 16.0,
                 'sensor.temperature_sdb_enfants': 16.0,
                 'sensor.temperature_chambre_laurent': 20.0,
                 'sensor.temperature_sejour': 21.0})
evaluer(m)
verifier("chambres vides à 16° (>15) -> pas de demande", demande(m), 'False')

print("\n=== État du capteur (consigne maximale) ===")
m = Monde(presents=['leo', 'pablo', 'laurent'], horaire=True, semaine=41)
evaluer(m)
verifier("max = SdB à 21°", rendre(etat_tpl, m), '21.0')

print(f"\n{'Tous les tests passent.' if not echecs else str(echecs) + ' test(s) en échec.'}")
raise SystemExit(1 if echecs else 0)
