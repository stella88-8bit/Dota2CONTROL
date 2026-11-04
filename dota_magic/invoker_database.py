"""Versioned Invoker values from installed Valve game files, with SQLite lookup."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
import itertools
import json
import math
from pathlib import Path
import re
import sqlite3
import tempfile

from integration.keyvalues import parse
from integration.vpk_reader import read_file, source_hash
from dota_magic.spell_phrases import SPELLS

ROOT = Path(__file__).resolve().parent.parent
DATABASE = ROOT / 'data/invoker.sqlite3'
RULES = ROOT / 'data/invoker_rules.json'
DEFAULT_VPK = Path.home() / 'Library/Application Support/Steam/steamapps/common/dota 2 beta/game/dota/pak01_dir.vpk'
HERO_FILE = 'scripts/npc/heroes/npc_dota_hero_invoker.txt'
SCHEMA_VERSION = '2'
ORBS = {name: sequence for name, sequence in SPELLS.values()}
LEVEL_KEYS = {'quaslevel': 0, 'wexlevel': 1, 'exortlevel': 2}


def extract_rules(vpk_path=DEFAULT_VPK):
    raw = read_file(Path(vpk_path), HERO_FILE)
    hero = parse(raw.decode('utf-8-sig'))['DOTAHeroes']['npc_dota_hero_invoker']
    definitions = hero['AbilityDefinitions']
    names = ['invoker_' + name.replace(' ', '_') for name in ORBS]
    names += ['invoker_invoke', 'invoker_quas', 'invoker_wex', 'invoker_exort']
    reduced = {}
    for name in names:
        definition = definitions[name]
        reduced[name.removeprefix('invoker_').replace('_', ' ')] = {
            k: v for k, v in definition.items()
            if k in ('AbilityValues', 'AbilityCastPoint', 'AbilityCooldown', 'AbilityCastRange',
                     'AbilityManaCost', 'AbilityBehavior', 'MaxLevel', 'HasScepterUpgrade',
                     'HasShardUpgrade', 'ScepterUpgradeID', 'ShardUpgradeID',
                     'AbilityUnitDamageType','SpellImmunityType','SpellDispellableType',
                     'AbilityUnitTargetTeam','AbilityUnitTargetType','AbilityType','Innate')}
    manifest = next((parent/'appmanifest_570.acf' for parent in Path(vpk_path).resolve().parents
                     if (parent/'appmanifest_570.acf').is_file()),None)
    match = re.search(r'"buildid"\s+"(\d+)"', manifest.read_text()) if manifest is not None else None
    maximum_rank = max(int(_value(reduced[orb]['AbilityValues']['max_level'], (1,1,1), orb,
                                  {'special_bonus_scepter_' + str(index+1)}))
                       for index,orb in enumerate(('quas','wex','exort')))
    return {'schema_version': SCHEMA_VERSION, 'source': HERO_FILE,
            'source_sha256': source_hash(raw), 'steam_build_id': match.group(1) if match else None,
            'extracted_at': datetime.now(timezone.utc).isoformat(),
            'hero_levels': [1, 30], 'orb_levels': [0, maximum_rank],
            'rank_indexing': 'Effective GSI orb level 1 selects first value; level 9 selects ninth. No extra Aghanim level is added.',
            'talents': {str(i + 1): hero['Ability' + str(17 + i)] for i in range(8)},
            'definitions': reduced}


def _pick(raw, levelkey, levels, spell):
    if not isinstance(raw, str):
        raise ValueError('Expected a numeric string: ' + repr(raw))
    values = [float(v) for v in raw.split()]
    if not values or not all(math.isfinite(v) for v in values):
        raise ValueError('Invalid numeric values: ' + raw)
    if len(values) == 1:
        return values[0]
    if levelkey in LEVEL_KEYS:
        rank = levels[LEVEL_KEYS[levelkey]]
    elif spell in ('quas', 'wex', 'exort'):
        rank = levels[('quas', 'wex', 'exort').index(spell)]
    else:
        raise ValueError(f'No level key for {spell}: {raw}')
    if rank == 0:
        return None
    if rank > len(values):
        raise ValueError('Rank outside source data')
    return values[rank - 1]


def _value(rule, levels, spell, bonuses, inherited_key=None):
    if isinstance(rule, str):
        return _pick(rule, inherited_key, levels, spell)
    levelkey = rule.get('levelkey', inherited_key)
    result = _pick(rule['value'], levelkey, levels, spell)
    for name, modifier in rule.items():
        if not name.startswith('special_bonus_') or name not in bonuses:
            continue
        if isinstance(modifier, dict):
            replacement = _value(modifier, levels, spell, bonuses, levelkey)
            result = replacement
            continue
        operation = 'replace'
        expression = modifier
        if modifier.startswith(('x', '*')):
            operation, expression = 'multiply', modifier[1:]
        elif modifier.startswith(('+', '-')):
            operation = 'add'
        if expression.endswith('%'):
            operation = 'percent'
            expression = expression[:-1]
        amount = _pick(expression, levelkey, levels, spell)
        if result is None or amount is None:
            result = None
        elif operation == 'replace':
            result = amount
        elif operation == 'add':
            result += amount
        elif operation == 'multiply':
            result *= amount
        else:
            result *= 1 + amount / 100
    return result


def evaluate(definition, levels, spell, bonuses=frozenset()):
    values = {key: _value(rule, levels, spell, bonuses)
              for key, rule in definition.get('AbilityValues', {}).items()}
    for key in ('AbilityCastPoint', 'AbilityManaCost', 'AbilityCastRange', 'AbilityCooldown'):
        if key in definition and key not in values:
            values[key] = _value(definition[key], levels, spell, bonuses)
    values.setdefault('AbilityCastPoint', 0.0)
    return values


def build_database(rules, output=DATABASE):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(prefix=output.name + '.', suffix='.tmp', dir=output.parent, delete=False)
    temporary = Path(handle.name)
    handle.close()
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.executescript('''
                PRAGMA journal_mode=OFF;
                PRAGMA synchronous=OFF;
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE spell_definition (spell TEXT PRIMARY KEY, definition_json TEXT NOT NULL);
                CREATE TABLE orb_state (
                    quas INTEGER, wex INTEGER, exort INTEGER, invoke_cooldown REAL NOT NULL,
                    PRIMARY KEY (quas,wex,exort));
                CREATE TABLE hero_state (
                    hero_level INTEGER, quas INTEGER, wex INTEGER, exort INTEGER,
                    orb_point_budget_upper_bound INTEGER NOT NULL,
                    PRIMARY KEY (hero_level,quas,wex,exort));
                CREATE TABLE spell_profile (
                    quas INTEGER, wex INTEGER, exort INTEGER, spell TEXT, available INTEGER NOT NULL,
                    values_json TEXT NOT NULL, PRIMARY KEY (quas,wex,exort,spell));
                CREATE VIEW all_spell_states AS
                    SELECT h.hero_level,p.*,o.invoke_cooldown
                    FROM hero_state h JOIN spell_profile p USING(quas,wex,exort)
                    JOIN orb_state o USING(quas,wex,exort);
            ''')
            db.executemany('INSERT INTO metadata VALUES (?,?)',
                           [(key, json.dumps(value, ensure_ascii=False)) for key, value in rules.items()
                            if key != 'definitions'])
            db.executemany('INSERT INTO spell_definition VALUES (?,?)',
                           [(name, json.dumps(definition, separators=(',', ':')))
                            for name, definition in rules['definitions'].items()])
            invoke = rules['definitions']['invoke']
            base = float(invoke['AbilityCooldown'])
            reduction = float(invoke['AbilityValues']['cooldown_reduction_per_orb'])
            bonus_levels = [int(invoke['AbilityValues'][key]) for key in
                            ('first_ability_level','second_ability_level','third_ability_level')]
            # Store raw game cooldown. A separate input-pacing floor is not a game stat.
            for levels in itertools.product(range(rules['orb_levels'][1]+1), repeat=3):
                cooldown = round(max(0, base - reduction * sum(levels)), 6)
                db.execute('INSERT INTO orb_state VALUES (?,?,?,?)', (*levels, cooldown))
                for spell, sequence in ORBS.items():
                    available = all(levels['qwe'.index(key)] > 0 for key in set(sequence))
                    values = evaluate(rules['definitions'][spell], levels, spell)
                    db.execute('INSERT INTO spell_profile VALUES (?,?,?,?,?,?)',
                               (*levels, spell, available, json.dumps(values, separators=(',', ':'))))
                db.executemany('INSERT INTO hero_state VALUES (?,?,?,?,?)',
                               [(hero_level, *levels, hero_level + sum(hero_level >= n for n in bonus_levels))
                                for hero_level in range(1,31)])
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('SQLite integrity check failed')
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def ensure_database(vpk_path=DEFAULT_VPK, output=DATABASE, rules_path=RULES):
    rules = extract_rules(vpk_path)
    if Path(output).is_file():
        try:
            existing = SpellDatabase(output).metadata
        except (sqlite3.DatabaseError, ValueError):
            existing = {}
        if existing.get('source_sha256') == rules['source_sha256'] and existing.get('schema_version') == SCHEMA_VERSION:
            return Path(output)
    build_database(rules, output)
    Path(rules_path).parent.mkdir(parents=True, exist_ok=True)
    Path(rules_path).write_text(json.dumps(rules, ensure_ascii=False, indent=2) + '\n')
    return Path(output)


class SpellDatabase:
    def __init__(self, path=DATABASE):
        self.path = Path(path).resolve()
        with closing(self._connect()) as db:
            self.metadata = {key: json.loads(value) for key, value in db.execute('SELECT key,value FROM metadata')}
            self.definitions = {key: json.loads(value) for key, value in db.execute('SELECT spell,definition_json FROM spell_definition')}
        if self.metadata.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('Unsupported Invoker database schema')

    def _connect(self):
        return sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)

    @lru_cache(maxsize=1024, typed=True)
    def profile(self, hero_level, quas, wex, exort):
        if isinstance(hero_level, bool) or not isinstance(hero_level, int) or not 1 <= hero_level <= 30:
            raise ValueError('Hero level must be an integer from 1 to 30')
        levels = (quas, wex, exort)
        if any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= self.metadata['orb_levels'][1] for v in levels):
            raise ValueError('Orb levels must be integers from 0 to ' + str(self.metadata['orb_levels'][1]))
        with closing(self._connect()) as db:
            cooldown = db.execute('SELECT invoke_cooldown FROM orb_state WHERE quas=? AND wex=? AND exort=?', levels).fetchone()[0]
            rows = db.execute('SELECT spell,available,values_json FROM all_spell_states WHERE hero_level=? AND quas=? AND wex=? AND exort=?',
                              (hero_level, *levels)).fetchall()
        return {'hero_level': hero_level, 'levels': levels, 'invoke_cooldown': cooldown,
                'orbs': {orb: {'level':levels[i],'values':evaluate(self.definitions[orb],levels,orb)}
                         for i,orb in enumerate(('quas','wex','exort'))},
                'invoke_values':evaluate(self.definitions['invoke'],levels,'invoke'),
                'spells': {name: {'available': bool(available), 'values': json.loads(values)}
                           for name, available, values in rows}}

    def resolve(self, hero_level, levels, *, talents=(), scepter_option=None, shard_option=None):
        baseline = self.profile(hero_level, *levels)
        bonuses = set(talents)
        for kind, option in (('scepter', scepter_option), ('shard', shard_option)):
            if option is not None:
                if option not in (1,2,3):
                    raise ValueError(kind + ' option must be 1, 2 or 3')
                bonuses.add('special_bonus_' + kind + '_' + str(option))
        return {**baseline, 'spells': {
            name: {'available': entry['available'],
                   'values': evaluate(self.definitions[name], levels, name, bonuses)}
            for name, entry in baseline['spells'].items()},
            'orbs': {orb: {'level':levels[i],'values':evaluate(self.definitions[orb],levels,orb,bonuses)}
                     for i,orb in enumerate(('quas','wex','exort'))},
            'bonuses': sorted(bonuses), 'scepter_option': scepter_option, 'shard_option': shard_option}

    def from_gsi(self, hero, abilities, *, scepter_option=None, shard_option=None):
        levels = []
        for i, name in enumerate(('quas', 'wex', 'exort')):
            ability = abilities.get('ability' + str(i), {})
            if ability.get('name') != 'invoker_' + name:
                raise ValueError('GSI is missing orb levels')
            levels.append(ability.get('level'))
        if hero.get('level') is None:
            raise ValueError('GSI is missing Invoker hero level')
        # GSI already reports effective orb levels: never add another Scepter level.
        selected = scepter_option
        if selected is None and hero.get('aghanims_scepter') and levels.count(9) == 1:
            selected = levels.index(9) + 1
        talents = [name for index, name in self.metadata['talents'].items()
                   if hero.get('talent_' + index) is True]
        return self.resolve(hero['level'], tuple(levels), talents=talents,
                            scepter_option=selected if hero.get('aghanims_scepter') else None,
                            shard_option=shard_option if hero.get('aghanims_shard') else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--vpk', type=Path, default=DEFAULT_VPK)
    parser.add_argument('--database', type=Path, default=DATABASE)
    parser.add_argument('--hero-level', type=int, default=30)
    parser.add_argument('--quas', type=int, default=8)
    parser.add_argument('--wex', type=int, default=8)
    parser.add_argument('--exort', type=int, default=9)
    parser.add_argument('--scepter', type=int, choices=(1,2,3))
    parser.add_argument('--shard', type=int, choices=(1,2,3))
    args = parser.parse_args()
    if args.build or not args.database.is_file():
        ensure_database(args.vpk, args.database)
    database = SpellDatabase(args.database)
    profile = database.resolve(args.hero_level, (args.quas,args.wex,args.exort),
                               scepter_option=args.scepter, shard_option=args.shard)
    print(json.dumps({'source': database.metadata, **profile}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
