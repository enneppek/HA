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
TPL_CHAUDIERE = capteur(chauffage, 'Chauffage consigne chaudière')['state']


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
                 temp_min=True, manuel=False, clim_etat='off', reglages=None):
        # Les valeurs par défaut reflètent la configuration réelle :
        # déshumidification seule, froid et appoint chauffage désactivés.
        self.presents = set(presents)
        self.horaire = horaire
        self.boosts = set(boosts)
        self.temps = temps or {}
        self.humidites = humidites or {}
        self.semaine = semaine
        self.exterieur = exterieur
        self.clim = {'froid': clim_froid, 'chaud': clim_chaud, 'deshu': clim_deshu}
        self.temp_min, self.manuel, self.clim_etat = temp_min, manuel, clim_etat
        self.reglages = {**self.REGLAGES, **(reglages or {})}
        self.pieces = self.consignes = self.relais = self.ordres = None
        self.demande = False
        self.text = None

    def states(self, eid):
        if eid is None:
            return 'unknown'
        if eid in self.reglages:
            return str(self.reglages[eid])
        if eid == 'binary_sensor.chauffage_demande_chaudiere':
            return 'on' if self.demande else 'off'
        if eid == 'schedule.chauffage':
            return 'on' if self.horaire else 'off'
        if eid == 'sensor.temperature_exterieure':
            return str(self.exterieur)
        if eid == 'sensor.chauffage_temperature_exterieure':
            return str(self.text)
        if eid == 'input_boolean.clim_maintien_temp_min':
            return 'on' if self.temp_min else 'off'
        if eid == 'input_boolean.clim_pilotage_manuel':
            return 'on' if self.manuel else 'off'
        if eid.startswith('climate.clim_'):
            return self.clim_etat
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
    m.demande = rendre(TPL_DEMANDE, m) == 'True'
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
# Une erreur de syntaxe Jinja laisse le YAML valide : seul le rendu échoue,
# et Home Assistant se contente alors d'un capteur « unavailable ». Ce contrôle
# compile chaque template des deux packages, y compris ceux qu'aucun scénario
# ci-dessous n'exerce.


def templates(noeud, chemin="") :
    """Parcourt le YAML et rend chaque chaîne contenant du Jinja."""
    if isinstance(noeud, dict):
        for cle, valeur in noeud.items():
            yield from templates(valeur, f"{chemin}.{cle}")
    elif isinstance(noeud, list):
        for i, valeur in enumerate(noeud):
            yield from templates(valeur, f"{chemin}[{i}]")
    elif isinstance(noeud, str) and ('{{' in noeud or '{%' in noeud):
        yield chemin, noeud


erreurs = 0
for nom, paquet in (('chauffage', chauffage), ('clim', clim_pkg)):
    for chemin, tpl in templates(paquet, nom):
        try:
            Environment().parse(tpl)
        except Exception as e:
            erreurs += 1
            echecs.append(chemin)
            print(f"  {ROUGE}ÉCHEC{RAZ} {chemin}")
            print(f"         {e}")
verifier("tous les templates compilent", erreurs, 0)

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

titre("Pièces communes")
m = evaluer(Monde(presents=['leo'], semaine=41))
verifier("cuisine chauffée dès qu'une personne est là",
         m.consignes['cuisine'], 19.0)
m = evaluer(Monde(presents=[], semaine=41))
verifier("maison vide : cuisine à 15°", m.consignes['cuisine'], 15.0)
verifier("maison vide : salon à 15°", m.consignes['salon'], 15.0)

titre("Présences partielles")
m = evaluer(Monde(presents=['leo', 'laurent'], semaine=41))
verifier("Léo présent : sa chambre chauffe", m.consignes['chambre_leo'], 19.5)
verifier("Pablo absent : sa chambre à 15°", m.consignes['chambre_pablo'], 15.0)
verifier("SdB commune : chauffée par le seul Léo", m.consignes['sdb_enfants'], 21.0)

m = evaluer(Monde(presents=['leo'], semaine=41))
verifier("boulangerie : Lolo absent, elle reste à 15°",
         m.consignes['boulangerie'], 15.0)
m = evaluer(Monde(presents=['laurent'], semaine=41))
verifier("boulangerie : Lolo présent, elle chauffe",
         m.consignes['boulangerie'], 19.0)

titre("Bouton confort")
m = evaluer(Monde(presents=['laurent'], horaire=False, semaine=40,
                  boosts=['chambre_pablo']))
verifier("forçage malgré l'absence", m.consignes['chambre_pablo'], 19.5)
verifier("les autres pièces ne bougent pas", m.consignes['chambre_leo'], 15.0)

# =============================================================================
titre("Arbitrage radiateur / clim")
froid_partout = {f'sensor.temperature_{p}': 16.0 for p in
                 ['chambre_leo', 'chambre_pablo', 'sdb_enfants',
                  'chambre_laurent', 'salon', 'cuisine',
                  'boulangerie']}

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  temps=froid_partout, exterieur=12.0, clim_chaud=True))
verifier("chambre Lolo (sans radiateur) revient à la clim",
         m.relais['chambre_laurent'], 'clim')
verifier("les pièces avec radiateur restent au radiateur",
         m.relais['chambre_leo'], 'radiateur')
verifier("salon (radiateur, pas de clim) au radiateur",
         m.relais['salon'], 'radiateur')
verifier("le salon porte bien deux vannes",
         len(m.pieces['salon']['vannes']), 2)
verifier("la cuisine aussi", len(m.pieces['cuisine']['vannes']), 2)
verifier("la boulangerie en porte une",
         len(m.pieces['boulangerie']['vannes']), 1)
verifier("la chambre de Lolo n'en porte aucune",
         m.pieces['chambre_laurent']['vannes'], [])

m = evaluer(Monde(presents=['laurent'], semaine=41, temps=froid_partout,
                  exterieur=-5.0, clim_chaud=True))
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
                         'sensor.temperature_salon': 21.0}))
verifier("déficit chez Léo -> demande", rendre(TPL_DEMANDE, m), 'True')

m = evaluer(Monde(presents=['laurent'], semaine=40,
                  temps={**froid_partout,
                         'sensor.temperature_salon': 21.0,
                         'sensor.temperature_cuisine': 21.0,
                         'sensor.temperature_boulangerie': 21.0}))
verifier("chambres vides à 16° (>15) -> pas de demande",
         rendre(TPL_DEMANDE, m), 'False')

m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={**froid_partout,
                         'sensor.temperature_salon': 21.0,
                         'sensor.temperature_cuisine': 21.0,
                         'sensor.temperature_boulangerie': 21.0}))
verifier("chambre Lolo froide mais servie par la clim -> pas de chaudière",
         rendre(TPL_DEMANDE, m), 'False')

# =============================================================================
m = evaluer(Monde(presents=['laurent'], semaine=40,
                  temps={**froid_partout, 'sensor.temperature_salon': 21.0}))
verifier("cuisine froide et occupée -> demande", rendre(TPL_DEMANDE, m), 'True')

titre("Chaudière — le T6 n'est plus qu'un relais")
# Le T6 est dans la cuisine. Le scénario qui cassait l'installation : cuisine
# à bonne température, chambre d'enfant glaciale. Le brûleur doit tourner.
m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  temps={'sensor.temperature_cuisine': 22.0,
                         'sensor.temperature_salon': 21.0,
                         'sensor.temperature_chambre_leo': 16.0,
                         'sensor.temperature_chambre_pablo': 16.0,
                         'sensor.temperature_sdb_enfants': 21.0}))
verifier("cuisine à 22° mais chambres froides -> demande maintenue",
         rendre(TPL_DEMANDE, m), 'True')
verifier("  -> consigne d'appel envoyée au T6",
         rendre(TPL_CHAUDIERE, m), '24.0')

m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  temps={'sensor.temperature_cuisine': 21.0,
                         'sensor.temperature_salon': 21.0,
                         'sensor.temperature_boulangerie': 21.0,
                         'sensor.temperature_chambre_leo': 20.0,
                         'sensor.temperature_chambre_pablo': 20.0,
                         'sensor.temperature_sdb_enfants': 22.0}))
verifier("toutes les pièces à température -> pas de demande",
         rendre(TPL_DEMANDE, m), 'False')
verifier("  -> consigne de repos, le brûleur relâche",
         rendre(TPL_CHAUDIERE, m), '10.0')

m = evaluer(Monde(presents=['leo'], semaine=41,
                  reglages={'input_number.chaudiere_consigne_marche': 30},
                  temps={'sensor.temperature_cuisine': 28.0,
                         'sensor.temperature_salon': 21.0,
                         'sensor.temperature_chambre_leo': 16.0,
                         'sensor.temperature_chambre_pablo': 20.0,
                         'sensor.temperature_sdb_enfants': 22.0}))
verifier("consigne d'appel relevable si la cuisine chauffe trop",
         rendre(TPL_CHAUDIERE, m), '30.0')

titre("Clim — déshumidification (comportement par défaut)")
m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={'sensor.temperature_chambre_laurent': 19.0},
                  humidites={'sensor.humidite_chambre_laurent': 72.0}))
verifier("72 % d'humidité -> mode chaud, pas dry",
         m.ordres['chambre_laurent']['mode'], 'heat')
verifier("  -> consigne = ambiante + delta", m.ordres['chambre_laurent']['temp'], 20.5)

m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={'sensor.temperature_chambre_laurent': 19.0},
                  humidites={'sensor.humidite_chambre_laurent': 55.0}))
verifier("air sec : arrêt", m.ordres['chambre_laurent']['mode'], 'off')

m = evaluer(Monde(presents=['laurent'], semaine=41, clim_deshu=False,
                  temps={'sensor.temperature_chambre_laurent': 19.0},
                  humidites={'sensor.humidite_chambre_laurent': 72.0}))
verifier("déshumidification désactivée : arrêt",
         m.ordres['chambre_laurent']['mode'], 'off')

titre("Clim — hystérésis d'humidité")
m = evaluer(Monde(presents=['laurent'], semaine=41, clim_etat='heat',
                  temps={'sensor.temperature_chambre_laurent': 19.0},
                  humidites={'sensor.humidite_chambre_laurent': 62.0}))
verifier("déjà en marche à 62 % : poursuit",
         m.ordres['chambre_laurent']['mode'], 'heat')

m = evaluer(Monde(presents=['laurent'], semaine=41, clim_etat='off',
                  temps={'sensor.temperature_chambre_laurent': 19.0},
                  humidites={'sensor.humidite_chambre_laurent': 62.0}))
verifier("à l'arrêt à 62 % : ne redémarre pas",
         m.ordres['chambre_laurent']['mode'], 'off')

titre("Clim — limite haute d'assèchement")
m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={'sensor.temperature_chambre_laurent': 21.5},
                  humidites={'sensor.humidite_chambre_laurent': 72.0}))
verifier("ambiante + delta dépasse la limite : bridé à 22°",
         m.ordres['chambre_laurent']['temp'], 22.0)

m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={'sensor.temperature_chambre_laurent': 23.0},
                  humidites={'sensor.humidite_chambre_laurent': 72.0}))
verifier("déjà au-dessus de la limite : on n'insiste pas",
         m.ordres['chambre_laurent']['mode'], 'off')

titre("Clim — température minimale, prioritaire sur tout")
m = evaluer(Monde(presents=[], semaine=40,
                  temps={'sensor.temperature_chambre_laurent': 9.0}))
verifier("pièce vide à 9° : chauffe malgré l'absence",
         m.ordres['chambre_laurent']['mode'], 'heat')
verifier("  -> au minimum réglé, pas au confort", m.ordres['chambre_laurent']['temp'], 15.0)

m = evaluer(Monde(presents=[], semaine=40, temp_min=False,
                  temps={'sensor.temperature_chambre_laurent': 9.0}))
verifier("maintien désactivé : plus rien ne chauffe",
         m.ordres['chambre_laurent']['mode'], 'off')

titre("Clim — les deux garanties sont paramétrables")
m = evaluer(Monde(presents=[], semaine=40,
                  reglages={'input_number.clim_temp_min': 17},
                  temps={'sensor.temperature_chambre_laurent': 16.0}))
verifier("minimum porté à 17° : 16° déclenche la chauffe",
         m.ordres['chambre_laurent']['mode'], 'heat')
verifier("  -> jusqu'à 17°", m.ordres['chambre_laurent']['temp'], 17.0)

m = evaluer(Monde(presents=[], semaine=40,
                  reglages={'input_number.clim_temp_min': 10},
                  temps={'sensor.temperature_chambre_laurent': 12.0}))
verifier("minimum abaissé à 10° : 12° ne déclenche rien",
         m.ordres['chambre_laurent']['mode'], 'off')

m = evaluer(Monde(presents=['laurent'], semaine=41,
                  reglages={'input_number.clim_seuil_humidite': 55},
                  temps={'sensor.temperature_chambre_laurent': 19.0},
                  humidites={'sensor.humidite_chambre_laurent': 60.0}))
verifier("seuil d'humidité abaissé à 55 % : 60 % déclenche l'assèchement",
         m.ordres['chambre_laurent']['mode'], 'heat')

titre("Clim — rôles désactivés par défaut")
m = evaluer(Monde(presents=['laurent'], semaine=41, exterieur=30.0,
                  temps={'sensor.temperature_chambre_laurent': 28.0}))
verifier("28° mais rafraîchissement désactivé : arrêt",
         m.ordres['chambre_laurent']['mode'], 'off')

m = evaluer(Monde(presents=['laurent'], semaine=41, exterieur=30.0,
                  clim_froid=True,
                  temps={'sensor.temperature_chambre_laurent': 28.0}))
verifier("rafraîchissement activé : froid",
         m.ordres['chambre_laurent']['mode'], 'cool')

m = evaluer(Monde(presents=['laurent'], semaine=41,
                  temps={'sensor.temperature_chambre_laurent': 17.0}))
verifier("17° mais appoint désactivé : pas de chauffe",
         m.ordres['chambre_laurent']['mode'], 'off')

m = evaluer(Monde(presents=['laurent'], semaine=41, clim_chaud=True,
                  temps={'sensor.temperature_chambre_laurent': 17.0}))
verifier("appoint activé : chauffe à la consigne du moment",
         m.ordres['chambre_laurent']['temp'], 19.5)

titre("Cohérence d'ensemble")
m = evaluer(Monde(presents=['leo', 'pablo', 'laurent'], semaine=41,
                  temps=froid_partout, clim_chaud=True))
double = [p for p in m.pieces
          if m.relais.get(p) == 'clim'
          and m.consignes.get(p, 0) > m.pieces[p]['absence']
          and m.pieces[p]['vannes']]
verifier("aucune pièce chauffée par les deux sources à la fois", double, [])
verifier("état du capteur = consigne maximale", rendre(TPL_ETAT, m), '21.0')

# =============================================================================
print()
if echecs:
    print(f"{ROUGE}{len(echecs)} test(s) en échec{RAZ} : " + ", ".join(echecs))
    raise SystemExit(1)
print(f"{VERT}Tous les tests passent.{RAZ}")
